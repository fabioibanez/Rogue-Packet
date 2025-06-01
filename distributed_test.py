#!/usr/bin/env python3
"""
BitTorrent Network Deployment Script with Programmatic AMI Lookup
"""

# Constants
# File Paths and Names
DEFAULT_CONFIG_PATH = "config.yaml"  # Used in Config and BitTorrentDeployer initialization
LOGS_DIR = "logs"  # Directory for storing log files from instances
TORRENT_TEMP_DIR = "/tmp/torrents"  # Directory for storing torrent files on instances
SEED_TEMP_DIR = "/tmp/seed"  # Directory for storing seed files on instances
BITTORRENT_PROJECT_DIR = "/tmp/bittorrent-project"  # Directory for cloning GitHub repo on instances
LOG_FILE_PATH = "/tmp/bittorrent.log"  # Path to store BitTorrent client logs on instances
INSTANCE_ID_FILE = "/tmp/instance_id.txt"  # File to store instance ID on instances
TORRENT_FILENAME = "file.torrent"  # Default filename for downloaded torrent files
SEED_FILENAME = "seed_file"  # Default filename for seed files
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"  # Format for logging

# API Endpoints
LOGS_ENDPOINT = '/logs'  # Endpoint for sending final logs (LogHandler.do_POST and generate_user_data)
STREAM_ENDPOINT = '/stream'  # Endpoint for streaming log updates (LogHandler.do_POST and generate_user_data)
COMPLETION_ENDPOINT = '/completion'  # Endpoint for completion notification (LogHandler.do_POST and generate_user_data)
READY_ENDPOINT = '/ready'  # Endpoint for instance ready notification (synchronization barrier)
START_ENDPOINT = '/start'  # Endpoint for checking if all instances are ready to start
IP_API_URL = 'https://api.ipify.org'  # API for getting public IP (used in _get_public_ip)

# HTTP Constants
HTTP_OK = 200  # HTTP status for successful responses (used in LogHandler methods)
HTTP_NOT_FOUND = 404  # HTTP status for not found (used in LogHandler.do_POST)
CONTENT_TYPE_JSON = "Content-Type: application/json"  # Content type header (used in generate_user_data)

# AWS Constants
DEFAULT_INSTANCE_TYPE = "t2.micro"  # Default EC2 instance type if not specified in config
DEFAULT_REGION = "us-east-1"  # Default AWS region if not specified in config
EC2_SERVICE_NAME = 'ec2'  # EC2 service name for boto3 (used in get_ec2_client)

# AMI Constants
UBUNTU_OWNER_ID = '099720109477'  # Canonical (Ubuntu) owner ID
UBUNTU_AMI_NAME_PATTERN = 'ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*'  # Ubuntu 22.04 AMI name pattern
AMI_ARCHITECTURE = 'x86_64'  # Required architecture for AMI
AMI_STATE_AVAILABLE = 'available'  # Required AMI state

# Timing Constants
DEFAULT_TIMEOUT_MINUTES = 30  # Default timeout if not specified in config
COMPLETION_CHECK_INTERVAL = 10  # Seconds between completion checks (used in wait_for_completion)
DEFAULT_CONTROLLER_PORT = 8080  # Default port for controller server if not specified in config
STREAM_INTERVAL = 15  # Seconds between log streaming updates

# Installation Commands
UPDATE_CMD = "apt-get update"  # Update package lists command (used in generate_user_data)
INSTALL_PACKAGES_CMD = "apt-get install -y git python3 python3-pip python3-dev python3-venv build-essential libssl-dev libffi-dev"  # Install required packages (used in generate_user_data)
INSTALL_DEPS_CMD = "python3 -m pip install -r requirements.txt --timeout 300"  # Install Python dependencies (used in generate_user_data)
SHUTDOWN_CMD = "shutdown -h now"  # Command to shutdown instance (used in generate_user_data)

# Role Constants
ROLE_SEEDER = "seeder"  # Role identifier for seeders (used in deploy_region)
ROLE_LEECHER = "leecher"  # Role identifier for leechers (used in deploy_region)

# Status Constants
STATUS_COMPLETE = "complete"  # Status indicating completion (used in generate_user_data)

# Color Constants for Terminal Output
COLOR_RESET = '\033[0m'
COLOR_BOLD = '\033[1m'
COLOR_RED = '\033[91m'
COLOR_GREEN = '\033[92m'
COLOR_YELLOW = '\033[93m'
COLOR_BLUE = '\033[94m'
COLOR_MAGENTA = '\033[95m'
COLOR_CYAN = '\033[96m'

# Random words for run naming
RUN_WORDS = [
    'alpha', 'bravo', 'charlie', 'delta', 'echo', 'foxtrot', 'golf', 'hotel',
    'india', 'juliet', 'kilo', 'lima', 'mike', 'november', 'oscar', 'papa',
    'quebec', 'romeo', 'sierra', 'tango', 'uniform', 'victor', 'whiskey',
    'xray', 'yankee', 'zulu', 'phoenix', 'thunder', 'lightning', 'storm',
    'falcon', 'eagle', 'hawk', 'raven', 'wolf', 'tiger', 'lion', 'bear'
]

import yaml
import time
import requests
import os
import base64
import threading
import json
import boto3
import random
import signal
import sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor

class Config:
    def __init__(self, config_path=DEFAULT_CONFIG_PATH):
        with open(config_path, "r") as f:
            self.data = yaml.safe_load(f)
    
    def get_aws_config(self):
        return self.data['aws']
    
    def get_regions(self):
        return self.data['regions']
    
    def get_controller_port(self):
        return self.data['controller']['port']
    
    def get_bittorrent_config(self):
        return self.data['bittorrent']
    
    def get_timeout_minutes(self):
        return self.data['timeout_minutes']

