#!/usr/bin/env python3
"""
Script for downloading and playing YouTube videos.
Usage: python play_from_youtube.py YOUTUBE_URL
"""

import subprocess
import sys
import os
import time
import signal
from urllib.parse import urlparse
import re

def get_filename_from_url(url):
    """Generate filename from video URL"""
    # Extract video ID from YouTube URL
    if 'youtube.com/watch?v=' in url:
        video_id = url.split('v=')[1].split('&')[0]
    elif 'youtu.be/' in url:
        video_id = url.split('youtu.be/')[1].split('?')[0]
    else:
        # If we can't extract ID, use timestamp
        video_id = f"video_{int(time.time())}"
    
    return f"youtube_{video_id}.mp4"

def get_video_url(youtube_url):
    """Get direct video URL using youtube-dl"""
    try:
        # Get URL in format 18 (360p mp4 with audio)
        result = subprocess.run(
            ['youtube-dl', '-f', 'best*[vcodec!=none][acodec!=none][protocol=https]' ,'-g', youtube_url],
            capture_output=True,
            text=True,
            check=True
        )
        
        video_url = result.stdout.strip()
        if not video_url:
            print("Error: failed to get video URL")
            sys.exit(1)
        print(f"Download URL: {video_url}")
        with open("urls.txt", "a") as file:
            file.write(video_url)
            file.write("\n")

        return video_url
    
    except subprocess.CalledProcessError as e:
        print(f"Error getting URL: {e}")
        print(f"stderr: {e.stderr}")
        sys.exit(1)
    except FileNotFoundError:
        print("Error: youtube-dl is not installed. Install it with command:")
        print("pip install youtube-dl")
        sys.exit(1)

def download_video(video_url, output_file, proxy="192.168.1.1:1080"):
    """Download video with resume support for interrupted downloads"""
    max_retries = 100  # Maximum number of attempts
    retry_delay = 5    # Delay between attempts in seconds
    
    for attempt in range(1, max_retries + 1):
        try:
            print(f"Download attempt #{attempt}")
            
            # Check current file size for resume
            current_size = 0
            if os.path.exists(output_file):
                current_size = os.path.getsize(output_file)
                print(f"File already exists, size: {current_size} bytes")
            
            # Build curl command
            curl_cmd = [
                'curl',
#                '--socks5', proxy,
                '--continue-at', '-',  # Resume support
                '--retry', '3',
                '--retry-delay', '5',
                '--retry-max-time', '60',
                '--fail',  # Return error on HTTP errors
                '-L',
                '--progress-bar',  # Show progress
                '-o', output_file,
                video_url
            ]
            
            # Run curl
            process = subprocess.run(curl_cmd, check=False)
            
            if process.returncode == 0:
                print(f"Video successfully downloaded: {output_file}")
                
                # Check that file is not empty
                if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                    return True
                else:
                    print("Warning: downloaded file is empty")
                    if attempt < max_retries:
                        print(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        continue
            else:
                print(f"Download error (code {process.returncode})")
                
                # Check if download can be resumed
                if attempt < max_retries:
                    print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    print("Maximum number of attempts reached")
                    return False
                    
        except KeyboardInterrupt:
            print("\nDownload interrupted by user")
            print(f"Partially downloaded file saved as: {output_file}")
            print("You can resume download later by running the script again")
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected error: {e}")
            if attempt < max_retries:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                return False
    
    return False

def play_video(video_file):
    """Play video using mpv"""
    try:
        print(f"Starting playback: {video_file}")
        
        # Run mpv with specified DISPLAY
        env = os.environ.copy()
        env['DISPLAY'] = ':0'
        
        # Run mpv in background so script can exit
        subprocess.Popen(
            ['mpv', video_file],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        print("Video launched in mpv player")
        
    except FileNotFoundError:
        print("Error: mpv is not installed")
        print("Install mpv: sudo apt install mpv")
        sys.exit(1)
    except Exception as e:
        print(f"Error launching video: {e}")
        sys.exit(1)

def signal_handler(sig, frame):
    """Signal handler for graceful shutdown"""
    print("\nScript interrupted")
    sys.exit(0)

def main():
    if len(sys.argv) != 2:
        print("Usage: python play_from_youtube.py YOUTUBE_URL")
        print("Example: python play_from_youtube.py https://www.youtube.com/watch?v=dQw49WXcQ")
        sys.exit(1)
    
    # Set up signal handler
    signal.signal(signal.SIGINT, signal_handler)
    
    youtube_url = sys.argv[1]
    
    # Check if this is a YouTube URL
    if not ('youtube.com' in youtube_url or 'youtu.be' in youtube_url):
        print("Warning: this may not be a YouTube URL")
    
    print(f"Processing video: {youtube_url}")
    
    # Get direct video URL
    print("Getting direct video URL...")
    video_url = get_video_url(youtube_url)
    print(f"Download URL obtained")
    
    # Generate filename
    output_file = get_filename_from_url(youtube_url)
    
    # Download video
    print(f"Starting download to file: {output_file}")
    
    if download_video(video_url, output_file):
        # Play video
        play_video(output_file)
        
        print("Done! Video launched and script is exiting.")
        print(f"File saved as: {output_file}")
    else:
        print("Failed to download video completely")
        if os.path.exists(output_file):
            print(f"Partially downloaded file: {output_file}")
        sys.exit(1)

if __name__ == "__main__":
    main()
