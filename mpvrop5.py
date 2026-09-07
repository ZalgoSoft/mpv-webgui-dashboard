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
DEBUG = False

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

auto_update_enabled: Set[str] = set()
auto_update_values: Dict[str, Any] = {}
auto_update_thread = None
auto_update_running = False
auto_update_lock = threading.Lock()

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
        if request_id is None:
            self.request_id += 1
            request_id = self.request_id
            
        msg = {"command": command, "request_id": request_id}
        if async_mode:
            msg["async"] = True
            
        try:
            logger.debug(f"Sending: {json.dumps(msg)}")
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self.socket_path)
            sock.send((json.dumps(msg) + "\n").encode('utf-8'))
            
            response = ""
            while True:
                chunk = sock.recv(4096).decode('utf-8')
                if not chunk:
                    break
                response += chunk
                if '\n' in chunk:
                    break
            sock.close()
            
            for line in response.strip().split('\n'):
                if line.strip():
                    try:
                        data = json.loads(line)
                        if data.get('request_id') == request_id:
                            return data
                    except json.JSONDecodeError:
                        pass
            
            return {"error": "no_response", "data": None}
        except Exception as e:
            logger.error(f"MPV error: {e}")
            return {"error": str(e), "data": None}
    
    def get_command_list(self) -> Dict:
        return self._send_command(["get_property", "command-list"])
    
    def get_property_list(self) -> Dict:
        return self._send_command(["get_property", "property-list"])
    
    def get_input_bindings(self) -> Dict:
        return self._send_command(["get_property", "input-bindings"])
    
    def get_option_info(self, option_name: str) -> Dict:
        return self._send_command(["get_property", f"option-info/{option_name}"])
    
    def get_property_value(self, prop_name: str) -> Dict:
        return self._send_command(["get_property", prop_name])
    
    def set_property(self, prop_name: str, value: Any) -> Dict:
        return self._send_command(["set_property", prop_name, value])
    
    def execute_command(self, cmd_name: str, args: List[Any]) -> Dict:
        return self._send_command([cmd_name] + args)


class MPVDataCollector:
    """Collect data from mpv with progress tracking"""
    
    def __init__(self):
        self.mpv = MPVConnection()
        
    def collect_all(self):
        mpv_data["updating"] = True
        mpv_data["update_progress"] = 0
        mpv_data["update_total"] = 0
        
        try:
            logger.info("Starting data collection")
            
            # Get lists
            for key, method in [
                ("commands", self.mpv.get_command_list),
                ("properties", self.mpv.get_property_list),
                ("input_bindings", self.mpv.get_input_bindings)
            ]:
                response = method()
                if response.get('error') == 'success':
                    mpv_data[key] = response.get('data', [])
                    logger.info(f"Loaded {len(mpv_data[key])} {key}")
                mpv_data["update_progress"] += 1
            
            # Get property info and values
            mpv_data["property_info"] = {}
            mpv_data["property_values"] = {}
            
            total = len(mpv_data["properties"])
            mpv_data["update_total"] = total + 3
            
            for idx, prop in enumerate(mpv_data["properties"]):
                if prop.startswith('option-info/'):
                    continue
                
                info = self.mpv.get_option_info(prop)
                if info.get('error') == 'success' and info.get('data'):
                    mpv_data["property_info"][prop] = info.get('data')
                else:
                    mpv_data["property_info"][prop] = {"type": "String"}
                
                value = self.mpv.get_property_value(prop)
                mpv_data["property_values"][prop] = value.get('data') if value.get('error') == 'success' else None
                
                mpv_data["update_progress"] += 1
                time.sleep(0.005)
            
            logger.info("Data collection completed")
        except Exception as e:
            logger.error(f"Collection error: {e}", exc_info=True)
        
        mpv_data["updating"] = False
        mpv_data["last_update"] = time.time()


