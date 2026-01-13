"""
IP端口扫描Web应用
功能：支持IP端口扫描、自定义端口范围、多线程扫描、实时结果展示

关键：使用子进程执行端口扫描，完全绕过eventlet的socket patch问题
"""

# 必须在最开始打猴子补丁
import eventlet
eventlet.monkey_patch()

import subprocess
import sys
import json
import csv
import io
from flask import Flask, render_template, request, Response, make_response
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'port_scanner_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# 常见端口服务映射
COMMON_SERVICES = {
    20: 'FTP-Data', 21: 'FTP', 22: 'SSH', 23: 'Telnet', 25: 'SMTP',
    53: 'DNS', 67: 'DHCP', 68: 'DHCP', 69: 'TFTP', 80: 'HTTP',
    110: 'POP3', 119: 'NNTP', 123: 'NTP', 135: 'RPC', 137: 'NetBIOS',
    138: 'NetBIOS', 139: 'NetBIOS', 143: 'IMAP', 161: 'SNMP', 162: 'SNMP',
    179: 'BGP', 194: 'IRC', 389: 'LDAP', 443: 'HTTPS', 445: 'SMB',
    465: 'SMTPS', 514: 'Syslog', 515: 'LPD', 587: 'SMTP', 636: 'LDAPS',
    993: 'IMAPS', 995: 'POP3S', 1080: 'SOCKS', 1433: 'MSSQL', 1434: 'MSSQL',
    1521: 'Oracle', 1723: 'PPTP', 2049: 'NFS', 3306: 'MySQL', 3389: 'RDP',
    5432: 'PostgreSQL', 5900: 'VNC', 5901: 'VNC', 6379: 'Redis', 8080: 'HTTP-Alt',
    8443: 'HTTPS-Alt', 9000: 'PHP-FPM', 9200: 'Elasticsearch', 11211: 'Memcached',
    27017: 'MongoDB', 27018: 'MongoDB', 50000: 'DB2'
}

# 存储扫描任务状态
scan_tasks = {}


def get_service_name(port):
    """获取端口对应的服务名称"""
    return COMMON_SERVICES.get(port, '-')


