#!/usr/bin/env python3
"""
Enhanced BitTorrent Network Deployment Script with Two-Phase Deployment
- Phase 1: Deploy all seeders first and wait for them to be ready
- Phase 2: Deploy leechers after seeders are serving
- Includes CSV file collection from BitTorrent clients
"""

# Timing Constants for Coordinated Startup
SETUP_COMPLETION_WAIT_SECONDS = 10  # Wait after all instances finish setup
LEECHER_START_INTERVAL_SECONDS = 5  # Wait between each leecher starting
POST_LEECHERS_WAIT_SECONDS = 10     # Wait after all leechers start before seeders
# Seeders start in parallel (no interval needed)

# Constants
LOGS_DIR = "logs"
TORRENT_TEMP_DIR = "/tmp/torrents"
SEED_TEMP_DIR = "/tmp/seed"
BITTORRENT_PROJECT_DIR = "/tmp/bittorrent-project"
LOG_FILE_PATH = "/tmp/bittorrent.log"
TORRENT_FILENAME = "file.torrent"
SEED_FILENAME = "seed_file"

# API Endpoints
LOGS_ENDPOINT = '/logs'
STREAM_ENDPOINT = '/stream'
COMPLETION_ENDPOINT = '/completion'
CSV_ENDPOINT = '/csv'
SETUP_COMPLETE_ENDPOINT = '/setup_complete'
START_SIGNAL_ENDPOINT = '/start_signal'
IP_API_URL = 'https://api.ipify.org'

# HTTP Constants
HTTP_OK = 200
HTTP_NOT_FOUND = 404

# AWS Constants
DEFAULT_INSTANCE_TYPE = "t2.micro"
DEFAULT_REGION = "us-east-1"
EC2_SERVICE_NAME = 'ec2'

# AMI Constants
UBUNTU_OWNER_ID = '099720109477'
UBUNTU_AMI_NAME_PATTERN = 'ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*'
AMI_ARCHITECTURE = 'x86_64'
AMI_STATE_AVAILABLE = 'available'

# Timing Constants
DEFAULT_TIMEOUT_MINUTES = 30
COMPLETION_CHECK_INTERVAL = 10
DEFAULT_CONTROLLER_PORT = 8080

# Installation Commands
UPDATE_CMD = "apt-get update"
INSTALL_PACKAGES_CMD = "apt-get install -y git python3 python3-pip python3-dev python3-venv build-essential libssl-dev libffi-dev"
INSTALL_DEPS_CMD = "python3 -m pip install -r requirements.txt --timeout 300"
SHUTDOWN_CMD = "shutdown -h now"

# Role Constants
ROLE_SEEDER = "seeder"
ROLE_LEECHER = "leecher"

# Status Constants
STATUS_COMPLETE = "complete"

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