class LogHandler(BaseHTTPRequestHandler):
    logs_dir = LOGS_DIR
    completion_status = {}
    ready_instances = set()  # Track instances that are ready to start
    total_expected_instances = 0  # Total number of instances expected
    instance_status = {}  # Track current status of each instance
    run_name = None
    log_files = {}  # Track open log files for streaming
    last_display_time = 0  # For throttling status updates
    
    # Status stages
    STATUS_STARTING = "starting"
    STATUS_UPDATING = "updating"
    STATUS_INSTALLING = "installing"
    STATUS_DOWNLOADING = "downloading"
    STATUS_READY = "ready"
    STATUS_WAITING = "waiting_sync"
    STATUS_SEEDING = "seeding"
    STATUS_DOWNLOADING_BT = "downloading_bt"
    STATUS_COMPLETED = "completed"
    STATUS_ERROR = "error"
    
    @classmethod
    def set_run_name(cls, run_name):
        cls.run_name = run_name
        # Create the run directory
        run_dir = os.path.join(cls.logs_dir, run_name)
        os.makedirs(run_dir, exist_ok=True)
    
    @classmethod
    def set_total_instances(cls, total):
        cls.total_expected_instances = total
        cls.ready_instances = set()  # Reset ready instances
        cls.instance_status = {}  # Reset instance status
    
    @classmethod
    def update_instance_status(cls, instance_id, status, progress=None, message=None):
        """Update instance status and refresh display"""
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
        import os
        
        # Clear screen and move cursor to top
        print('\033[2J\033[H', end='')
        
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
        ready_count = len(cls.ready_instances)
        completed_count = len([i for i in cls.instance_status.values() if i['status'] == cls.STATUS_COMPLETED])
        
        print(f"\n{COLOR_BOLD}📊 Summary:{COLOR_RESET}")
        print(f"  Total: {total_instances}/{cls.total_expected_instances} | Ready: {ready_count} | Completed: {completed_count}")
        
        if ready_count >= cls.total_expected_instances and ready_count > 0:
            print(f"  {COLOR_GREEN}🚀 All instances synchronized - BitTorrent phase active{COLOR_RESET}")
        elif ready_count > 0:
            print(f"  {COLOR_YELLOW}🔄 Waiting for synchronization ({ready_count}/{cls.total_expected_instances}){COLOR_RESET}")
        else:
            print(f"  {COLOR_CYAN}⚙️ Setup phase in progress{COLOR_RESET}")
    
    @classmethod 
    def _get_status_display(cls, status, progress=None):
        """Get emoji and text for status display"""
        status_map = {
            cls.STATUS_STARTING: ("🔄", "Starting up"),
            cls.STATUS_UPDATING: ("📦", "Updating system"), 
            cls.STATUS_INSTALLING: ("⚙️", "Installing packages"),
            cls.STATUS_DOWNLOADING: ("⬇️", "Downloading files"),
            cls.STATUS_READY: ("✅", "Setup complete"),
            cls.STATUS_WAITING: ("⏳", "Waiting for sync"),
            cls.STATUS_SEEDING: ("🌱", "Seeding"),
            cls.STATUS_DOWNLOADING_BT: ("📥", f"Downloading {progress}%" if progress else "Downloading"),
            cls.STATUS_COMPLETED: ("🎉", "Completed"),
            cls.STATUS_ERROR: ("❌", "Error")
        }
        
        emoji, text = status_map.get(status, ("❓", f"Unknown: {status}"))
        
        # Add progress for downloading
        if status == cls.STATUS_DOWNLOADING_BT and progress is not None:
            text = f"Downloading {progress:.1f}%"
            
        return emoji, text
    
    def do_POST(self):
        if self.path == LOGS_ENDPOINT:
            self._handle_logs()
        elif self.path == STREAM_ENDPOINT:
            self._handle_stream()
        elif self.path == COMPLETION_ENDPOINT:
            self._handle_completion()
        elif self.path == READY_ENDPOINT:
            self._handle_ready()
        else:
            self.send_response(HTTP_NOT_FOUND)
            self.end_headers()
    
    def do_GET(self):
        if self.path == START_ENDPOINT:
            self._handle_start_check()
        else:
            self.send_response(HTTP_NOT_FOUND)
            self.end_headers()
    
    def _handle_logs(self):
        # Handle final log file upload (same as before)
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
    
    def _handle_ready(self):
        """Handle instance ready notification for synchronization"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode())
            instance_id = data.get('instance_id')
            status = data.get('status', 'ready')
            
            if instance_id:
                self.ready_instances.add(instance_id)
                self.update_instance_status(instance_id, self.STATUS_WAITING)
                
                # Check if all instances are ready
                if len(self.ready_instances) >= self.total_expected_instances:
                    # Transition all instances to their BitTorrent phase
                    for ready_id in self.ready_instances:
                        if 'seeder' in ready_id:
                            self.update_instance_status(ready_id, self.STATUS_SEEDING)
                        else:
                            self.update_instance_status(ready_id, self.STATUS_DOWNLOADING_BT, progress=0)
                    
                    # Force a status update to show the transition
                    self.display_status_dashboard()
                    
        except json.JSONDecodeError:
            pass
        
        self.send_response(HTTP_OK)
        self.end_headers()
    
    def _handle_start_check(self):
        """Handle requests from instances checking if they can start BitTorrent"""
        # Return 200 if all instances are ready, 202 if still waiting
        if len(self.ready_instances) >= self.total_expected_instances:
            response = {"status": "start", "message": "All instances ready, begin BitTorrent"}
            status_code = HTTP_OK
        else:
            response = {"status": "wait", "message": f"Waiting for instances ({len(self.ready_instances)}/{self.total_expected_instances})"}
            status_code = 202  # Accepted but not ready
        
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())
    
    def _handle_stream(self):
        """Handle streaming log updates - now updates status dashboard instead of printing lines"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode())
            instance_id = data.get('instance_id')
            log_chunk = data.get('log_chunk', '').strip()
            timestamp = data.get('timestamp', time.time())
            
            if instance_id and log_chunk:
                # Save to log file
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
        """Parse log chunk and update instance status accordingly"""
        log_lower = log_chunk.lower()
        
        # Determine role from instance_id
        is_seeder = 'seeder' in instance_id
        
        # Parse different status updates
        if 'starting setup' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_STARTING)
        elif 'system update' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_UPDATING)
        elif 'installing' in log_lower and ('packages' in log_lower or 'dependencies' in log_lower):
            self.update_instance_status(instance_id, self.STATUS_INSTALLING)
        elif 'downloading' in log_lower and ('torrent' in log_lower or 'seed' in log_lower):
            self.update_instance_status(instance_id, self.STATUS_DOWNLOADING)
        elif 'setup complete' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_READY)
        elif 'waiting for synchronization' in log_lower or 'waiting for all instances' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_WAITING)
        elif 'starting bittorrent client as seeder' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_SEEDING)
        elif 'starting bittorrent client as leecher' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_DOWNLOADING_BT, progress=0)
        elif 'bittorrent client finished' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_COMPLETED)
        # Parse BitTorrent progress for leechers
        elif not is_seeder and ('downloaded' in log_lower or 'progress' in log_lower or '%' in log_chunk):
            progress = self._extract_progress(log_chunk)
            if progress is not None:
                self.update_instance_status(instance_id, self.STATUS_DOWNLOADING_BT, progress=progress)
        elif 'error' in log_lower or 'failed' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_ERROR, message=log_chunk[:50])
    
    def _extract_progress(self, log_chunk):
        """Extract download progress percentage from log chunk"""
        import re
        
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
        """Parse byte string like '1.5MB' to bytes"""
        import re
        match = re.match(r'(\d+(?:\.\d+)?)\s*([KMG]?B?)', byte_str.upper())
        if not match:
            return 0
        
        value = float(match.group(1))
        unit = match.group(2)
        
        multipliers = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, '': 1}
        return int(value * multipliers.get(unit, 1))
    
    def _handle_completion(self):
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
    def __init__(self, port):
        self.port = port
        self.server = None
        self.handler = LogHandler
    
    def start(self):
        self.server = HTTPServer(('0.0.0.0', self.port), self.handler)
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()
        return self.handler
    
    def stop(self):
        if self.server:
            self.server.shutdown()

