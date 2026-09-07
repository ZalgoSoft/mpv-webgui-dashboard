#!/usr/bin/env python3
"""
MPV Web Panel - HTTP server for controlling mpv via JSON IPC
"""

import json
import socket
import threading
import time
import queue
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from typing import Dict, List, Any, Optional, Set
import os
import sys

# Configuration
MPV_SOCKET = "/tmp/mpv-web-socket"
HOST = "0.0.0.0"
PORT = 8082
DEBUG = False  # Set to True for debug output

# Global state
mpv_data = {
    "commands": [],
    "properties": [],
    "property_info": {},
    "property_values": {},
    "input_bindings": [],
    "updating": False,
    "last_update": 0,
    "update_progress": 0,
    "update_total": 0
}

# Auto-update state on server
auto_update_enabled: Set[str] = set()
auto_update_values: Dict[str, Any] = {}
auto_update_thread = None
auto_update_running = False
auto_update_lock = threading.Lock()

# Event queue
event_queue = queue.Queue()

# Setup logging
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MPVConnection:
    """Client for JSON IPC communication with mpv"""
    
    def __init__(self, socket_path=MPV_SOCKET):
        self.socket_path = socket_path
        self.request_id = 0
        
    def _send_command(self, command: List[Any], async_mode: bool = False, request_id: Optional[int] = None) -> Dict:
        """Send command to mpv via JSON IPC"""
        if request_id is None:
            self.request_id += 1
            request_id = self.request_id
            
        msg = {
            "command": command,
            "request_id": request_id
        }
        if async_mode:
            msg["async"] = True
            
        try:
            logger.debug(f"Sending command: {json.dumps(msg)}")
            
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self.socket_path)
            
            json_msg = json.dumps(msg) + "\n"
            sock.send(json_msg.encode('utf-8'))
            
            response = ""
            while True:
                chunk = sock.recv(4096).decode('utf-8')
                if not chunk:
                    break
                response += chunk
                if '\n' in chunk:
                    break
                    
            sock.close()
            
            logger.debug(f"Received response: {response}")
            
            lines = response.strip().split('\n')
            for line in lines:
                if line.strip():
                    try:
                        data = json.loads(line)
                        if data.get('request_id') == request_id:
                            return data
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON decode error: {e}")
            
            return {"error": "no_response", "data": None}
            
        except Exception as e:
            logger.error(f"MPV connection error: {e}")
            return {"error": str(e), "data": None}
    
    def get_command_list(self) -> Dict:
        """Get list of available commands"""
        return self._send_command(["get_property", "command-list"])
    
    def get_property_list(self) -> Dict:
        """Get list of properties"""
        return self._send_command(["get_property", "property-list"])
    
    def get_input_bindings(self) -> Dict:
        """Get input bindings"""
        return self._send_command(["get_property", "input-bindings"])
    
    def get_option_info(self, option_name: str) -> Dict:
        """Get option information"""
        return self._send_command(["get_property", f"option-info/{option_name}"])
    
    def get_property_value(self, prop_name: str) -> Dict:
        """Get property value"""
        return self._send_command(["get_property", prop_name])
    
    def set_property(self, prop_name: str, value: Any) -> Dict:
        """Set property value"""
        return self._send_command(["set_property", prop_name, value])
    
    def execute_command(self, cmd_name: str, args: List[Any]) -> Dict:
        """Execute command"""
        return self._send_command([cmd_name] + args)


