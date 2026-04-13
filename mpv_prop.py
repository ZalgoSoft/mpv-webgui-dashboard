#!/usr/bin/env python3
import json
import socket
import threading
import time
#from http.server import HTTPServer, BaseHTTPRequestListener
from http.server import HTTPServer, BaseHTTPRequestHandler

from urllib.parse import parse_qs, urlparse
import os

SOCKET_PATH = "/tmp/mpv-web-socket"
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>MPV Property Inspector</title>
    <meta charset="utf-8">
    <style>
/* Основные стили */
* {
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Arial', sans-serif;
    margin: 0;
    padding: 20px;
    background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
    color: #e0e0e0;
    min-height: 100vh;
}

/* Контролы */
#controls {
    position: sticky;
    top: 0;
    background: rgba(30, 30, 30, 0.95);
    backdrop-filter: blur(10px);
    padding: 15px 20px;
    z-index: 1000;
    border-radius: 12px;
    margin-bottom: 20px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
    border: 1px solid #444;
}

button {
    padding: 10px 20px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    background: linear-gradient(135deg, #5a9e5a 0%, #4CAF50 100%);
    color: white;
    border: none;
    border-radius: 8px;
    transition: all 0.2s ease;
    box-shadow: 0 2px 8px rgba(76, 175, 80, 0.2);
}

button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(76, 175, 80, 0.3);
    background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
}

button:active {
    transform: translateY(0);
}

.search-input {
    flex: 1;
    min-width: 250px;
    padding: 10px 16px;
    font-size: 14px;
    background: #333;
    border: 1px solid #555;
    border-radius: 8px;
    color: #fff;
    transition: all 0.2s ease;
}

.search-input:focus {
    outline: none;
    border-color: #4CAF50;
    box-shadow: 0 0 0 3px rgba(76, 175, 80, 0.1);
    background: #3a3a3a;
}

.search-input::placeholder {
    color: #999;
}

/* Статус */
#status {
    margin: 15px 0;
    padding: 10px 16px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    background: #2a2a2a;
    border-left: 4px solid #4CAF50;
}

.loading {
    color: #ffaa00;
    animation: pulse 1.5s ease-in-out infinite;
}

.error {
    color: #ff5555;
}

.success {
    color: #55ff55;
}

/* Группы */
.group-container {
    margin: 25px 0;
    background: #2a2a2a;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
    border: 1px solid #3a3a3a;
    transition: box-shadow 0.2s ease;
}

.group-container:hover {
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.3);
}

