#!/usr/bin/env python3
"""
MPV Web Dashboard with JSON IPC control
Provides full playback control, media info display, and file browser
"""

import os
import json
import subprocess
import threading
import time
import glob
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import socket
import select
from datetime import datetime
import time

# Configuration
MPV_SOCKET = "/tmp/mpv-web-socket"
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080
DISPLAY_ENV = ":0"

class MPVController:
    """Manages MPV instance and IPC communication"""
    
    def __init__(self):
        self.process = None
        self.socket_path = MPV_SOCKET
        self._start_mpv()
        
    def _start_mpv(self):
        """Launch MPV with IPC server enabled"""
        # Remove old socket if exists
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
            
        env = os.environ.copy()
        env["DISPLAY"] = DISPLAY_ENV
        
        cmd = [
            "mpv",
            "--idle=yes",
#            "--force-window=yes",
#            "--keep-open=yes",
            "--input-ipc-server=" + self.socket_path,
#            "--osc=yes",
#            "--osd-level=2",
            "--fullscreen=yes",
            "--ontop=no" 
#,
#            "--video-sync=display-resample",
#            "--hwdec=auto"
        ]
        
        self.process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Wait for socket to be ready
        for _ in range(50):
            if os.path.exists(self.socket_path):
                break
            time.sleep(0.1)

        media_extensions = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.mp3', '.flac', '.wav'}
        current_dir = os.getcwd()
        for item in sorted(Path(current_dir).iterdir()):
            if item.is_file() and item.suffix.lower() in media_extensions:
                self.send_command({"command": ["loadfile", str(item.absolute()), "append-play"]})
        print(f"[PLAYLIST] Initial playlist loaded")
        time.sleep(0.5)
        self._unmute_audio()

    def ensure_mpv_running(self):
        """Check if MPV is running and restart if needed"""
        if self.process and self.process.poll() is not None:
            print("[MPV] Process died, restarting...")
            self._start_mpv()
        elif not os.path.exists(self.socket_path):
            print("[MPV] Socket missing, restarting...")
            self._start_mpv()
        return os.path.exists(self.socket_path)
            
    def send_command(self, command):
        """Send JSON command to MPV and get response"""
        self.ensure_mpv_running() 
        if not os.path.exists(self.socket_path):
            return None
            
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(self.socket_path)
            
            # Send command
            cmd_json = json.dumps(command) + "\n"
            if not (isinstance(command.get("command"), list) and 
                    command["command"][0] == "get_property"):
                print(f"[IPC SEND] {cmd_json.strip()}")
            sock.send(cmd_json.encode())
            
            # Wait for response with timeout
            ready = select.select([sock], [], [], 1.0)
            if ready[0]:
                response = sock.recv(4096).decode()
                if not (isinstance(command.get("command"), list) and 
                        command["command"][0] == "get_property"):
                    print(f"[IPC RECV] {response.strip()}")
                return json.loads(response)
            return None
            
        except Exception as e:
            print(f"IPC Error: {e}")
            return None
        finally:
            sock.close()
            
    def get_property(self, prop_name):
        """Get MPV property value"""
        cmd = {"command": ["get_property", prop_name]}
        response = self.send_command(cmd)
        return response.get("data") if response else None
        
    def set_property(self, prop_name, value):
        """Set MPV property value"""
        cmd = {"command": ["set_property", prop_name, value]}
        return self.send_command(cmd)
        
    def observe_property(self, prop_name):
        """Start observing a property for changes"""
        cmd = {"command": ["observe_property", 1, prop_name]}
        return self.send_command(cmd)

    def get_media_info(self):
        """Get comprehensive media information"""
        info = {
            "path": self.get_property("path"),
            "filename": self.get_property("filename"),
            "media-title": self.get_property("media-title"),
            "duration": self.get_property("duration"),
            "time-pos": self.get_property("time-pos"),
            "time-remaining": self.get_property("time-remaining"),
            "percent-pos": self.get_property("percent-pos"),
            "pause": self.get_property("pause"),
            "volume": self.get_property("volume"),
            "mute": self.get_property("mute"),
            "speed": self.get_property("speed"),
            "loop": self.get_property("loop"),
            "video-codec": self.get_property("video-codec"),
            "audio-codec": self.get_property("audio-codec"),
            "video-bitrate": self.get_property("video-bitrate"),
            "audio-bitrate": self.get_property("audio-bitrate"),
            "width": self.get_property("width"),
            "height": self.get_property("height"),
            "fps": self.get_property("container-fps"),
            "audio-channels": self.get_property("audio-channels"),
            "audio-samplerate": self.get_property("audio-samplerate"),
            "file-size": self.get_property("file-size"),
            "playlist-count": self.get_property("playlist-count"),
            "playlist-pos": self.get_property("playlist-pos"),
            "chapter": self.get_property("chapter"),
            "chapters": self.get_property("chapters"),
            "seekable": self.get_property("seekable"),
            "stream-path": self.get_property("stream-path"),
            "demuxer": self.get_property("current-demuxer")
        }
        return info

    def _unmute_audio(self):
        """Execute audio unmute command"""
        print("[AUDIO] Unmuting audio...")
        subprocess.run(
            ["amixer", "-c", "0", "cset", "numid=24", "on"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False
        )

    def load_file(self, filepath, mode="replace"):
        """Load media file or stream"""
        self._unmute_audio()
        cmd = {"command": ["loadfile", filepath, mode]}
        result = self.send_command(cmd)
        # Auto-unpause after loading
        time.sleep(0.2)
        self.set_property("pause", False)
        return result

    def playlist_next(self):
        """Play next item in playlist"""
        cmd = {"command": ["playlist-next"]}
        return self.send_command(cmd)
        
    def playlist_prev(self):
        """Play previous item in playlist"""
        cmd = {"command": ["playlist-prev"]}
        return self.send_command(cmd)
        
    def toggle_pause(self):
        """Toggle pause state"""
        cmd = {"command": ["cycle", "pause"]}
        return self.send_command(cmd)
        
    def stop(self):
        """Stop playback"""
        cmd = {"command": ["stop"]}
        return self.send_command(cmd)
        
    def seek(self, seconds, mode="relative"):
        """Seek in current media"""
        cmd = {"command": ["seek", seconds, mode]}
        return self.send_command(cmd)
        
    def add_volume(self, delta):
        """Adjust volume by delta"""
        cmd = {"command": ["add", "volume", delta]}
        return self.send_command(cmd)
        
    def cycle_loop(self):
        """Cycle through loop modes"""
        cmd = {"command": ["cycle-values", "loop", "inf", "no"]}
        return self.send_command(cmd)
        
    def get_v4l_devices(self):
        """Get available V4L devices"""
        devices = glob.glob("/dev/video*")
        return devices
        
    def cleanup(self):
        """Terminate MPV process"""
        if self.process:
            self.process.terminate()
            self.process.wait()
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

class WebHandler(BaseHTTPRequestHandler):
    """HTTP request handler for web dashboard"""
    
    mpv_controller = None
    
#    def log_message(self, format, *args):
#        """Override to provide custom logging"""
#        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#        print(f"[{timestamp}] {self.address_string()} - {format % args}")

    def log_message(self, format, *args):
        """Suppress default logging"""
        pass
    
    def do_GET(self):
        """Handle GET requests"""
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == "/":
            self._serve_dashboard()
        elif path == "/api/status":
            self._api_status()
        elif path == "/api/files":
            self._api_files()
        elif path == "/api/v4l":
            self._api_v4l_devices()
        elif path == "/api/command":
            self._api_command(parsed.query)
        else:
            self._send_response(404, "Not Found")
    
    def do_POST(self):
        """Handle POST requests"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode()
    
        print(f"[DEBUG POST] Path: {self.path}")
        print(f"[DEBUG POST] Content-Type: {self.headers.get('Content-Type')}")
        print(f"[DEBUG POST] Raw data:\n{post_data}")
    
        if self.path == "/api/command":
            self._api_command_post(post_data)
        else:
            self._send_response(404, "Not Found")
    
    def _send_response(self, code, data, content_type="text/plain"):
        """Send HTTP response"""
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        
        if isinstance(data, (dict, list)):
            data = json.dumps(data, indent=2)
            self.wfile.write(data.encode())
        else:
            self.wfile.write(str(data).encode())
    
    def _serve_dashboard(self):
        """Serve main dashboard HTML"""
        html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MPV Dashboard</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;font-family:system-ui,monospace}
        body{background:#0a0a0a;color:#e0e0e0;padding:20px;min-height:100vh}
        .container{max-width:1400px;margin:0 auto}
        h1{color:#4fc3f7;margin-bottom:20px;font-size:2em;font-weight:300}
        h2{color:#81d4fa;margin:15px 0;font-size:1.3em;font-weight:400}
        .grid{display:grid;grid-template-columns:1fr 400px;gap:20px}
        .panel{background:#1a1a1a;border-radius:8px;padding:20px;border:1px solid #333}
        .controls{display:flex;gap:10px;margin:20px 0;flex-wrap:wrap}
        button{background:#2a2a2a;color:#fff;border:1px solid #444;padding:10px 20px;border-radius:5px;cursor:pointer;font-size:14px;transition:all 0.2s}
        button:hover{background:#3a3a3a;border-color:#666}
        button.primary{background:#0288d1;border-color:#4fc3f7}
        button.primary:hover{background:#0277bd}
        button.danger{background:#d32f2f;border-color:#ef5350}
        button.danger:hover{background:#c62828}
        input,select{background:#2a2a2a;color:#fff;border:1px solid #444;padding:10px;border-radius:5px;font-size:14px}
        input[type="range"]{width:100%;padding:0}
        input[type="text"],select{width:100%}
        .info-grid{display:grid;grid-template-columns:auto 1fr;gap:8px 15px;margin-top:15px}
        .info-label{color:#888}
        .info-value{color:#4fc3f7;word-break:break-word}
        .file-list{max-height:400px;overflow-y:auto;margin-top:15px}
        .file-item{padding:8px;border-bottom:1px solid #333;cursor:pointer;transition:background 0.2s}
        .file-item:hover{background:#2a2a2a}
        .file-item i{color:#888;margin-right:10px}
        .progress-bar{width:100%;height:6px;background:#333;border-radius:3px;margin:15px 0;cursor:pointer;position:relative}
        .progress-fill{height:100%;background:#4fc3f7;border-radius:3px;width:0%;transition:width 0.1s}
        .time-display{display:flex;justify-content:space-between;margin-top:5px;font-size:12px;color:#888}
        .status-badge{display:inline-block;padding:3px 10px;border-radius:12px;font-size:12px;background:#333}
        .status-badge.playing{background:#2e7d32;color:#fff}
        .status-badge.paused{background:#f57c00;color:#fff}
        .volume-control{display:flex;align-items:center;gap:10px}
        .tabs{display:flex;gap:5px;margin-bottom:15px;border-bottom:1px solid #333}
        .tab{padding:8px 16px;background:none;border:none;color:#888;cursor:pointer;border-bottom:2px solid transparent}
        .tab.active{color:#4fc3f7;border-bottom-color:#4fc3f7}
        .tab-content{display:none}
        .tab-content.active{display:block}
        .url-input{margin-top:15px}
        .shortcut-hint{font-size:12px;color:#666;margin-top:5px}
        @media(max-width:768px){.grid{grid-template-columns:1fr}}
    </style>
</head>
<body>
    <div class="container">
        <h1>🎬 MPV Media Player Dashboard</h1>
        
        <div class="grid">
            <div class="main-panel">
                <div class="panel">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <h2>Now Playing</h2>
                        <span class="status-badge" id="playback-status">STOPPED</span>
                    </div>
                    
                    <div id="now-playing-title" style="font-size:1.2em;margin:10px 0;color:#fff">No media loaded</div>
                    
                    <div class="progress-bar" id="seek-bar">
                        <div class="progress-fill" id="progress-fill"></div>
                    </div>
                    
                    <div class="time-display">
                        <span id="current-time">00:00:00</span>
                        <span id="duration-time">00:00:00</span>
                    </div>
                    
                    <div class="controls">
                        <button onclick="sendCommand('playlist-prev')">⏮ Prev</button>
                        <button onclick="sendCommand('toggle-pause')">⏯ Play/Pause</button>
                        <button onclick="sendCommand('set-pause', {pause: false})">▶ Play</button>
                        <button onclick="sendCommand('set-pause', {pause: true})">⏸ Pause</button>
                        <button onclick="sendCommand('stop')">⏹ Stop</button>
                        <button onclick="sendCommand('playlist-next')">⏭ Next</button>
                        <button onclick="sendCommand('cycle-loop')">🔁 Loop</button>
                    </div>
                    
                    <div class="controls">
                        <button onclick="seekRelative(-10)">⏪ -10s</button>
                        <button onclick="seekRelative(10)">⏩ +10s</button>
                        <button onclick="seekRelative(-60)">◀◀ -60s</button>
                        <button onclick="seekRelative(60)">▶▶ +60s</button>
                        <button onclick="sendCommand('add-volume', {delta:-5})">🔉 -5</button>
                        <button onclick="sendCommand('add-volume', {delta:5})">🔊 +5</button>
                    </div>
                    
                    <div class="volume-control">
                        <span>🔈 Volume:</span>
                        <input type="range" id="volume-slider" min="0" max="130" value="100" onchange="setVolume(this.value)">
                        <span id="volume-value">100%</span>
                        <span id="mute-indicator" style="margin-left:10px;color:#f57c00"></span>
                    </div>
                </div>
                
                <div class="panel">
                    <div class="tabs">
                        <button class="tab active" onclick="switchTab('info')">Media Info</button>
                        <button class="tab" onclick="switchTab('codec')">Codec Info</button>
                        <button class="tab" onclick="switchTab('stream')">Stream/URL</button>
                    </div>
                    
                    <div id="tab-info" class="tab-content active">
                        <div class="info-grid" id="media-info"></div>
                    </div>
                    
                    <div id="tab-codec" class="tab-content">
                        <div class="info-grid" id="codec-info"></div>
                    </div>
                    
                    <div id="tab-stream" class="tab-content">
                        <div class="url-input">
                            <h3>Open Network Stream</h3>
                            <input type="text" id="stream-url" placeholder="http://, rtsp://, udp://, etc.">
                            <button onclick="loadStream()" style="margin-top:10px">Load Stream</button>
                        </div>
                        <div class="url-input">
                            <h3>Open V4L Device</h3>
                            <select id="v4l-select"></select>
                            <button onclick="loadV4L()" style="margin-top:10px">Load Device</button>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="side-panel">
                <div class="panel">
                    <h2>📁 Media Files</h2>
                    <div style="margin:10px 0">
                        <input type="text" id="file-filter" placeholder="Filter files..." onkeyup="filterFiles()">
                    </div>
                    <div class="file-list" id="file-list">
                        Loading files...
                    </div>
                    <div class="shortcut-hint">
                        Current directory: <span id="current-dir"></span>
                    </div>
                </div>
                
                <div class="panel">
                    <h2>🎯 Quick Controls</h2>
                    <button onclick="setSpeed(1.0)">1x</button>
                    <button onclick="setSpeed(1.5)">1.5x</button>
                    <button onclick="setSpeed(2.0)">2x</button>
                    <button onclick="setSpeed(0.5)">0.5x</button>
                    <button onclick="toggleSubtitle()">📝 Subs</button>
                    <button onclick="cycleAudioTrack()">🔊 Audio</button>
                    <button onclick="takeScreenshot()">📸 Screenshot</button>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let currentFiles = [];
        let updateInterval = null;
        
        // Initialize on page load
        document.addEventListener('DOMContentLoaded', () => {
            loadFiles();
            loadV4LDevices();
            startStatusUpdates();
            
            // Seek bar click handler
            document.getElementById('seek-bar').addEventListener('click', seekToPosition);
        });
        
        function startStatusUpdates() {
            if (updateInterval) clearInterval(updateInterval);
            updateInterval = setInterval(updateStatus, 1000);
        }
        
        async function updateStatus() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                updateUI(data);
            } catch (e) {
                console.error('Status update failed:', e);
            }
        }
        
        function updateUI(data) {
            // Update title
            const title = data['media-title'] || data.filename || 'No media loaded';
            document.getElementById('now-playing-title').textContent = title;
            
            // Update status badge
            const statusBadge = document.getElementById('playback-status');
            if (data.pause) {
                statusBadge.textContent = 'PAUSED';
                statusBadge.className = 'status-badge paused';
            } else if (data.path) {
                statusBadge.textContent = 'PLAYING';
                statusBadge.className = 'status-badge playing';
            } else {
                statusBadge.textContent = 'STOPPED';
                statusBadge.className = 'status-badge';
            }
            
            // Update progress
            if (data.duration && data['time-pos']) {
                const percent = (data['time-pos'] / data.duration) * 100;
                document.getElementById('progress-fill').style.width = percent + '%';
                document.getElementById('current-time').textContent = formatTime(data['time-pos']);
                document.getElementById('duration-time').textContent = formatTime(data.duration);
            } else {
                document.getElementById('progress-fill').style.width = '0%';
                document.getElementById('current-time').textContent = '00:00:00';
                document.getElementById('duration-time').textContent = '00:00:00';
            }
            
            // Update volume
            if (data.volume !== undefined) {
                document.getElementById('volume-slider').value = data.volume;
                document.getElementById('volume-value').textContent = data.volume + '%';
                document.getElementById('mute-indicator').textContent = data.mute ? '🔇 MUTED' : '';
            }
            
            // Update media info
            updateInfoGrid('media-info', {
                'File': data.filename || 'N/A',
                'Title': data['media-title'] || 'N/A',
                'Duration': formatTime(data.duration),
                'Position': formatTime(data['time-pos']),
                'Remaining': formatTime(data['time-remaining']),
                'Playlist': `${data['playlist-pos'] || 0}/${data['playlist-count'] || 0}`,
                'Speed': data.speed ? data.speed.toFixed(2) + 'x' : '1.00x',
                'Loop': data.loop || 'no',
                'Seekable': data.seekable ? 'Yes' : 'No',
                'File Size': formatBytes(data['file-size'])
            });
            
            // Update codec info
            updateInfoGrid('codec-info', {
                'Video Codec': data['video-codec'] || 'N/A',
                'Audio Codec': data['audio-codec'] || 'N/A',
                'Resolution': data.width && data.height ? `${data.width}x${data.height}` : 'N/A',
                'FPS': data.fps ? data.fps.toFixed(2) : 'N/A',
                'Video Bitrate': data['video-bitrate'] ? formatBitrate(data['video-bitrate']) : 'N/A',
                'Audio Bitrate': data['audio-bitrate'] ? formatBitrate(data['audio-bitrate']) : 'N/A',
                'Audio Channels': data['audio-channels'] || 'N/A',
                'Sample Rate': data['audio-samplerate'] ? (data['audio-samplerate']/1000).toFixed(1) + ' kHz' : 'N/A',
                'Demuxer': data.demuxer || 'N/A',
                'Stream Path': data['stream-path'] || 'N/A'
            });
        }
        
        function updateInfoGrid(gridId, items) {
            const grid = document.getElementById(gridId);
            let html = '';
            for (const [key, value] of Object.entries(items)) {
                html += `<div class="info-label">${key}:</div>`;
                html += `<div class="info-value">${value || 'N/A'}</div>`;
            }
            grid.innerHTML = html;
        }
        
        async function sendCommand(cmd, params = {}) {
            try {
                const formData = new FormData();
                formData.append('command', cmd);
                formData.append('params', JSON.stringify(params));
                
                await fetch('/api/command', {
                    method: 'POST',
                    body: formData
                });
                
                // Immediate status update
                setTimeout(updateStatus, 100);
            } catch (e) {
                console.error('Command failed:', e);
            }
        }
        
        async function loadFiles() {
            try {
                const response = await fetch('/api/files');
                currentFiles = await response.json();
                displayFiles(currentFiles);
                document.getElementById('current-dir').textContent = currentFiles.directory || '.';
            } catch (e) {
                console.error('Failed to load files:', e);
            }
        }
        
        function displayFiles(files) {
            const container = document.getElementById('file-list');
            if (!files.list || files.list.length === 0) {
                container.innerHTML = '<div class="file-item">No media files found</div>';
                return;
            }
            
            let html = '';
            for (const file of files.list) {
                const icon = file.type === 'dir' ? '📁' : getFileIcon(file.name);
                html += `<div class="file-item" onclick="playFile('${escapeHtml(file.path)}')">`;
                html += `<i>${icon}</i> ${escapeHtml(file.name)}`;
                if (file.size) html += ` <span style="color:#666;font-size:12px">(${formatBytes(file.size)})</span>`;
                html += '</div>';
            }
            container.innerHTML = html;
        }
        
        function getFileIcon(filename) {
            const ext = filename.split('.').pop().toLowerCase();
            const icons = {
                mp4: '🎬', mkv: '🎬', avi: '🎬', mov: '🎬', webm: '🎬',
                mp3: '🎵', flac: '🎵', wav: '🎵', ogg: '🎵', m4a: '🎵',
                jpg: '🖼', png: '🖼', gif: '🖼', bmp: '🖼',
                srt: '📝', ass: '📝', vtt: '📝'
            };
            return icons[ext] || '📄';
        }
        
        function playFile(path) {
            sendCommand('loadfile', {path: path});
        }
        
        function filterFiles() {
            const filter = document.getElementById('file-filter').value.toLowerCase();
            const filtered = currentFiles.list.filter(f => 
                f.name.toLowerCase().includes(filter)
            );
            displayFiles({list: filtered, directory: currentFiles.directory});
        }
        
        async function loadV4LDevices() {
            try {
                const response = await fetch('/api/v4l');
                const devices = await response.json();
                const select = document.getElementById('v4l-select');
                select.innerHTML = devices.map(d => 
                    `<option value="${d}">${d}</option>`
                ).join('');
            } catch (e) {
                console.error('Failed to load V4L devices:', e);
            }
        }
        
        function loadStream() {
            const url = document.getElementById('stream-url').value;
            if (url) sendCommand('loadfile', {path: url});
        }
        
        function loadV4L() {
            const device = document.getElementById('v4l-select').value;
            if (device) sendCommand('loadfile', {path: `av://v4l2:${device}`});
        }
        
        function seekRelative(seconds) {
            sendCommand('seek', {seconds: seconds, mode: 'relative'});
        }
        
        function seekToPosition(e) {
            const bar = document.getElementById('seek-bar');
            const rect = bar.getBoundingClientRect();
            const percent = (e.clientX - rect.left) / rect.width;
            sendCommand('seek', {seconds: percent * 100, mode: 'absolute-percent'});
        }
        
        function setVolume(value) {
            sendCommand('set-property', {property: 'volume', value: parseFloat(value)});
            document.getElementById('volume-value').textContent = value + '%';
        }
        
        function setSpeed(speed) {
            sendCommand('set-property', {property: 'speed', value: speed});
        }
        
        function toggleSubtitle() {
            sendCommand('cycle', {property: 'sub-visibility'});
        }
        
        function cycleAudioTrack() {
            sendCommand('cycle', {property: 'audio'});
        }
        
        function takeScreenshot() {
            sendCommand('screenshot');
        }
        
        function switchTab(tabName) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            
            document.querySelector(`[onclick="switchTab('${tabName}')"]`).classList.add('active');
            document.getElementById(`tab-${tabName}`).classList.add('active');
        }
        
        function formatTime(seconds) {
            if (!seconds || seconds < 0) return '00:00:00';
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            const s = Math.floor(seconds % 60);
            return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
        }
        
        function formatBytes(bytes) {
            if (!bytes) return 'N/A';
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(1024));
            return (bytes / Math.pow(1024, i)).toFixed(2) + ' ' + sizes[i];
        }
        
        function formatBitrate(bps) {
            if (!bps) return 'N/A';
            return (bps / 1000).toFixed(0) + ' kbps';
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
    </script>
</body>
</html>"""
        
        self._send_response(200, html, "text/html")
    
    def _api_status(self):
        """API endpoint for current status"""
        if not self.mpv_controller:
            self._send_response(500, {"error": "MPV controller not initialized"})
            return
            
        info = self.mpv_controller.get_media_info()
        self._send_response(200, info, "application/json")
    
    def _api_files(self):
        """API endpoint for file listing"""
        current_dir = os.getcwd()
        files = []
        
        # Supported media extensions
        media_extensions = {
            '.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv',
            '.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac', '.opus',
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
            '.srt', '.ass', '.vtt', '.ssa'
        }
        
        try:
            for item in sorted(Path(current_dir).iterdir()):
                if item.is_file() and item.suffix.lower() in media_extensions:
                    files.append({
                        "name": item.name,
                        "path": str(item.absolute()),
                        "size": item.stat().st_size,
                        "type": "file"
                    })
                elif item.is_dir():
                    files.append({
                        "name": item.name + "/",
                        "path": str(item.absolute()),
                        "type": "dir"
                    })
        except Exception as e:
            print(f"Error reading directory: {e}")
            
        result = {
            "directory": current_dir,
            "list": files
        }
        self._send_response(200, result, "application/json")
    
    def _api_v4l_devices(self):
        """API endpoint for V4L devices"""
        devices = self.mpv_controller.get_v4l_devices()
        self._send_response(200, devices, "application/json")
    
    def _api_command(self, query_string):
        """Handle GET command requests (legacy)"""
        params = parse_qs(query_string)
        cmd = params.get('cmd', [''])[0]
        
        if cmd == 'play':
            path = params.get('path', [''])[0]
            if path:
                self.mpv_controller.load_file(path)
                
        self._send_response(200, {"status": "ok"})
    

    def _api_command_post(self, post_data):
        """Handle POST command requests"""
        try:
            import cgi
            from io import BytesIO
        
            content_type = self.headers.get('Content-Type', '')
            print(f"[DEBUG API] Parsing POST, Content-Type: {content_type}")
        
            if 'multipart/form-data' in content_type:
                environ = {
                    'REQUEST_METHOD': 'POST',
                    'CONTENT_TYPE': content_type,
                    'CONTENT_LENGTH': self.headers.get('Content-Length', '0'),
                }
                form = cgi.FieldStorage(
                    fp=BytesIO(post_data.encode()),
                    environ=environ,
                    keep_blank_values=True
                )
                command = form.getvalue('command', '')
                params_raw = form.getvalue('params', '{}')
                print(f"[DEBUG API] Command: {command}")
                print(f"[DEBUG API] Params raw: {params_raw}")
                cmd_params = json.loads(params_raw)
                print(f"[DEBUG API] Params parsed: {cmd_params}")
            
            result = {"status": "ok"}
            
            if command == 'loadfile':
                path = cmd_params.get('path', '')
                if path:
                    self.mpv_controller.load_file(path)
                    
            elif command == 'playlist-next':
                self.mpv_controller.playlist_next()
                
            elif command == 'playlist-prev':
                self.mpv_controller.playlist_prev()
                
            elif command == 'toggle-pause':
                self.mpv_controller.toggle_pause()

            elif command == 'set-pause':
                pause_state = cmd_params.get('pause', False)
                self.mpv_controller.set_property("pause", pause_state)                

            elif command == 'stop':
                self.mpv_controller.stop()
                
            elif command == 'seek':
                seconds = cmd_params.get('seconds', 0)
                mode = cmd_params.get('mode', 'relative')
                self.mpv_controller.seek(seconds, mode)
                
            elif command == 'add-volume':
                delta = cmd_params.get('delta', 5)
                self.mpv_controller.add_volume(delta)
                
            elif command == 'set-property':
                prop = cmd_params.get('property', '')
                value = cmd_params.get('value')
                if prop and value is not None:
                    self.mpv_controller.set_property(prop, value)
                    
            elif command == 'cycle':
                prop = cmd_params.get('property', '')
                if prop:
                    self.mpv_controller.send_command({"command": ["cycle", prop]})
                    
            elif command == 'cycle-loop':
                self.mpv_controller.cycle_loop()
                
            elif command == 'screenshot':
                self.mpv_controller.send_command({"command": ["screenshot"]})
                
            self._send_response(200, result, "application/json")
            
        except Exception as e:
            self._send_response(500, {"error": str(e)}, "application/json")

def main():
    """Main entry point"""
    print("Starting MPV Web Dashboard...")
    print(f"DISPLAY={DISPLAY_ENV}")
    print(f"HTTP Server: http://{HTTP_HOST}:{HTTP_PORT}")
    
    # Initialize MPV controller
    controller = MPVController()
    WebHandler.mpv_controller = controller
    
    # Start HTTP server
    server = HTTPServer((HTTP_HOST, HTTP_PORT), WebHandler)
    
    try:
        print("Server running. Press Ctrl+C to stop.")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        controller.cleanup()
        server.shutdown()
        print("Done.")

if __name__ == "__main__":
    main()
