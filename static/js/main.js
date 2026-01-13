/**
 * 端口扫描器 - 前端JavaScript
 * 功能：Socket.IO通信、表单处理、实时更新、断点续扫
 */

// 全局变量
let socket = null;
let sessionId = null;
let isScanning = false;
let canResume = false;  // 是否可以继续扫描

// DOM元素
const elements = {
    form: document.getElementById('scanForm'),
    ipAddress: document.getElementById('ipAddress'),
    ipError: document.getElementById('ipError'),
    startPort: document.getElementById('startPort'),
    endPort: document.getElementById('endPort'),
    threads: document.getElementById('threads'),
    threadsInput: document.getElementById('threadsInput'),
    timeout: document.getElementById('timeout'),
    timeoutValue: document.getElementById('timeoutValue'),
    startBtn: document.getElementById('startBtn'),
    resumeBtn: document.getElementById('resumeBtn'),
    stopBtn: document.getElementById('stopBtn'),
    progressCard: document.getElementById('progressCard'),
    progressFill: document.getElementById('progressFill'),
    progressText: document.getElementById('progressText'),
    scanStats: document.getElementById('scanStats'),
    statusBadge: document.getElementById('statusBadge'),
    resultsBody: document.getElementById('resultsBody'),
    resultCount: document.getElementById('resultCount'),
    exportBtn: document.getElementById('exportBtn')
};

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    initSocket();
    initEventListeners();
});

/**
 * 初始化Socket.IO连接
 */
function initSocket() {
    socket = io();
    
    socket.on('connect', () => {
        console.log('已连接到服务器');
    });
    
    socket.on('connected', (data) => {
        sessionId = data.sid;
        console.log('会话ID:', sessionId);
    });
    
    socket.on('disconnect', () => {
        console.log('与服务器断开连接');
        resetUI();
    });
    
    socket.on('scan_started', (data) => {
        console.log('扫描开始:', data.message);
        isScanning = true;
        canResume = false;
        updateUIForScanning(true);
    });
    
    socket.on('scan_progress', (data) => {
        updateProgress(data);
    });
    
    socket.on('port_found', (data) => {
        addPortResult(data);
    });
    
    socket.on('scan_complete', (data) => {
        console.log('扫描完成:', data);
        isScanning = false;
        canResume = false;
        updateUIForComplete();
    });
    
    socket.on('scan_stopped', (data) => {
        console.log('扫描停止:', data.message);
        isScanning = false;
        canResume = data.can_resume || false;
        updateUIForStopped();
    });
    
    socket.on('scan_error', (data) => {
        console.error('扫描错误:', data.message);
        showError(data.message);
        isScanning = false;
        updateUIForScanning(false);
    });
}

/**
 * 初始化事件监听
 */
function initEventListeners() {
    // 表单提交
    elements.form.addEventListener('submit', handleSubmit);
    
    // 停止按钮
    elements.stopBtn.addEventListener('click', handleStop);
    
    // 继续扫描按钮
    elements.resumeBtn.addEventListener('click', handleResume);
    
    // 线程数滑动条 -> 输入框同步
    elements.threads.addEventListener('input', (e) => {
        elements.threadsInput.value = e.target.value;
    });
    
    // 线程数输入框 -> 滑动条同步
    elements.threadsInput.addEventListener('input', (e) => {
        let value = parseInt(e.target.value, 10);
        // 范围限制
        if (value < 1) value = 1;
        if (value > 500) value = 500;
        
        // 滑动条使用最接近的10的倍数，但至少为10
        let sliderValue = Math.round(value / 10) * 10;
        if (sliderValue < 10) sliderValue = 10;
        elements.threads.value = sliderValue;
    });
    
    elements.threadsInput.addEventListener('blur', (e) => {
        let value = parseInt(e.target.value, 10) || 50;
        if (value < 1) value = 1;
        if (value > 500) value = 500;
        e.target.value = value;
        
        let sliderValue = Math.round(value / 10) * 10;
        if (sliderValue < 10) sliderValue = 10;
        elements.threads.value = sliderValue;
    });
    
    // 超时滑动条
    elements.timeout.addEventListener('input', (e) => {
        elements.timeoutValue.textContent = parseFloat(e.target.value).toFixed(1);
    });
    
    // 预设按钮
    document.querySelectorAll('.preset-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            elements.startPort.value = btn.dataset.start;
            elements.endPort.value = btn.dataset.end;
        });
    });
    
    // 导出按钮
    elements.exportBtn.addEventListener('click', handleExport);
    
    // IP输入验证
    elements.ipAddress.addEventListener('input', validateIP);
}

/**
 * 验证IP地址格式
 */
function validateIP() {
    const ip = elements.ipAddress.value.trim();
    const ipRegex = /^(\d{1,3}\.){3}\d{1,3}$/;
    
    if (!ip) {
        elements.ipError.textContent = '';
        return false;
    }
    
    if (!ipRegex.test(ip)) {
        elements.ipError.textContent = 'IP地址格式无效';
        return false;
    }
    
    const parts = ip.split('.');
    for (const part of parts) {
        const num = parseInt(part, 10);
        if (num < 0 || num > 255) {
            elements.ipError.textContent = 'IP地址各段必须在0-255之间';
            return false;
        }
    }
    
    elements.ipError.textContent = '';
    return true;
}