def run_scan(sid, ip, start_port, end_port, threads, timeout, resume=False):
    """
    执行端口扫描
    使用子进程执行扫描脚本，完全绕过eventlet socket问题
    """
    # 检查是否断点续扫
    if resume and sid in scan_tasks and scan_tasks[sid].get('paused'):
        last_port = scan_tasks[sid].get('last_scanned_port', start_port - 1)
        actual_start = last_port + 1
        original_start = scan_tasks[sid].get('start_port', start_port)
        # 保留之前的开放端口列表，更新threads和timeout
        scan_tasks[sid]['threads'] = threads
        scan_tasks[sid]['timeout'] = timeout
    else:
        actual_start = start_port
        original_start = start_port
        scan_tasks[sid] = {
            'running': True,
            'paused': False,
            'open_ports': [],
            'last_scanned_port': start_port - 1,
            'start_port': start_port,
            'end_port': end_port,
            'ip': ip,
            'threads': threads,
            'timeout': timeout
        }
    
    scan_tasks[sid]['running'] = True
    scan_tasks[sid]['paused'] = False
    
    total = end_port - original_start + 1
    scanned_base = actual_start - original_start
    
    # 使用子进程执行扫描
    try:
        proc = subprocess.Popen(
            [sys.executable, 'scanner.py', ip, str(actual_start), str(end_port), str(threads), str(timeout)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            
            # 检查是否需要停止
            if not scan_tasks.get(sid, {}).get('running', False):
                proc.terminate()
                scan_tasks[sid]['paused'] = True
                socketio.emit('scan_stopped', {
                    'message': '扫描已停止',
                    'can_resume': True
                }, room=sid)
                return
            
            try:
                data = json.loads(line)
                
                if data['type'] == 'progress':
                    scan_tasks[sid]['last_scanned_port'] = data['current_port']
                    scanned = scanned_base + data['scanned']
                    progress = int(scanned / total * 100)
                    socketio.emit('scan_progress', {
                        'progress': progress,
                        'scanned': scanned,
                        'total': total,
                        'open_count': len(scan_tasks[sid]['open_ports'])
                    }, room=sid)
                    eventlet.sleep(0)
                    
                elif data['type'] == 'open':
                    port = data['port']
                    service = get_service_name(port)
                    port_info = {'port': port, 'service': service}
                    # 只添加到scan_tasks中的列表，避免重复
                    scan_tasks[sid]['open_ports'].append(port_info)
                    socketio.emit('port_found', {
                        'port': port,
                        'service': service,
                        'status': '开放'
                    }, room=sid)
                    
            except json.JSONDecodeError:
                pass
        
        proc.wait()
        
    except Exception as e:
        socketio.emit('scan_error', {'message': f'扫描错误: {str(e)}'}, room=sid)
        return
    
    # 扫描完成
    scan_tasks[sid]['running'] = False
    scan_tasks[sid]['paused'] = False
    open_ports = scan_tasks[sid]['open_ports']
    socketio.emit('scan_complete', {
        'message': '扫描完成',
        'total_ports': total,
        'open_count': len(open_ports),
        'open_ports': sorted(open_ports, key=lambda x: x['port'])
    }, room=sid)


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/export/<sid>')
def export_csv(sid):
    """导出CSV"""
    if sid not in scan_tasks:
        return "没有扫描结果", 404
    
    output = io.BytesIO()
    output.write(b'\xef\xbb\xbf')  # UTF-8 BOM
    
    text_wrapper = io.TextIOWrapper(output, encoding='utf-8', newline='')
    writer = csv.writer(text_wrapper)
    writer.writerow(['端口', '服务', '状态'])
    
    for port_info in sorted(scan_tasks[sid].get('open_ports', []), key=lambda x: x['port']):
        writer.writerow([port_info['port'], port_info['service'], '开放'])
    
    text_wrapper.flush()
    output.seek(0)
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment;filename=scan_result_{sid[:8]}.csv'
    return response


@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    emit('connected', {'sid': request.sid})


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开"""
    sid = request.sid
    if sid in scan_tasks:
        scan_tasks[sid]['running'] = False
        scan_tasks[sid]['paused'] = True


@socketio.on('start_scan')
def handle_start_scan(data):
    """开始扫描"""
    sid = request.sid
    ip = data.get('ip', '').strip()
    start_port = int(data.get('start_port', 1))
    end_port = int(data.get('end_port', 65535))
    threads = int(data.get('threads', 20))
    timeout = float(data.get('timeout', 1.0))
    resume = data.get('resume', False)
    
    # 验证IP格式
    import socket
    try:
        socket.inet_aton(ip)
    except socket.error:
        emit('scan_error', {'message': 'IP地址格式无效'})
        return
    
    # 验证端口范围
    if not (1 <= start_port <= 65535 and 1 <= end_port <= 65535):
        emit('scan_error', {'message': '端口范围必须在1-65535之间'})
        return
    
    if start_port > end_port:
        emit('scan_error', {'message': '起始端口不能大于结束端口'})
        return
    
    # 如果不是续扫，清除之前的任务
    if not resume and sid in scan_tasks:
        scan_tasks[sid] = None
    
    emit('scan_started', {'message': '扫描开始', 'resume': resume})
    eventlet.spawn(run_scan, sid, ip, start_port, end_port, threads, timeout, resume)


@socketio.on('resume_scan')
def handle_resume_scan(data):
    """继续扫描（使用前端传递的参数）"""
    sid = request.sid
    if sid not in scan_tasks or not scan_tasks[sid].get('paused'):
        emit('scan_error', {'message': '没有可继续的扫描任务'})
        return
    
    task = scan_tasks[sid]
    ip = task.get('ip')
    start_port = task.get('start_port', 1)
    end_port = task.get('end_port', 65535)
    
    # 使用前端传递的参数，如果没有则使用保存的或默认值
    threads = int(data.get('threads', task.get('threads', 50)))
    timeout = float(data.get('timeout', task.get('timeout', 1.0)))
    
    emit('scan_started', {'message': '继续扫描', 'resume': True})
    eventlet.spawn(run_scan, sid, ip, start_port, end_port, threads, timeout, True)


@socketio.on('stop_scan')
def handle_stop_scan():
    """停止扫描"""
    sid = request.sid
    if sid in scan_tasks:
        scan_tasks[sid]['running'] = False


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
