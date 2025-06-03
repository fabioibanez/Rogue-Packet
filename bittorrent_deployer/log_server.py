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
    instance_states = {}  # Simple state tracking: "startup", "core-run", "completed", "error"
    run_name = None
    
    def log_message(self, format, *args):
        """Suppress default HTTP server access logs"""
        pass  # Do nothing - suppresses all HTTP request logging
    
    @classmethod
    def set_run_name(cls, run_name):
        """
        Set the run name and create log directories
        
        Args:
            run_name (str): Unique run identifier
        """
        cls.run_name = run_name
        run_dir = os.path.join(cls.logs_dir, run_name)
        os.makedirs(run_dir, exist_ok=True)
        
        # Create subdirectories for different log phases
        os.makedirs(os.path.join(run_dir, "startup"), exist_ok=True)
        os.makedirs(os.path.join(run_dir, "core-run"), exist_ok=True)
    
    @classmethod
    def update_instance_state(cls, instance_id, state):
        """
        Update instance state
        
        Args:
            instance_id (str): Instance identifier
            state (str): Current state ("startup", "core-run", "completed", "error")
        """
        cls.instance_states[instance_id] = {
            'state': state,
            'timestamp': time.time()
        }
        cls.display_simple_status()
    
    @classmethod
    def display_simple_status(cls):
        """Display simple status summary"""
        print(f"\n=== BitTorrent Network Status ({cls.run_name}) ===")
        
        # Group by state
        states = {}
        for instance_id, info in cls.instance_states.items():
            state = info['state']
            if state not in states:
                states[state] = []
            states[state].append(instance_id)
        
        for state, instances in states.items():
            emoji = {
                'startup': '🔄',
                'core-run': '🚀', 
                'completed': '✅',
                'error': '❌'
            }.get(state, '❓')
            
            print(f"{emoji} {state.upper()}: {len(instances)} instances")
            for instance_id in instances:
                print(f"    {instance_id}")
        
        total = len(cls.instance_states)
        completed = len(states.get('completed', []))
        print(f"\nTotal: {total} | Completed: {completed}")
        print("=" * 50)
    
    def do_POST(self):
        """Handle POST requests from EC2 instances"""
        if self.path == LOGS_ENDPOINT:
            self._handle_logs()
        elif self.path == STREAM_ENDPOINT:
            self._handle_stream()
        elif self.path == COMPLETION_ENDPOINT:
            self._handle_completion()
        elif self.path == '/state':
            self._handle_state_update()
        else:
            self.send_response(HTTP_NOT_FOUND)
            self.end_headers()
    
    def _handle_state_update(self):
        """Handle state updates from instances"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode())
            instance_id = data.get('instance_id')
            state = data.get('state')
            
            if instance_id and state:
                self.update_instance_state(instance_id, state)
                
        except json.JSONDecodeError:
            pass
        
        self.send_response(HTTP_OK)
        self.end_headers()
    
    def _handle_logs(self):
        """Handle final log file upload from instances (now with phase separation)"""
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
        phase = None
        log_data = None
        
        for part in parts:
            if b'name="instance_id"' in part:
                instance_id = part.split(b'\r\n\r\n')[1].split(b'\r\n')[0].decode()
            elif b'name="phase"' in part:
                phase = part.split(b'\r\n\r\n')[1].split(b'\r\n')[0].decode()
            elif b'name="logfile"' in part:
                log_data = part.split(b'\r\n\r\n', 1)[1].rsplit(b'\r\n', 1)[0]
        
        if instance_id and phase and log_data:
            run_dir = os.path.join(self.logs_dir, self.run_name)
            phase_dir = os.path.join(run_dir, phase)
            os.makedirs(phase_dir, exist_ok=True)
            
            log_path = os.path.join(phase_dir, f"{instance_id}_{phase}.log")
            with open(log_path, 'wb') as f:
                f.write(log_data)
            print(f"📝 Final {phase} log received from {instance_id}")
        
        self.send_response(HTTP_OK)
        self.end_headers()
    
    def _handle_stream(self):
        """Handle streaming log chunks from instances (now with phase separation)"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode())
            instance_id = data.get('instance_id')
            phase = data.get('phase', 'unknown')
            log_chunk = data.get('log_chunk', '').strip()
            timestamp = data.get('timestamp', time.time())
            
            if instance_id and log_chunk:
                # Save to appropriate phase stream log file
                run_dir = os.path.join(self.logs_dir, self.run_name)
                phase_dir = os.path.join(run_dir, phase) 
                os.makedirs(phase_dir, exist_ok=True)
                
                log_path = os.path.join(phase_dir, f"{instance_id}_{phase}_stream.log")
                
                with open(log_path, 'a') as f:
                    f.write(f"[{datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')}] {log_chunk}\n")
                
        except json.JSONDecodeError:
            pass
        
        self.send_response(HTTP_OK)
        self.end_headers()
    
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
                self.update_instance_state(instance_id, "error")
            else:
                self.update_instance_state(instance_id, "completed")
        
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