/**
 * 处理表单提交
 */
function handleSubmit(e) {
    e.preventDefault();
    
    if (isScanning) return;
    
    // 验证输入
    if (!validateIP()) {
        elements.ipAddress.focus();
        return;
    }
    
    const startPort = parseInt(elements.startPort.value, 10);
    const endPort = parseInt(elements.endPort.value, 10);
    
    if (startPort > endPort) {
        showError('起始端口不能大于结束端口');
        return;
    }
    
    // 清空之前的结果
    clearResults();
    canResume = false;
    
    // 发送扫描请求
    socket.emit('start_scan', {
        ip: elements.ipAddress.value.trim(),
        start_port: startPort,
        end_port: endPort,
        threads: parseInt(elements.threadsInput.value, 10),
        timeout: parseFloat(elements.timeout.value),
        resume: false
    });
}

/**
 * 处理继续扫描
 */
function handleResume() {
    if (isScanning || !canResume) return;
    
    // 发送当前设置的线程数和超时参数
    socket.emit('resume_scan', {
        threads: parseInt(elements.threadsInput.value, 10),
        timeout: parseFloat(elements.timeout.value)
    });
}

/**
 * 处理停止扫描
 */
function handleStop() {
    if (!isScanning) return;
    socket.emit('stop_scan');
}

/**
 * 处理导出CSV
 */
function handleExport() {
    if (!sessionId) return;
    window.open(`/export/${sessionId}`, '_blank');
}

/**
 * 更新扫描进度
 */
function updateProgress(data) {
    elements.progressFill.style.width = `${data.progress}%`;
    elements.progressText.textContent = `${data.progress}%`;
    elements.scanStats.textContent = `已扫描: ${data.scanned.toLocaleString()} / ${data.total.toLocaleString()} | 开放端口: ${data.open_count}`;
}

/**
 * 添加端口扫描结果
 */
function addPortResult(data) {
    // 移除空行提示
    const emptyRow = elements.resultsBody.querySelector('.empty-row');
    if (emptyRow) {
        emptyRow.remove();
    }
    
    // 创建新行
    const row = document.createElement('tr');
    row.className = 'new-row';
    row.innerHTML = `
        <td>${data.port}</td>
        <td>${data.service}</td>
        <td><span class="port-status open">● 开放</span></td>
    `;
    
    // 按端口号排序插入
    const rows = Array.from(elements.resultsBody.querySelectorAll('tr'));
    const insertIndex = rows.findIndex(r => {
        const port = parseInt(r.querySelector('td')?.textContent, 10);
        return port > data.port;
    });
    
    if (insertIndex === -1) {
        elements.resultsBody.appendChild(row);
    } else {
        elements.resultsBody.insertBefore(row, rows[insertIndex]);
    }
    
    // 更新计数
    const count = elements.resultsBody.querySelectorAll('tr:not(.empty-row)').length;
    elements.resultCount.textContent = `(${count})`;
}

/**
 * 清空结果
 */
function clearResults() {
    elements.resultsBody.innerHTML = '<tr class="empty-row"><td colspan="3">正在扫描...</td></tr>';
    elements.resultCount.textContent = '(0)';
}

/**
 * 更新UI为扫描中状态
 */
function updateUIForScanning(scanning) {
    elements.startBtn.disabled = scanning;
    elements.stopBtn.disabled = !scanning;
    elements.exportBtn.disabled = true;
    elements.resumeBtn.style.display = 'none';
    elements.resumeBtn.disabled = true;
    
    if (scanning) {
        elements.progressCard.style.display = 'block';
        elements.progressFill.style.width = '0%';
        elements.progressFill.classList.remove('paused');
        elements.progressText.textContent = '0%';
        elements.scanStats.textContent = '准备中...';
        elements.statusBadge.textContent = '进行中';
        elements.statusBadge.className = 'status-badge';
    }
}

/**
 * 更新UI为完成状态
 */
function updateUIForComplete() {
    elements.startBtn.disabled = false;
    elements.stopBtn.disabled = true;
    elements.exportBtn.disabled = false;
    elements.resumeBtn.style.display = 'none';
    elements.resumeBtn.disabled = true;
    elements.progressFill.classList.add('paused');
    elements.statusBadge.textContent = '已完成';
    elements.statusBadge.classList.add('complete');
}

/**
 * 更新UI为停止状态
 */
function updateUIForStopped() {
    elements.startBtn.disabled = false;
    elements.stopBtn.disabled = true;
    elements.exportBtn.disabled = false;
    elements.progressFill.classList.add('paused');
    elements.statusBadge.textContent = '已停止';
    elements.statusBadge.classList.add('stopped');
    
    // 显示继续扫描按钮
    if (canResume) {
        elements.resumeBtn.style.display = 'inline-flex';
        elements.resumeBtn.disabled = false;
    }
}

/**
 * 重置UI
 */
function resetUI() {
    isScanning = false;
    canResume = false;
    elements.startBtn.disabled = false;
    elements.stopBtn.disabled = true;
    elements.resumeBtn.style.display = 'none';
    elements.resumeBtn.disabled = true;
}

/**
 * 显示错误信息
 */
function showError(message) {
    elements.ipError.textContent = message;
    elements.ipAddress.focus();
}
