#!/usr/bin/env python3
import os
import subprocess
import signal
import threading
import tempfile
import json
import time
import glob
import urllib.parse
import queue
import hashlib
import psutil
from http.server import HTTPServer, BaseHTTPRequestHandler
import cgi
import io
from datetime import datetime
import sys
import shutil
from collections import defaultdict

UPLOAD_DIR = os.getcwd()  # Current directory
MPV_PROCESS = None
MPV_LOCK = threading.Lock()
PLAYLIST_MODE = {"loop": False, "single": True, "random": False}
PROXY_SETTINGS = {"enabled": False, "socks5": "127.0.0.1:1080"}
SAVE_TO_DISK = True
CURRENT_THEME = "dark"

# URL history storage
URL_HISTORY_FILE = os.path.join(UPLOAD_DIR, ".url_history.json")
url_history = []

# Global dictionary to track upload progress
upload_progress = {}
progress_lock = threading.Lock()

def load_url_history():
    """Load URL history from file"""
    global url_history
    try:
        if os.path.exists(URL_HISTORY_FILE):
            with open(URL_HISTORY_FILE, 'r') as f:
                url_history = json.load(f)
    except Exception as e:
        print(f"[HISTORY] Error loading URL history: {e}")

def save_url_history():
    """Save URL history to file"""
    try:
        with open(URL_HISTORY_FILE, 'w') as f:
            json.dump(url_history[-50:], f)  # Keep last 50 URLs
    except Exception as e:
        print(f"[HISTORY] Error saving URL history: {e}")

def add_to_history(url):
    """Add URL to history"""
    global url_history
    if url not in url_history:
        url_history.insert(0, url)
        if len(url_history) > 50:
            url_history = url_history[:50]
        save_url_history()

def get_system_status():
    """Get system status information"""
    try:
        # Check if mpv is running
        mpv_running = False
        if MPV_PROCESS and MPV_PROCESS.poll() is None:
            mpv_running = True
        
        # Get disk usage
        disk_usage = psutil.disk_usage(UPLOAD_DIR)
        disk_free_gb = disk_usage.free / (1024**3)
        disk_total_gb = disk_usage.total / (1024**3)
        disk_percent = disk_usage.percent
        
        # Get CPU usage
        cpu_percent = psutil.cpu_percent(interval=0.1)
        
        return {
            "mpv_running": mpv_running,
            "disk_free_gb": round(disk_free_gb, 2),
            "disk_total_gb": round(disk_total_gb, 2),
            "disk_percent": disk_percent,
            "cpu_percent": cpu_percent
        }
    except Exception as e:
        print(f"[STATUS] Error getting system status: {e}")
        return {
            "mpv_running": False,
            "disk_free_gb": 0,
            "disk_total_gb": 0,
            "disk_percent": 0,
            "cpu_percent": 0
        }

def find_duplicate_files():
    """Find duplicate media files by MD5 hash"""
    media_extensions = ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', 
                       '.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a']
    
    hash_map = defaultdict(list)
    
    for ext in media_extensions:
        pattern = os.path.join(UPLOAD_DIR, f"*{ext}")
        for filepath in glob.glob(pattern):
            if os.path.isfile(filepath):
                try:
                    # Calculate MD5 hash
                    md5_hash = hashlib.md5()
                    with open(filepath, "rb") as f:
                        for chunk in iter(lambda: f.read(4096), b""):
                            md5_hash.update(chunk)
                    file_hash = md5_hash.hexdigest()
                    
                    stat = os.stat(filepath)
                    hash_map[file_hash].append({
                        "path": filepath,
                        "name": os.path.basename(filepath),
                        "size": stat.st_size,
                        "modified": stat.st_mtime
                    })
                except Exception as e:
                    print(f"[DUPLICATE] Error processing {filepath}: {e}")
    
    # Return only duplicates
    duplicates = {h: files for h, files in hash_map.items() if len(files) > 1}
    return duplicates