class MPVDataCollector:
    """Collect data from mpv with progress tracking"""
    
    def __init__(self):
        self.mpv = MPVConnection()
        self.lock = threading.Lock()
        
    def collect_all(self):
        """Collect all data with progress tracking"""
        with self.lock:
            mpv_data["updating"] = True
            mpv_data["update_progress"] = 0
            mpv_data["update_total"] = 0
            
            try:
                logger.info("Starting data collection from mpv")
                
                # Get command list
                logger.debug("Fetching command list...")
                cmd_response = self.mpv.get_command_list()
                if cmd_response.get('error') == 'success':
                    mpv_data["commands"] = cmd_response.get('data', [])
                    logger.info(f"Loaded {len(mpv_data['commands'])} commands")
                mpv_data["update_progress"] += 1
                
                # Get property list
                logger.debug("Fetching property list...")
                prop_response = self.mpv.get_property_list()
                if prop_response.get('error') == 'success':
                    mpv_data["properties"] = prop_response.get('data', [])
                    logger.info(f"Loaded {len(mpv_data['properties'])} properties")
                mpv_data["update_progress"] += 1
                
                # Get input bindings
                logger.debug("Fetching input bindings...")
                bind_response = self.mpv.get_input_bindings()
                if bind_response.get('error') == 'success':
                    mpv_data["input_bindings"] = bind_response.get('data', [])
                    logger.info(f"Loaded {len(mpv_data['input_bindings'])} input bindings")
                mpv_data["update_progress"] += 1
                
                # Collect property info and values
                mpv_data["property_info"] = {}
                mpv_data["property_values"] = {}
                
                total_props = len(mpv_data["properties"])
                mpv_data["update_total"] = total_props + 3
                
                for idx, prop in enumerate(mpv_data["properties"]):
                    if prop.startswith('option-info/'):
                        continue
                    
                    if idx % 10 == 0:
                        logger.debug(f"Fetching property info: {idx}/{total_props}")
                    
                    info = self.mpv.get_option_info(prop)
                    if info.get('error') == 'success' and info.get('data'):
                        mpv_data["property_info"][prop] = info.get('data')
                    
                    value = self.mpv.get_property_value(prop)
                    if value.get('error') == 'success':
                        mpv_data["property_values"][prop] = value.get('data')
                    
                    mpv_data["update_progress"] += 1
                    time.sleep(0.005)
                
                logger.info("Data collection completed")
                
            except Exception as e:
                logger.error(f"Error collecting data: {e}", exc_info=True)
            
            mpv_data["updating"] = False
            mpv_data["last_update"] = time.time()


class AutoUpdateThread:
    """Thread for auto-updating property values on server"""
    
    def __init__(self):
        self.running = False
        self.thread = None
        self.mpv = MPVConnection()
        self.update_interval = 0.5
        
    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()
        logger.info("Auto-update thread started")
        
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        logger.info("Auto-update thread stopped")
        
    def _run(self):
        while self.running:
            try:
                with auto_update_lock:
                    if auto_update_enabled:
                        for prop_name in list(auto_update_enabled):
                            value = self.mpv.get_property_value(prop_name)
                            if value.get('error') == 'success':
                                auto_update_values[prop_name] = value.get('data')
                                logger.debug(f"Auto-updated {prop_name}: {value.get('data')}")
                            time.sleep(0.01)
            except Exception as e:
                logger.error(f"Auto-update error: {e}")
            time.sleep(self.update_interval)


class HTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler"""
    
    def do_GET(self):
        """Handle GET requests"""
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        
        logger.debug(f"GET request: {path}")
        
        if path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode('utf-8'))
            
        elif path == '/api/status':
            self.send_json_response({
                'commands': len(mpv_data["commands"]),
                'properties': len(mpv_data["properties"]),
                'bindings': len(mpv_data["input_bindings"]),
                'updating': mpv_data["updating"],
                'last_update': mpv_data["last_update"],
                'progress': mpv_data["update_progress"],
                'total': mpv_data["update_total"]
            })
            
        elif path == '/api/commands':
            self.send_json_response(mpv_data["commands"])
            
        elif path == '/api/properties':
            self.send_json_response({
                'properties': mpv_data["properties"],
                'property_info': mpv_data["property_info"],
                'property_values': mpv_data["property_values"]
            })
            
        elif path == '/api/bindings':
            self.send_json_response(mpv_data["input_bindings"])
            
        elif path == '/api/property/value':
            prop_name = query.get('name', [''])[0]
            if prop_name:
                mpv = MPVConnection()
                value = mpv.get_property_value(prop_name)
                self.send_json_response(value)
            else:
                self.send_json_response({'error': 'Property name required'}, 400)
                
        elif path == '/api/auto-update/values':
            with auto_update_lock:
                values = dict(auto_update_values)
            self.send_json_response(values)
            
        elif path == '/api/auto-update/status':
            self.send_json_response({
                'running': auto_update_running,
                'properties': list(auto_update_enabled)
            })
            
        elif path == '/api/update':
            threading.Thread(target=self._update_mpv_data).start()
            self.send_json_response({'status': 'updating'})
            
        elif path == '/api/update/single':
            threading.Thread(target=self._single_update).start()
            self.send_json_response({'status': 'updating'})
            
        else:
            self.send_response(404)
            self.end_headers()
            
    def do_POST(self):
        """Handle POST requests"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        
        logger.debug(f"POST request: {self.path}, data: {post_data[:200]}...")
        
        try:
            data = json.loads(post_data) if post_data else {}
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            self.send_json_response({'error': 'Invalid JSON'}, 400)
            return
            
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == '/api/command/execute':
            cmd_name = data.get('command', '')
            args = data.get('args', [])
            if cmd_name:
                mpv = MPVConnection()
                result = mpv.execute_command(cmd_name, args)
                logger.info(f"Executed command: {cmd_name} with args: {args}")
                self.send_json_response(result)
            else:
                self.send_json_response({'error': 'Command name required'}, 400)
                
        elif path == '/api/property/set':
            prop_name = data.get('name', '')
            value = data.get('value')
            if prop_name:
                mpv = MPVConnection()
                result = mpv.set_property(prop_name, value)
                logger.info(f"Set property: {prop_name} = {value}")
                self.send_json_response(result)
            else:
                self.send_json_response({'error': 'Property name required'}, 400)
                
        elif path == '/api/auto-update/toggle':
            prop_name = data.get('name', '')
            if prop_name:
                global auto_update_running, auto_update_thread
                
                with auto_update_lock:
                    if prop_name in auto_update_enabled:
                        auto_update_enabled.remove(prop_name)
                        auto_update_values.pop(prop_name, None)
                        enabled = False
                    else:
                        auto_update_enabled.add(prop_name)
                        enabled = True
                
                if auto_update_enabled and not auto_update_running:
                    auto_update_thread = AutoUpdateThread()
                    auto_update_thread.start()
                    auto_update_running = True
                elif not auto_update_enabled and auto_update_running:
                    auto_update_thread.stop()
                    auto_update_running = False
                
                logger.info(f"Auto-update for {prop_name}: {enabled}")
                self.send_json_response({'status': 'ok', 'enabled': enabled})
            else:
                self.send_json_response({'error': 'Property name required'}, 400)
                
        else:
            self.send_response(404)
            self.end_headers()
            
    def _update_mpv_data(self):
        collector = MPVDataCollector()
        collector.collect_all()
        
    def _single_update(self):
        mpv = MPVConnection()
        updated = {}
        
        for prop in mpv_data["properties"]:
            if prop.startswith('option-info/'):
                continue
            value = mpv.get_property_value(prop)
            if value.get('error') == 'success':
                mpv_data["property_values"][prop] = value.get('data')
                updated[prop] = value.get('data')
            time.sleep(0.005)
        
        logger.info(f"Single update completed: {len(updated)} properties updated")
        
    def send_json_response(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        response = json.dumps(data, ensure_ascii=False)
        self.wfile.write(response.encode('utf-8'))
        
    def log_message(self, format, *args):
        logger.debug(f"HTTP: {format % args}")


# HTML Page with compact design and brighter colors
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MPV Panel</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d0d0d; 
            color: #e8e8e8; 
            padding: 12px;
            font-size: 13px;
        }
        .container { max-width: 100%; }
        h1 { 
            color: #ff6b6b; 
            font-size: 20px;
            margin-bottom: 12px;
            font-weight: 600;
            letter-spacing: -0.5px;
        }
        .status-bar { 
            background: #1a1a1a; 
            padding: 10px 15px; 
            border-radius: 8px; 
            margin-bottom: 12px; 
            border: 1px solid #2a2a2a; 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            flex-wrap: wrap; 
            gap: 8px; 
        }
        .status-bar .info { display: flex; gap: 15px; flex-wrap: wrap; font-size: 12px; }
        .status-bar .info span { color: #888; }
        .status-bar .info strong { color: #ff6b6b; }
        .btn { 
            background: #2a2a2a; 
            color: #e8e8e8; 
            border: 1px solid #3a3a3a; 
            padding: 5px 14px; 
            border-radius: 5px; 
            cursor: pointer; 
            font-size: 12px; 
            transition: all 0.2s; 
        }
        .btn:hover { background: #3a3a3a; border-color: #ff6b6b; }
        .btn-primary { background: #ff6b6b; color: #0d0d0d; border-color: #ff6b6b; }
        .btn-primary:hover { background: #ff5252; border-color: #ff5252; }
        .btn-success { background: #51cf66; color: #0d0d0d; border-color: #51cf66; }
        .btn-success:hover { background: #40c057; border-color: #40c057; }
        .tabs { 
            display: flex; 
            gap: 6px; 
            margin-bottom: 12px; 
            flex-wrap: wrap; 
        }
        .tab { 
            padding: 6px 16px; 
            background: #1a1a1a; 
            border: 1px solid #2a2a2a; 
            border-radius: 6px; 
            cursor: pointer; 
            transition: all 0.2s; 
            color: #888; 
            font-size: 13px;
        }
        .tab:hover { background: #2a2a2a; color: #e8e8e8; }
        .tab.active { background: #ff6b6b; color: #0d0d0d; border-color: #ff6b6b; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .search-box { 
            background: #1a1a1a; 
            border: 1px solid #2a2a2a; 
            color: #e8e8e8; 
            padding: 6px 12px; 
            border-radius: 6px; 
            width: 100%; 
            max-width: 250px; 
            margin-bottom: 12px; 
            font-size: 13px; 
        }
        .search-box:focus { outline: none; border-color: #ff6b6b; }
        .grid { 
            display: grid; 
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); 
            gap: 10px; 
        }
        .card { 
            background: #1a1a1a; 
            border: 1px solid #2a2a2a; 
            border-radius: 8px; 
            padding: 12px; 
            transition: all 0.2s;
            cursor: default;
        }
        .card:hover { 
            border-color: #ff6b6b; 
            transform: translateY(-1px);
            box-shadow: 0 2px 12px rgba(255,107,107,0.1);
        }
        .card .name { 
            font-weight: 600; 
            color: #ff6b6b; 
            margin-bottom: 4px; 
            font-size: 14px;
            word-break: break-all;
        }
        .card .type { color: #888; font-size: 11px; margin-bottom: 4px; }
        .card .value { 
            background: #0d0d0d; 
            padding: 6px 10px; 
            border-radius: 5px; 
            font-family: 'Courier New', monospace; 
            font-size: 12px; 
            margin: 6px 0; 
            overflow-x: auto; 
            max-height: 120px; 
            overflow-y: auto;
            border: 1px solid #1a1a1a;
        }
        .card .value .nested { padding-left: 12px; border-left: 2px solid #ff6b6b; margin: 3px 0; }
        .card .value .nested-item { display: flex; gap: 8px; padding: 2px 0; font-size: 12px; }
        .card .value .nested-item .key { color: #ff6b6b; }
        .card .value .nested-item .val { color: #51cf66; }
        .card .actions { display: flex; gap: 5px; margin-top: 8px; flex-wrap: wrap; }
        .card .actions .btn { font-size: 11px; padding: 4px 10px; }
        .card .auto-update { 
            display: flex; 
            align-items: center; 
            gap: 6px; 
            margin-top: 6px; 
            font-size: 11px; 
            color: #888;
        }
        .card .auto-update input[type="checkbox"] { 
            accent-color: #ff6b6b; 
            width: 14px; 
            height: 14px; 
            cursor: pointer; 
        }
        .cmd-args { margin: 4px 0; }
        .cmd-arg { 
            display: inline-block; 
            background: #0d0d0d; 
            padding: 2px 8px; 
            border-radius: 3px; 
            margin: 2px 3px 2px 0; 
            font-size: 11px; 
            font-family: 'Courier New', monospace; 
            border: 1px solid #1a1a1a; 
        }
        .cmd-arg.optional { opacity: 0.6; }
        .cmd-arg .arg-name { color: #ff6b6b; }
        .cmd-arg .arg-type { color: #888; }
        .bindings-key { 
            display: inline-block; 
            background: #0d0d0d; 
            padding: 2px 10px; 
            border-radius: 4px; 
            font-family: 'Courier New', monospace; 
            font-size: 12px; 
            border: 1px solid #ff6b6b; 
            margin: 2px;
            color: #ff6b6b;
        }
        .bindings-cmd { color: #51cf66; font-family: 'Courier New', monospace; font-size: 12px; }
        .loading { text-align: center; padding: 30px; color: #888; font-size: 14px; }
        .badge { 
            display: inline-block; 
            padding: 1px 8px; 
            border-radius: 3px; 
            font-size: 10px; 
            margin-left: 4px; 
        }
        .badge-success { background: #51cf66; color: #0d0d0d; }
        .badge-warning { background: #fcc419; color: #0d0d0d; }
        .badge-error { background: #ff6b6b; color: #0d0d0d; }
        .toast { 
            position: fixed; 
            bottom: 20px; 
            right: 20px; 
            background: #1a1a1a; 
            border: 1px solid #2a2a2a; 
            border-radius: 6px; 
            padding: 10px 20px; 
            z-index: 2000; 
            display: none; 
            font-size: 13px;
        }
        .toast.show { display: block; animation: fadeIn 0.3s; }
        .toast.success { border-color: #51cf66; }
        .toast.error { border-color: #ff6b6b; }
        .progress-bar { 
            width: 100%; 
            height: 3px; 
            background: #1a1a1a; 
            border-radius: 2px; 
            overflow: hidden; 
            margin: 4px 0; 
        }
        .progress-bar .fill { height: 100%; background: #ff6b6b; transition: width 0.3s; }
        .range-control { 
            display: flex; 
            align-items: center; 
            gap: 8px; 
            margin: 4px 0;
        }
        .range-control input[type="range"] {
            flex: 1;
            height: 4px;
            -webkit-appearance: none;
            background: #2a2a2a;
            border-radius: 2px;
            outline: none;
        }
        .range-control input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 14px;
            height: 14px;
            border-radius: 50%;
            background: #ff6b6b;
            cursor: pointer;
        }
        .range-control .range-val {
            min-width: 40px;
            text-align: center;
            color: #ff6b6b;
            font-size: 12px;
            font-weight: 600;
        }
        select, input[type="text"] {
            background: #0d0d0d;
            border: 1px solid #2a2a2a;
            color: #e8e8e8;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            width: 100%;
        }
        select:focus, input[type="text"]:focus {
            outline: none;
            border-color: #ff6b6b;
        }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } .search-box { max-width: 100%; } }
    </style>
</head>
<body>
<div class="container">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:10px;">
        <h1>🎬 MPV Panel</h1>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
            <button class="btn btn-primary" onclick="updateData()">⟳ Refresh</button>
            <button class="btn btn-success" onclick="singleUpdate()">⚡ Values</button>
            <button class="btn" onclick="toggleAllAutoUpdate()">⏱ Auto</button>
        </div>
    </div>
    <div class="status-bar">
        <div class="info">
            <span>Cmd: <strong id="cmdCount">0</strong></span>
            <span>Prop: <strong id="propCount">0</strong></span>
            <span>Bind: <strong id="bindCount">0</strong></span>
            <span id="statusText" style="color:#51cf66;">● Ready</span>
        </div>
        <div style="font-size:12px;color:#888;" id="progressText"></div>
    </div>
    <div class="progress-bar" id="progressBar" style="display:none;"><div class="fill" id="progressFill" style="width:0%"></div></div>
    
    <div class="tabs">
        <div class="tab active" onclick="switchTab('commands')">📋 Commands</div>
        <div class="tab" onclick="switchTab('properties')">⚙️ Properties</div>
        <div class="tab" onclick="switchTab('bindings')">⌨️ Bindings</div>
    </div>
    
    <div id="tab-commands" class="tab-content active">
        <input type="text" class="search-box" placeholder="Search commands..." oninput="filterItems('commands', this.value)">
        <div id="commands-grid" class="grid"></div>
    </div>
    
    <div id="tab-properties" class="tab-content">
        <input type="text" class="search-box" placeholder="Search properties..." oninput="filterItems('properties', this.value)">
        <div id="properties-grid" class="grid"></div>
    </div>
    
    <div id="tab-bindings" class="tab-content">
        <input type="text" class="search-box" placeholder="Search bindings..." oninput="filterItems('bindings', this.value)">
        <div id="bindings-grid" class="grid"></div>
    </div>
</div>
<div class="toast" id="toast"></div>

<script>
let commandsData = [], propertiesData = [], propertyInfo = {}, propertyValues = {}, bindingsData = [];
let autoUpdateEnabled = new Set(), currentFilter = '', autoUpdateValues = {};
let hoverTimers = {};

function showToast(msg, type='success') {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast show ' + type;
    clearTimeout(t._timeout);
    t._timeout = setTimeout(() => t.className = 'toast', 2500);
}

function switchTab(tab) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelector(`.tab[onclick="switchTab('${tab}')"]`).classList.add('active');
    document.getElementById(`tab-${tab}`).classList.add('active');
    if (tab === 'commands') renderCommands(commandsData);
    else if (tab === 'properties') renderProperties(propertiesData);
    else renderBindings(bindingsData);
}

function filterItems(type, filter) {
    currentFilter = filter.toLowerCase();
    if (type === 'commands') renderCommands(commandsData);
    else if (type === 'properties') renderProperties(propertiesData);
    else renderBindings(bindingsData);
}

function formatValue(v) {
    if (v === null || v === undefined) return '—';
    if (typeof v === 'object') return JSON.stringify(v, null, 2);
    return String(v);
}

function renderNested(obj) {
    if (obj === null || obj === undefined) return '—';
    if (typeof obj !== 'object') return formatValue(obj);
    let html = '<div class="nested">';
    for (const [k, v] of Object.entries(obj)) {
        if (typeof v === 'object' && v !== null) {
            html += `<div class="nested-item"><span class="key">${k}:</span>${renderNested(v)}</div>`;
        } else {
            html += `<div class="nested-item"><span class="key">${k}:</span><span class="val">${formatValue(v)}</span></div>`;
        }
    }
    html += '</div>';
    return html;
}

function renderCommands(cmds) {
    const grid = document.getElementById('commands-grid');
    const filtered = cmds.filter(c => c.name.toLowerCase().includes(currentFilter));
    if (!filtered.length) { grid.innerHTML = '<div class="loading">No commands</div>'; return; }
    grid.innerHTML = filtered.map(c => `
        <div class="card">
            <div class="name">${c.name}</div>
            <div class="cmd-args">
                ${c.args && c.args.length ? c.args.map(a => 
                    `<span class="cmd-arg ${a.optional?'optional':''}">
                        <span class="arg-name">${a.name}</span>:<span class="arg-type">${a.type}</span>
                        ${a.optional ? '↕' : ''}
                        ${a.choices ? ' ['+a.choices.join('|')+']' : ''}
                    </span>`
                ).join('') : '<span style="color:#666;font-size:11px;">No args</span>'}
            </div>
            <div class="type">${c.vararg ? '↕ Variable args' : 'Fixed args'}</div>
            <div class="actions">
                <button class="btn btn-primary" onclick="executeCmd('${c.name}')">▶ Execute</button>
            </div>
        </div>
    `).join('');
}

function renderProperties(props) {
    const grid = document.getElementById('properties-grid');
    const filtered = props.filter(p => p.toLowerCase().includes(currentFilter) && !p.startsWith('option-info/'));
    if (!filtered.length) { grid.innerHTML = '<div class="loading">No properties</div>'; return; }
    grid.innerHTML = filtered.map(p => {
        const info = propertyInfo[p] || {};
        const val = propertyValues[p];
        const isAuto = autoUpdateEnabled.has(p);
        const valHtml = typeof val === 'object' && val !== null ? renderNested(val) : 
            `<pre style="margin:0;font-family:inherit;font-size:12px;">${formatValue(val)}</pre>`;
        
        let ctrlHtml = '';
        if (info.type === 'Flag') {
            ctrlHtml = `<input type="checkbox" ${val ? 'checked' : ''} onchange="setProp('${p}', this.checked)" style="accent-color:#ff6b6b;">`;
        } else if (info.type === 'Integer' || info.type === 'Integer64') {
            const mn = info.min !== undefined ? info.min : 0;
            const mx = info.max !== undefined ? info.max : 100;
            const v = val !== undefined ? val : 0;
            ctrlHtml = `<div class="range-control">
                <input type="range" min="${mn}" max="${mx}" step="1" value="${v}" 
                    oninput="document.getElementById('rv-${p}').textContent=this.value; setProp('${p}', parseInt(this.value))">
                <span class="range-val" id="rv-${p}">${v}</span>
            </div>`;
        } else if (info.type === 'Double' || info.type === 'Time') {
            const mn = info.min !== undefined ? info.min : 0;
            const mx = info.max !== undefined ? info.max : 100;
            const st = info.type === 'Time' ? 0.1 : 0.01;
            const v = val !== undefined ? val : 0;
            ctrlHtml = `<div class="range-control">
                <input type="range" min="${mn}" max="${mx}" step="${st}" value="${v}" 
                    oninput="document.getElementById('rv-${p}').textContent=Number(this.value).toFixed(2); setProp('${p}', parseFloat(this.value))">
                <span class="range-val" id="rv-${p}">${Number(v).toFixed(2)}</span>
            </div>`;
        } else if (info.choices && info.choices.length) {
            ctrlHtml = `<select onchange="setProp('${p}', this.value)">
                ${info.choices.map(c => `<option value="${c}" ${c===val?'selected':''}>${c}</option>`).join('')}
            </select>`;
        } else if (info.type === 'String') {
            ctrlHtml = `<input type="text" value="${val!==undefined?val:''}" onchange="setProp('${p}', this.value)">`;
        }
        
        return `
            <div class="card" id="prop-${p}" 
                 onmouseenter="startHoverUpdate('${p}')" 
                 onmouseleave="stopHoverUpdate('${p}')">
                <div class="name">${p}</div>
                <div class="type">${info.type||'Unknown'}${info.default_value!==undefined ? ' | def: '+formatValue(info.default_value) : ''}</div>
                ${info.min!==undefined ? `<div class="type">min: ${info.min}</div>` : ''}
                ${info.max!==undefined ? `<div class="type">max: ${info.max}</div>` : ''}
                ${info.choices ? `<div class="type">choices: ${info.choices.join(', ')}</div>` : ''}
                <div class="value" id="value-${p}">${valHtml}</div>
                ${ctrlHtml ? `<div style="margin:4px 0;">${ctrlHtml}</div>` : ''}
                <div class="auto-update">
                    <input type="checkbox" ${isAuto?'checked':''} onchange="toggleAuto('${p}')">
                    <span>Auto</span>
                    <button class="btn" onclick="getProp('${p}')" style="margin-left:auto;font-size:10px;padding:2px 8px;">↻</button>
                </div>
            </div>
        `;
    }).join('');
}

function renderBindings(bindings) {
    const grid = document.getElementById('bindings-grid');
    const filtered = bindings.filter(b => 
        (b.key||'').toLowerCase().includes(currentFilter) ||
        (b.cmd||'').toLowerCase().includes(currentFilter) ||
        (b.comment||'').toLowerCase().includes(currentFilter)
    );
    if (!filtered.length) { grid.innerHTML = '<div class="loading">No bindings</div>'; return; }
    grid.innerHTML = filtered.map(b => `
        <div class="card">
            <div class="name"><span class="bindings-key">${b.key||'N/A'}</span></div>
            <div class="bindings-cmd">${b.cmd||'No command'}</div>
            ${b.comment ? `<div class="type" style="color:#888;">${b.comment}</div>` : ''}
            <div class="type">${b.section||'default'}${b.is_weak?' weak':''}${b.owner?' owner:'+b.owner:''}</div>
        </div>
    `).join('');
}

async function executeCmd(name) {
    const cmd = commandsData.find(c => c.name === name);
    if (!cmd) return;
    let args = [];
    if (cmd.args && cmd.args.length) {
        const inputs = cmd.args.map((a,i) => 
            `${a.name} (${a.type})${a.optional?' [opt]':''}`
        ).join(' ');
        const argStr = prompt(`Args for ${name}: ${inputs} Separate with commas:`);
        if (argStr === null) return;
        if (argStr.trim()) {
            args = argStr.split(',').map(s => s.trim());
            args = args.map((v,i) => {
                const a = cmd.args[i];
                if (!a) return v;
                if (a.type === 'Integer' || a.type === 'Integer64') return parseInt(v);
                if (a.type === 'Double' || a.type === 'Time' || a.type === 'Float') return parseFloat(v);
                if (a.type === 'Flag') return v.toLowerCase() === 'true' || v === '1';
                if (a.type === 'Choice') { const n = parseFloat(v); return !isNaN(n) ? n : v; }
                return v;
            });
        }
    }
    try {
        const r = await fetch('/api/command/execute', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({command:name, args})
        });
        const res = await r.json();
        showToast(res.error === 'success' ? `✓ ${name}` : `✗ ${res.error}`, res.error === 'success' ? 'success' : 'error');
    } catch(e) { showToast('Error: '+e.message, 'error'); }
}

async function getProp(name) {
    try {
        const r = await fetch(`/api/property/value?name=${encodeURIComponent(name)}`);
        const d = await r.json();
        if (d.error === 'success') {
            propertyValues[name] = d.data;
            const el = document.getElementById(`value-${name}`);
            if (el) el.innerHTML = typeof d.data === 'object' && d.data !== null ? 
                renderNested(d.data) : `<pre style="margin:0;font-family:inherit;font-size:12px;">${formatValue(d.data)}</pre>`;
        }
    } catch(e) { showToast('Error: '+e.message, 'error'); }
}

async function setProp(name, val) {
    try {
        const r = await fetch('/api/property/set', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({name, value:val})
        });
        const d = await r.json();
        if (d.error === 'success') {
            propertyValues[name] = val;
            const el = document.getElementById(`value-${name}`);
            if (el) el.innerHTML = typeof val === 'object' && val !== null ? 
                renderNested(val) : `<pre style="margin:0;font-family:inherit;font-size:12px;">${formatValue(val)}</pre>`;
        }
    } catch(e) { showToast('Error: '+e.message, 'error'); }
}

async function toggleAuto(name) {
    try {
        const r = await fetch('/api/auto-update/toggle', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({name})
        });
        const d = await r.json();
        if (d.status === 'ok') {
            if (d.enabled) autoUpdateEnabled.add(name);
            else autoUpdateEnabled.delete(name);
        }
    } catch(e) { showToast('Error: '+e.message, 'error'); }
}

async function toggleAllAutoUpdate() {
    const any = autoUpdateEnabled.size > 0;
    for (const p of propertiesData) {
        if (p.startsWith('option-info/')) continue;
        try {
            const r = await fetch('/api/auto-update/toggle', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({name:p})
            });
            const d = await r.json();
            if (d.status === 'ok') {
                if (d.enabled) autoUpdateEnabled.add(p);
                else autoUpdateEnabled.delete(p);
            }
        } catch(e) { console.error(e); }
    }
    renderProperties(propertiesData);
    showToast(any ? 'Auto OFF' : 'Auto ON');
}

function startHoverUpdate(name) {
    if (hoverTimers[name]) clearInterval(hoverTimers[name]);
    hoverTimers[name] = setInterval(() => getProp(name), 1000);
}

function stopHoverUpdate(name) {
    if (hoverTimers[name]) {
        clearInterval(hoverTimers[name]);
        delete hoverTimers[name];
    }
}

async function updateData() {
    showToast('Updating...');
    document.getElementById('statusText').textContent = '⏳ Updating...';
    document.getElementById('progressBar').style.display = 'block';
    try {
        await fetch('/api/update', {method:'POST'});
        await checkProgress();
    } catch(e) { showToast('Error: '+e.message, 'error'); }
}

async function singleUpdate() {
    try {
        await fetch('/api/update/single', {method:'POST'});
        await new Promise(r => setTimeout(r, 500));
        await loadData();
        showToast('Values updated');
    } catch(e) { showToast('Error: '+e.message, 'error'); }
}

async function checkProgress() {
    let done = false;
    while (!done) {
        const r = await fetch('/api/status');
        const s = await r.json();
        if (!s.updating) done = true;
        else if (s.total > 0) {
            const pct = Math.round((s.progress / s.total) * 100);
            document.getElementById('progressFill').style.width = pct + '%';
            document.getElementById('progressText').textContent = `${s.progress}/${s.total}`;
        }
        await new Promise(r => setTimeout(r, 500));
    }
    document.getElementById('progressBar').style.display = 'none';
    document.getElementById('progressText').textContent = '';
    await loadData();
    showToast('Updated');
}

async function loadData() {
    try {
        let r = await fetch('/api/commands');
        commandsData = await r.json();
        r = await fetch('/api/properties');
        const d = await r.json();
        propertiesData = d.properties || [];
        propertyInfo = d.property_info || {};
        propertyValues = d.property_values || {};
        r = await fetch('/api/bindings');
        bindingsData = await r.json();
        r = await fetch('/api/auto-update/status');
        const as = await r.json();
        autoUpdateEnabled = new Set(as.properties || []);
        
        document.getElementById('cmdCount').textContent = commandsData.length;
        document.getElementById('propCount').textContent = propertiesData.length;
        document.getElementById('bindCount').textContent = bindingsData.length;
        document.getElementById('statusText').textContent = '● Ready';
        document.getElementById('statusText').style.color = '#51cf66';
        
        renderCommands(commandsData);
        renderProperties(propertiesData);
        renderBindings(bindingsData);
    } catch(e) {
        document.getElementById('statusText').textContent = '✗ Error';
        document.getElementById('statusText').style.color = '#ff6b6b';
        showToast('Load error: '+e.message, 'error');
    }
}

// Auto-update values from server
setInterval(async () => {
    if (autoUpdateEnabled.size > 0) {
        try {
            const r = await fetch('/api/auto-update/values');
            const vals = await r.json();
            for (const [p, v] of Object.entries(vals)) {
                propertyValues[p] = v;
                const el = document.getElementById(`value-${p}`);
                if (el) {
                    el.innerHTML = typeof v === 'object' && v !== null ? 
                        renderNested(v) : `<pre style="margin:0;font-family:inherit;font-size:12px;">${formatValue(v)}</pre>`;
                }
            }
        } catch(e) { console.error('Auto fetch error:', e); }
    }
}, 800);

loadData();
</script>
</body>
</html>
"""


def main():
    """Start the server"""
    if not os.path.exists(MPV_SOCKET):
        logger.warning(f"Socket {MPV_SOCKET} not found")
        logger.warning("Make sure mpv is running with --input-ipc-server=/tmp/mpv-web-socket")
    
    logger.info("Starting initial data collection...")
    collector = MPVDataCollector()
    threading.Thread(target=collector.collect_all, daemon=True).start()
    
    server = HTTPServer((HOST, PORT), HTTPHandler)
    logger.info(f"🚀 MPV Web Panel running at http://{HOST}:{PORT}")
    logger.info(f"📡 Using socket: {MPV_SOCKET}")
    logger.info(f"🐛 Debug mode: {'ON' if DEBUG else 'OFF'}")
    logger.info("Press Ctrl+C to stop")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("\nStopping server...")
        if auto_update_running and auto_update_thread:
            auto_update_thread.stop()
        server.shutdown()
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
