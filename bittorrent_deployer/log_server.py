"""
HTTP Log Server for BitTorrent Network Deployment
"""

import os
import json
import time
import threading
import re
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from .constants import (
    LOGS_DIR, HTTP_OK, HTTP_NOT_FOUND, LOGS_ENDPOINT, STREAM_ENDPOINT,
    COMPLETION_ENDPOINT, COLOR_RESET, COLOR_BOLD, COLOR_RED, COLOR_GREEN,
    COLOR_YELLOW, COLOR_BLUE, COLOR_MAGENTA, COLOR_CYAN
)


class LogHandler(BaseHTTPRequestHandler):
    """HTTP request handler for collecting logs and status from EC2 instances"""
    
    # Class variables for shared state across requests
    logs_dir = LOGS_DIR
    completion_status = {}
    instance_status = {}
    run_name = None
    last_display_time = 0
    
    # Status stages
    STATUS_STARTING = "starting"
    STATUS_UPDATING = "updating"
    STATUS_INSTALLING = "installing"
    STATUS_DOWNLOADING = "downloading"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_ERROR = "error"
    
    @classmethod
    def set_run_name(cls, run_name):
        """
        Set the run name and create log directory
        
        Args:
            run_name (str): Unique run identifier
        """
        cls.run_name = run_name
        run_dir = os.path.join(cls.logs_dir, run_name)
        os.makedirs(run_dir, exist_ok=True)
    
    @classmethod
    def update_instance_status(cls, instance_id, status, progress=None, message=None):
        """
        Update instance status and refresh display
        
        Args:
            instance_id (str): Instance identifier
            status (str): Current status
            progress (float, optional): Progress percentage
            message (str, optional): Additional status message
        """
        cls.instance_status[instance_id] = {
            'status': status,
            'progress': progress,
            'message': message or '',
            'timestamp': time.time()
        }
        
        # Throttle display updates to avoid spam
        current_time = time.time()
        if current_time - cls.last_display_time > 1.0:  # Update max once per second
            cls.display_status_dashboard()
            cls.last_display_time = current_time
    
    @classmethod
    def display_status_dashboard(cls):
        """Display a clean status dashboard"""
        print('\033[2J\033[H', end='')  # Clear screen and move cursor to top
        
        print(f"{COLOR_BOLD}{COLOR_MAGENTA}🚀 BitTorrent Network Status Dashboard{COLOR_RESET}")
        print(f"{COLOR_BOLD}{COLOR_YELLOW}📁 Run: {cls.run_name}{COLOR_RESET}")
        print("=" * 80)
        
        # Group by region and role
        regions = {}
        for instance_id, info in cls.instance_status.items():
            # Parse instance_id format: "region-role-index" 
            # Handle multi-part regions like "eu-west-1"
            parts = instance_id.split('-')
            if len(parts) >= 3:
                # Find the role (seeder or leecher) in the parts
                role = None
                region_parts = []
                
                for i, part in enumerate(parts):
                    if part in ['seeder', 'leecher']:
                        role = part
                        region_parts = parts[:i]  # Everything before the role
                        break
                
                if role and region_parts:
                    region = '-'.join(region_parts)  # Reconstruct region name
                    if region not in regions:
                        regions[region] = {'seeders': [], 'leechers': []}
                    regions[region][role + 's'].append((instance_id, info))
        
        for region_name, roles in regions.items():
            print(f"\n{COLOR_BOLD}{COLOR_BLUE}🌍 {region_name.upper()}{COLOR_RESET}")
            
            # Show seeders
            if roles['seeders']:
                print(f"  {COLOR_GREEN}🌱 Seeders:{COLOR_RESET}")
                for instance_id, info in roles['seeders']:
                    status_emoji, status_text = cls._get_status_display(info['status'], info.get('progress'))
                    print(f"    {status_emoji} {instance_id}: {status_text}")
            
            # Show leechers  
            if roles['leechers']:
                print(f"  {COLOR_BLUE}📥 Leechers:{COLOR_RESET}")
                for instance_id, info in roles['leechers']:
                    status_emoji, status_text = cls._get_status_display(info['status'], info.get('progress'))
                    print(f"    {status_emoji} {instance_id}: {status_text}")
        
        # Summary
        total_instances = len(cls.instance_status)
        completed_count = len([i for i in cls.instance_status.values() if i['status'] == cls.STATUS_COMPLETED])
        running_count = len([i for i in cls.instance_status.values() if i['status'] == cls.STATUS_RUNNING])
        
        print(f"\n{COLOR_BOLD}📊 Summary:{COLOR_RESET}")
        print(f"  Total: {total_instances} | Running: {running_count} | Completed: {completed_count}")
    
    @classmethod 
    def _get_status_display(cls, status, progress=None):
        """
        Get emoji and text for status display
        
        Args:
            status (str): Current status
            progress (float, optional): Progress percentage
            
        Returns:
            tuple: (emoji, status_text)
        """
        status_map = {
            cls.STATUS_STARTING: ("🔄", "Starting up"),
            cls.STATUS_UPDATING: ("📦", "Updating system"), 
            cls.STATUS_INSTALLING: ("⚙️", "Installing packages"),
            cls.STATUS_DOWNLOADING: ("⬇️", "Downloading files"),
            cls.STATUS_RUNNING: ("🚀", f"Running BitTorrent {progress}%" if progress else "Running BitTorrent"),
            cls.STATUS_COMPLETED: ("🎉", "Completed"),
            cls.STATUS_ERROR: ("❌", "Error")
        }
        
        emoji, text = status_map.get(status, ("❓", f"Unknown: {status}"))
        
        if status == cls.STATUS_RUNNING and progress is not None:
            text = f"Running BitTorrent {progress:.1f}%"
            
        return emoji, text
    
    def do_POST(self):
        """Handle POST requests from EC2 instances"""
        if self.path == LOGS_ENDPOINT:
            self._handle_logs()
        elif self.path == STREAM_ENDPOINT:
            self._handle_stream()
        elif self.path == COMPLETION_ENDPOINT:
            self._handle_completion()
        else:
            self.send_response(HTTP_NOT_FOUND)
            self.end_headers()
    
    def _handle_logs(self):
        """Handle final log file upload from instances"""
        content_type = self.headers.get('Content-Type', '')
        if not content_type.startswith('multipart/form-data'):
            self.send_response(400)
            self.end_headers()
            return
        
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        boundary = content_type.split('boundary=')[1].encode()
        parts = post_data.split(b'--' + boundary)
        
        instance_id = None
        log_data = None
        
        for part in parts:
            if b'name="instance_id"' in part:
                instance_id = part.split(b'\r\n\r\n')[1].split(b'\r\n')[0].decode()
            elif b'name="logfile"' in part:
                log_data = part.split(b'\r\n\r\n', 1)[1].rsplit(b'\r\n', 1)[0]
        
        if instance_id and log_data:
            run_dir = os.path.join(self.logs_dir, self.run_name)
            os.makedirs(run_dir, exist_ok=True)
            log_path = os.path.join(run_dir, f"{instance_id}.log")
            with open(log_path, 'wb') as f:
                f.write(log_data)
            print(f"{COLOR_GREEN}📝 Final log received from {instance_id}{COLOR_RESET}")
        
        self.send_response(HTTP_OK)
        self.end_headers()
    
    def _handle_stream(self):
        """Handle streaming log updates from instances"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode())
            instance_id = data.get('instance_id')
            log_chunk = data.get('log_chunk', '').strip()
            timestamp = data.get('timestamp', time.time())
            
            if instance_id and log_chunk:
                # Save to stream log file
                run_dir = os.path.join(self.logs_dir, self.run_name)
                os.makedirs(run_dir, exist_ok=True)
                log_path = os.path.join(run_dir, f"{instance_id}_stream.log")
                
                with open(log_path, 'a') as f:
                    f.write(f"[{datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')}] {log_chunk}\n")
                
                # Parse log chunk to determine status
                self._parse_log_for_status(instance_id, log_chunk)
                
        except json.JSONDecodeError:
            pass
        
        self.send_response(HTTP_OK)
        self.end_headers()
    
    def _parse_log_for_status(self, instance_id, log_chunk):
        """
        Parse log chunk and update instance status accordingly
        
        Args:
            instance_id (str): Instance identifier
            log_chunk (str): Log message from instance
        """
        log_lower = log_chunk.lower()
        
        is_seeder = 'seeder' in instance_id
        
        if 'starting setup' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_STARTING)
        elif 'system update' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_UPDATING)
        elif 'installing' in log_lower and ('packages' in log_lower or 'dependencies' in log_lower):
            self.update_instance_status(instance_id, self.STATUS_INSTALLING)
        elif 'downloading' in log_lower and ('torrent' in log_lower or 'seed' in log_lower):
            self.update_instance_status(instance_id, self.STATUS_DOWNLOADING)
        elif 'starting bittorrent client' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_RUNNING)
        elif 'bittorrent client finished' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_COMPLETED)
        elif not is_seeder and ('downloaded' in log_lower or 'progress' in log_lower or '%' in log_chunk):
            progress = self._extract_progress(log_chunk)
            if progress is not None:
                self.update_instance_status(instance_id, self.STATUS_RUNNING, progress=progress)
        elif 'error' in log_lower or 'failed' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_ERROR, message=log_chunk[:50])
    
    def _extract_progress(self, log_chunk):
        """
        Extract download progress percentage from log chunk
        
        Args:
            log_chunk (str): Log message containing progress info
            
        Returns:
            float or None: Progress percentage if found
        """
        # Look for percentage patterns
        percent_match = re.search(r'(\d+(?:\.\d+)?)\s*%', log_chunk)
        if percent_match:
            return float(percent_match.group(1))
        
        # Look for "X/Y bytes" patterns and calculate percentage
        bytes_match = re.search(r'(\d+(?:\.\d+)?[KMG]?B?)\s*/\s*(\d+(?:\.\d+)?[KMG]?B?)', log_chunk)
        if bytes_match:
            try:
                downloaded = self._parse_bytes(bytes_match.group(1))
                total = self._parse_bytes(bytes_match.group(2))
                if total > 0:
                    return (downloaded / total) * 100
            except:
                pass
        
        return None
    
    def _parse_bytes(self, byte_str):
        """
        Parse byte string like '1.5MB' to bytes
        
        Args:
            byte_str (str): Byte string with unit
            
        Returns:
            int: Number of bytes
        """
        match = re.match(r'(\d+(?:\.\d+)?)\s*([KMG]?B?)', byte_str.upper())
        if not match:
            return 0
        
        value = float(match.group(1))
        unit = match.group(2)
        
        multipliers = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, '': 1}
        return int(value * multipliers.get(unit, 1))
    
    def _handle_completion(self):
        """Handle completion notification from instances"""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data.decode())
        
        instance_id = data.get('instance_id')
        status = data.get('status')
        
        if instance_id:
            self.completion_status[instance_id] = status
            if status == "interrupted":
                self.update_instance_status(instance_id, self.STATUS_ERROR, message="Interrupted")
            else:
                self.update_instance_status(instance_id, self.STATUS_COMPLETED)
        
        self.send_response(HTTP_OK)
        self.end_headers()


class LogServer:
    """HTTP server wrapper for log collection"""
    
    def __init__(self, port):
        """
        Initialize log server
        
        Args:
            port (int): Port to bind the server to
        """
        self.port = port
        self.server = None
        self.handler = LogHandler
    
    def start(self):
        """
        Start the HTTP server in a background thread
        
        Returns:
            LogHandler: Handler class for accessing server state
        """
        self.server = HTTPServer(('0.0.0.0', self.port), self.handler)
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()
        return self.handler
    
    def stop(self):
        """Stop the HTTP server"""
        if self.server:
            self.server.shutdown()