class AWSManager:
    def __init__(self, aws_config):
        self.aws_config = aws_config
        self.region_clients = {}
        self.region_amis = {}  # Cache for AMI IDs per region
    
    def get_ec2_client(self, region):
        if region not in self.region_clients:
            self.region_clients[region] = boto3.client(
                EC2_SERVICE_NAME,
                region_name=region,
            )
        return self.region_clients[region]
    
    def get_latest_ubuntu_ami(self, region):
        """Get latest Ubuntu 22.04 AMI for the specified region"""
        if region in self.region_amis:
            return self.region_amis[region], None
        
        try:
            ec2_client = self.get_ec2_client(region)
            
            response = ec2_client.describe_images(
                Owners=[UBUNTU_OWNER_ID],  # Canonical (Ubuntu)
                Filters=[
                    {
                        'Name': 'name', 
                        'Values': [UBUNTU_AMI_NAME_PATTERN]
                    },
                    {
                        'Name': 'state', 
                        'Values': [AMI_STATE_AVAILABLE]
                    },
                    {
                        'Name': 'architecture',
                        'Values': [AMI_ARCHITECTURE]
                    }
                ]
            )
            
            if not response['Images']:
                return None, f"No Ubuntu 22.04 AMIs found in {region}"
            
            # Sort by creation date and get the latest
            latest_ami = sorted(
                response['Images'], 
                key=lambda x: x['CreationDate'], 
                reverse=True
            )[0]
            
            ami_info = {
                'ami_id': latest_ami['ImageId'],
                'name': latest_ami['Name'],
                'creation_date': latest_ami['CreationDate'],
                'description': latest_ami.get('Description', 'N/A')
            }
            
            # Cache the result
            self.region_amis[region] = ami_info
            
            return ami_info, None
            
        except Exception as e:
            return None, f"Failed to lookup AMI in {region}: {str(e)}"
    
    def validate_ami_availability(self, region, ami_id):
        """Validate that an AMI is available and accessible"""
        try:
            ec2_client = self.get_ec2_client(region)
            response = ec2_client.describe_images(ImageIds=[ami_id])
            
            if not response['Images']:
                return False, f"AMI {ami_id} not found in {region}"
            
            ami = response['Images'][0]
            if ami['State'] != AMI_STATE_AVAILABLE:
                return False, f"AMI {ami_id} is not available (state: {ami['State']})"
            
            return True, "AMI is available and accessible"
            
        except Exception as e:
            return False, f"Error validating AMI {ami_id}: {str(e)}"
    
    def generate_user_data(self, github_repo, torrent_url, seed_fileurl, role, controller_ip, controller_port, instance_id):
        script = f"""#!/bin/bash
# Debug: Log all commands and outputs
set -x
exec > >(tee -a /tmp/startup.log) 2>&1

# Function to send log updates to controller
send_log_update() {{
    local message="$1"
    curl -s -X POST -H "Content-Type: application/json" \\
        -d '{{"instance_id": "{instance_id}", "log_chunk": "'"$message"'", "timestamp": '$(date +%s)'}}' \\
        http://{controller_ip}:{controller_port}{STREAM_ENDPOINT} > /dev/null 2>&1 || true
}}

# Function to send final logs on exit
send_final_logs() {{
    echo "=== Sending emergency/final logs to controller ==="
    send_log_update "Instance {instance_id} is shutting down (potentially interrupted)"
    
    # Try to send whatever logs we have
    if [ -f {LOG_FILE_PATH} ]; then
        echo "Sending final BitTorrent logs..."
        curl -X POST -F "instance_id={instance_id}" -F "logfile=@{LOG_FILE_PATH}" http://{controller_ip}:{controller_port}{LOGS_ENDPOINT} || true
    else
        # If no main log file, create one with startup log
        echo "Creating emergency log file..."
        cp /tmp/startup.log {LOG_FILE_PATH} 2>/dev/null || echo "Emergency log from {instance_id}" > {LOG_FILE_PATH}
        curl -X POST -F "instance_id={instance_id}" -F "logfile=@{LOG_FILE_PATH}" http://{controller_ip}:{controller_port}{LOGS_ENDPOINT} || true
    fi
    
    # Send completion notification
    curl -X POST -H "Content-Type: application/json" -d '{{"instance_id": "{instance_id}", "status": "interrupted"}}' http://{controller_ip}:{controller_port}{COMPLETION_ENDPOINT} || true
}}

# Set up trap to send logs on any exit
trap 'send_final_logs' EXIT TERM INT

# Function to stream log file changes
start_log_streaming() {{
    {{
        # Stream startup log
        tail -f /tmp/startup.log | while read line; do
            send_log_update "STARTUP: $line"
            sleep 0.5
        done &
        
        # Stream main BitTorrent log when it appears
        while [ ! -f {LOG_FILE_PATH} ]; do sleep 2; done
        tail -f {LOG_FILE_PATH} | while read line; do
            send_log_update "BITTORRENT: $line"
            sleep 0.5
        done &
    }} &
}}

echo "=== Starting instance setup for {instance_id} ==="
send_log_update "Instance {instance_id} starting setup (Role: {role})"

echo "Role: {role}"
echo "Torrent URL: {torrent_url}"
echo "Controller: {controller_ip}:{controller_port}"
echo "Timestamp: $(date)"

echo "=== System Update ==="
send_log_update "Starting system update..."
{UPDATE_CMD}
echo "System update completed with exit code: $?"
send_log_update "System update completed with exit code: $?"

echo "=== Installing System Packages ==="
send_log_update "Installing system packages..."
{INSTALL_PACKAGES_CMD}
echo "System packages installed with exit code: $?"
send_log_update "System packages installation completed"

echo "=== Python and pip versions ==="
python3 --version
pip3 --version

echo "=== Cloning Repository ==="
send_log_update "Cloning repository from {github_repo}"
git clone -b feat/distribed {github_repo} {BITTORRENT_PROJECT_DIR}
echo "Git clone completed with exit code: $?"
send_log_update "Repository cloned successfully"

cd {BITTORRENT_PROJECT_DIR}
echo "Current directory: $(pwd)"
echo "Directory contents:"
ls -la

echo "=== Checking requirements.txt ==="
if [ -f requirements.txt ]; then
    echo "requirements.txt found:"
    cat requirements.txt
    echo "--- End of requirements.txt ---"
    send_log_update "Found requirements.txt with $(wc -l < requirements.txt) packages"
else
    echo "ERROR: requirements.txt not found!"
    send_log_update "ERROR: requirements.txt not found!"
    ls -la
    exit 1
fi

echo "=== Installing Python Dependencies ==="
send_log_update "Starting Python dependencies installation..."
# Update pip first
python3 -m pip install --upgrade pip
echo "pip upgrade completed with exit code: $?"

# Install dependencies with verbose output and timeout
python3 -m pip install -r requirements.txt --verbose --timeout 300
PIP_EXIT_CODE=$?
echo "pip install completed with exit code: $PIP_EXIT_CODE"
send_log_update "Python dependencies installation completed (exit code: $PIP_EXIT_CODE)"

if [ $PIP_EXIT_CODE -ne 0 ]; then
    echo "ERROR: pip install failed!"
    send_log_update "ERROR: pip install failed, trying individual packages..."
    
    # Try installing each package individually
    echo "Installing packages individually:"
    while IFS= read -r package; do
        if [[ ! "$package" =~ ^[[:space:]]*# ]] && [[ -n "$package" ]]; then
            echo "Installing: $package"
            send_log_update "Installing individual package: $package"
            python3 -m pip install "$package" --verbose --timeout 300
            echo "Exit code for $package: $?"
        fi
    done < requirements.txt
fi

echo "=== Installed packages ==="
python3 -m pip list

# Create necessary directories
mkdir -p {TORRENT_TEMP_DIR}
mkdir -p {SEED_TEMP_DIR}

echo "=== Downloading torrent file ==="
send_log_update "Downloading torrent file..."
echo "URL: {torrent_url}"
curl -L -v -o {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} {torrent_url}
CURL_EXIT_CODE=$?
echo "curl completed with exit code: $CURL_EXIT_CODE"
send_log_update "Torrent file download completed (exit code: $CURL_EXIT_CODE)"

echo "=== Torrent file info ==="
ls -la {TORRENT_TEMP_DIR}/{TORRENT_FILENAME}
file {TORRENT_TEMP_DIR}/{TORRENT_FILENAME}
echo "File size: $(stat -c%s {TORRENT_TEMP_DIR}/{TORRENT_FILENAME}) bytes"
head -c 100 {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} | hexdump -C

# Role-specific setup
if [ "{role}" == "{ROLE_SEEDER}" ]; then
    echo "=== Seeder Setup: Downloading actual file ==="
    send_log_update "Seeder downloading actual file for seeding..."
    echo "Seed file URL: {seed_fileurl}"
    curl -L -v -o {SEED_TEMP_DIR}/{SEED_FILENAME} {seed_fileurl}
    SEED_CURL_EXIT_CODE=$?
    echo "Seed file download completed with exit code: $SEED_CURL_EXIT_CODE"
    send_log_update "Seed file download completed (exit code: $SEED_CURL_EXIT_CODE)"
    
    echo "=== Seed file info ==="
    ls -la {SEED_TEMP_DIR}/{SEED_FILENAME}
    file {SEED_TEMP_DIR}/{SEED_FILENAME}
    echo "Seed file size: $(stat -c%s {SEED_TEMP_DIR}/{SEED_FILENAME}) bytes"
    
    if [ $SEED_CURL_EXIT_CODE -ne 0 ]; then
        echo "ERROR: Failed to download seed file!"
        send_log_update "ERROR: Failed to download seed file for seeder!"
        exit 1
    fi
else
    echo "=== Leecher Setup: No seed file needed ==="
    send_log_update "Leecher setup - will download file via BitTorrent"
fi

export BITTORRENT_ROLE="{role}"
export INSTANCE_ID="{instance_id}"
echo "{instance_id}" > {INSTANCE_ID_FILE}

echo "=== Environment Variables ==="
echo "BITTORRENT_ROLE=$BITTORRENT_ROLE"
echo "INSTANCE_ID=$INSTANCE_ID"

echo "=== Testing Python imports ==="
python3 -c '
try:
    import sys
    print("Python path:", sys.path)
    # Try importing common packages that might be in requirements.txt
    test_imports = ["requests", "bcoding", "bitstring", "bencode"]
    for pkg in test_imports:
        try:
            __import__(pkg)
            print(f"✓ {{pkg}} import successful")
        except ImportError as e:
            print(f"✗ {{pkg}} import failed: {{e}}")
except Exception as e:
    print(f"Python test failed: {{e}}")
'

# Start log streaming in background
start_log_streaming

echo "=== Setup Complete - Waiting for All Instances ==="
send_log_update "Setup complete, waiting for synchronization barrier..."

# Notify controller that this instance is ready
echo "Notifying controller that {instance_id} is ready..."
curl -X POST -H "Content-Type: application/json" \\
    -d '{{"instance_id": "{instance_id}", "status": "ready"}}' \\
    http://{controller_ip}:{controller_port}{READY_ENDPOINT}

echo "Waiting for all instances to be ready before starting BitTorrent..."
send_log_update "Waiting for all instances to be ready..."

# Poll the controller until all instances are ready
while true; do
    RESPONSE=$(curl -s http://{controller_ip}:{controller_port}{START_ENDPOINT})
    STATUS=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', 'unknown'))" 2>/dev/null || echo "unknown")
    
    if [ "$STATUS" = "start" ]; then
        echo "✅ All instances ready! Starting BitTorrent client..."
        send_log_update "All instances ready, starting BitTorrent client!"
        break
    else
        echo "⏳ Still waiting for other instances... (Status: $STATUS)"
        send_log_update "Still waiting for synchronization..."
        sleep 5
    fi
done

echo "=== Running BitTorrent client ==="
if [ "{role}" == "{ROLE_SEEDER}" ]; then
    send_log_update "Starting BitTorrent client as SEEDER with -s flag..."
    echo "Command: python3 -m main -s {TORRENT_TEMP_DIR}/{TORRENT_FILENAME}"
    echo "Seed file available at: {SEED_TEMP_DIR}/{SEED_FILENAME}"
    python3 -m main -s {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} > {LOG_FILE_PATH} 2>&1
else
    send_log_update "Starting BitTorrent client as LEECHER..."
    echo "Command: python3 -m main {TORRENT_TEMP_DIR}/{TORRENT_FILENAME}"
    python3 -m main {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} > {LOG_FILE_PATH} 2>&1
fi

BITTORRENT_EXIT_CODE=$?
echo "BitTorrent client completed with exit code: $BITTORRENT_EXIT_CODE"
send_log_update "BitTorrent client finished (exit code: $BITTORRENT_EXIT_CODE)"

echo "=== BitTorrent client finished ==="
echo "Log file size: $(wc -l < {LOG_FILE_PATH}) lines"
echo "Log file first 10 lines:"
head -10 {LOG_FILE_PATH}
echo "Log file last 10 lines:"
tail -10 {LOG_FILE_PATH}

# Stop log streaming
pkill -f "tail -f" 2>/dev/null || true

# Append startup log to main log for debugging
echo "" >> {LOG_FILE_PATH}
echo "=======================================" >> {LOG_FILE_PATH}
echo "=== STARTUP LOG ===" >> {LOG_FILE_PATH}
echo "=======================================" >> {LOG_FILE_PATH}
cat /tmp/startup.log >> {LOG_FILE_PATH}

echo "=== Sending final logs to controller ==="
send_log_update "Sending final logs to controller..."
curl -X POST -F "instance_id={instance_id}" -F "logfile=@{LOG_FILE_PATH}" http://{controller_ip}:{controller_port}{LOGS_ENDPOINT}
CURL_LOG_EXIT_CODE=$?
echo "Log upload completed with exit code: $CURL_LOG_EXIT_CODE"

curl -X POST -H "{CONTENT_TYPE_JSON}" -d '{{"instance_id": "{instance_id}", "status": "{STATUS_COMPLETE}"}}' http://{controller_ip}:{controller_port}{COMPLETION_ENDPOINT}
CURL_COMPLETION_EXIT_CODE=$?
echo "Completion notification sent with exit code: $CURL_COMPLETION_EXIT_CODE"

echo "=== Instance setup completed ==="
send_log_update "Instance setup completed, shutting down..."
echo "Final timestamp: $(date)"

# Remove the trap since we're exiting normally
trap - EXIT TERM INT

{SHUTDOWN_CMD}
"""
        return base64.b64encode(script.encode()).decode()
    
    def launch_instance(self, region, user_data, ami_id):
        ec2_client = self.get_ec2_client(region)
        
        response = ec2_client.run_instances(
            ImageId=ami_id,
            InstanceType=self.aws_config.get('instance_type', DEFAULT_INSTANCE_TYPE),
            MinCount=1,
            MaxCount=1,
            UserData=user_data,
            SecurityGroupIds=[self.aws_config['security_group']]
        )
        
        return response['Instances'][0]['InstanceId']
    
    def terminate_instances(self, region, instance_ids):
        if not instance_ids:
            return
        
        ec2_client = self.get_ec2_client(region)
        ec2_client.terminate_instances(InstanceIds=instance_ids)