# File Paths and Names
DEFAULT_CONFIG_PATH = "config.yaml"
DEFAULT_CONFIG_PATH = os.environ.get('CPATH', DEFAULT_CONFIG_PATH)
print(f"{COLOR_GREEN}Using config path: {DEFAULT_CONFIG_PATH}{COLOR_RESET}")

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
    instance_status = {}
    csv_files = {}  # Track CSV files received
    setup_completions = {}  # Track setup completion
    start_signals = {}  # Track start signals sent
    run_name = None
    last_display_time = 0
    
    # Status stages
    STATUS_STARTING = "starting"
    STATUS_UPDATING = "updating"
    STATUS_INSTALLING = "installing"
    STATUS_DOWNLOADING = "downloading"
    STATUS_SETUP_COMPLETE = "setup_complete"
    STATUS_WAITING_START = "waiting_start"
    STATUS_RUNNING = "running"
    STATUS_COLLECTING_CSV = "collecting_csv"
    STATUS_COMPLETED = "completed"
    STATUS_ERROR = "error"
    
    @classmethod
    def set_run_name(cls, run_name):
        cls.run_name = run_name
        run_dir = os.path.join(cls.logs_dir, run_name)
        csv_dir = os.path.join(run_dir, "csv_files")
        os.makedirs(run_dir, exist_ok=True)
        os.makedirs(csv_dir, exist_ok=True)
    
    @classmethod
    def update_instance_status(cls, instance_id, status, progress=None, message=None):
        """Update instance status and refresh display"""
        cls.instance_status[instance_id] = {
            'status': status,
            'progress': progress,
            'message': message or '',
            'timestamp': time.time()
        }
        
        # Throttle display updates
        current_time = time.time()
        if current_time - cls.last_display_time > 1.0:
            cls.display_status_dashboard()
            cls.last_display_time = current_time
    
    @classmethod
    def display_status_dashboard(cls):
        """Display a clean status dashboard"""
        print('\033[2J\033[H', end='')  # Clear screen
        
        print(f"{COLOR_BOLD}{COLOR_MAGENTA}🚀 BitTorrent Network Status Dashboard{COLOR_RESET}")
        print(f"{COLOR_BOLD}{COLOR_YELLOW}📁 Run: {cls.run_name}{COLOR_RESET}")
        print("=" * 80)
        
        # Group by region and role
        regions = {}
        for instance_id, info in cls.instance_status.items():
            parts = instance_id.split('-')
            if len(parts) >= 3:
                role = None
                region_parts = []
                
                for i, part in enumerate(parts):
                    if part in ['seeder', 'leecher']:
                        role = part
                        region_parts = parts[:i]
                        break
                
                if role and region_parts:
                    region = '-'.join(region_parts)
                    if region not in regions:
                        regions[region] = {'seeders': [], 'leechers': []}
                    regions[region][role + 's'].append((instance_id, info))
        
        for region_name, roles in regions.items():
            print(f"\n{COLOR_BOLD}{COLOR_BLUE}🌍 {region_name.upper()}{COLOR_RESET}")
            
            if roles['seeders']:
                print(f"  {COLOR_GREEN}🌱 Seeders:{COLOR_RESET}")
                for instance_id, info in roles['seeders']:
                    status_emoji, status_text = cls._get_status_display(info['status'], info.get('progress'))
                    csv_info = cls._get_csv_info(instance_id)
                    print(f"    {status_emoji} {instance_id}: {status_text}{csv_info}")
            
            if roles['leechers']:
                print(f"  {COLOR_BLUE}📥 Leechers:{COLOR_RESET}")
                for instance_id, info in roles['leechers']:
                    status_emoji, status_text = cls._get_status_display(info['status'], info.get('progress'))
                    csv_info = cls._get_csv_info(instance_id)
                    print(f"    {status_emoji} {instance_id}: {status_text}{csv_info}")
        
        # Summary
        total_instances = len(cls.instance_status)
        completed_count = len([i for i in cls.instance_status.values() if i['status'] == cls.STATUS_COMPLETED])
        running_count = len([i for i in cls.instance_status.values() if i['status'] == cls.STATUS_RUNNING])
        csv_count = len(cls.csv_files)
        
        print(f"\n{COLOR_BOLD}📊 Summary:{COLOR_RESET}")
        print(f"  Total: {total_instances} | Running: {running_count} | Completed: {completed_count} | CSV Files: {csv_count}")
    
    @classmethod
    def _get_csv_info(cls, instance_id):
        """Get CSV file info for display"""
        if instance_id in cls.csv_files:
            csv_count = len(cls.csv_files[instance_id])
            return f" {COLOR_CYAN}[{csv_count} CSV]{COLOR_RESET}"
        return ""
    
    @classmethod 
    def _get_status_display(cls, status, progress=None):
        """Get emoji and text for status display"""
        status_map = {
            cls.STATUS_STARTING: ("🔄", "Starting up"),
            cls.STATUS_UPDATING: ("📦", "Updating system"), 
            cls.STATUS_INSTALLING: ("⚙️", "Installing packages"),
            cls.STATUS_DOWNLOADING: ("⬇️", "Downloading files"),
            cls.STATUS_SETUP_COMPLETE: ("✅", "Setup complete"),
            cls.STATUS_WAITING_START: ("⏳", "Waiting for start signal"),
            cls.STATUS_RUNNING: ("🚀", f"Running BitTorrent {progress}%" if progress else "Running BitTorrent"),
            cls.STATUS_COLLECTING_CSV: ("📊", "Collecting CSV files"),
            cls.STATUS_COMPLETED: ("🎉", "Completed"),
            cls.STATUS_ERROR: ("❌", "Error")
        }
        
        emoji, text = status_map.get(status, ("❓", f"Unknown: {status}"))
        
        if status == cls.STATUS_RUNNING and progress is not None:
            text = f"Running BitTorrent {progress:.1f}%"
            
        return emoji, text
    
    def do_POST(self):
        if self.path == LOGS_ENDPOINT:
            self._handle_logs()
        elif self.path == STREAM_ENDPOINT:
            self._handle_stream()
        elif self.path == COMPLETION_ENDPOINT:
            self._handle_completion()
        elif self.path == CSV_ENDPOINT:
            self._handle_csv()
        elif self.path == SETUP_COMPLETE_ENDPOINT:
            self._handle_setup_complete()
        else:
            self.send_response(HTTP_NOT_FOUND)
            self.end_headers()
    
    def do_GET(self):
        if self.path.startswith(START_SIGNAL_ENDPOINT):
            self._handle_start_signal()
        else:
            self.send_response(HTTP_NOT_FOUND)
            self.end_headers()
    
    def _handle_csv(self):
        """Handle CSV file uploads from instances"""
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
        csv_filename = None
        csv_data = None
        
        for part in parts:
            if b'name="instance_id"' in part:
                instance_id = part.split(b'\r\n\r\n')[1].split(b'\r\n')[0].decode()
            elif b'name="csv_filename"' in part:
                csv_filename = part.split(b'\r\n\r\n')[1].split(b'\r\n')[0].decode()
            elif b'name="csv_file"' in part:
                csv_data = part.split(b'\r\n\r\n', 1)[1].rsplit(b'\r\n', 1)[0]
        
        if instance_id and csv_filename and csv_data:
            # Save CSV file
            run_dir = os.path.join(self.logs_dir, self.run_name)
            csv_dir = os.path.join(run_dir, "csv_files")
            os.makedirs(csv_dir, exist_ok=True)
            
            csv_path = os.path.join(csv_dir, f"{instance_id}_{csv_filename}")
            with open(csv_path, 'wb') as f:
                f.write(csv_data)
            
            # Track CSV file
            if instance_id not in self.csv_files:
                self.csv_files[instance_id] = []
            self.csv_files[instance_id].append({
                'filename': csv_filename,
                'path': csv_path,
                'size': len(csv_data),
                'timestamp': time.time()
            })
            
            print(f"{COLOR_CYAN}📊 CSV file received: {instance_id}/{csv_filename} ({len(csv_data)} bytes){COLOR_RESET}")
        
        self.send_response(HTTP_OK)
        self.end_headers()
    
    def _handle_setup_complete(self):
        """Handle setup completion notifications from instances"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode())
            instance_id = data.get('instance_id')
            
            if instance_id:
                self.setup_completions[instance_id] = time.time()
                self.update_instance_status(instance_id, self.STATUS_SETUP_COMPLETE)
                print(f"{COLOR_GREEN}✅ Setup completed: {instance_id}{COLOR_RESET}")
                
        except json.JSONDecodeError:
            pass
        
        self.send_response(HTTP_OK)
        self.end_headers()
    
    def _handle_start_signal(self):
        """Handle start signal requests from instances"""
        # Parse instance_id from query parameters
        from urllib.parse import urlparse, parse_qs
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)
        instance_id = query_params.get('instance_id', [None])[0]
        
        if instance_id:
            # Check if this instance should start (controlled by main coordination logic)
            should_start = instance_id in self.start_signals
            
            if should_start:
                self.send_response(HTTP_OK)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"start": True}).encode())
                self.update_instance_status(instance_id, self.STATUS_RUNNING)
            else:
                self.send_response(HTTP_OK)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"start": False}).encode())
        else:
            self.send_response(400)
            self.end_headers()
    
    def _handle_logs(self):
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
        """Handle streaming log updates"""
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
        
        is_seeder = 'seeder' in instance_id
        
        if 'starting setup' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_STARTING)
        elif 'system update' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_UPDATING)
        elif 'installing' in log_lower and ('packages' in log_lower or 'dependencies' in log_lower):
            self.update_instance_status(instance_id, self.STATUS_INSTALLING)
        elif 'downloading' in log_lower and ('torrent' in log_lower or 'seed' in log_lower):
            self.update_instance_status(instance_id, self.STATUS_DOWNLOADING)
        elif 'setup completed' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_SETUP_COMPLETE)
        elif 'waiting for start signal' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_WAITING_START)
        elif 'starting bittorrent client' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_RUNNING)
        elif 'collecting csv files' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_COLLECTING_CSV)
        elif 'bittorrent client finished' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_COMPLETED)
        elif not is_seeder and ('downloaded' in log_lower or 'progress' in log_lower or '%' in log_chunk):
            progress = self._extract_progress(log_chunk)
            if progress is not None:
                self.update_instance_status(instance_id, self.STATUS_RUNNING, progress=progress)
        elif 'error' in log_lower or 'failed' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_ERROR, message=log_chunk[:50])
    
    def _extract_progress(self, log_chunk):
        """Extract download progress percentage from log chunk"""
        import re
        
        percent_match = re.search(r'(\d+(?:\.\d+)?)\s*%', log_chunk)
        if percent_match:
            return float(percent_match.group(1))
        
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
        self.region_amis = {}
        self.region_security_groups = {}
    
    def get_ec2_client(self, region):
        if region not in self.region_clients:
            self.region_clients[region] = boto3.client(
                EC2_SERVICE_NAME,
                region_name=region,
            )
        return self.region_clients[region]
    
    def create_simple_security_group(self, region):
        """Create a simple All-All security group matching the image"""
        if region in self.region_security_groups:
            return self.region_security_groups[region], None
            
        try:
            ec2_client = self.get_ec2_client(region)
            
            # Create security group
            group_name = f"bittorrent-all-{int(time.time())}"
            group_description = "All traffic allowed - BitTorrent testing"
            
            response = ec2_client.create_security_group(
                GroupName=group_name,
                Description=group_description
            )
            
            security_group_id = response['GroupId']
            
            # Add simple All-All inbound rule (matching your image)
            ec2_client.authorize_security_group_ingress(
                GroupId=security_group_id,
                IpPermissions=[
                    {
                        'IpProtocol': '-1',  # All protocols
                        'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                    }
                ]
            )
            
            # Remove default outbound rule and add All-All outbound rule
            # First get the default outbound rules to remove them
            try:
                sg_info = ec2_client.describe_security_groups(GroupIds=[security_group_id])
                default_egress = sg_info['SecurityGroups'][0]['IpPermissionsEgress']
                
                if default_egress:
                    ec2_client.revoke_security_group_egress(
                        GroupId=security_group_id,
                        IpPermissions=default_egress
                    )
            except Exception:
                pass  # Ignore if we can't remove default rules
            
            # Add our All-All outbound rule
            ec2_client.authorize_security_group_egress(
                GroupId=security_group_id,
                IpPermissions=[
                    {
                        'IpProtocol': '-1',  # All protocols
                        'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                    }
                ]
            )
            
            self.region_security_groups[region] = security_group_id
            return security_group_id, None
            
        except Exception as e:
            return None, f"Failed to create security group in {region}: {str(e)}"
    
    def cleanup_security_groups(self):
        """Clean up created security groups"""
        for region, sg_id in self.region_security_groups.items():
            try:
                ec2_client = self.get_ec2_client(region)
                ec2_client.delete_security_group(GroupId=sg_id)
                print(f"{COLOR_GREEN}✓ Deleted security group {sg_id} in {region}{COLOR_RESET}")
            except Exception as e:
                print(f"{COLOR_YELLOW}⚠ Could not delete security group {sg_id} in {region}: {e}{COLOR_RESET}")
    
    def get_latest_ubuntu_ami(self, region):
        """Get latest Ubuntu 22.04 AMI for the specified region"""
        if region in self.region_amis:
            return self.region_amis[region], None
        
        try:
            ec2_client = self.get_ec2_client(region)
            
            response = ec2_client.describe_images(
                Owners=[UBUNTU_OWNER_ID],
                Filters=[
                    {'Name': 'name', 'Values': [UBUNTU_AMI_NAME_PATTERN]},
                    {'Name': 'state', 'Values': [AMI_STATE_AVAILABLE]},
                    {'Name': 'architecture', 'Values': [AMI_ARCHITECTURE]}
                ]
            )
            
            if not response['Images']:
                return None, f"No Ubuntu 22.04 AMIs found in {region}"
            
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
            
            self.region_amis[region] = ami_info
            return ami_info, None
            
        except Exception as e:
            return None, f"Failed to lookup AMI in {region}: {str(e)}"
    
    def generate_user_data(self, github_repo, torrent_url, seed_fileurl, role, controller_ip, controller_port, instance_id):
        script = f"""#!/bin/bash