class AutoUpdateThread:
    """Thread for auto-updating property values"""
    
    def __init__(self):
        self.running = False
        self.thread = None
        self.mpv = MPVConnection()
        
    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info("Auto-update started")
        
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        logger.info("Auto-update stopped")
        
    def _run(self):
        while self.running:
            try:
                with auto_update_lock:
                    for prop_name in list(auto_update_enabled):
                        value = self.mpv.get_property_value(prop_name)
                        if value.get('error') == 'success':
                            auto_update_values[prop_name] = value.get('data')
                        time.sleep(0.01)
            except Exception as e:
                logger.error(f"Auto-update error: {e}")
            time.sleep(0.5)


class HTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler"""
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        
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
                self.send_json_response(mpv.get_property_value(prop_name))
            else:
                self.send_json_response({'error': 'Property name required'}, 400)
        elif path == '/api/auto-update/values':
            with auto_update_lock:
                self.send_json_response(dict(auto_update_values))
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
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        
        try:
            data = json.loads(post_data) if post_data else {}
        except json.JSONDecodeError:
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
                logger.info(f"Executed: {cmd_name}({args})")
                self.send_json_response(result)
            else:
                self.send_json_response({'error': 'Command required'}, 400)
        elif path == '/api/property/set':
            prop_name = data.get('name', '')
            value = data.get('value')
            if prop_name:
                mpv = MPVConnection()
                result = mpv.set_property(prop_name, value)
                logger.info(f"Set: {prop_name} = {value}")
                self.send_json_response(result)
            else:
                self.send_json_response({'error': 'Property required'}, 400)
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
                
                self.send_json_response({'status': 'ok', 'enabled': enabled})
            else:
                self.send_json_response({'error': 'Property required'}, 400)
        elif path == '/api/binding/execute':
            cmd = data.get('cmd', '')
            if cmd:
                mpv = MPVConnection()
                # Parse command string
                parts = cmd.split()
                cmd_name = parts[0] if parts else ''
                args = parts[1:] if len(parts) > 1 else []
                result = mpv.execute_command(cmd_name, args)
                logger.info(f"Executed binding: {cmd}")
                self.send_json_response(result)
            else:
                self.send_json_response({'error': 'Command required'}, 400)
        else:
            self.send_response(404)
            self.end_headers()
            
    def _update_mpv_data(self):
        MPVDataCollector().collect_all()
        
    def _single_update(self):
        mpv = MPVConnection()
        for prop in mpv_data["properties"]:
            if prop.startswith('option-info/'):
                continue
            value = mpv.get_property_value(prop)
            if value.get('error') == 'success':
                mpv_data["property_values"][prop] = value.get('data')
            time.sleep(0.005)
        logger.info("Single update completed")
        
    def send_json_response(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        
    def log_message(self, format, *args):
        logger.debug(f"HTTP: {format % args}")


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
            background: #f0f2f5;
            color: #1a1a2e;
            padding: 16px;
            font-size: 13px;
        }
        .container { max-width: 100%; }
        
        h1 { 
            color: #e94560;
            font-size: 22px;
            margin-bottom: 16px;
            font-weight: 700;
            letter-spacing: -0.5px;
        }
        
        .status-bar { 
            background: #ffffff;
            padding: 12px 18px;
            border-radius: 12px;
            margin-bottom: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
        }
        .status-bar .info { display: flex; gap: 20px; flex-wrap: wrap; font-size: 13px; }
        .status-bar .info span { color: #6c757d; }
        .status-bar .info strong { color: #e94560; font-weight: 600; }
        
        .btn { 
            background: #ffffff;
            color: #1a1a2e;
            border: 1px solid #dee2e6;
            padding: 6px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 500;
            transition: all 0.2s;
        }
        .btn:hover { 
            background: #f8f9fa;
            border-color: #e94560;
            transform: translateY(-1px);
            box-shadow: 0 2px 8px rgba(233,69,96,0.15);
        }
        .btn-primary { 
            background: #e94560;
            color: #fff;
            border-color: #e94560;
        }
        .btn-primary:hover { 
            background: #c73652;
            border-color: #c73652;
            box-shadow: 0 2px 12px rgba(233,69,96,0.3);
        }
        .btn-success { 
            background: #2d8a4e;
            color: #fff;
            border-color: #2d8a4e;
        }
        .btn-success:hover { 
            background: #237040;
            border-color: #237040;
        }
        .btn-sm { padding: 4px 12px; font-size: 11px; }
        
        .tabs { 
            display: flex; 
            gap: 8px; 
            margin-bottom: 16px; 
            flex-wrap: wrap; 
        }
        .tab { 
            padding: 8px 20px; 
            background: #ffffff;
            border: 1px solid #dee2e6;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.2s;
            color: #6c757d;
            font-size: 13px;
            font-weight: 500;
        }
        .tab:hover { 
            background: #f8f9fa;
            color: #1a1a2e;
        }
        .tab.active { 
            background: #e94560;
            color: #fff;
            border-color: #e94560;
            box-shadow: 0 2px 12px rgba(233,69,96,0.25);
        }
        
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        .search-box { 
            background: #ffffff;
            border: 1px solid #dee2e6;
            color: #1a1a2e;
            padding: 8px 14px;
            border-radius: 8px;
            width: 100%;
            max-width: 280px;
            margin-bottom: 16px;
            font-size: 13px;
            transition: border-color 0.2s;
        }
        .search-box:focus { 
            outline: none;
            border-color: #e94560;
            box-shadow: 0 0 0 3px rgba(233,69,96,0.1);
        }
        
        .filter-buttons { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px; }
        .filter-btn { 
            padding: 4px 14px;
            background: #ffffff;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            color: #6c757d;
            cursor: pointer;
            font-size: 11px;
            transition: all 0.2s;
        }
        .filter-btn:hover { 
            border-color: #e94560;
            color: #1a1a2e;
        }
        .filter-btn.active { 
            background: #e94560;
            color: #fff;
            border-color: #e94560;
        }
        
        .grid { 
            display: grid; 
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); 
            gap: 12px; 
        }
        
        .card { 
            background: #ffffff;
            border: 1px solid #e9ecef;
            border-radius: 12px;
            padding: 14px;
            transition: all 0.2s;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }
        .card:hover { 
            border-color: #e94560;
            transform: translateY(-2px);
            box-shadow: 0 4px 16px rgba(0,0,0,0.08);
        }
        
        .card .name { 
            font-weight: 600;
            color: #e94560;
            margin-bottom: 6px;
            font-size: 14px;
            word-break: break-all;
        }
        .card .type { 
            color: #6c757d;
            font-size: 11px;
            margin-bottom: 4px;
        }
        .card .value { 
            background: #f8f9fa;
            padding: 8px 12px;
            border-radius: 6px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            margin: 6px 0;
            overflow-x: auto;
            max-height: 120px;
            overflow-y: auto;
            border: 1px solid #e9ecef;
        }
        .card .value .nested { padding-left: 12px; border-left: 2px solid #e94560; margin: 3px 0; }
        .card .value .nested-item { display: flex; gap: 8px; padding: 2px 0; font-size: 12px; }
        .card .value .nested-item .key { color: #e94560; font-weight: 500; }
        .card .value .nested-item .val { color: #2d8a4e; }
        
        .card .actions { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
        .card .actions .btn { font-size: 11px; padding: 4px 12px; }
        
        .card .auto-update { 
            display: flex; 
            align-items: center; 
            gap: 8px; 
            margin-top: 8px;
            font-size: 12px;
            color: #6c757d;
        }
        .card .auto-update input[type="checkbox"] { 
            accent-color: #e94560;
            width: 16px;
            height: 16px;
            cursor: pointer;
        }
        
        .cmd-args { margin: 6px 0; }
        .cmd-arg { 
            background: #f8f9fa;
            padding: 6px 10px;
            border-radius: 6px;
            margin: 4px 0;
            font-size: 12px;
            border: 1px solid #e9ecef;
        }
        .cmd-arg .arg-label { 
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
            margin-bottom: 4px;
        }
        .cmd-arg .arg-name { color: #e94560; font-weight: 500; }
        .cmd-arg .arg-type { color: #6c757d; font-size: 11px; }
        .cmd-arg .arg-optional { color: #adb5bd; font-size: 10px; }
        
        .cmd-arg input, .cmd-arg select { 
            background: #ffffff;
            border: 1px solid #dee2e6;
            color: #1a1a2e;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            flex: 1;
            min-width: 80px;
            transition: border-color 0.2s;
        }
        .cmd-arg input:focus, .cmd-arg select:focus { 
            outline: none;
            border-color: #e94560;
            box-shadow: 0 0 0 3px rgba(233,69,96,0.1);
        }
        .cmd-arg input[type="color"] { 
            width: 40px;
            height: 32px;
            padding: 2px;
            cursor: pointer;
        }
        .cmd-arg input[type="checkbox"] { 
            width: 16px;
            height: 16px;
            accent-color: #e94560;
            flex: 0 0 auto;
        }
        .cmd-arg .range-control {
            display: flex;
            align-items: center;
            gap: 10px;
            flex: 1;
        }
        .cmd-arg .range-control input[type="range"] {
            flex: 1;
            height: 4px;
            -webkit-appearance: none;
            background: #dee2e6;
            border-radius: 2px;
            outline: none;
        }
        .cmd-arg .range-control input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 14px;
            height: 14px;
            border-radius: 50%;
            background: #e94560;
            cursor: pointer;
        }
        .cmd-arg .range-control .range-val {
            min-width: 40px;
            text-align: center;
            color: #e94560;
            font-size: 12px;
            font-weight: 600;
        }
        
        .bindings-key { 
            display: inline-block;
            background: #f8f9fa;
            padding: 2px 12px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            border: 1px solid #e94560;
            color: #e94560;
            font-weight: 600;
        }
        .bindings-cmd { 
            color: #2d8a4e;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            word-break: break-all;
        }
        
        .loading { 
            text-align: center;
            padding: 40px;
            color: #6c757d;
            font-size: 14px;
        }
        
        .badge { 
            display: inline-block;
            padding: 2px 10px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 600;
            margin-left: 4px;
        }
        .badge-success { background: #d4edda; color: #155724; }
        .badge-warning { background: #fff3cd; color: #856404; }
        .badge-error { background: #f8d7da; color: #721c24; }
        
        .toast { 
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: #ffffff;
            border: 1px solid #e9ecef;
            border-radius: 10px;
            padding: 12px 24px;
            z-index: 2000;
            display: none;
            font-size: 13px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.12);
        }
        .toast.show { display: block; animation: slideIn 0.3s; }
        .toast.success { border-left: 4px solid #2d8a4e; }
        .toast.error { border-left: 4px solid #e94560; }
        
        .progress-bar { 
            width: 100%;
            height: 3px;
            background: #e9ecef;
            border-radius: 2px;
            overflow: hidden;
            margin: 6px 0;
        }
        .progress-bar .fill { 
            height: 100%;
            background: linear-gradient(90deg, #e94560, #ff6b6b);
            transition: width 0.3s;
        }
        
        .range-control { 
            display: flex;
            align-items: center;
            gap: 10px;
            margin: 6px 0;
        }
        .range-control input[type="range"] {
            flex: 1;
            height: 4px;
            -webkit-appearance: none;
            background: #dee2e6;
            border-radius: 2px;
            outline: none;
        }
        .range-control input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 16px;
            height: 16px;
            border-radius: 50%;
            background: #e94560;
            cursor: pointer;
        }
        .range-control .range-val {
            min-width: 45px;
            text-align: center;
            color: #e94560;
            font-size: 13px;
            font-weight: 600;
        }
        
        select, input[type="text"] {
            background: #ffffff;
            border: 1px solid #dee2e6;
            color: #1a1a2e;
            padding: 6px 10px;
            border-radius: 6px;
            font-size: 12px;
            width: 100%;
            transition: border-color 0.2s;
        }
        select:focus, input[type="text"]:focus {
            outline: none;
            border-color: #e94560;
            box-shadow: 0 0 0 3px rgba(233,69,96,0.1);
        }
        input[type="color"] {
            background: #ffffff;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            padding: 2px;
            cursor: pointer;
            width: 50px;
            height: 34px;
        }
        
        .updown-control {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .updown-control input[type="number"] {
            flex: 1;
            background: #ffffff;
            border: 1px solid #dee2e6;
            color: #1a1a2e;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            width: 100%;
        }
        .updown-control input[type="number"]:focus {
            outline: none;
            border-color: #e94560;
        }
        .updown-control .updown-btns {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .updown-control .updown-btns button {
            background: #f8f9fa;
            border: 1px solid #dee2e6;
            color: #1a1a2e;
            padding: 1px 8px;
            border-radius: 3px;
            cursor: pointer;
            font-size: 11px;
            line-height: 1.2;
        }
        .updown-control .updown-btns button:hover {
            background: #e94560;
            color: #fff;
            border-color: #e94560;
        }
        
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            .search-box { max-width: 100%; }
        }
    </style>
</head>
<body>
<div class="container">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px;">
        <h1>🎬 MPV Panel</h1>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
            <button class="btn btn-primary" onclick="updateData()">⟳ Refresh</button>
            <button class="btn btn-success" onclick="singleUpdate()">⚡ Values</button>
            <button class="btn" onclick="toggleAllAutoUpdate()">⏱ Auto</button>
            <button class="btn" onclick="toggleVisibleUpdate()">👁 Visible</button>
        </div>
    </div>
    
    <div class="status-bar">
        <div class="info">
            <span>Cmd: <strong id="cmdCount">0</strong></span>
            <span>Prop: <strong id="propCount">0</strong></span>
            <span>Bind: <strong id="bindCount">0</strong></span>
            <span id="statusText" style="color:#2d8a4e;">● Ready</span>
        </div>
        <div style="font-size:12px;color:#6c757d;" id="progressText"></div>
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
        <div class="filter-buttons" id="filterButtons">
            <button class="filter-btn active" data-type="all">All</button>
            <button class="filter-btn" data-type="String">String</button>
            <button class="filter-btn" data-type="Integer">Integer</button>
            <button class="filter-btn" data-type="Float">Float</button>
            <button class="filter-btn" data-type="Double">Double</button>
            <button class="filter-btn" data-type="Choice">Choice</button>
            <button class="filter-btn" data-type="Flag">Flag</button>
            <button class="filter-btn" data-type="Color">Color</button>
        </div>
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
let autoUpdateEnabled = new Set(), currentFilter = '', typeFilter = 'all';
let visibleUpdate = false, visibleInterval = null;

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

function setTypeFilter(type) {
    typeFilter = type;
    document.querySelectorAll('.filter-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.type === type);
    });
    renderProperties(propertiesData);
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
    if (!filtered.length) { grid.innerHTML = '<div class="loading">No commands found</div>'; return; }
    
    grid.innerHTML = filtered.map(c => {
        let argsHtml = '';
        if (c.args && c.args.length) {
            argsHtml = c.args.map((a, idx) => {
                let inputHtml = '';
                const hasMinMax = a.min !== undefined || a.max !== undefined;
                
                if (a.type === 'Flag') {
                    inputHtml = `<input type="checkbox" id="cmd_${c.name}_${idx}" style="width:16px;height:16px;accent-color:#e94560;">`;
                } else if ((a.type === 'Integer' || a.type === 'Integer64') && hasMinMax) {
                    const mn = a.min !== undefined ? a.min : 0;
                    const mx = a.max !== undefined ? a.max : 100;
                    inputHtml = `<div class="updown-control">
                        <input type="number" id="cmd_${c.name}_${idx}" min="${mn}" max="${mx}" value="0" step="1">
                    </div>`;
                } else if ((a.type === 'Float' || a.type === 'Double') && hasMinMax) {
                    const mn = a.min !== undefined ? a.min : 0;
                    const mx = a.max !== undefined ? a.max : 100;
                    inputHtml = `<div class="updown-control">
                        <input type="number" id="cmd_${c.name}_${idx}" min="${mn}" max="${mx}" value="0" step="0.1">
                    </div>`;
                } else if (a.type === 'Integer' || a.type === 'Integer64') {
                    inputHtml = `<div class="range-control">
                        <input type="range" id="cmd_${c.name}_${idx}" min="0" max="100" step="1" value="0"
                            oninput="document.getElementById('cmdv_${c.name}_${idx}').textContent=this.value">
                        <span class="range-val" id="cmdv_${c.name}_${idx}">0</span>
                    </div>`;
                } else if (a.type === 'Float' || a.type === 'Double') {
                    inputHtml = `<div class="range-control">
                        <input type="range" id="cmd_${c.name}_${idx}" min="0" max="100" step="0.1" value="0"
                            oninput="document.getElementById('cmdv_${c.name}_${idx}').textContent=Number(this.value).toFixed(1)">
                        <span class="range-val" id="cmdv_${c.name}_${idx}">0.0</span>
                    </div>`;
                } else if (a.type === 'Color') {
                    inputHtml = `<input type="color" id="cmd_${c.name}_${idx}" value="#FF000000">`;
                } else if (a.choices && a.choices.length) {
                    inputHtml = `<select id="cmd_${c.name}_${idx}">
                        ${a.choices.map(ch => `<option value="${ch}">${ch}</option>`).join('')}
                    </select>`;
                } else {
                    inputHtml = `<input type="text" id="cmd_${c.name}_${idx}" placeholder="Enter value">`;
                }
                
                return `<div class="cmd-arg">
                    <div class="arg-label">
                        <span class="arg-name">${a.name}</span>
                        <span class="arg-type">${a.type}</span>
                        ${a.optional ? '<span class="arg-optional">(optional)</span>' : ''}
                        ${a.min !== undefined ? `<span class="arg-optional">min:${a.min}</span>` : ''}
                        ${a.max !== undefined ? `<span class="arg-optional">max:${a.max}</span>` : ''}
                    </div>
                    ${inputHtml}
                </div>`;
            }).join('');
        } else {
            argsHtml = '<div style="color:#6c757d;font-size:11px;padding:4px 0;">No arguments</div>';
        }
        
        return `
            <div class="card">
                <div class="name">${c.name}</div>
                <div class="type">${c.vararg ? '↕ Variable arguments' : 'Fixed arguments'}</div>
                ${argsHtml}
                <div class="actions">
                    <button class="btn btn-primary btn-sm" onclick="executeCmd('${c.name}')">▶ Execute</button>
                </div>
            </div>
        `;
    }).join('');
}

function renderProperties(props) {
    const grid = document.getElementById('properties-grid');
    const filtered = props.filter(p => {
        if (p.startsWith('option-info/')) return false;
        if (!p.toLowerCase().includes(currentFilter)) return false;
        if (typeFilter !== 'all') {
            const info = propertyInfo[p] || {};
            return info.type === typeFilter;
        }
        return true;
    });
    
    if (!filtered.length) { grid.innerHTML = '<div class="loading">No properties found</div>'; return; }
    
    grid.innerHTML = filtered.map(p => {
        const info = propertyInfo[p] || { type: 'String' };
        const val = propertyValues[p];
        const isAuto = autoUpdateEnabled.has(p);
        const valHtml = typeof val === 'object' && val !== null ? renderNested(val) : 
            `<pre style="margin:0;font-family:inherit;font-size:12px;">${formatValue(val)}</pre>`;
        
        let ctrlHtml = '';
        const type = info.type || 'String';
        const hasMinMax = info.min !== undefined || info.max !== undefined;
        
        if (type === 'Flag') {
            ctrlHtml = `<input type="checkbox" ${val ? 'checked' : ''} onchange="setProp('${p}', this.checked)" style="accent-color:#e94560;">`;
        } else if ((type === 'Integer' || type === 'Integer64') && hasMinMax) {
            const mn = info.min !== undefined ? info.min : 0;
            const mx = info.max !== undefined ? info.max : 100;
            const v = val !== undefined && val !== null ? val : 0;
            ctrlHtml = `<div class="updown-control">
                <input type="number" min="${mn}" max="${mx}" value="${v}" step="1" 
                    onchange="setProp('${p}', parseInt(this.value))">
            </div>`;
        } else if ((type === 'Float' || type === 'Double') && hasMinMax) {
            const mn = info.min !== undefined ? info.min : 0;
            const mx = info.max !== undefined ? info.max : 100;
            const v = val !== undefined && val !== null ? val : 0;
            ctrlHtml = `<div class="updown-control">
                <input type="number" min="${mn}" max="${mx}" value="${v}" step="0.1" 
                    onchange="setProp('${p}', parseFloat(this.value))">
            </div>`;
        } else if (type === 'Integer' || type === 'Integer64') {
            const mn = info.min !== undefined ? info.min : 0;
            const mx = info.max !== undefined ? info.max : 100;
            const v = val !== undefined && val !== null ? val : 0;
            ctrlHtml = `<div class="range-control">
                <input type="range" min="${mn}" max="${mx}" step="1" value="${v}" 
                    oninput="document.getElementById('rv-${p}').textContent=this.value; setProp('${p}', parseInt(this.value))">
                <span class="range-val" id="rv-${p}">${v}</span>
            </div>`;
        } else if (type === 'Float' || type === 'Double') {
            const mn = info.min !== undefined ? info.min : 0;
            const mx = info.max !== undefined ? info.max : 100;
            const v = val !== undefined && val !== null ? val : 0;
            ctrlHtml = `<div class="range-control">
                <input type="range" min="${mn}" max="${mx}" step="0.1" value="${v}" 
                    oninput="document.getElementById('rv-${p}').textContent=Number(this.value).toFixed(1); setProp('${p}', parseFloat(this.value))">
                <span class="range-val" id="rv-${p}">${Number(v).toFixed(1)}</span>
            </div>`;
        } else if (type === 'Color') {
            ctrlHtml = `<input type="color" value="${val || '#FF000000'}" onchange="setProp('${p}', this.value)">`;
        } else if (info.choices && info.choices.length) {
            ctrlHtml = `<select onchange="setProp('${p}', this.value)">
                ${info.choices.map(c => `<option value="${c}" ${c===val?'selected':''}>${c}</option>`).join('')}
            </select>`;
        } else {
            ctrlHtml = `<input type="text" value="${val !== undefined && val !== null ? val : ''}" onchange="setProp('${p}', this.value)">`;
        }
        
        return `
            <div class="card" id="prop-${p}">
                <div class="name">${p}</div>
                <div class="type">${type}${info.default_value !== undefined ? ' | default: '+formatValue(info.default_value) : ''}</div>
                ${info.min !== undefined ? `<div class="type">min: ${info.min}</div>` : ''}
                ${info.max !== undefined ? `<div class="type">max: ${info.max}</div>` : ''}
                ${info.choices ? `<div class="type">choices: ${info.choices.join(', ')}</div>` : ''}
                <div class="value" id="value-${p}">${valHtml}</div>
                ${ctrlHtml ? `<div style="margin:6px 0;">${ctrlHtml}</div>` : ''}
                <div class="auto-update">
                    <input type="checkbox" ${isAuto?'checked':''} onchange="toggleAuto('${p}')">
                    <span>Auto-update</span>
                    <button class="btn btn-sm" onclick="getProp('${p}')" style="margin-left:auto;">↻ Get</button>
                    <button class="btn btn-primary btn-sm" onclick="setPropFromField('${p}')">Set</button>
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
    if (!filtered.length) { grid.innerHTML = '<div class="loading">No bindings found</div>'; return; }
    
    grid.innerHTML = filtered.map(b => `
        <div class="card">
            <div class="name"><span class="bindings-key">${b.key||'N/A'}</span></div>
            <div class="bindings-cmd">${b.cmd||'No command'}</div>
            ${b.comment ? `<div class="type" style="color:#6c757d;">${b.comment}</div>` : ''}
            <div class="type">${b.section||'default'}${b.is_weak?' weak':''}${b.owner?' owner:'+b.owner:''}</div>
            ${b.cmd ? `<div class="actions"><button class="btn btn-primary btn-sm" onclick="executeBinding('${b.cmd.replace(/'/g, "\\'")}')">▶ Execute</button></div>` : ''}
        </div>
    `).join('');
}

async function executeCmd(name) {
    const cmd = commandsData.find(c => c.name === name);
    if (!cmd) return;
    
    const args = [];
    let valid = true;
    
    if (cmd.args && cmd.args.length) {
        for (let i = 0; i < cmd.args.length; i++) {
            const el = document.getElementById(`cmd_${name}_${i}`);
            if (!el) continue;
            
            let val;
            const type = cmd.args[i].type;
            
            if (type === 'Flag') {
                val = el.checked;
            } else if (type === 'Integer' || type === 'Integer64') {
                val = parseInt(el.value);
            } else if (type === 'Float' || type === 'Double') {
                val = parseFloat(el.value);
            } else if (type === 'Color') {
                val = el.value;
            } else if (el.tagName === 'SELECT') {
                val = el.value;
            } else {
                val = el.value;
            }
            
            if (!cmd.args[i].optional && (val === undefined || val === '' || val === null)) {
                showToast(`Argument "${cmd.args[i].name}" is required`, 'error');
                valid = false;
                break;
            }
            args.push(val);
        }
    }
    
    if (!valid) return;
    
    try {
        const r = await fetch('/api/command/execute', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({command: name, args})
        });
        const res = await r.json();
        showToast(res.error === 'success' ? `✓ ${name}` : `✗ ${res.error}`, res.error === 'success' ? 'success' : 'error');
    } catch(e) { showToast('Error: '+e.message, 'error'); }
}

async function executeBinding(cmd) {
    try {
        const r = await fetch('/api/binding/execute', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({cmd})
        });
        const res = await r.json();
        showToast(res.error === 'success' ? `✓ ${cmd}` : `✗ ${res.error}`, res.error === 'success' ? 'success' : 'error');
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
            body: JSON.stringify({name, value: val})
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

async function setPropFromField(name) {
    const card = document.getElementById(`prop-${name}`);
    if (!card) return;
    const input = card.querySelector('input:not([type="checkbox"]), select');
    if (!input) return;
    let val = input.value;
    const info = propertyInfo[name] || {};
    const type = info.type || 'String';
    
    if (type === 'Integer' || type === 'Integer64') val = parseInt(val);
    else if (type === 'Float' || type === 'Double') val = parseFloat(val);
    else if (type === 'Flag') val = input.checked;
    
    await setProp(name, val);
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

function toggleVisibleUpdate() {
    visibleUpdate = !visibleUpdate;
    if (visibleUpdate) {
        showToast('Visible update ON');
        visibleInterval = setInterval(() => {
            const cards = document.querySelectorAll('#properties-grid .card');
            cards.forEach(card => {
                const name = card.id.replace('prop-', '');
                if (name) getProp(name);
            });
        }, 1000);
    } else {
        showToast('Visible update OFF');
        if (visibleInterval) {
            clearInterval(visibleInterval);
            visibleInterval = null;
        }
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
        document.getElementById('statusText').style.color = '#2d8a4e';
        
        renderCommands(commandsData);
        renderProperties(propertiesData);
        renderBindings(bindingsData);
    } catch(e) {
        document.getElementById('statusText').textContent = '✗ Error';
        document.getElementById('statusText').style.color = '#e94560';
        showToast('Load error: '+e.message, 'error');
    }
}

// Setup filter buttons
document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', function() {
        setTypeFilter(this.dataset.type);
    });
});

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