class BitTorrentDeployer:
    def __init__(self, config_path=DEFAULT_CONFIG_PATH):
        self.config = Config(config_path)
        self.aws_manager = AWSManager(self.config.get_aws_config())
        self.log_server = LogServer(self.config.get_controller_port())
        self.controller_ip = self._get_public_ip()
        self.region_instances = {}
        self.total_instance_count = 0
        self.cleanup_in_progress = False
        self.handler = None
        
        # Generate unique run name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_word = random.choice(RUN_WORDS)
        self.run_name = f"{random_word}_{timestamp}"
        
        # Set up log directory for this run
        LogHandler.set_run_name(self.run_name)
        
        # Calculate total instance count for synchronization
        for region in self.config.get_regions():
            self.total_instance_count += region['seeders'] + region['leechers']
        
        # Set up signal handler for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle keyboard interrupt (Ctrl+C) gracefully"""
        if self.cleanup_in_progress:
            print(f"\n{COLOR_RED}💀 Force terminating... (second Ctrl+C received){COLOR_RESET}")
            sys.exit(1)
        
        print(f"\n\n{COLOR_YELLOW}🛑 Keyboard interrupt received! Starting graceful cleanup...{COLOR_RESET}")
        self.cleanup_in_progress = True
        self._emergency_cleanup()
        sys.exit(0)
    
    def _emergency_cleanup(self):
        """Emergency cleanup when interrupted"""
        print(f"{COLOR_YELLOW}🚨 Emergency cleanup initiated{COLOR_RESET}")
        
        try:
            # Try to collect any available logs quickly
            if self.handler:
                print(f"{COLOR_CYAN}📡 Attempting to collect available logs...{COLOR_RESET}")
                time.sleep(2)  # Give a moment for any pending logs
                
                # Show what we have so far
                print(f"\n{COLOR_BOLD}=== Emergency Log Summary ==={COLOR_RESET}")
                run_dir = os.path.join(LOGS_DIR, self.run_name)
                
                if os.path.exists(run_dir):
                    for file in os.listdir(run_dir):
                        if file.endswith('.log'):
                            file_path = os.path.join(run_dir, file)
                            file_size = os.path.getsize(file_path)
                            print(f"{COLOR_GREEN}📝 {file} ({file_size} bytes){COLOR_RESET}")
                
                # Show completion status
                if self.handler.completion_status:
                    print(f"\n{COLOR_BOLD}=== Instance Status ==={COLOR_RESET}")
                    for instance_id, status in self.handler.completion_status.items():
                        print(f"{COLOR_GREEN}✅ {instance_id}: {status}{COLOR_RESET}")
        except Exception as e:
            print(f"{COLOR_RED}⚠ Error during log collection: {e}{COLOR_RESET}")
        
        # Force terminate all instances
        try:
            print(f"\n{COLOR_BOLD}=== Emergency Instance Termination ==={COLOR_RESET}")
            for region_name, instance_ids in self.region_instances.items():
                if instance_ids:
                    print(f"{COLOR_YELLOW}🔥 Force terminating {len(instance_ids)} instances in {region_name}...{COLOR_RESET}")
                    try:
                        self.aws_manager.terminate_instances(region_name, instance_ids)
                        print(f"{COLOR_GREEN}✓ Terminated instances in {region_name}{COLOR_RESET}")
                    except Exception as e:
                        print(f"{COLOR_RED}✗ Error terminating instances in {region_name}: {e}{COLOR_RESET}")
                        
            # Stop log server
            if self.log_server:
                self.log_server.stop()
                print(f"{COLOR_GREEN}✓ Log server stopped{COLOR_RESET}")
                
        except Exception as e:
            print(f"{COLOR_RED}⚠ Error during instance cleanup: {e}{COLOR_RESET}")
        
        print(f"\n{COLOR_BOLD}{COLOR_YELLOW}🛑 Emergency cleanup completed{COLOR_RESET}")
        print(f"{COLOR_BOLD}{COLOR_BLUE}📁 Partial logs saved in: {LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
        print(f"{COLOR_YELLOW}💡 Run again or check AWS console to ensure all instances are terminated{COLOR_RESET}")
    
    def _get_public_ip(self):
        response = requests.get(IP_API_URL)
        return response.text
    
    def _lookup_and_validate_amis(self):
        """Look up and validate AMIs for all regions"""
        print(f"\n{COLOR_BOLD}=== AMI Lookup and Validation ==={COLOR_RESET}")
        
        region_ami_map = {}
        all_regions = [region['name'] for region in self.config.get_regions()]
        
        for region_name in all_regions:
            print(f"🔍 Looking up Ubuntu 22.04 AMI for {region_name}...")
            
            ami_info, error = self.aws_manager.get_latest_ubuntu_ami(region_name)
            
            if ami_info:
                print(f"  {COLOR_GREEN}✓ Found AMI: {ami_info['ami_id']}{COLOR_RESET}")
                print(f"    Name: {ami_info['name']}")
                print(f"    Created: {ami_info['creation_date']}")
                
                # Validate AMI accessibility
                is_valid, validation_msg = self.aws_manager.validate_ami_availability(region_name, ami_info['ami_id'])
                if is_valid:
                    print(f"    {COLOR_GREEN}✓ AMI validated and accessible{COLOR_RESET}")
                    region_ami_map[region_name] = ami_info['ami_id']
                else:
                    print(f"    {COLOR_RED}✗ AMI validation failed: {validation_msg}{COLOR_RESET}")
                    return None, f"AMI validation failed for {region_name}: {validation_msg}"
            else:
                print(f"  {COLOR_RED}✗ AMI lookup failed: {error}{COLOR_RESET}")
                return None, f"AMI lookup failed for {region_name}: {error}"
        
        print(f"{COLOR_GREEN}✅ All AMIs validated successfully across {len(all_regions)} regions{COLOR_RESET}")
        return region_ami_map, None
    
    def deploy_region(self, region_config, torrent_url, seed_fileurl, ami_id):
        region_name = region_config['name']
        instance_ids = []
        
        # Deploy seeders
        for i in range(region_config['seeders']):
            instance_id = f"{region_name}-{ROLE_SEEDER}-{i}"
            user_data = self.aws_manager.generate_user_data(
                self.config.get_bittorrent_config()['github_repo'],
                torrent_url,
                seed_fileurl,
                ROLE_SEEDER,
                self.controller_ip,
                self.config.get_controller_port(),
                instance_id
            )
            
            ec2_id = self.aws_manager.launch_instance(region_name, user_data, ami_id)
            instance_ids.append(ec2_id)
        
        # Deploy leechers
        for i in range(region_config['leechers']):
            instance_id = f"{region_name}-{ROLE_LEECHER}-{i}"
            user_data = self.aws_manager.generate_user_data(
                self.config.get_bittorrent_config()['github_repo'],
                torrent_url,
                seed_fileurl,
                ROLE_LEECHER,
                self.controller_ip,
                self.config.get_controller_port(),
                instance_id
            )
            
            ec2_id = self.aws_manager.launch_instance(region_name, user_data, ami_id)
            instance_ids.append(ec2_id)
        
        return region_name, instance_ids
    
    def wait_for_completion(self, handler, timeout_minutes):
        timeout = time.time() + (timeout_minutes * 60)
        
        while time.time() < timeout:
            if self.cleanup_in_progress:
                return False
            if len(handler.completion_status) >= self.total_instance_count:
                return True
            time.sleep(COMPLETION_CHECK_INTERVAL)
        
        return False
    
    def run(self):
        try:
            print(f"{COLOR_BOLD}{COLOR_MAGENTA}🚀 BitTorrent Network Deployment{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_YELLOW}📁 Run Name: {self.run_name}{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_BLUE}💾 Logs Directory: {LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
            print(f"{COLOR_YELLOW}💡 Press Ctrl+C at any time for graceful cleanup{COLOR_RESET}")
            
            # Look up and validate AMIs for all regions
            region_ami_map, ami_error = self._lookup_and_validate_amis()
            if ami_error:
                print(f"\n{COLOR_RED}💥 AMI validation failed: {ami_error}{COLOR_RESET}")
                return {}
            
            # Start log server and set total instance count for synchronization
            self.handler = self.log_server.start()
            LogHandler.set_total_instances(self.total_instance_count)
            print(f"\n{COLOR_GREEN}🌐 Log server started on port {self.config.get_controller_port()}{COLOR_RESET}")
            print(f"{COLOR_GREEN}🌍 Controller IP: {self.controller_ip}{COLOR_RESET}")
            print(f"{COLOR_BLUE}🔄 Synchronization barrier set for {self.total_instance_count} instances{COLOR_RESET}")
            
            # Get torrent URL from GitHub
            torrent_url = self.config.get_bittorrent_config()['torrent_url']
            seed_fileurl = self.config.get_bittorrent_config()['seed_fileurl']
            github_repo = self.config.get_bittorrent_config()['github_repo']
            
            print(f"\n{COLOR_BOLD}=== Configuration ==={COLOR_RESET}")
            print(f"📂 GitHub repo: {github_repo}")
            print(f"📁 Torrent URL: {torrent_url}")
            print(f"🌱 Seed file URL: {seed_fileurl}")
            print(f"⚡ Commands to be run:")
            print(f"   🌱 Seeders: {COLOR_GREEN}python3 -m main -s /tmp/torrents/file.torrent{COLOR_RESET}")
            print(f"   📥 Leechers: {COLOR_BLUE}python3 -m main /tmp/torrents/file.torrent{COLOR_RESET}")
            
            # Test torrent URL accessibility
            print(f"\n{COLOR_BOLD}=== Testing URLs ==={COLOR_RESET}")
            try:
                import requests
                # Test torrent URL
                response = requests.head(torrent_url)
                print(f"🌐 Torrent URL status: {response.status_code}")
                if response.status_code == 200:
                    print(f"{COLOR_GREEN}✓ Torrent file accessible ({response.headers.get('content-length', 'unknown')} bytes){COLOR_RESET}")
                else:
                    print(f"{COLOR_RED}✗ Torrent URL returned {response.status_code} - this will cause failures!{COLOR_RESET}")
                
                # Test seed file URL
                seed_response = requests.head(seed_fileurl)
                print(f"🌱 Seed file URL status: {seed_response.status_code}")
                if seed_response.status_code == 200:
                    print(f"{COLOR_GREEN}✓ Seed file accessible ({seed_response.headers.get('content-length', 'unknown')} bytes){COLOR_RESET}")
                else:
                    print(f"{COLOR_RED}✗ Seed file URL returned {seed_response.status_code} - seeders will fail!{COLOR_RESET}")
                    
            except Exception as e:
                print(f"{COLOR_RED}✗ Could not test URLs: {e}{COLOR_RESET}")
            
            # Total instance count already calculated in __init__
            
            print(f"\n{COLOR_BOLD}=== Deployment Plan ==={COLOR_RESET}")
            for region in self.config.get_regions():
                ami_id = region_ami_map[region['name']]
                print(f"🌍 Region {region['name']}: {COLOR_GREEN}{region['seeders']} seeders{COLOR_RESET}, {COLOR_BLUE}{region['leechers']} leechers{COLOR_RESET} (AMI: {ami_id})")
            print(f"📊 Total instances: {COLOR_BOLD}{self.total_instance_count}{COLOR_RESET}")
            
            # Deploy instances
            print(f"\n{COLOR_BOLD}=== Launching Instances ==={COLOR_RESET}")
            with ThreadPoolExecutor() as executor:
                futures = []
                
                for region in self.config.get_regions():
                    ami_id = region_ami_map[region['name']]
                    futures.append(
                        executor.submit(
                            self.deploy_region,
                            region,
                            torrent_url,
                            seed_fileurl,
                            ami_id
                        )
                    )
                
                for future in futures:
                    if self.cleanup_in_progress:
                        break
                    region_name, instance_ids = future.result()
                    self.region_instances[region_name] = instance_ids
                    print(f"{COLOR_GREEN}✓ Launched {len(instance_ids)} instances in {region_name}{COLOR_RESET}")
            
            if self.cleanup_in_progress:
                return {}
                
            print(f"{COLOR_GREEN}✅ Deployed {self.total_instance_count} instances across {len(self.config.get_regions())} regions{COLOR_RESET}")
            
            # Wait for completion
            print(f"\n{COLOR_BOLD}=== Live Status Dashboard ==={COLOR_RESET}")
            print("🔄 Synchronization: All instances will wait until everyone is ready")
            print(f"⏱️  Will wait up to {self.config.get_timeout_minutes()} minutes...")
            print(f"📁 Logs being saved to: {COLOR_YELLOW}{LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
            print(f"{COLOR_YELLOW}💡 Press Ctrl+C anytime to stop and cleanup{COLOR_RESET}")
            print("\n" + "=" * 80)
            
            # Initial dashboard display
            LogHandler.display_status_dashboard()
            
            completed = self.wait_for_completion(self.handler, self.config.get_timeout_minutes())
            
            if self.cleanup_in_progress:
                return {}
            
            if completed:
                print(f"\n{COLOR_GREEN}✅ All instances completed successfully{COLOR_RESET}")
                # Final status display
                LogHandler.display_status_dashboard()
            else:
                print(f"\n{COLOR_YELLOW}⚠ Timeout reached, some instances may not have completed{COLOR_RESET}")
                # Final status display
                LogHandler.display_status_dashboard()
            
            # Process logs
            print(f"\n{COLOR_BOLD}=== Log Summary ==={COLOR_RESET}")
            run_dir = os.path.join(LOGS_DIR, self.run_name)
            for instance_id, status in self.handler.completion_status.items():
                final_log = os.path.join(run_dir, f"{instance_id}.log")
                stream_log = os.path.join(run_dir, f"{instance_id}_stream.log")
                
                if os.path.exists(final_log):
                    print(f"{COLOR_GREEN}✓ {instance_id}: {status} (final log: {final_log}){COLOR_RESET}")
                else:
                    print(f"{COLOR_RED}✗ {instance_id}: {status} (no final log){COLOR_RESET}")
                
                if os.path.exists(stream_log):
                    print(f"  {COLOR_CYAN}📡 Stream log: {stream_log}{COLOR_RESET}")
            
            # Cleanup resources
            print(f"\n{COLOR_BOLD}=== Cleanup ==={COLOR_RESET}")
            for region_name, instance_ids in self.region_instances.items():
                self.aws_manager.terminate_instances(region_name, instance_ids)
                print(f"{COLOR_GREEN}✓ Terminated {len(instance_ids)} instances in {region_name}{COLOR_RESET}")
            
            # Stop log server
            self.log_server.stop()
            print(f"{COLOR_GREEN}✓ Log server stopped{COLOR_RESET}")
            
            print(f"\n{COLOR_BOLD}{COLOR_MAGENTA}🎉 BitTorrent network test completed!{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_YELLOW}📁 All logs saved in: {LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
            
            return self.handler.completion_status
            
        except KeyboardInterrupt:
            # This should be handled by the signal handler, but just in case
            self._emergency_cleanup()
            sys.exit(0)
        except Exception as e:
            print(f"\n{COLOR_RED}💥 Unexpected error: {e}{COLOR_RESET}")
            if not self.cleanup_in_progress:
                self._emergency_cleanup()
            raise

if __name__ == "__main__":
    try:
        deployer = BitTorrentDeployer()
        deployer.run()
    except KeyboardInterrupt:
        print(f"\n{COLOR_YELLOW}🛑 Interrupted by user{COLOR_RESET}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{COLOR_RED}💥 Fatal error: {e}{COLOR_RESET}")
        sys.exit(1)