set -x
exec > >(tee -a /tmp/startup.log) 2>&1

send_log() {{
    curl -s -X POST -H "Content-Type: application/json" -d '{{"instance_id": "{instance_id}", "log_chunk": "'"$1"'", "timestamp": '$(date +%s)'}}' http://{controller_ip}:{controller_port}{STREAM_ENDPOINT} || true
}}

upload_csv() {{
    send_log "Collecting CSV files from project directory..."
    find {BITTORRENT_PROJECT_DIR} -name "*.csv" -type f | while read f; do
        if [ -f "$f" ]; then
            curl -X POST -F "instance_id={instance_id}" -F "csv_filename=$(basename "$f")" -F "csv_file=@$f" http://{controller_ip}:{controller_port}{CSV_ENDPOINT} || true
            send_log "Uploaded CSV: $(basename "$f")"
        fi
    done
}}

cleanup() {{
    send_log "Instance {instance_id} shutting down"
    upload_csv
    [ -f {LOG_FILE_PATH} ] && curl -X POST -F "instance_id={instance_id}" -F "logfile=@{LOG_FILE_PATH}" http://{controller_ip}:{controller_port}{LOGS_ENDPOINT} || true
    curl -X POST -H "Content-Type: application/json" -d '{{"instance_id": "{instance_id}", "status": "interrupted"}}' http://{controller_ip}:{controller_port}{COMPLETION_ENDPOINT} || true
}}

