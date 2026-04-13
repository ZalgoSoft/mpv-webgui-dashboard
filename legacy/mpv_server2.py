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
from http.server import HTTPServer, BaseHTTPRequestHandler
import cgi
import io
from datetime import datetime
import sys

UPLOAD_DIR = "./"
MPV_PROCESS = None
MPV_LOCK = threading.Lock()

# Global dictionary to track upload progress
upload_progress = {}
progress_lock = threading.Lock()

class StreamingMPVHandler:
    @staticmethod
    def unmute_audio():
        """Unmute audio using amixer before playing"""
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
    def stream_to_mpv_with_queue(data_queue, save_path, filename, total_size, progress_id):
        """Stream data from queue to mpv while saving to file"""
        global MPV_PROCESS
        
        print(f"[STREAM] Starting stream for {filename} (expected {total_size} bytes)")
        print(f"[STREAM] Saving to: {save_path}")

       # Unmute audio before starting mpv
        StreamingMPVHandler.unmute_audio()
            
        with MPV_LOCK:
            # Kill previous mpv
            StreamingMPVHandler.kill_existing_mpv()
            
            # Start mpv reading from stdin
            env = os.environ.copy()
            env["DISPLAY"] = ":0"
            
            print("[MPV] Starting mpv process...")
            MPV_PROCESS = subprocess.Popen(
                ["mpv", "--cache=yes", "--cache-secs=2", "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env
            )
            print(f"[MPV] Process started with PID: {MPV_PROCESS.pid}")
        
        bytes_written = 0
        start_time = time.time()
        
        # Open file for saving
        with open(save_path, 'wb') as save_file:
            print(f"[STREAM] Waiting for first data chunk...")
            
            while True:
                try:
                    # Get chunk from queue with timeout
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
                    
                    # Save to file
                    save_file.write(chunk)
                    bytes_written += len(chunk)
                    
                    # Update progress
                    with progress_lock:
                        if progress_id in upload_progress:
                            upload_progress[progress_id]["bytes_read"] = bytes_written
                            if total_size > 0:
                                upload_progress[progress_id]["percent"] = (bytes_written / total_size) * 100
                            upload_progress[progress_id]["speed"] = bytes_written / (time.time() - start_time) if time.time() - start_time > 0 else 0
                    
                    # Log progress periodically
                    if total_size > 0:
                        percent = (bytes_written / total_size) * 100
                        if int(percent) % 10 == 0 and int(percent) > upload_progress.get(progress_id, {}).get("last_logged", 0):
                            print(f"[STREAM] Progress: {bytes_written}/{total_size} bytes ({percent:.1f}%) - Queue size: {data_queue.qsize()}")
                            upload_progress[progress_id]["last_logged"] = int(percent)
                    
                except queue.Empty:
                    print("[STREAM] Queue timeout - assuming upload complete")
                    break
                except Exception as e:
                    print(f"[STREAM] Error processing chunk: {e}")
                    break
        
        # Close mpv stdin
        with MPV_LOCK:
            if MPV_PROCESS and MPV_PROCESS.poll() is None:
                try:
                    MPV_PROCESS.stdin.close()
                    print("[MPV] stdin closed")
                except Exception as e:
                    print(f"[MPV] Error closing stdin: {e}")
        
        elapsed = time.time() - start_time
        print(f"[STREAM] Completed streaming {filename}")
        print(f"[STREAM] Total bytes: {bytes_written}, Time: {elapsed:.2f}s, Avg speed: {bytes_written/elapsed/1024/1024:.2f} MB/s")
        print(f"[STREAM] File saved to: {save_path}")
        
        # Mark as complete
        with progress_lock:
            if progress_id in upload_progress:
                upload_progress[progress_id]["complete"] = True
                upload_progress[progress_id]["save_path"] = save_path
    
    @staticmethod
    def play_existing_file(filepath):
        """Play an existing file from disk"""
        global MPV_PROCESS
        
        print(f"[MPV] Playing existing file: {filepath}")
        
        # Check if file exists
        if not os.path.exists(filepath):
            print(f"[MPV] ERROR: File not found: {filepath}")
            return False

       # Unmute audio before starting mpv
        StreamingMPVHandler.unmute_audio()
            
        with MPV_LOCK:
            # Kill previous mpv
            StreamingMPVHandler.kill_existing_mpv()
            
            # Start mpv with file
            env = os.environ.copy()
            env["DISPLAY"] = ":0"
            
            print("[MPV] Starting mpv process with file...")
            
            # Use list form to handle spaces and special characters properly
            try:
                MPV_PROCESS = subprocess.Popen(
                    ["mpv", filepath],  # Pass as separate arguments, not a single string
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env
                )
                print(f"[MPV] Process started with PID: {MPV_PROCESS.pid}")
                return True
            except Exception as e:
                print(f"[MPV] Error starting mpv: {e}")
                return False


class FileUploadHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Properly decode the path for Unicode handling
        parsed_path = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed_path.path)
        
        if path == "/":
            self.serve_index()
        elif path == "/progress":
            self.serve_progress()
        elif path == "/files":
            self.serve_file_list()
        elif path.startswith("/play/"):
            # Extract filename from path and play it
            filename = path[6:]  # Remove "/play/"
            self.play_file(filename)
        else:
            self.send_error(404)
    
    def serve_index(self):
        """Serve the main HTML page"""
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>MPV Stream Uploader</title>
            <meta charset="utf-8">
            <style>
    body { font-family: Arial, sans-serif; margin: 20px; background: #1a1a1a; color: #e0e0e0; }
    .container { max-width: 800px; margin: 0 auto; }
    .upload-section { border: 1px solid #444; padding: 20px; margin: 20px 0; border-radius: 5px; background: #2d2d2d; }
    .files-section { border: 1px solid #444; padding: 20px; margin: 20px 0; border-radius: 5px; background: #2d2d2d; }
    input[type="file"] { margin: 10px 0; color: #e0e0e0; }
    input[type="submit"] { padding: 10px 20px; background: #4CAF50; color: white; border: none; border-radius: 3px; cursor: pointer; }
    input[type="submit"]:hover { background: #45a049; }
    .progress-container { margin: 20px 0; display: none; }
    .progress-bar { width: 100%; height: 30px; background: #3a3a3a; border-radius: 5px; overflow: hidden; }
    .progress-fill { height: 100%; background: #4CAF50; width: 0%; transition: width 0.3s; }
    .progress-text { margin: 10px 0; color: #b0b0b0; }
    .file-list { list-style: none; padding: 0; }
    .file-item { padding: 10px; margin: 5px 0; background: #3a3a3a; border-radius: 3px; display: flex; justify-content: space-between; align-items: center; }
    .file-item:hover { background: #4a4a4a; }
    .play-btn { padding: 5px 15px; background: #2196F3; color: white; border: none; border-radius: 3px; cursor: pointer; text-decoration: none; }
    .play-btn:hover { background: #1976D2; }
    .delete-btn { padding: 5px 15px; background: #f44336; color: white; border: none; border-radius: 3px; cursor: pointer; margin-left: 10px; }
    .delete-btn:hover { background: #d32f2f; }
    .status { margin: 10px 0; padding: 10px; border-radius: 3px; }
    .status.success { background: #1b5e20; color: #a5d6a7; }
    .status.error { background: #b71c1c; color: #ffcdd2; }
    .refresh-btn { padding: 5px 15px; background: #ff9800; color: white; border: none; border-radius: 3px; cursor: pointer; }
    .refresh-btn:hover { background: #f57c00; }
    h1, h2 { color: #ffffff; }
    small { color: #b0b0b0; }
    strong { color: #ffffff; }
           </style>
        </head>
        <body>
            <div class="container">
                <h1>MPV Remote Player</h1>
                
                <div class="upload-section">
                    <h2>Upload and Play Video (Streaming)</h2>
                    <form id="uploadForm" enctype="multipart/form-data">
                        <input type="file" id="videoFile" name="video" accept="video/*,audio/*" required>
                        <br>
                        <input type="submit" value="Upload and Stream">
                    </form>
                    
                    <div id="progressContainer" class="progress-container">
                        <div class="progress-bar">
                            <div id="progressFill" class="progress-fill"></div>
                        </div>
                        <div id="progressText" class="progress-text"></div>
                    </div>
                    
                    <div id="uploadStatus" class="status" style="display:none;"></div>
                </div>
                
                <div class="files-section">
                    <h2>Media Files <button class="refresh-btn" onclick="loadFileList()">Refresh</button></h2>
                    <div id="fileListContainer">
                        Loading files...
                    </div>
                </div>
            </div>
            
            <script>
                const uploadForm = document.getElementById('uploadForm');
                const progressContainer = document.getElementById('progressContainer');
                const progressFill = document.getElementById('progressFill');
                const progressText = document.getElementById('progressText');
                const uploadStatus = document.getElementById('uploadStatus');
                
                uploadForm.addEventListener('submit', async (e) => {
                    e.preventDefault();
                    
                    const fileInput = document.getElementById('videoFile');
                    const file = fileInput.files[0];
                    
                    if (!file) {
                        showStatus('Please select a file', 'error');
                        return;
                    }
                    
                    const formData = new FormData();
                    formData.append('video', file);
                    
                    // Generate unique ID for this upload
                    const uploadId = Date.now() + '-' + Math.random().toString(36);
                    
                    // Show progress container
                    progressContainer.style.display = 'block';
                    uploadStatus.style.display = 'none';
                    
                    try {
                        const response = await fetch('/upload', {
                            method: 'POST',
                            body: formData,
                            headers: {
                                'X-Upload-ID': uploadId,
                                'X-File-Size': file.size
                            }
                        });
                        
                        if (response.ok) {
                            showStatus('Streaming started! MPV should begin playback shortly...', 'success');
                            fileInput.value = '';
                            
                            // Start polling for progress
                            pollProgress(uploadId);
                            
                            // Refresh file list after upload completes
                            setTimeout(loadFileList, 3000);
                        } else {
                            showStatus('Upload failed', 'error');
                            progressContainer.style.display = 'none';
                        }
                    } catch (error) {
                        showStatus('Upload error: ' + error.message, 'error');
                        progressContainer.style.display = 'none';
                    }
                });
                
                async function pollProgress(uploadId) {
                    const checkProgress = async () => {
                        try {
                            const response = await fetch('/progress?id=' + uploadId);
                            const data = await response.json();
                            
                            if (data.exists) {
                                const percent = data.percent || 0;
                                progressFill.style.width = percent + '%';
                                
                                const speedMB = (data.speed || 0) / 1024 / 1024;
                                const totalMB = data.total_size / 1024 / 1024;
                                const loadedMB = data.bytes_read / 1024 / 1024;
                                
                                progressText.innerHTML = `
                                    ${loadedMB.toFixed(2)} MB / ${totalMB.toFixed(2)} MB (${percent.toFixed(1)}%)<br>
                                    Speed: ${speedMB.toFixed(2)} MB/s<br>
                                    File: ${data.filename}
                                `;
                                
                                if (data.complete) {
                                    progressText.innerHTML += '<br>✅ Upload complete!';
                                    setTimeout(() => {
                                        progressContainer.style.display = 'none';
                                    }, 3000);
                                    loadFileList();
                                } else {
                                    setTimeout(checkProgress, 500);
                                }
                            } else {
                                setTimeout(checkProgress, 500);
                            }
                        } catch (error) {
                            console.error('Progress check error:', error);
                            setTimeout(checkProgress, 500);
                        }
                    };
                    
                    checkProgress();
                }
                
                function showStatus(message, type) {
                    uploadStatus.style.display = 'block';
                    uploadStatus.textContent = message;
                    uploadStatus.className = 'status ' + type;
                    
                    if (type === 'success') {
                        setTimeout(() => {
                            uploadStatus.style.display = 'none';
                        }, 5000);
                    }
                }
                
                async function loadFileList() {
                    try {
                        const response = await fetch('/files');
                        const files = await response.json();
                        
                        const container = document.getElementById('fileListContainer');
                        
                        if (files.length === 0) {
                            container.innerHTML = '<p>No media files found</p>';
                            return;
                        }
                        
                        let html = '<ul class="file-list">';
                        files.forEach(file => {
                            const sizeMB = (file.size / 1024 / 1024).toFixed(2);
                            const date = new Date(file.modified * 1000).toLocaleString();
                            
                            html += `
                                <li class="file-item">
                                    <div>
                                        <strong>${escapeHtml(file.name)}</strong><br>
                                        <small>Size: ${sizeMB} MB | Modified: ${date}</small>
                                    </div>
                                    <div>
                                        <button class="play-btn" onclick="playFile('${encodeURIComponent(file.name)}')">Play</button>
                                    </div>
                                </li>
                            `;
                        });
                        html += '</ul>';
                        
                        container.innerHTML = html;
                    } catch (error) {
                        document.getElementById('fileListContainer').innerHTML = '<p>Error loading files</p>';
                    }
                }
                
                async function playFile(filename) {
                    try {
                        showStatus('Playing: ' + filename, 'success');
                        const response = await fetch('/play/' + encodeURIComponent(filename));
                        const data = await response.json();
                        
                        if (data.status === 'playing') {
                            showStatus('Playing: ' + filename, 'success');
                        } else {
                            showStatus('Error playing file', 'error');
                        }
                        
                        loadFileList();
                    } catch (error) {
                        showStatus('Error playing file: ' + error.message, 'error');
                    }
                }
                
                function escapeHtml(text) {
                    const div = document.createElement('div');
                    div.textContent = text;
                    return div.innerHTML;
                }
                
                // Load file list on page load
                loadFileList();
                
                // Auto-refresh file list every 10 seconds
                setInterval(loadFileList, 10000);
            </script>
        </body>
        </html>
        """
        self.wfile.write(html.encode("utf-8"))
    
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
        
        # Find media files
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
        
        # Sort by modification time (newest first)
        files.sort(key=lambda x: x['modified'], reverse=True)
        
        # Ensure proper JSON encoding for Unicode
        response_json = json.dumps(files, ensure_ascii=False)
        self.wfile.write(response_json.encode('utf-8'))
    
    def play_file(self, filename):
        """Play an existing file"""
        # URL decode the filename properly
        filename = urllib.parse.unquote(filename)
        
        # Security: prevent directory traversal
        filename = os.path.basename(filename)
        filepath = os.path.join(UPLOAD_DIR, filename)
        
        print(f"[SERVER] Request to play file: {filepath}")
        print(f"[SERVER] File exists: {os.path.exists(filepath)}")
        
        if not os.path.exists(filepath):
            print(f"[SERVER] ERROR: File not found: {filepath}")
            self.send_error(404, "File not found")
            return
        
        # Start playing in background thread
        thread = threading.Thread(
            target=StreamingMPVHandler.play_existing_file,
            args=(filepath,)  # Pass as single argument, not with shell=True
        )
        thread.daemon = True
        thread.start()
        
        # Return success
        self.send_response(200)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        
        response = {'status': 'playing', 'file': filename}
        self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))
    
    def do_POST(self):
        if self.path == "/upload":
            self.handle_streaming_upload()
        else:
            self.send_error(404)
    
    def handle_streaming_upload(self):
        """Handle file upload with real streaming to mpv"""
        # Get upload ID and file size from headers
        upload_id = self.headers.get('X-Upload-ID', str(int(time.time())))
        expected_size = int(self.headers.get('X-File-Size', 0))
        
        content_type = self.headers.get("Content-Type", "")
        
        if "multipart/form-data" not in content_type:
            self.send_error(400, "Expected multipart/form-data")
            return
        
        # Get boundary
        boundary = None
        for part in content_type.split(";"):
            if "boundary=" in part:
                boundary = part.split("boundary=")[1].strip()
                break
        
        if not boundary:
            self.send_error(400, "No boundary found")
            return
        
        # Read headers to find filename and skip to data
        boundary_bytes = ("--" + boundary).encode()
        content_length = int(self.headers.get("Content-Length", 0))
        
        print(f"[UPLOAD] Starting streaming upload, expected size: {content_length} bytes")
        
        # Read the first part to get filename and headers
        buffer_size = 8192
        header_data = b''
        filename = None
        data_started = False
        
        # Create a queue for streaming data
        data_queue = queue.Queue()
        
        # Variables for tracking
        bytes_processed = 0
        headers_parsed = False
        
        # Read data in chunks
        while bytes_processed < content_length:
            chunk_size = min(buffer_size, content_length - bytes_processed)
            chunk = self.rfile.read(chunk_size)
            
            if not chunk:
                break
            
            bytes_processed += len(chunk)
            
            if not headers_parsed:
                header_data += chunk
                
                # Look for the end of headers
                header_end = header_data.find(b'\r\n\r\n')
                if header_end != -1:
                    # Parse headers
                    headers_part = header_data[:header_end].decode('utf-8', errors='ignore')
                    
                    # Extract filename
                    for line in headers_part.split('\r\n'):
                        if 'filename=' in line:
                            filename = line.split('filename=')[1].strip('"')
                            break
                    
                    # Find the start of actual data
                    data_start = header_end + 4
                    
                    # If we have data after headers in this chunk, process it
                    if len(header_data) > data_start:
                        first_data_chunk = header_data[data_start:]
                        if first_data_chunk:
                            # Remove trailing boundary if present
                            if first_data_chunk.endswith(b'\r\n'):
                                first_data_chunk = first_data_chunk[:-2]
                            
                            if first_data_chunk:
                                data_queue.put(first_data_chunk)
                    
                    headers_parsed = True
                    header_data = None  # Free memory
                    
                    if not filename:
                        print("[UPLOAD] ERROR: No filename in headers")
                        self.send_error(400, "No filename")
                        return
                    
                    print(f"[UPLOAD] Filename: {filename}")
                    
                    # Generate save path
                    base, ext = os.path.splitext(filename)
                    if not ext:
                        ext = ".mp4"
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    save_filename = f"{base}_{timestamp}{ext}"
                    save_path = os.path.join(UPLOAD_DIR, save_filename)
                    
                    # Initialize progress tracking
                    with progress_lock:
                        upload_progress[upload_id] = {
                            'filename': filename,
                            'save_filename': save_filename,
                            'total_size': expected_size if expected_size > 0 else content_length,
                            'bytes_read': 0,
                            'percent': 0,
                            'speed': 0,
                            'complete': False,
                            'last_logged': 0
                        }
                    
                    print(f"[UPLOAD] Will save to: {save_path}")
                    print(f"[UPLOAD] Starting streaming thread...")
                    
                    # Start streaming thread
                    stream_thread = threading.Thread(
                        target=StreamingMPVHandler.stream_to_mpv_with_queue,
                        args=(data_queue, save_path, filename, 
                              expected_size if expected_size > 0 else content_length, 
                              upload_id)
                    )
                    stream_thread.daemon = True
                    stream_thread.start()
                    
                    # Send response immediately
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
                # Process data chunk
                # Remove trailing boundary markers if present
                if chunk.endswith(b'\r\n') and b'--' + boundary.encode() in chunk:
                    chunk = chunk.replace(b'--' + boundary.encode() + b'--\r\n', b'')
                    chunk = chunk.replace(b'\r\n--' + boundary.encode() + b'--\r\n', b'')
                
                if chunk:
                    data_queue.put(chunk)
                    print(f"[UPLOAD] Received chunk: {len(chunk)} bytes, total: {bytes_processed}/{content_length}")
        
        # Signal end of stream
        data_queue.put(None)
        print(f"[UPLOAD] Upload complete, total bytes: {bytes_processed}")
    
    def log_message(self, format, *args):
        """Override to provide custom logging"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#        print(f"[{timestamp}] {self.address_string()} - {format % args}")

def main():
    # Create upload directory if it doesn't exist
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    print("=" * 50)
    print("MPV Remote Player Server with Real Streaming")
    print("=" * 50)
    print(f"Upload directory: {UPLOAD_DIR}")
    print(f"Server starting on http://0.0.0.0:8080")
    print("Press Ctrl+C to stop...")
    print("=" * 50)
    
    server = HTTPServer(("0.0.0.0", 8080), FileUploadHandler)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopping server...")
        # StreamingMPVHandler.kill_existing_mpv()
        server.shutdown()
        print("[SHUTDOWN] Server stopped")

if __name__ == "__main__":
    main()
