"""
独立端口扫描脚本
不受eventlet monkey patch影响，使用原生socket进行准确的端口扫描
输出JSON格式的扫描结果
"""

import socket
import sys
import json
from concurrent.futures import ThreadPoolExecutor, as_completed


def scan_port(ip, port, timeout):
    """
    扫描单个端口
    使用原生socket，只有真正建立TCP连接才返回开放
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        # 只有返回0才表示端口开放
        return result == 0
    except socket.timeout:
        return False
    except ConnectionRefusedError:
        return False
    except OSError:
        return False
    except Exception:
        return False


def main():
    if len(sys.argv) < 6:
        print(json.dumps({'type': 'error', 'message': '参数不足'}))
        sys.exit(1)
    
    ip = sys.argv[1]
    start_port = int(sys.argv[2])
    end_port = int(sys.argv[3])
    threads = int(sys.argv[4])
    timeout = float(sys.argv[5])
    
    ports = list(range(start_port, end_port + 1))
    total = len(ports)
    scanned = 0
    
    # 每扫描多少端口报告一次进度
    report_interval = max(1, total // 100)
    
    with ThreadPoolExecutor(max_workers=threads) as executor:
        # 提交所有任务
        futures = {executor.submit(scan_port, ip, port, timeout): port for port in ports}
        
        for future in as_completed(futures):
            port = futures[future]
            scanned += 1
            
            try:
                is_open = future.result()
                if is_open:
                    # 发现开放端口
                    print(json.dumps({'type': 'open', 'port': port}), flush=True)
            except Exception:
                pass
            
            # 报告进度
            if scanned % report_interval == 0 or scanned == total:
                print(json.dumps({
                    'type': 'progress',
                    'scanned': scanned,
                    'total': total,
                    'current_port': port
                }), flush=True)
    
    # 扫描完成
    print(json.dumps({'type': 'complete'}), flush=True)


if __name__ == '__main__':
    main()