trap cleanup EXIT TERM INT

echo "=== Starting {instance_id} ({role}) ==="
send_log "Instance {instance_id} starting setup (Role: {role})"

echo "=== System Update ==="
send_log "Starting system update..."
{UPDATE_CMD}
send_log "System update completed"

echo "=== Installing Packages ==="
send_log "Installing system packages..."
{INSTALL_PACKAGES_CMD} tree
send_log "System packages installation completed"

echo "=== Network Configuration ==="
send_log "Configuring network settings..."
PUBLIC_IP=$(curl -s https://api.ipify.org || echo "unknown")
PRIVATE_IP=$(hostname -I | awk '{{print $1}}' || echo "unknown")
send_log "Network - Public IP: $PUBLIC_IP, Private IP: $PRIVATE_IP"

# Configure iptables
iptables -F 2>/dev/null || true
iptables -P INPUT ACCEPT 2>/dev/null || true
iptables -P OUTPUT ACCEPT 2>/dev/null || true
send_log "Network configuration completed"

echo "=== Cloning Repository ==="
send_log "Cloning repository from {github_repo}"
git clone -b feat/distribed {github_repo} {BITTORRENT_PROJECT_DIR}
send_log "Repository cloned successfully"

echo "=== Installing Dependencies ==="
cd {BITTORRENT_PROJECT_DIR}
send_log "Starting Python dependencies installation..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt --timeout 300
PIP_EXIT=$?
if [ $PIP_EXIT -ne 0 ]; then
    send_log "ERROR: pip install failed"
    exit 1
fi
send_log "Python dependencies installation completed"

echo "=== Downloading Files ==="
mkdir -p {TORRENT_TEMP_DIR}
send_log "Downloading torrent file..."
curl -L -o {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} {torrent_url}
send_log "Torrent file download completed"

# Role-specific setup
if [ "{role}" == "{ROLE_SEEDER}" ]; then
    send_log "Seeder downloading seed file to project directory..."
    SEED_FILE=$(basename "{seed_fileurl}")
    [ -z "$SEED_FILE" ] && SEED_FILE="{SEED_FILENAME}"
    curl -L -o "$SEED_FILE" {seed_fileurl}
    if [ ! -f "$SEED_FILE" ]; then
        send_log "ERROR: Failed to download seed file"
        exit 1
    fi
    send_log "Seed file downloaded: $SEED_FILE"
else
    send_log "Leecher setup - will download via BitTorrent"
fi

echo "=== Environment Setup ==="
export BITTORRENT_ROLE="{role}"
export INSTANCE_ID="{instance_id}"
export PUBLIC_IP="$PUBLIC_IP"
export BITTORRENT_PORT=6881
export BITTORRENT_BIND_IP="0.0.0.0"
export BITTORRENT_ANNOUNCE_IP="$PUBLIC_IP"
send_log "BitTorrent environment configured - Role: {role}, Port: 6881"

echo "=== Setup Completed ==="
send_log "Setup completed - waiting for coordinated start signal..."
curl -X POST -H "Content-Type: application/json" -d '{{"instance_id": "{instance_id}"}}' http://{controller_ip}:{controller_port}{SETUP_COMPLETE_ENDPOINT}

echo "=== Waiting for Start Signal ==="
send_log "Waiting for start signal from controller..."
while true; do
    RESPONSE=$(curl -s http://{controller_ip}:{controller_port}{START_SIGNAL_ENDPOINT}?instance_id={instance_id})
    START_SIGNAL=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('start', False))" 2>/dev/null || echo "False")
    
    if [ "$START_SIGNAL" = "True" ]; then
        break
    fi
    sleep 2
done

echo "=== Start Signal Received ==="
send_log "Start signal received - beginning BitTorrent execution..."

# Start log streaming
tail -f /tmp/startup.log | while read line; do send_log "STARTUP: $line"; sleep 0.5; done &

echo "=== Directory Structure Verification ===" >> {LOG_FILE_PATH}
echo "Current working directory: $(pwd)" >> {LOG_FILE_PATH}
echo "Directory tree before BitTorrent execution:" >> {LOG_FILE_PATH}
tree . >> {LOG_FILE_PATH} 2>&1
echo "Torrent temp directory contents:" >> {LOG_FILE_PATH}
ls -la {TORRENT_TEMP_DIR}/ >> {LOG_FILE_PATH} 2>&1
echo "========================================" >> {LOG_FILE_PATH}

echo "=== Starting BitTorrent Client ==="
send_log "Starting BitTorrent client from project directory..."

if [ "{role}" == "{ROLE_SEEDER}" ]; then
    send_log "Starting BitTorrent client as SEEDER"
    python3 -m main -s {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} > {LOG_FILE_PATH} 2>&1
else
    send_log "Starting BitTorrent client as LEECHER"
    python3 -m main {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} > {LOG_FILE_PATH} 2>&1
fi

echo "=== BitTorrent Completed ==="
send_log "BitTorrent client finished"

# Stop log streaming
pkill -f "tail -f" 2>/dev/null || true

echo "=== Final Steps ==="
upload_csv
send_log "Sending final logs to controller..."
curl -X POST -F "instance_id={instance_id}" -F "logfile=@{LOG_FILE_PATH}" http://{controller_ip}:{controller_port}{LOGS_ENDPOINT}
curl -X POST -H "Content-Type: application/json" -d '{{"instance_id": "{instance_id}", "status": "{STATUS_COMPLETE}"}}' http://{controller_ip}:{controller_port}{COMPLETION_ENDPOINT}

send_log "Instance setup completed, shutting down..."
trap - EXIT TERM INT
{SHUTDOWN_CMD}
"""
        return base64.b64encode(script.encode()).decode()
    
    def launch_instance(self, region, user_data, ami_id, security_group_id):
        ec2_client = self.get_ec2_client(region)
        
        response = ec2_client.run_instances(
            ImageId=ami_id,
            InstanceType=self.aws_config.get('instance_type', DEFAULT_INSTANCE_TYPE),
            MinCount=1,
            MaxCount=1,
            UserData=user_data,
            SecurityGroupIds=[security_group_id]
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
        self.cleanup_in_progress = False
        self.handler = None
        
        # Generate unique run name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_word = random.choice(RUN_WORDS)
        self.run_name = f"{random_word}_{timestamp}"
        
        LogHandler.set_run_name(self.run_name)
        
        # Calculate instance counts
        self.total_seeder_count = 0
        self.total_leecher_count = 0
        for region in self.config.get_regions():
            self.total_seeder_count += region['seeders']
            self.total_leecher_count += region['leechers']
        self.total_instance_count = self.total_seeder_count + self.total_leecher_count
        
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
            if self.handler:
                print(f"{COLOR_CYAN}📡 Attempting to collect available logs...{COLOR_RESET}")
                time.sleep(2)
                
                print(f"\n{COLOR_BOLD}=== Emergency Log Summary ==={COLOR_RESET}")
                run_dir = os.path.join(LOGS_DIR, self.run_name)
                
                if os.path.exists(run_dir):
                    for file in os.listdir(run_dir):
                        if file.endswith('.log'):
                            file_path = os.path.join(run_dir, file)
                            file_size = os.path.getsize(file_path)
                            print(f"{COLOR_GREEN}📝 {file} ({file_size} bytes){COLOR_RESET}")
                
                # Show CSV files collected
                csv_dir = os.path.join(run_dir, "csv_files")
                if os.path.exists(csv_dir):
                    csv_files = [f for f in os.listdir(csv_dir) if f.endswith('.csv')]
                    if csv_files:
                        print(f"\n{COLOR_BOLD}=== CSV Files Collected ==={COLOR_RESET}")
                        for csv_file in csv_files:
                            csv_path = os.path.join(csv_dir, csv_file)
                            csv_size = os.path.getsize(csv_path)
                            print(f"{COLOR_CYAN}📊 {csv_file} ({csv_size} bytes){COLOR_RESET}")
                
                if self.handler.completion_status:
                    print(f"\n{COLOR_BOLD}=== Instance Status ==={COLOR_RESET}")
                    for instance_id, status in self.handler.completion_status.items():
                        print(f"{COLOR_GREEN}✅ {instance_id}: {status}{COLOR_RESET}")
        except Exception as e:
            print(f"{COLOR_RED}⚠ Error during log collection: {e}{COLOR_RESET}")
        
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
            
            # Wait a bit for instances to terminate before cleaning up security groups
            print(f"{COLOR_YELLOW}⏳ Waiting briefly for instances to terminate...{COLOR_RESET}")
            time.sleep(10)
            
            try:
                self.aws_manager.cleanup_security_groups()
            except Exception as e:
                print(f"{COLOR_YELLOW}⚠ Error cleaning up security groups: {e}{COLOR_RESET}")
                        
            if self.log_server:
                self.log_server.stop()
                print(f"{COLOR_GREEN}✓ Log server stopped{COLOR_RESET}")
                
        except Exception as e:
            print(f"{COLOR_RED}⚠ Error during instance cleanup: {e}{COLOR_RESET}")
        
        print(f"\n{COLOR_BOLD}{COLOR_YELLOW}🛑 Emergency cleanup completed{COLOR_RESET}")
        print(f"{COLOR_BOLD}{COLOR_BLUE}📁 Partial logs saved in: {LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
        if os.path.exists(os.path.join(LOGS_DIR, self.run_name, "csv_files")):
            print(f"{COLOR_BOLD}{COLOR_CYAN}📊 CSV files saved in: {LOGS_DIR}/{self.run_name}/csv_files/{COLOR_RESET}")
    
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
                region_ami_map[region_name] = ami_info['ami_id']
            else:
                print(f"  {COLOR_RED}✗ AMI lookup failed: {error}{COLOR_RESET}")
                return None, f"AMI lookup failed for {region_name}: {error}"
        
        print(f"{COLOR_GREEN}✅ All AMIs found successfully across {len(all_regions)} regions{COLOR_RESET}")
        return region_ami_map, None
    
    def deploy_region(self, region_config, torrent_url, seed_fileurl, ami_id):
        """Deploy all instances (seeders and leechers) for this region"""
        region_name = region_config['name']
        instance_ids = []
        
        # Create simple All-All security group for this region
        security_group_id, sg_error = self.aws_manager.create_simple_security_group(region_name)
        if sg_error:
            print(f"{COLOR_RED}✗ Failed to create security group in {region_name}: {sg_error}{COLOR_RESET}")
            return region_name, []
        
        print(f"{COLOR_GREEN}✓ Created All-All security group {security_group_id} in {region_name}{COLOR_RESET}")
        
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
            
            ec2_id = self.aws_manager.launch_instance(region_name, user_data, ami_id, security_group_id)
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
            
            ec2_id = self.aws_manager.launch_instance(region_name, user_data, ami_id, security_group_id)
            instance_ids.append(ec2_id)
        
        return region_name, instance_ids
    
    def wait_for_all_setup_complete(self, handler, timeout_minutes):
        """Wait for all instances to complete setup"""
        print(f"\n{COLOR_BOLD}=== Waiting for All Instances Setup Completion ==={COLOR_RESET}")
        print(f"⚙️  Waiting for {self.total_instance_count} instances to complete setup...")
        print(f"⏱️  Timeout: {timeout_minutes} minutes")
        
        timeout = time.time() + (timeout_minutes * 60)
        
        while time.time() < timeout:
            if self.cleanup_in_progress:
                return False
            
            setup_complete_count = len(handler.setup_completions)
            print(f"\r⚙️  Setup completed: {setup_complete_count}/{self.total_instance_count} ({(setup_complete_count/self.total_instance_count)*100:.1f}%)", end='', flush=True)
            
            if setup_complete_count >= self.total_instance_count:
                print(f"\n{COLOR_GREEN}✅ All {setup_complete_count} instances completed setup!{COLOR_RESET}")
                return True
            
            time.sleep(5)
        
        print(f"\n{COLOR_YELLOW}⚠ Timeout: Only {setup_complete_count}/{self.total_instance_count} instances completed setup{COLOR_RESET}")
        return False
    
    def coordinate_staggered_startup(self, handler):
        """Coordinate staggered startup: Leechers first, then Seeders in parallel"""
        print(f"\n{COLOR_BOLD}=== Coordinated Staggered Startup ==={COLOR_RESET}")
        
        # Wait configured time after setup completion
        print(f"{COLOR_CYAN}⏳ Waiting {SETUP_COMPLETION_WAIT_SECONDS} seconds after setup completion...{COLOR_RESET}")
        time.sleep(SETUP_COMPLETION_WAIT_SECONDS)
        
        # Get seeder and leecher instance IDs
        seeder_instances = []
        leecher_instances = []
        
        for instance_id in handler.setup_completions.keys():
            if 'seeder' in instance_id:
                seeder_instances.append(instance_id)
            elif 'leecher' in instance_id:
                leecher_instances.append(instance_id)
        
        # Start leechers first with staggered timing
        print(f"\n{COLOR_BLUE}📥 Starting {len(leecher_instances)} leechers first with {LEECHER_START_INTERVAL_SECONDS}s intervals...{COLOR_RESET}")
        for i, leecher_id in enumerate(leecher_instances):
            if self.cleanup_in_progress:
                return False
            
            print(f"{COLOR_BLUE}📥 Starting leecher {i+1}/{len(leecher_instances)}: {leecher_id}{COLOR_RESET}")
            handler.start_signals[leecher_id] = time.time()
            
            if i < len(leecher_instances) - 1:  # Don't wait after the last one
                time.sleep(LEECHER_START_INTERVAL_SECONDS)
        
        # Wait configured time after all leechers start
        print(f"{COLOR_CYAN}⏳ Waiting {POST_LEECHERS_WAIT_SECONDS} seconds for leechers to establish...{COLOR_RESET}")
        time.sleep(POST_LEECHERS_WAIT_SECONDS)
        
        # Start all seeders in parallel (no intervals)
        print(f"\n{COLOR_GREEN}🌱 Starting all {len(seeder_instances)} seeders in parallel...{COLOR_RESET}")
        for seeder_id in seeder_instances:
            if self.cleanup_in_progress:
                return False
            
            print(f"{COLOR_GREEN}🌱 Starting seeder: {seeder_id}{COLOR_RESET}")
            handler.start_signals[seeder_id] = time.time()
        
        print(f"{COLOR_BOLD}{COLOR_MAGENTA}🚀 Staggered startup complete! Leechers started first, then seeders in parallel.{COLOR_RESET}")
        return True
    
    def wait_for_completion(self, handler, timeout_minutes):
        """Wait for all instances to complete"""
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
            print(f"{COLOR_BOLD}{COLOR_MAGENTA}🚀 Enhanced BitTorrent Network Deployment with CSV Collection{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_YELLOW}📁 Run Name: {self.run_name}{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_BLUE}💾 Logs Directory: {LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_CYAN}📊 CSV Files Directory: {LOGS_DIR}/{self.run_name}/csv_files/{COLOR_RESET}")
            print(f"{COLOR_YELLOW}💡 Press Ctrl+C at any time for graceful cleanup{COLOR_RESET}")
            print(f"{COLOR_CYAN}⚙️  Phase 1: All instances complete setup in parallel{COLOR_RESET}")
            print(f"{COLOR_BLUE}📥 Phase 2: Start leechers first with staggered timing{COLOR_RESET}")
            print(f"{COLOR_GREEN}🌱 Phase 3: Start seeders in parallel after leechers{COLOR_RESET}")
            
            # Look up AMIs
            region_ami_map, ami_error = self._lookup_and_validate_amis()
            if ami_error:
                print(f"\n{COLOR_RED}💥 AMI validation failed: {ami_error}{COLOR_RESET}")
                return {}
            
            # Start log server
            self.handler = self.log_server.start()
            print(f"\n{COLOR_GREEN}🌐 Log server started on port {self.config.get_controller_port()}{COLOR_RESET}")
            print(f"{COLOR_GREEN}🌍 Controller IP: {self.controller_ip}{COLOR_RESET}")
            print(f"{COLOR_CYAN}📊 CSV collection endpoint: /csv{COLOR_RESET}")
            
            # Get URLs
            torrent_url = self.config.get_bittorrent_config()['torrent_url']
            seed_fileurl = self.config.get_bittorrent_config()['seed_fileurl']
            github_repo = self.config.get_bittorrent_config()['github_repo']
            
            print(f"\n{COLOR_BOLD}=== Configuration ==={COLOR_RESET}")
            print(f"📂 GitHub repo: {github_repo}")
            print(f"📁 Torrent URL: {torrent_url}")
            print(f"🌱 Seed file URL: {seed_fileurl}")
            print(f"🔒 Security: Creating All-All security groups (matching your setup)")
            
            print(f"\n{COLOR_BOLD}=== Deployment Plan ==={COLOR_RESET}")
            for region in self.config.get_regions():
                ami_id = region_ami_map[region['name']]
                print(f"🌍 Region {region['name']}: {COLOR_GREEN}{region['seeders']} seeders{COLOR_RESET}, {COLOR_BLUE}{region['leechers']} leechers{COLOR_RESET} (AMI: {ami_id})")
            print(f"📊 Total: {COLOR_GREEN}{self.total_seeder_count} seeders{COLOR_RESET}, {COLOR_BLUE}{self.total_leecher_count} leechers{COLOR_RESET} = {COLOR_BOLD}{self.total_instance_count} instances{COLOR_RESET}")
            print(f"{COLOR_YELLOW}🔄 Coordinated startup timing:{COLOR_RESET}")
            print(f"  • Setup completion wait: {SETUP_COMPLETION_WAIT_SECONDS}s")
            print(f"  • Leecher start interval: {LEECHER_START_INTERVAL_SECONDS}s (leechers start first)")
            print(f"  • Post-leechers wait: {POST_LEECHERS_WAIT_SECONDS}s")
            print(f"  • Seeders: All start in parallel (after leechers)")
            
            # =================================================================
            # DEPLOY ALL INSTANCES (SETUP ONLY)
            # =================================================================
            print(f"\n{COLOR_BOLD}{COLOR_CYAN}=== Deploying All Instances for Setup ==={COLOR_RESET}")
            print(f"⚙️  Deploying {self.total_instance_count} instances across {len(self.config.get_regions())} regions...")
            print(f"📦 All instances will complete setup in parallel, then wait for coordinated start signals")
            
            futures = []
            with ThreadPoolExecutor() as executor:
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
                
                # Collect all instance IDs
                for future in futures:
                    if self.cleanup_in_progress:
                        break
                    region_name, instance_ids = future.result()
                    self.region_instances[region_name] = instance_ids
                    if instance_ids:
                        print(f"{COLOR_GREEN}✓ Launched {len(instance_ids)} instances in {region_name}{COLOR_RESET}")
            
            if self.cleanup_in_progress:
                return {}
                
            print(f"{COLOR_GREEN}✅ All {self.total_instance_count} instances deployed and setting up in parallel{COLOR_RESET}")
            
            # =================================================================
            # WAIT FOR ALL SETUP COMPLETIONS
            # =================================================================
            setup_complete = self.wait_for_all_setup_complete(self.handler, 
                                                            max(15, self.config.get_timeout_minutes() // 2))
            
            if not setup_complete:
                print(f"{COLOR_RED}💥 Setup Phase Failed: Not all instances completed setup in time{COLOR_RESET}")
                if not self.cleanup_in_progress:
                    self._emergency_cleanup()
                return {}
            
            # =================================================================
            # COORDINATE STAGGERED STARTUP
            # =================================================================
            startup_success = self.coordinate_staggered_startup(self.handler)
            
            if not startup_success:
                print(f"{COLOR_RED}💥 Startup Coordination Failed{COLOR_RESET}")
                if not self.cleanup_in_progress:
                    self._emergency_cleanup()
                return {}
            
            # Wait for completion
            print(f"\n{COLOR_BOLD}=== Live Status Dashboard ==={COLOR_RESET}")
            print("⚙️  All instances completed setup and received coordinated start signals")
            print("📥 Leechers started first with staggered timing")
            print("🌱 Seeders started in parallel after leechers were established")  
            print("📊 CSV files will be automatically collected after BitTorrent completion")
            print(f"⏱️  Will wait up to {self.config.get_timeout_minutes()} minutes for all to complete...")
            print(f"📁 Logs being saved to: {COLOR_YELLOW}{LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
            print(f"📊 CSV files being saved to: {COLOR_CYAN}{LOGS_DIR}/{self.run_name}/csv_files/{COLOR_RESET}")
            print(f"{COLOR_YELLOW}💡 Press Ctrl+C anytime to stop and cleanup{COLOR_RESET}")
            print("\n" + "=" * 80)
            
            # Initial dashboard display
            LogHandler.display_status_dashboard()
            
            completed = self.wait_for_completion(self.handler, self.config.get_timeout_minutes())
            
            if self.cleanup_in_progress:
                return {}
            
            if completed:
                print(f"\n{COLOR_GREEN}✅ All instances completed successfully{COLOR_RESET}")
                LogHandler.display_status_dashboard()
            else:
                print(f"\n{COLOR_YELLOW}⚠ Timeout reached, some instances may not have completed{COLOR_RESET}")
                LogHandler.display_status_dashboard()
            
            # Process logs and CSV files
            print(f"\n{COLOR_BOLD}=== Results Summary ==={COLOR_RESET}")
            run_dir = os.path.join(LOGS_DIR, self.run_name)
            csv_dir = os.path.join(run_dir, "csv_files")
            
            for instance_id, status in self.handler.completion_status.items():
                final_log = os.path.join(run_dir, f"{instance_id}.log")
                stream_log = os.path.join(run_dir, f"{instance_id}_stream.log")
                
                if os.path.exists(final_log):
                    print(f"{COLOR_GREEN}✓ {instance_id}: {status} (final log: {final_log}){COLOR_RESET}")
                else:
                    print(f"{COLOR_RED}✗ {instance_id}: {status} (no final log){COLOR_RESET}")
                
                if os.path.exists(stream_log):
                    print(f"  {COLOR_CYAN}📡 Stream log: {stream_log}{COLOR_RESET}")
                
                # Show CSV files for this instance
                if instance_id in self.handler.csv_files:
                    csv_info = self.handler.csv_files[instance_id]
                    print(f"  {COLOR_CYAN}📊 CSV files: {len(csv_info)} files{COLOR_RESET}")
                    for csv_file in csv_info:
                        print(f"    📊 {csv_file['filename']} ({csv_file['size']} bytes)")
            
            # CSV Summary
            total_csv_files = sum(len(files) for files in self.handler.csv_files.values())
            if total_csv_files > 0:
                print(f"\n{COLOR_BOLD}=== CSV Files Summary ==={COLOR_RESET}")
                print(f"{COLOR_CYAN}📊 Total CSV files collected: {total_csv_files}{COLOR_RESET}")
                print(f"{COLOR_CYAN}📁 CSV files location: {csv_dir}{COLOR_RESET}")
                
                if os.path.exists(csv_dir):
                    all_csv_files = [f for f in os.listdir(csv_dir) if f.endswith('.csv')]
                    for csv_file in all_csv_files:
                        csv_path = os.path.join(csv_dir, csv_file)
                        csv_size = os.path.getsize(csv_path)
                        print(f"  📊 {csv_file} ({csv_size} bytes)")
            else:
                print(f"\n{COLOR_YELLOW}⚠ No CSV files were collected{COLOR_RESET}")
            
            # Cleanup resources
            print(f"\n{COLOR_BOLD}=== Cleanup ==={COLOR_RESET}")
            for region_name, instance_ids in self.region_instances.items():
                self.aws_manager.terminate_instances(region_name, instance_ids)
                print(f"{COLOR_GREEN}✓ Terminated {len(instance_ids)} instances in {region_name}{COLOR_RESET}")
            
            # Wait a bit for instances to terminate before cleaning up security groups
            print(f"{COLOR_YELLOW}⏳ Waiting for instances to terminate before cleaning up security groups...{COLOR_RESET}")
            time.sleep(30)
            
            self.aws_manager.cleanup_security_groups()
            
            self.log_server.stop()
            print(f"{COLOR_GREEN}✓ Log server stopped{COLOR_RESET}")
            
            print(f"\n{COLOR_BOLD}{COLOR_MAGENTA}🎉 Coordinated BitTorrent Network Test Completed!{COLOR_RESET}")
            print(f"{COLOR_CYAN}⚙️  All instances completed setup in parallel{COLOR_RESET}")
            print(f"{COLOR_BLUE}📥 {self.total_leecher_count} leechers started first with {LEECHER_START_INTERVAL_SECONDS}s intervals{COLOR_RESET}")
            print(f"{COLOR_GREEN}🌱 {self.total_seeder_count} seeders started in parallel after leechers{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_YELLOW}📁 All logs saved in: {LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
            if total_csv_files > 0:
                print(f"{COLOR_BOLD}{COLOR_CYAN}📊 {total_csv_files} CSV files saved in: {LOGS_DIR}/{self.run_name}/csv_files/{COLOR_RESET}")
            
            return self.handler.completion_status
            
        except KeyboardInterrupt:
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