class StreamingMPVHandler:
    @staticmethod
    def unmute_audio():
        """Unmute audio using amixer after mpv starts"""
        try:
            print("[AUDIO] Unmuting audio...")
            subprocess.run(
                ["amixer", "-c", "0", "cset", "numid=24", "on"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )
            print("[AUDIO] Audio unmuted successfully")
        except Exception as e:
            print(f"[AUDIO] Error unmuting audio: {e}")
    
    @staticmethod
    def kill_existing_mpv():
        """Kill all running mpv processes"""
        try:
            print("[MPV] Terminating all existing mpv processes...")
            subprocess.run(["pkill", "-9", "mpv"], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
            print("[MPV] All mpv processes terminated")
        except Exception as e:
            print(f"[MPV] Error killing mpv processes: {e}")
    
    @staticmethod
    def build_mpv_command(filepath=None, stream=False, url=None, device=None):
        """Build mpv command with all options"""
        cmd = ["mpv"]
        
        # Add proxy if enabled
        if PROXY_SETTINGS["enabled"] and PROXY_SETTINGS["socks5"]:
            cmd.extend([f"--ytdl-raw-options=proxy={PROXY_SETTINGS['socks5']}"])
        
        # Add loop options
        if PLAYLIST_MODE["loop"]:
            if PLAYLIST_MODE["single"]:
                cmd.append("--loop-file=inf")
            else:
                cmd.append("--loop-playlist=inf")
        
        # Add shuffle if random play enabled
        if PLAYLIST_MODE["random"]:
            cmd.append("--shuffle")
        
        # Add input source
        if device:
            cmd.append(f"av://v4l2:{device}")
        elif url:
            cmd.append(url)
        elif stream:
            cmd.extend(["--cache=yes", "--cache-secs=2", "-"])
        elif filepath:
            cmd.append(filepath)
        
        return cmd
    
    @staticmethod
    def stream_to_mpv_with_queue(data_queue, save_path, filename, total_size, progress_id):
        """Stream data from queue to mpv while saving to file"""
        global MPV_PROCESS
        
        print(f"[STREAM] Starting stream for {filename} (expected {total_size} bytes)")
        
        with MPV_LOCK:
            # Kill previous mpv
            StreamingMPVHandler.kill_existing_mpv()
            
            # Start mpv reading from stdin
            env = os.environ.copy()
            env["DISPLAY"] = ":0"
            
            cmd = StreamingMPVHandler.build_mpv_command(stream=True)
            print(f"[MPV] Command: {' '.join(cmd)}")
            
            MPV_PROCESS = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env
            )
            print(f"[MPV] Process started with PID: {MPV_PROCESS.pid}")
            
            # Unmute after mpv starts
            time.sleep(0.5)
            StreamingMPVHandler.unmute_audio()
        
        bytes_written = 0
        start_time = time.time()
        
        # Open file for saving if needed
        save_file = None
        if SAVE_TO_DISK:
            print(f"[STREAM] Saving to: {save_path}")
            save_file = open(save_path, 'wb')
        else:
            print(f"[STREAM] Not saving to disk (SAVE_TO_DISK=False)")
        
        try:
            while True:
                try:
                    chunk = data_queue.get(timeout=30)
                    
                    if chunk is None:  # End of stream marker
                        print(f"[STREAM] Received end-of-stream marker")
                        break
                    
                    # Write to mpv immediately
                    if MPV_PROCESS and MPV_PROCESS.poll() is None:
                        try:
                            MPV_PROCESS.stdin.write(chunk)
                            MPV_PROCESS.stdin.flush()
                            if bytes_written == 0:
                                print(f"[STREAM] First chunk sent to mpv! ({len(chunk)} bytes)")
                        except BrokenPipeError:
                            print("[MPV] Broken pipe, mpv may have exited")
                            break
                    
                    # Save to file if enabled
                    if save_file:
                        save_file.write(chunk)
                    
                    bytes_written += len(chunk)
                    
                    # Update progress
                    with progress_lock:
                        if progress_id in upload_progress:
                            upload_progress[progress_id]["bytes_read"] = bytes_written
                            if total_size > 0:
                                upload_progress[progress_id]["percent"] = (bytes_written / total_size) * 100
                            upload_progress[progress_id]["speed"] = bytes_written / (time.time() - start_time) if time.time() - start_time > 0 else 0
                    
                except queue.Empty:
                    print("[STREAM] Queue timeout - assuming upload complete")
                    break
                except Exception as e:
                    print(f"[STREAM] Error processing chunk: {e}")
                    break
        finally:
            if save_file:
                save_file.close()
        
        # Close mpv stdin
        with MPV_LOCK:
            if MPV_PROCESS and MPV_PROCESS.poll() is None:
                try:
                    MPV_PROCESS.stdin.close()
                except:
                    pass
        
        elapsed = time.time() - start_time
        print(f"[STREAM] Completed streaming {filename}")
        print(f"[STREAM] Total bytes: {bytes_written}, Time: {elapsed:.2f}s")
        
        # Mark as complete
        with progress_lock:
            if progress_id in upload_progress:
                upload_progress[progress_id]["complete"] = True
                if SAVE_TO_DISK:
                    upload_progress[progress_id]["save_path"] = save_path
    
    @staticmethod
    def play_existing_file(filepath):
        """Play an existing file from disk"""
        global MPV_PROCESS
        
        print(f"[MPV] Playing existing file: {filepath}")
        
        if not os.path.exists(filepath):
            print(f"[MPV] ERROR: File not found: {filepath}")
            return False
        
        with MPV_LOCK:
            StreamingMPVHandler.kill_existing_mpv()
            
            env = os.environ.copy()
            env["DISPLAY"] = ":0"
            
            cmd = StreamingMPVHandler.build_mpv_command(filepath=filepath)
            print(f"[MPV] Command: {' '.join(cmd)}")
            
            try:
                MPV_PROCESS = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env
                )
                print(f"[MPV] Process started with PID: {MPV_PROCESS.pid}")
                
                # Unmute after mpv starts
                time.sleep(0.5)
                StreamingMPVHandler.unmute_audio()
                
                return True
            except Exception as e:
                print(f"[MPV] Error starting mpv: {e}")
                return False
    
    @staticmethod
    def play_url(url):
        """Play network URL"""
        global MPV_PROCESS
        
        print(f"[MPV] Playing URL: {url}")
        
        # Add to history
        add_to_history(url)
        
        with MPV_LOCK:
            StreamingMPVHandler.kill_existing_mpv()
            
            env = os.environ.copy()
            env["DISPLAY"] = ":0"
            
            cmd = StreamingMPVHandler.build_mpv_command(url=url)
            print(f"[MPV] Command: {' '.join(cmd)}")
            
            try:
                MPV_PROCESS = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env
                )
                print(f"[MPV] Process started with PID: {MPV_PROCESS.pid}")
                
                # Unmute after mpv starts
                time.sleep(0.5)
                StreamingMPVHandler.unmute_audio()
                
                return True
            except Exception as e:
                print(f"[MPV] Error starting mpv: {e}")
                return False
    
    @staticmethod
    def play_device(device):
        """Play from video device"""
        global MPV_PROCESS
        
        print(f"[MPV] Playing from device: {device}")
        
        with MPV_LOCK:
            StreamingMPVHandler.kill_existing_mpv()
            
            env = os.environ.copy()
            env["DISPLAY"] = ":0"
            
            cmd = StreamingMPVHandler.build_mpv_command(device=device)
            print(f"[MPV] Command: {' '.join(cmd)}")
            
            try:
                MPV_PROCESS = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env
                )
                print(f"[MPV] Process started with PID: {MPV_PROCESS.pid}")
                
                # Unmute after mpv starts
                time.sleep(0.5)
                StreamingMPVHandler.unmute_audio()
                
                return True
            except Exception as e:
                print(f"[MPV] Error starting mpv: {e}")
                return False
    
    @staticmethod
    def stop_playback():
        """Stop current playback"""
        global MPV_PROCESS
        
        print("[MPV] Stopping playback...")
        with MPV_LOCK:
            if MPV_PROCESS and MPV_PROCESS.poll() is None:
                MPV_PROCESS.terminate()
                try:
                    MPV_PROCESS.wait(timeout=2)
                except:
                    MPV_PROCESS.kill()
                print("[MPV] Playback stopped")
                return True
        return False

class FileUploadHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed_path.path)
        
        if path == "/":
            self.serve_index()
        elif path == "/progress":
            self.serve_progress()
        elif path == "/files":
            self.serve_file_list()
        elif path == "/status":
            self.serve_status()
        elif path == "/settings":
            self.serve_settings()
        elif path == "/url-history":
            self.serve_url_history()
        elif path == "/video-devices":
            self.serve_video_devices()
        elif path == "/duplicates":
            self.serve_duplicates()
        elif path.startswith("/play/"):
            filename = path[6:]
            self.play_file(filename)
        else:
            self.send_error(404)
    
    def do_POST(self):
        if self.path == "/upload":
            self.handle_streaming_upload()
        elif self.path == "/play-url":
            self.handle_play_url()
        elif self.path == "/play-device":
            self.handle_play_device()
        elif self.path == "/stop":
            self.handle_stop()
        elif self.path == "/settings":
            self.handle_settings()
        elif self.path == "/delete-duplicates":
            self.handle_delete_duplicates()
        else:
            self.send_error(404)
    
    def serve_index(self):
        """Serve the main HTML page"""
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        
        theme_css = """
        <style>
            :root {
                --bg-primary: #1a1a1a;
                --bg-secondary: #2d2d2d;
                --bg-hover: #4a4a4a;
                --text-primary: #e0e0e0;
                --text-secondary: #b0b0b0;
                --border-color: #444;
                --success-bg: #1b5e20;
                --success-text: #a5d6a7;
                --error-bg: #b71c1c;
                --error-text: #ffcdd2;
            }
            
            .light-theme {
                --bg-primary: #f5f5f5;
                --bg-secondary: #ffffff;
                --bg-hover: #e9e9e9;
                --text-primary: #333333;
                --text-secondary: #666666;
                --border-color: #ddd;
                --success-bg: #d4edda;
                --success-text: #155724;
                --error-bg: #f8d7da;
                --error-text: #721c24;
            }
            
            * { margin: 0; padding: 0; box-sizing: border-box; }
            
            body { 
                font-family: Arial, sans-serif; 
                background: var(--bg-primary); 
                color: var(--text-primary);
                transition: all 0.3s;
            }
            
            .app-container { display: flex; min-height: 100vh; }
            
            /* Sidebar Styles */
            .sidebar {
                width: 300px;
                background: var(--bg-secondary);
                border-right: 1px solid var(--border-color);
                padding: 20px;
                overflow-y: auto;
                transition: transform 0.3s;
            }
            
            .sidebar.collapsed { transform: translateX(-300px); }
            
            .sidebar-toggle {
                position: fixed;
                left: 300px;
                top: 20px;
                background: var(--bg-secondary);
                border: 1px solid var(--border-color);
                color: var(--text-primary);
                padding: 10px;
                cursor: pointer;
                border-radius: 0 5px 5px 0;
                transition: left 0.3s;
                z-index: 100;
            }
            
            .sidebar.collapsed + .sidebar-toggle { left: 0; }
            
            .sidebar-section {
                margin-bottom: 25px;
                padding-bottom: 20px;
                border-bottom: 1px solid var(--border-color);
            }
            
            .sidebar-section h3 {
                margin-bottom: 15px;
                color: var(--text-primary);
            }
            
            /* Main Content */
            .main-content {
                flex: 1;
                padding: 20px;
                margin-left: 0;
            }
            
            .container { max-width: 800px; margin: 0 auto; }
            
            /* Status Bar */
            .status-bar {
                background: var(--bg-secondary);
                border: 1px solid var(--border-color);
                padding: 15px;
                border-radius: 5px;
                margin-bottom: 20px;
                display: flex;
                justify-content: space-around;
                flex-wrap: wrap;
            }
            
            .status-item {
                display: flex;
                align-items: center;
                gap: 10px;
            }
            
            .status-indicator {
                width: 12px;
                height: 12px;
                border-radius: 50%;
                background: #666;
            }
            
            .status-indicator.active { background: #4CAF50; }
            .status-indicator.inactive { background: #f44336; }
            
            /* Upload Section */
            .upload-section, .url-section, .device-section {
                border: 1px solid var(--border-color);
                padding: 20px;
                margin: 20px 0;
                border-radius: 5px;
                background: var(--bg-secondary);
            }
            
            input[type="text"], input[type="url"], select {
                width: 100%;
                padding: 10px;
                margin: 10px 0;
                background: var(--bg-primary);
                border: 1px solid var(--border-color);
                color: var(--text-primary);
                border-radius: 3px;
            }
            
            button {
                padding: 10px 20px;
                background: #4CAF50;
                color: white;
                border: none;
                border-radius: 3px;
                cursor: pointer;
                margin: 5px;
            }
            
            button:hover { opacity: 0.9; }
            button.danger { background: #f44336; }
            button.warning { background: #ff9800; }
            
            .file-list { list-style: none; padding: 0; }
            .file-item {
                padding: 10px;
                margin: 5px 0;
                background: var(--bg-primary);
                border-radius: 3px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            
            .file-item:hover { background: var(--bg-hover); }
            
            .progress-container { margin: 20px 0; display: none; }
            .progress-bar {
                width: 100%;
                height: 30px;
                background: var(--bg-primary);
                border-radius: 5px;
                overflow: hidden;
            }
            .progress-fill {
                height: 100%;
                background: #4CAF50;
                width: 0%;
                transition: width 0.3s;
            }
            
            .checkbox-group { margin: 10px 0; }
            .checkbox-group label {
                display: block;
                margin: 5px 0;
                color: var(--text-secondary);
            }
            
            .status {
                margin: 10px 0;
                padding: 10px;
                border-radius: 3px;
            }
            .status.success { background: var(--success-bg); color: var(--success-text); }
            .status.error { background: var(--error-bg); color: var(--error-text); }
            
            .tab-container { margin: 20px 0; }
            .tabs {
                display: flex;
                border-bottom: 1px solid var(--border-color);
            }
            .tab {
                padding: 10px 20px;
                cursor: pointer;
                background: none;
                border: none;
                color: var(--text-secondary);
            }
            .tab.active {
                color: var(--text-primary);
                border-bottom: 2px solid #4CAF50;
            }
            .tab-content { display: none; padding: 20px 0; }
            .tab-content.active { display: block; }
        </style>
        """
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>MPV Remote Player</title>
            <meta charset="utf-8">
            {theme_css}
        </head>
        <body>
            <div class="app-container">
                <!-- Sidebar Toggle -->
                <button class="sidebar-toggle" onclick="toggleSidebar()">☰</button>
                
                <!-- Sidebar -->
                <div class="sidebar" id="sidebar">
                    <h2>Settings</h2>
                    
                    <div class="sidebar-section">
                        <h3>Playback Mode</h3>
                        <button onclick="playPlaylist()">▶ Play All as Playlist</button>
                        <button onclick="stopPlayback()" class="danger">⏹ Stop Playback</button>
                        
                        <div class="checkbox-group">
                            <label>
                                <input type="checkbox" id="loopPlay" onchange="updateSettings()"> Loop Play
                            </label>
                            <label>
                                <input type="checkbox" id="loopSingle" onchange="updateSettings()"> Single File Loop
                            </label>
                            <label>
                                <input type="checkbox" id="randomPlay" onchange="updateSettings()"> Random Play
                            </label>
                        </div>
                    </div>
                    
                    <div class="sidebar-section">
                        <h3>Options</h3>
                        <div class="checkbox-group">
                            <label>
                                <input type="checkbox" id="saveToDisk" checked onchange="updateSettings()"> Save files to disk
                            </label>
                            <label>
                                <input type="checkbox" id="useProxy" onchange="updateSettings()"> Use SOCKS5 Proxy
                            </label>
                        </div>
                        <input type="text" id="proxyAddress" placeholder="Proxy address (127.0.0.1:1080)" value="127.0.0.1:1080">
                        <button onclick="toggleTheme()">🌓 Toggle Theme</button>
                        <button onclick="findDuplicates()" class="warning">🔍 Find Duplicates</button>
                    </div>
                    
                    <div class="sidebar-section">
                        <h3>URL History</h3>
                        <div id="urlHistoryList"></div>
                    </div>
                </div>
                
                <!-- Main Content -->
                <div class="main-content">
                    <div class="container">
                        <h1>MPV Remote Player</h1>
                        
                        <!-- Status Bar -->
                        <div class="status-bar" id="statusBar">
                            <div class="status-item">
                                <span class="status-indicator" id="mpvIndicator"></span>
                                <span id="mpvStatus">MPV: Checking...</span>
                            </div>
                            <div class="status-item">
                                <span>💾 <span id="diskStatus">Disk: --</span></span>
                            </div>
                            <div class="status-item">
                                <span>⚡ <span id="cpuStatus">CPU: --</span></span>
                            </div>
                        </div>
                        
                        <!-- Tabs -->
                        <div class="tab-container">
                            <div class="tabs">
                                <button class="tab active" onclick="switchTab('upload')">Upload File</button>
                                <button class="tab" onclick="switchTab('url')">Network URL</button>
                                <button class="tab" onclick="switchTab('device')">Video Device</button>
                                <button class="tab" onclick="switchTab('files')">Local Files</button>
                            </div>
                            
                            <!-- Upload Tab -->
                            <div class="tab-content active" id="tab-upload">
                                <div class="upload-section">
                                    <h2>Upload and Stream Video</h2>
                                    <form id="uploadForm" enctype="multipart/form-data">
                                        <input type="file" id="videoFile" name="video" accept="video/*,audio/*" required>
                                        <br>
                                        <button type="submit">Upload and Stream</button>
                                    </form>
                                    
                                    <div id="progressContainer" class="progress-container">
                                        <div class="progress-bar">
                                            <div id="progressFill" class="progress-fill"></div>
                                        </div>
                                        <div id="progressText" class="progress-text"></div>
                                    </div>
                                </div>
                            </div>
                            
                            <!-- URL Tab -->
                            <div class="tab-content" id="tab-url">
                                <div class="url-section">
                                    <h2>Play Network URL</h2>
                                    <input type="url" id="urlInput" placeholder="https://example.com/video.mp4">
                                    <button onclick="playUrl()">Play URL</button>
                                    <div id="urlStatus"></div>
                                </div>
                            </div>
                            
                            <!-- Device Tab -->
                            <div class="tab-content" id="tab-device">
                                <div class="device-section">
                                    <h2>Play from Video Device</h2>
                                    <select id="deviceSelect"></select>
                                    <button onclick="playDevice()">Play Device</button>
                                </div>
                            </div>
                            
                            <!-- Files Tab -->
                            <div class="tab-content" id="tab-files">
                                <div class="files-section">
                                    <h2>Local Media Files</h2>
                                    <button onclick="loadFileList()">Refresh</button>
                                    <div id="fileListContainer">Loading files...</div>
                                </div>
                            </div>
                        </div>
                        
                        <div id="globalStatus" class="status" style="display:none;"></div>
                    </div>
                </div>
            </div>
            
            <script>
                let currentTheme = 'dark';
                let settings = {{
                    loop: false,
                    single: true,
                    random: false,
                    saveToDisk: true,
                    useProxy: false,
                    proxyAddress: '127.0.0.1:1080'
                }};
                
                // Initialize
                document.addEventListener('DOMContentLoaded', () => {{
                    loadSettings();
                    updateStatus();
                    loadUrlHistory();
                    loadVideoDevices();
                    loadFileList();
                    setInterval(updateStatus, 2000);
                    setInterval(loadUrlHistory, 10000);
                }});
                
                // Upload form handler
                document.getElementById('uploadForm').addEventListener('submit', async (e) => {{
                    e.preventDefault();
                    const fileInput = document.getElementById('videoFile');
                    const file = fileInput.files[0];
                    if (!file) return;
                    
                    const formData = new FormData();
                    formData.append('video', file);
                    
                    const uploadId = Date.now() + '-' + Math.random().toString(36);
                    document.getElementById('progressContainer').style.display = 'block';
                    
                    try {{
                        const response = await fetch('/upload', {{
                            method: 'POST',
                            body: formData,
                            headers: {{
                                'X-Upload-ID': uploadId,
                                'X-File-Size': file.size
                            }}
                        }});
                        
                        if (response.ok) {{
                            fileInput.value = '';
                            pollProgress(uploadId);
                        }}
                    }} catch (error) {{
                        showStatus('Upload error: ' + error.message, 'error');
                    }}
                }});
                
                function toggleSidebar() {{
                    document.getElementById('sidebar').classList.toggle('collapsed');
                }}
                
                function switchTab(tabName) {{
                    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                    event.target.classList.add('active');
                    document.getElementById('tab-' + tabName).classList.add('active');
                    
                    if (tabName === 'files') loadFileList();
                    if (tabName === 'device') loadVideoDevices();
                }}
                
                async function updateStatus() {{
                    try {{
                        const response = await fetch('/status');
                        const data = await response.json();
                        
                        document.getElementById('mpvIndicator').className = 
                            'status-indicator ' + (data.mpv_running ? 'active' : 'inactive');
                        document.getElementById('mpvStatus').textContent = 
                            'MPV: ' + (data.mpv_running ? 'Running' : 'Stopped');
                        document.getElementById('diskStatus').textContent = 
                            `Disk: ${{data.disk_free_gb}}GB / ${{data.disk_total_gb}}GB (${{data.disk_percent}}%)`;
                        document.getElementById('cpuStatus').textContent = 
                            `CPU: ${{data.cpu_percent}}%`;
                    }} catch (error) {{
                        console.error('Status error:', error);
                    }}
                }}
                
                async function updateSettings() {{
                    settings.loop = document.getElementById('loopPlay')?.checked || false;
                    settings.single = document.getElementById('loopSingle')?.checked || true;
                    settings.random = document.getElementById('randomPlay')?.checked || false;
                    settings.saveToDisk = document.getElementById('saveToDisk')?.checked ?? true;
                    settings.useProxy = document.getElementById('useProxy')?.checked || false;
                    settings.proxyAddress = document.getElementById('proxyAddress')?.value || '127.0.0.1:1080';
                    
                    await fetch('/settings', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify(settings)
                    }});
                }}
                
                async function loadSettings() {{
                    try {{
                        const response = await fetch('/settings');
                        const data = await response.json();
                        settings = data;
                        
                        document.getElementById('loopPlay').checked = data.loop;
                        document.getElementById('loopSingle').checked = data.single;
                        document.getElementById('randomPlay').checked = data.random;
                        document.getElementById('saveToDisk').checked = data.saveToDisk;
                        document.getElementById('useProxy').checked = data.useProxy;
                        document.getElementById('proxyAddress').value = data.proxyAddress;
                    }} catch (error) {{
                        console.error('Settings error:', error);
                    }}
                }}
                
                function toggleTheme() {{
                    currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
                    document.body.className = currentTheme === 'light' ? 'light-theme' : '';
                }}
                
                async function playPlaylist() {{
                    const files = await fetch('/files').then(r => r.json());
                    for (const file of files) {{
                        await fetch('/play/' + encodeURIComponent(file.name));
                        await new Promise(resolve => setTimeout(resolve, 500));
                    }}
                }}
                
                async function stopPlayback() {{
                    await fetch('/stop', {{method: 'POST'}});
                    showStatus('Playback stopped', 'success');
                }}
                
                async function playUrl() {{
                    const url = document.getElementById('urlInput').value;
                    if (!url) return;
                    
                    const response = await fetch('/play-url', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({{url: url}})
                    }});
                    
                    if (response.ok) {{
                        showStatus('Playing URL: ' + url, 'success');
                        loadUrlHistory();
                    }}
                }}
                
                async function playDevice() {{
                    const device = document.getElementById('deviceSelect').value;
                    if (!device) return;
                    
                    await fetch('/play-device', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({{device: device}})
                    }});
                    
                    showStatus('Playing from device: ' + device, 'success');
                }}
                
                async function loadUrlHistory() {{
                    try {{
                        const response = await fetch('/url-history');
                        const history = await response.json();
                        
                        const container = document.getElementById('urlHistoryList');
                        if (history.length === 0) {{
                            container.innerHTML = '<p>No URL history</p>';
                            return;
                        }}
                        
                        let html = '<ul class="file-list">';
                        history.slice(0, 10).forEach(url => {{
                            const shortUrl = url.length > 40 ? url.substring(0, 40) + '...' : url;
                            html += `
                                <li class="file-item">
                                    <span title="${{url}}">${{shortUrl}}</span>
                                    <button class="play-btn" onclick="playHistoryUrl('${{encodeURIComponent(url)}}')">Play</button>
                                </li>
                            `;
                        }});
                        html += '</ul>';
                        container.innerHTML = html;
                    }} catch (error) {{
                        console.error('History error:', error);
                    }}
                }}
                
                async function playHistoryUrl(url) {{
                    await fetch('/play-url', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({{url: decodeURIComponent(url)}})
                    }});
                    showStatus('Playing: ' + decodeURIComponent(url), 'success');
                }}
                
                async function loadVideoDevices() {{
                    try {{
                        const response = await fetch('/video-devices');
                        const devices = await response.json();
                        
                        const select = document.getElementById('deviceSelect');
                        select.innerHTML = devices.map(d => 
                            `<option value="${{d}}">${{d}}</option>`
                        ).join('');
                    }} catch (error) {{
                        console.error('Devices error:', error);
                    }}
                }}
                
                async function findDuplicates() {{
                    const response = await fetch('/duplicates');
                    const duplicates = await response.json();
                    
                    if (Object.keys(duplicates).length === 0) {{
                        alert('No duplicates found');
                        return;
                    }}
                    
                    let message = 'Duplicates found:\\n';
                    for (const [hash, files] of Object.entries(duplicates)) {{
                        message += `\\nHash: ${{hash.substring(0, 8)}}...\\n`;
                        files.forEach(f => message += `  - ${{f.name}}\\n`);
                    }}
                    
                    if (confirm(message + '\\nDelete duplicates (keep newest)?')) {{
                        await fetch('/delete-duplicates', {{method: 'POST'}});
                        loadFileList();
                        showStatus('Duplicates deleted', 'success');
                    }}
                }}
                
                async function loadFileList() {{
                    try {{
                        const response = await fetch('/files');
                        const files = await response.json();
                        
                        const container = document.getElementById('fileListContainer');
                        if (files.length === 0) {{
                            container.innerHTML = '<p>No media files found</p>';
                            return;
                        }}
                        
                        let html = '<ul class="file-list">';
                        files.forEach(file => {{
                            const sizeMB = (file.size / 1024 / 1024).toFixed(2);
                            html += `
                                <li class="file-item">
                                    <div>
                                        <strong>${{escapeHtml(file.name)}}</strong><br>
                                        <small>Size: ${{sizeMB}} MB</small>
                                    </div>
                                    <div>
                                        <button class="play-btn" onclick="playFile('${{encodeURIComponent(file.name)}}')">Play</button>
                                    </div>
                                </li>
                            `;
                        }});
                        html += '</ul>';
                        container.innerHTML = html;
                    }} catch (error) {{
                        console.error('File list error:', error);
                    }}
                }}
                
                async function playFile(filename) {{
                    await fetch('/play/' + encodeURIComponent(filename));
                    showStatus('Playing: ' + filename, 'success');
                }}
                
                async function pollProgress(uploadId) {{
                    const checkProgress = async () => {{
                        try {{
                            const response = await fetch('/progress?id=' + uploadId);
                            const data = await response.json();
                            
                            if (data.exists) {{
                                const percent = data.percent || 0;
                                document.getElementById('progressFill').style.width = percent + '%';
                                
                                const speedMB = (data.speed || 0) / 1024 / 1024;
                                const totalMB = data.total_size / 1024 / 1024;
                                const loadedMB = data.bytes_read / 1024 / 1024;
                                
                                document.getElementById('progressText').innerHTML = `
                                    ${{loadedMB.toFixed(2)}} MB / ${{totalMB.toFixed(2)}} MB (${{percent.toFixed(1)}}%)<br>
                                    Speed: ${{speedMB.toFixed(2)}} MB/s
                                `;
                                
                                if (data.complete) {{
                                    setTimeout(() => {{
                                        document.getElementById('progressContainer').style.display = 'none';
                                    }}, 3000);
                                    loadFileList();
                                }} else {{
                                    setTimeout(checkProgress, 500);
                                }}
                            }}
                        }} catch (error) {{
                            console.error('Progress error:', error);
                        }}
                    }};
                    checkProgress();
                }}
                
                function showStatus(message, type) {{
                    const statusEl = document.getElementById('globalStatus');
                    statusEl.style.display = 'block';
                    statusEl.textContent = message;
                    statusEl.className = 'status ' + type;
                    setTimeout(() => statusEl.style.display = 'none', 5000);
                }}
                
                function escapeHtml(text) {{
                    const div = document.createElement('div');
                    div.textContent = text;
                    return div.innerHTML;
                }}
            </script>
        </body>
        </html>
        """
        self.wfile.write(html.encode("utf-8"))
    
    # Continue with other methods...
    # (I'll provide the remaining handler methods in the next part due to length)

    def serve_progress(self):
        """Serve upload progress as JSON"""
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        upload_id = params.get('id', [''])[0]
        
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        
        with progress_lock:
            if upload_id and upload_id in upload_progress:
                progress_data = upload_progress[upload_id].copy()
                progress_data['exists'] = True
            else:
                progress_data = {'exists': False}
        
        self.wfile.write(json.dumps(progress_data).encode())
    
    def serve_file_list(self):
        """Serve list of media files as JSON"""
        self.send_response(200)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        
        media_extensions = ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', 
                           '.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a']
        
        files = []
        for ext in media_extensions:
            pattern = os.path.join(UPLOAD_DIR, f"*{ext}")
            for filepath in glob.glob(pattern):
                if os.path.isfile(filepath):
                    stat = os.stat(filepath)
                    files.append({
                        'name': os.path.basename(filepath),
                        'path': filepath,
                        'size': stat.st_size,
                        'modified': stat.st_mtime
                    })
        
        files.sort(key=lambda x: x['modified'], reverse=True)
        response_json = json.dumps(files, ensure_ascii=False)
        self.wfile.write(response_json.encode('utf-8'))
    
    def serve_status(self):
        """Serve system status as JSON"""
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        
        status = get_system_status()
        self.wfile.write(json.dumps(status).encode())
    
    def serve_settings(self):
        """Serve current settings as JSON"""
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        
        settings = {
            "loop": PLAYLIST_MODE["loop"],
            "single": PLAYLIST_MODE["single"],
            "random": PLAYLIST_MODE["random"],
            "saveToDisk": SAVE_TO_DISK,
            "useProxy": PROXY_SETTINGS["enabled"],
            "proxyAddress": PROXY_SETTINGS["socks5"]
        }
        self.wfile.write(json.dumps(settings).encode())
    
    def serve_url_history(self):
        """Serve URL history as JSON"""
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(url_history, ensure_ascii=False).encode('utf-8'))
    
    def serve_video_devices(self):
        """Serve list of video devices"""
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        
        devices = []
        for i in range(10):  # Check /dev/video0 to /dev/video9
            dev_path = f"/dev/video{i}"
            if os.path.exists(dev_path):
                devices.append(dev_path)
        
        self.wfile.write(json.dumps(devices).encode())
    
    def serve_duplicates(self):
        """Serve duplicate files list"""
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        
        duplicates = find_duplicate_files()
        # Convert to serializable format
        result = {}
        for hash_val, files in duplicates.items():
            result[hash_val] = [
                {
                    "name": f["name"],
                    "path": f["path"],
                    "size": f["size"],
                    "modified": f["modified"]
                }
                for f in files
            ]
        
        self.wfile.write(json.dumps(result).encode())
    
    def play_file(self, filename):
        """Play an existing file"""
        filename = urllib.parse.unquote(filename)
        filename = os.path.basename(filename)
        filepath = os.path.abspath(os.path.join(UPLOAD_DIR, filename))
        
        print(f"[SERVER] Request to play file: {filepath}")
        
        if not os.path.exists(filepath):
            print(f"[SERVER] ERROR: File not found: {filepath}")
            self.send_error(404, "File not found")
            return
        
        thread = threading.Thread(
            target=StreamingMPVHandler.play_existing_file,
            args=(filepath,)
        )
        thread.daemon = True
        thread.start()
        
        self.send_response(200)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        
        response = {'status': 'playing', 'file': filename}
        self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))
    
    def handle_streaming_upload(self):
        """Handle file upload with real streaming to mpv"""
        upload_id = self.headers.get('X-Upload-ID', str(int(time.time())))
        expected_size = int(self.headers.get('X-File-Size', 0))
        
        content_type = self.headers.get("Content-Type", "")
        
        if "multipart/form-data" not in content_type:
            self.send_error(400, "Expected multipart/form-data")
            return
        
        boundary = None
        for part in content_type.split(";"):
            if "boundary=" in part:
                boundary = part.split("boundary=")[1].strip()
                break
        
        if not boundary:
            self.send_error(400, "No boundary found")
            return
        
        boundary_bytes = ("--" + boundary).encode()
        content_length = int(self.headers.get("Content-Length", 0))
        
        print(f"[UPLOAD] Starting streaming upload, expected size: {content_length} bytes")
        
        buffer_size = 8192
        header_data = b''
        filename = None
        data_started = False
        data_queue = queue.Queue()
        bytes_processed = 0
        headers_parsed = False
        save_path = None
        
        while bytes_processed < content_length:
            chunk_size = min(buffer_size, content_length - bytes_processed)
            chunk = self.rfile.read(chunk_size)
            
            if not chunk:
                break
            
            bytes_processed += len(chunk)
            
            if not headers_parsed:
                header_data += chunk
                
                header_end = header_data.find(b'\r\n\r\n')
                if header_end != -1:
                    headers_part = header_data[:header_end].decode('utf-8', errors='ignore')
                    
                    for line in headers_part.split('\r\n'):
                        if 'filename=' in line:
                            filename = line.split('filename=')[1].strip('"')
                            break
                    
                    data_start = header_end + 4
                    
                    if len(header_data) > data_start:
                        first_data_chunk = header_data[data_start:]
                        if first_data_chunk.endswith(b'\r\n'):
                            first_data_chunk = first_data_chunk[:-2]
                        
                        if first_data_chunk:
                            data_queue.put(first_data_chunk)
                    
                    headers_parsed = True
                    header_data = None
                    
                    if not filename:
                        print("[UPLOAD] ERROR: No filename in headers")
                        self.send_error(400, "No filename")
                        return
                    
                    print(f"[UPLOAD] Filename: {filename}")
                    
                    if SAVE_TO_DISK:
                        base, ext = os.path.splitext(filename)
                        if not ext:
                            ext = ".mp4"
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        save_filename = f"{base}_{timestamp}{ext}"
                        save_path = os.path.join(UPLOAD_DIR, save_filename)
                    else:
                        save_path = None
                    
                    with progress_lock:
                        upload_progress[upload_id] = {
                            'filename': filename,
                            'save_filename': os.path.basename(save_path) if save_path else None,
                            'total_size': expected_size if expected_size > 0 else content_length,
                            'bytes_read': 0,
                            'percent': 0,
                            'speed': 0,
                            'complete': False,
                            'last_logged': 0
                        }
                    
                    stream_thread = threading.Thread(
                        target=StreamingMPVHandler.stream_to_mpv_with_queue,
                        args=(data_queue, save_path, filename, 
                              expected_size if expected_size > 0 else content_length, 
                              upload_id)
                    )
                    stream_thread.daemon = True
                    stream_thread.start()
                    
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    
                    response = {
                        'status': 'streaming',
                        'filename': filename,
                        'upload_id': upload_id
                    }
                    self.wfile.write(json.dumps(response).encode())
            else:
                if chunk.endswith(b'\r\n') and b'--' + boundary.encode() in chunk:
                    chunk = chunk.replace(b'--' + boundary.encode() + b'--\r\n', b'')
                    chunk = chunk.replace(b'\r\n--' + boundary.encode() + b'--\r\n', b'')
                
                if chunk:
                    data_queue.put(chunk)
        
        data_queue.put(None)
        print(f"[UPLOAD] Upload complete, total bytes: {bytes_processed}")
    
    def handle_play_url(self):
        """Handle URL playback request"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode('utf-8'))
            url = data.get('url', '')
            
            if not url:
                self.send_error(400, "No URL provided")
                return
            
            thread = threading.Thread(
                target=StreamingMPVHandler.play_url,
                args=(url,)
            )
            thread.daemon = True
            thread.start()
            
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'playing', 'url': url}).encode())
            
        except Exception as e:
            print(f"[URL] Error: {e}")
            self.send_error(400, "Invalid request")
    
    def handle_play_device(self):
        """Handle device playback request"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode('utf-8'))
            device = data.get('device', '')
            
            if not device:
                self.send_error(400, "No device provided")
                return
            
            thread = threading.Thread(
                target=StreamingMPVHandler.play_device,
                args=(device,)
            )
            thread.daemon = True
            thread.start()
            
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'playing', 'device': device}).encode())
            
        except Exception as e:
            print(f"[DEVICE] Error: {e}")
            self.send_error(400, "Invalid request")
    
    def handle_stop(self):
        """Handle stop playback request"""
        result = StreamingMPVHandler.stop_playback()
        
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({'stopped': result}).encode())
    
    def handle_settings(self):
        """Handle settings update"""
        global PLAYLIST_MODE, SAVE_TO_DISK, PROXY_SETTINGS
        
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode('utf-8'))
            
            PLAYLIST_MODE["loop"] = data.get('loop', False)
            PLAYLIST_MODE["single"] = data.get('single', True)
            PLAYLIST_MODE["random"] = data.get('random', False)
            SAVE_TO_DISK = data.get('saveToDisk', True)
            PROXY_SETTINGS["enabled"] = data.get('useProxy', False)
            PROXY_SETTINGS["socks5"] = data.get('proxyAddress', '127.0.0.1:1080')
            
            print(f"[SETTINGS] Updated: loop={PLAYLIST_MODE['loop']}, "
                  f"single={PLAYLIST_MODE['single']}, random={PLAYLIST_MODE['random']}, "
                  f"saveToDisk={SAVE_TO_DISK}, proxy={PROXY_SETTINGS}")
            
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok'}).encode())
            
        except Exception as e:
            print(f"[SETTINGS] Error: {e}")
            self.send_error(400, "Invalid request")
    
    def handle_delete_duplicates(self):
        """Delete duplicate files, keeping the newest one"""
        duplicates = find_duplicate_files()
        deleted_count = 0
        
        for hash_val, files in duplicates.items():
            # Sort by modification time (newest first)
            files.sort(key=lambda x: x['modified'], reverse=True)
            
            # Keep the first (newest) file, delete the rest
            for file_info in files[1:]:
                try:
                    os.remove(file_info['path'])
                    print(f"[DUPLICATE] Deleted: {file_info['path']}")
                    deleted_count += 1
                except Exception as e:
                    print(f"[DUPLICATE] Error deleting {file_info['path']}: {e}")
        
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({'deleted': deleted_count}).encode())
    
    def log_message(self, format, *args):
        """Override to provide custom logging"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} - {format % args}")

def main():
    # Create upload directory if it doesn't exist
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # Load URL history
    load_url_history()
    
    print("=" * 60)
    print("MPV Remote Player Server with Advanced Features")
    print("=" * 60)
    print(f"Working directory: {UPLOAD_DIR}")
    print(f"Server starting on http://0.0.0.0:8080")
    print("Press Ctrl+C to stop...")
    print("=" * 60)
    
    # Check for required dependencies
    try:
        import psutil
        print("[OK] psutil module found")
    except ImportError:
        print("[WARN] psutil not installed. Install with: pip3 install psutil")
    
    # Check mpv availability
    try:
        subprocess.run(["mpv", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[OK] mpv found")
    except:
        print("[ERROR] mpv not found. Please install mpv first.")
        sys.exit(1)
    
    server = HTTPServer(("0.0.0.0", 8080), FileUploadHandler)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopping server...")
        StreamingMPVHandler.kill_existing_mpv()
        server.shutdown()
        print("[SHUTDOWN] Server stopped")

if __name__ == "__main__":
    main()
