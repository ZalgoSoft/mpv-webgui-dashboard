#!/usr/bin/env python3
import os
import subprocess
import signal
import threading
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
import cgi
import io

UPLOAD_DIR = "./"
MPV_PROCESS = None
MPV_LOCK = threading.Lock()

class StreamingMPVHandler:
    @staticmethod
    def kill_existing_mpv():
        """Убить все запущенные процессы mpv"""
        try:
            subprocess.run(["pkill", "-9", "mpv"], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
        except Exception:
            pass
    
    @staticmethod
    def stream_to_mpv(file_stream, save_path):
        """Потоковая передача данных в mpv с сохранением"""
        global MPV_PROCESS
        
        with MPV_LOCK:
            # Убиваем предыдущий mpv
            StreamingMPVHandler.kill_existing_mpv()
            
            # Запускаем mpv с чтением из stdin
            env = os.environ.copy()
            env["DISPLAY"] = ":0"
            
            MPV_PROCESS = subprocess.Popen(
                ["mpv", "--cache=yes", "--cache-secs=2", "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env
            )
        
        # Открываем файл для сохранения
        with open(save_path, 'wb') as save_file:
            # Читаем чанками и передаём в mpv и в файл
            while True:
                chunk = file_stream.read(8192)
                if not chunk:
                    break
                
                # Пишем в mpv
                if MPV_PROCESS and MPV_PROCESS.poll() is None:
                    try:
                        MPV_PROCESS.stdin.write(chunk)
                        MPV_PROCESS.stdin.flush()
                    except BrokenPipeError:
                        pass
                
                # Сохраняем в файл
                save_file.write(chunk)
        
        # Закрываем stdin mpv
        with MPV_LOCK:
            if MPV_PROCESS and MPV_PROCESS.poll() is None:
                try:
                    MPV_PROCESS.stdin.close()
                except:
                    pass

class FileUploadHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
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
                    body { font-family: Arial, sans-serif; margin: 50px; }
                    .container { max-width: 500px; margin: 0 auto; }
                    input[type="file"] { margin: 20px 0; }
                    input[type="submit"] { padding: 10px 20px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h2>Загрузить видео для MPV</h2>
                    <form action="/upload" method="post" enctype="multipart/form-data">
                        <input type="file" name="video" accept="video/*,audio/*" required>
                        <br>
                        <input type="submit" value="Отправить и проиграть">
                    </form>
                </div>
            </body>
            </html>
            """
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_error(404)
    
    def do_POST(self):
        if self.path == "/upload":
            # Парсим multipart форму
            content_type = self.headers.get("Content-Type", "")
            
            if "multipart/form-data" not in content_type:
                self.send_error(400, "Expected multipart/form-data")
                return
            
            # Получаем boundary
            boundary = None
            for part in content_type.split(";"):
                if "boundary=" in part:
                    boundary = part.split("boundary=")[1].strip()
                    break
            
            if not boundary:
                self.send_error(400, "No boundary found")
                return
            
            # Читаем сырые данные POST запроса
            content_length = int(self.headers.get("Content-Length", 0))
            raw_data = self.rfile.read(content_length)
            
            # Парсим multipart данные
            boundary_bytes = ("--" + boundary).encode()
            parts = raw_data.split(boundary_bytes)
            
            filename = None
            file_data_start = None
            
            for part in parts:
                if b"Content-Disposition: form-data" in part:
                    # Извлекаем имя файла
                    if b"filename=" in part:
                        header_end = part.find(b"\r\n\r\n")
                        if header_end != -1:
                            headers = part[:header_end].decode("utf-8", errors="ignore")
                            for header in headers.split("\r\n"):
                                if "filename=" in header:
                                    filename = header.split("filename=")[1].strip('"')
                            
                            file_data_start = part.find(b"\r\n\r\n")
                            if file_data_start != -1:
                                file_data = part[file_data_start + 4:]
                                # Убираем завершающие \r\n
                                if file_data.endswith(b"\r\n"):
                                    file_data = file_data[:-2]
                                break
            
            if not filename or file_data is None:
                self.send_error(400, "No file uploaded")
                return
            
            # Генерируем имя файла для сохранения
            base, ext = os.path.splitext(filename)
            if not ext:
                ext = ".mp4"
            save_path = os.path.join(UPLOAD_DIR, f"{base}_{os.urandom(4).hex()}{ext}")
            
            # Создаём file-like объект из полученных данных
            file_stream = io.BytesIO(file_data)
            
            # Запускаем потоковую передачу в фоне
            thread = threading.Thread(
                target=StreamingMPVHandler.stream_to_mpv,
                args=(file_stream, save_path)
            )
            thread.daemon = True
            thread.start()
            
            # Отправляем ответ
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            
            response_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Success</title>
                <meta charset="utf-8">
            </head>
            <body>
                <h2>Файл загружается и проигрывается!</h2>
                <p>Файл: {filename}</p>
                <p>Сохраняется в: {save_path}</p>
                <a href="/">Загрузить ещё</a>
            </body>
            </html>
            """
            self.wfile.write(response_html.encode("utf-8"))
        else:
            self.send_error(404)
    
    def log_message(self, format, *args):
        # Тихий режим
        pass

def main():
    # Создаём директорию для сохранения если её нет
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    server = HTTPServer(("0.0.0.0", 8080), FileUploadHandler)
    print("Веб-сервер запущен на http://0.0.0.0:8080")
    print(f"Файлы сохраняются в: {UPLOAD_DIR}")
    print("Нажмите Ctrl+C для остановки...")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка сервера...")
        StreamingMPVHandler.kill_existing_mpv()
        server.shutdown()

if __name__ == "__main__":
    main()