.group-header {
    padding: 16px 20px;
    background: linear-gradient(135deg, #333 0%, #2d2d2d 100%);
    border-bottom: 2px solid #4CAF50;
    cursor: pointer;
    user-select: none;
    display: flex;
    align-items: center;
    gap: 12px;
    transition: background 0.2s ease;
}

.group-header:hover {
    background: linear-gradient(135deg, #383838 0%, #333 100%);
}

.group-header.collapsed {
    border-bottom-color: #555;
}

.group-title {
    font-size: 18px;
    font-weight: 600;
    color: #fff;
    letter-spacing: 0.3px;
}

.group-count {
    background: #4CAF50;
    color: white;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
}

/* Сетка свойств */
.properties-grid {
    padding: 5px 0;
}

.property-row {
    display: grid;
    grid-template-columns: 250px 1fr;
    border-bottom: 1px solid #3a3a3a;
    transition: background 0.15s ease;
    animation: fadeIn 0.3s ease;
}

.property-row:hover {
    background: #323232;
}

.property-row:last-child {
    border-bottom: none;
}

.property-name {
    padding: 12px 16px;
    font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
    font-size: 13px;
    color: #6ed4c0;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
    border-right: 1px solid #3a3a3a;
    word-break: break-word;
}

.property-name:hover {
    background: #3a3a3a;
    color: #8ee4d0;
    padding-left: 20px;
}

.property-value {
    padding: 8px 16px;
    font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
    font-size: 13px;
    word-break: break-word;
    display: flex;
    align-items: center;
    min-height: 45px;
}

/* Вложенные структуры */
.object-container,
.array-container {
    width: 100%;
}

.object-header,
.array-header {
    padding: 8px 12px;
    background: #333;
    border-radius: 6px;
    cursor: pointer;
    user-select: none;
    font-weight: 600;
    font-size: 12px;
    color: #aaa;
    transition: all 0.15s ease;
    border: 1px solid #444;
    margin-bottom: 4px;
}

.object-header:hover,
.array-header:hover {
    background: #3a3a3a;
    color: #fff;
    border-color: #4CAF50;
}

.toggle-icon {
    display: inline-block;
    width: 16px;
    margin-right: 4px;
    color: #4CAF50;
    transition: transform 0.2s ease;
}

.nested-content {
    margin-left: 16px;
    padding-left: 12px;
    border-left: 2px solid #4CAF50;
    display: block;
    animation: slideDown 0.2s ease;
}

.array-item {
    display: flex;
    align-items: flex-start;
    margin: 6px 0;
    padding: 4px 0;
}

.array-index {
    min-width: 40px;
    color: #888;
    font-size: 12px;
    font-weight: 500;
    padding: 4px 8px 4px 0;
}

.array-value {
    flex: 1;
}

.object-property {
    display: flex;
    align-items: flex-start;
    margin: 6px 0;
    padding: 4px 0;
}

.object-key {
    min-width: 120px;
    color: #6ed4c0;
    font-weight: 500;
    padding: 4px 12px 4px 0;
}

.object-value {
    flex: 1;
}

/* Типы значений */
.null-value {
    color: #888;
    font-style: italic;
}

.boolean-value {
    font-weight: 600;
}

.boolean-value.true {
    color: #55cc55;
}

.boolean-value.false {
    color: #cc5555;
}

.number-value {
    color: #b5cea8;
}

.string-value {
    color: #ce9178;
}

.empty-array,
.empty-object {
    color: #888;
    font-style: italic;
}

/* Уведомления */
.notification {
    position: fixed;
    top: 20px;
    right: 20px;
    padding: 12px 20px;
    background: #333;
    color: white;
    border-radius: 8px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    z-index: 9999;
    opacity: 0;
    transform: translateX(400px);
    transition: all 0.3s ease;
    border-left: 4px solid #4CAF50;
}

.notification.show {
    opacity: 1;
    transform: translateX(0);
}

.notification.success {
    border-left-color: #4CAF50;
}

.notification.error {
    border-left-color: #f44336;
}

.notification.info {
    border-left-color: #2196F3;
}

/* Анимации */
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(-10px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes slideDown {
    from { opacity: 0; transform: translateY(-5px); }
    to { opacity: 1; transform: translateY(0); }
}

/* Скроллбар */
::-webkit-scrollbar {
    width: 10px;
    height: 10px;
}

::-webkit-scrollbar-track {
    background: #2a2a2a;
    border-radius: 5px;
}

::-webkit-scrollbar-thumb {
    background: #555;
    border-radius: 5px;
}

::-webkit-scrollbar-thumb:hover {
    background: #666;
}

/* Адаптивность */
@media (max-width: 768px) {
    body {
        padding: 10px;
    }
    
    .property-row {
        grid-template-columns: 1fr;
    }
    
    .property-name {
        border-right: none;
        border-bottom: 1px solid #3a3a3a;
        background: #323232;
    }
    
    .object-property {
        flex-direction: column;
    }
    
    .object-key {
        min-width: auto;
        margin-bottom: 4px;
    }
    
    #controls {
        flex-direction: column;
        align-items: stretch;
    }
    
    .search-input {
        width: 100%;
    }
}
    </style>
</head>
<body>
    <div id="controls">
        <button onclick="getPropertyList()">📋 Get Property List</button>
        <button onclick="getAllProperties()">🔍 Get All Properties Values</button>
        <span id="status">Ready</span>
    </div>
    <div id="content">
        <div class="group-container">
            <div class="group-title">No data loaded</div>
            <p>Click "Get Property List" to load properties</p>
        </div>
    </div>
    <script>
let propertyGroups = {};
let propertyList = [];

async function apiCall(endpoint, body = null) {
    const options = {
        method: body ? 'POST' : 'GET',
        headers: body ? {'Content-Type': 'application/json'} : {}
    };
    if (body) options.body = JSON.stringify(body);
    
    try {
        const response = await fetch(endpoint, options);
        return await response.json();
    } catch (e) {
        console.error('API call failed:', e);
        return {error: e.message};
    }
}

async function getPropertyList() {
    document.getElementById('status').innerHTML = '<span class="loading">Loading property list...</span>';
    const result = await apiCall('/api/get_property_list');
    
    if (result.error && result.error !== 'success') {
        document.getElementById('status').innerHTML = `<span class="error">Error: ${result.error}</span>`;
        return;
    }
    
    propertyList = result.data || [];
    propertyGroups = groupProperties(propertyList);
    renderGroups();
    document.getElementById('status').innerHTML = `<span class="success">Loaded ${propertyList.length} properties</span>`;
}

function groupProperties(properties) {
    const groups = {
        'Playback': ['pause', 'speed', 'time-pos', 'duration', 'percent-pos', 'time-remaining', 'playback-time', 'eof-reached', 'seeking', 'core-idle'],
        'File & Stream': ['path', 'filename', 'media-title', 'file-size', 'file-format', 'stream-open-filename', 'stream-path', 'current-demuxer', 'demuxer-via-network', 'cache-speed', 'cache-buffering-state'],
        'Video': ['video-format', 'video-codec', 'video-params', 'width', 'height', 'dwidth', 'dheight', 'video-aspect-override', 'display-fps', 'estimated-vf-fps', 'container-fps', 'deinterlace-active', 'hwdec-current'],
        'Audio': ['volume', 'mute', 'audio-codec', 'audio-codec-name', 'audio-params', 'audio-device', 'aid', 'audio-delay', 'current-ao'],
        'Subtitles': ['sid', 'sub-delay', 'sub-speed', 'sub-pos', 'sub-text', 'sub-start', 'sub-end', 'secondary-sid', 'sub-visibility'],
        'Track Info': ['track-list', 'current-tracks', 'chapter', 'chapters', 'edition', 'editions', 'playlist', 'playlist-pos', 'playlist-count'],
        'Window & Display': ['fullscreen', 'window-scale', 'ontop', 'border', 'geometry', 'display-names', 'display-fps', 'focused', 'osd-width', 'osd-height'],
        'Options & Config': ['options', 'profile', 'config', 'config-dir', 'include', 'script-opts', 'watch-later-dir'],
        'MPV Info': ['mpv-version', 'ffmpeg-version', 'libass-version', 'platform', 'property-list', 'command-list', 'input-bindings']
    };
    
    const grouped = {};
    const assigned = new Set();
    
    for (const group of Object.keys(groups)) {
        grouped[group] = [];
    }
    grouped['Other'] = [];
    
    for (const prop of properties) {
        let found = false;
        for (const [group, props] of Object.entries(groups)) {
            if (props.includes(prop)) {
                grouped[group].push(prop);
                assigned.add(prop);
                found = true;
                break;
            }
        }
        if (!found) {
            grouped['Other'].push(prop);
        }
    }
    
    for (const group of Object.keys(grouped)) {
        grouped[group].sort();
    }
    
    return grouped;
}

// ========== РЕКУРСИВНАЯ ФУНКЦИЯ С DIV-СТРУКТУРОЙ ==========
function renderNestedDiv(data, depth = 0) {
    const id = `nested_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    
    // 1. Обработка null/undefined
    if (data === null || data === undefined) {
        return `<span class="null-value">null</span>`;
    }
    
    // 2. Обработка примитивов
    if (typeof data !== 'object') {
        if (typeof data === 'boolean') {
            return `<span class="boolean-value ${data}">${data ? '✓' : '✗'} ${data}</span>`;
        }
        if (typeof data === 'number') {
            const formatted = Number.isInteger(data) ? String(data) : data.toFixed(6).replace(/\\.?0+$/, '');
            return `<span class="number-value">${formatted}</span>`;
        }
        return `<span class="string-value">${String(data).replace(/</g, '&lt;').replace(/>/g, '&gt;')}</span>`;
    }
    
    // 3. Обработка массивов
    if (Array.isArray(data)) {
        if (data.length === 0) {
            return `<span class="empty-array">[ ]</span>`;
        }
        
        let html = `<div class="array-container">`;
        html += `<div class="array-header" onclick="toggleNested('${id}')">`;
        html += `<span class="toggle-icon">▼</span> Array [${data.length}]`;
        html += `</div>`;
        html += `<div id="${id}" class="nested-content">`;
        
        data.forEach((item, index) => {
            html += `<div class="array-item">`;
            html += `<span class="array-index">[${index}]</span>`;
            html += `<div class="array-value">${renderNestedDiv(item, depth + 1)}</div>`;
            html += `</div>`;
        });
        
        html += `</div></div>`;
        return html;
    }
    
    // 4. Обработка объектов
    if (Object.keys(data).length === 0) {
        return `<span class="empty-object">{ }</span>`;
    }
    
    let html = `<div class="object-container">`;
    html += `<div class="object-header" onclick="toggleNested('${id}')">`;
    html += `<span class="toggle-icon">▼</span> Object {${Object.keys(data).length}}`;
    html += `</div>`;
    html += `<div id="${id}" class="nested-content">`;
    
    const keys = Object.keys(data).sort();
    for (const key of keys) {
        html += `<div class="object-property">`;
        html += `<span class="object-key">${key}:</span>`;
        html += `<div class="object-value">${renderNestedDiv(data[key], depth + 1)}</div>`;
        html += `</div>`;
    }
    
    html += `</div></div>`;
    return html;
}

// ========== ФУНКЦИЯ ДЛЯ РАСКРЫТИЯ/СКРЫТИЯ ==========
function toggleNested(id) {
    const element = document.getElementById(id);
    const header = element.previousElementSibling;
    const icon = header.querySelector('.toggle-icon');
    
    if (element.style.display === 'none') {
        element.style.display = 'block';
        icon.textContent = '▼';
    } else {
        element.style.display = 'none';
        icon.textContent = '▶';
    }
}

// ========== КОПИРОВАНИЕ ЗНАЧЕНИЯ В БУФЕР ==========
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showNotification('Copied to clipboard!', 'success');
    } catch (err) {
        showNotification('Failed to copy', 'error');
    }
}

// ========== ПОКАЗ УВЕДОМЛЕНИЙ ==========
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.classList.add('show');
        setTimeout(() => {
            notification.classList.remove('show');
            setTimeout(() => notification.remove(), 300);
        }, 2000);
    }, 10);
}

// ========== ОТРИСОВКА ГРУПП ==========
function renderGroups() {
    const container = document.getElementById('content');
    let html = '';
    
    for (const [groupName, props] of Object.entries(propertyGroups)) {
        if (props.length === 0) continue;
        
        html += `<div class="group-container">`;
        html += `<div class="group-header">`;
        html += `<span class="group-title">${groupName}</span>`;
        html += `<span class="group-count">${props.length}</span>`;
        html += `</div>`;
        html += `<div class="properties-grid">`;
        
        for (const prop of props) {
            const safeId = prop.replace(/[^a-zA-Z0-9-]/g, '_');
            html += `<div class="property-row">`;
            html += `<div class="property-name" title="Click to copy" onclick="copyToClipboard('${prop}')">${prop}</div>`;
            html += `<div id="val_${safeId}" class="property-value" data-property="${prop}">—</div>`;
            html += `</div>`;
        }
        
        html += `</div></div>`;
    }
    
    container.innerHTML = html;
}

// ========== ПОЛУЧЕНИЕ ВСЕХ СВОЙСТВ ==========
async function getAllProperties() {
    if (propertyList.length === 0) {
        alert('Please load property list first');
        return;
    }
    
    document.getElementById('status').innerHTML = '<span class="loading">Getting all property values...</span>';
    
    const result = await apiCall('/api/get_all_properties', propertyList);
    
    if (result.error) {
        document.getElementById('status').innerHTML = `<span class="error">Error: ${result.error}</span>`;
        return;
    }
    
    let updatedCount = 0;
    for (const [prop, value] of Object.entries(result.values || {})) {
        const cell = document.getElementById(`val_${prop.replace(/[^a-zA-Z0-9-]/g, '_')}`);
        if (cell) {
            cell.innerHTML = renderNestedDiv(value);
            updatedCount++;
        }
    }
    
    document.getElementById('status').innerHTML = `<span class="success">Updated ${updatedCount} property values</span>`;
}

// ========== ФИЛЬТРАЦИЯ СВОЙСТВ ==========
function filterProperties(searchTerm) {
    const rows = document.querySelectorAll('.property-row');
    const groups = document.querySelectorAll('.group-container');
    
    rows.forEach(row => {
        const name = row.querySelector('.property-name').textContent.toLowerCase();
        if (name.includes(searchTerm.toLowerCase())) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
    
    // Скрываем пустые группы
    groups.forEach(group => {
        const visibleRows = group.querySelectorAll('.property-row:not([style*="display: none"])');
        if (visibleRows.length === 0) {
            group.style.display = 'none';
        } else {
            group.style.display = '';
        }
    });
}

// ========== СВОРАЧИВАНИЕ/РАЗВОРАЧИВАНИЕ ВСЕХ ГРУПП ==========
function toggleAllGroups(expand = true) {
    const groups = document.querySelectorAll('.group-container');
    groups.forEach(group => {
        const content = group.querySelector('.properties-grid');
        const header = group.querySelector('.group-header');
        if (expand) {
            content.style.display = '';
            header.classList.remove('collapsed');
        } else {
            content.style.display = 'none';
            header.classList.add('collapsed');
        }
    });
}

// ========== ИНИЦИАЛИЗАЦИЯ ==========
window.onload = () => {
    getPropertyList();
    
    // Добавляем поле поиска
    const controls = document.getElementById('controls');
    const searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.placeholder = '🔍 Filter properties...';
    searchInput.className = 'search-input';
    searchInput.oninput = (e) => filterProperties(e.target.value);
    controls.appendChild(searchInput);
    
    // Кнопки управления группами
    const expandAllBtn = document.createElement('button');
    expandAllBtn.textContent = 'Expand All';
    expandAllBtn.onclick = () => toggleAllGroups(true);
    
    const collapseAllBtn = document.createElement('button');
    collapseAllBtn.textContent = 'Collapse All';
    collapseAllBtn.onclick = () => toggleAllGroups(false);
    
    controls.appendChild(expandAllBtn);
    controls.appendChild(collapseAllBtn);
};
    </script>
</body>
</html>
"""

class MPVClient:
    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.request_id = 0
        self.lock = threading.Lock()
    
    def _send_command(self, command):
        """Отправляет команду в MPV и возвращает ответ"""
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(self.socket_path)
            
            with self.lock:
                self.request_id += 1
                req_id = self.request_id
            
            request = {"command": command, "request_id": req_id}
            sock.send((json.dumps(request) + "\n").encode())
            
            response_data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b"\n" in response_data:
                    break
            
            sock.close()
            
            if response_data:
                return json.loads(response_data.decode().strip())
            return {"error": "no response"}
            
        except FileNotFoundError:
            return {"error": f"Socket {self.socket_path} not found. Is MPV running with --input-ipc-server={self.socket_path}?"}
        except socket.timeout:
            return {"error": "Connection timeout"}
        except Exception as e:
            return {"error": str(e)}
    
    def get_property_list(self):
        """Получает список всех свойств"""
        return self._send_command(["get_property", "property-list"])
    
    def get_property(self, name):
        """Получает значение одного свойства"""
        return self._send_command(["get_property", name])
    
    def get_all_properties(self, properties):
        """Получает значения всех указанных свойств"""
        result = {}
        for prop in properties:
            resp = self.get_property(prop)
            if "data" in resp:
                result[prop] = resp["data"]
            else:
                result[prop] = None
        return result

class MPVHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode())
            
        elif parsed.path == "/api/get_property_list":
            mpv = MPVClient(SOCKET_PATH)
            response = mpv.get_property_list()
            self._send_json(response)
            
        else:
            self.send_error(404)
    
    def do_POST(self):
        parsed = urlparse(self.path)
        
        if parsed.path == "/api/get_all_properties":
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            
            try:
                properties = json.loads(body.decode())
                mpv = MPVClient(SOCKET_PATH)
                values = mpv.get_all_properties(properties)
                self._send_json({"values": values, "error": None})
            except Exception as e:
                self._send_json({"error": str(e)})
                
        else:
            self.send_error(404)
    
    def _send_json(self, data):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
#    def log_message(self, format, *args):
        # Подавляем стандартный вывод логов
#        pass

def main():
    # Проверяем существование сокета
    if not os.path.exists(SOCKET_PATH):
        print(f"Warning: Socket {SOCKET_PATH} does not exist.")
        print(f"Start MPV with: mpv --input-ipc-server={SOCKET_PATH}")
    
    server = HTTPServer(('0.0.0.0', 8081), MPVHandler)
    print(f"Server running at http://0.0.0.0:8081")
    print(f"MPV socket: {SOCKET_PATH}")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()

if __name__ == "__main__":
    main()
