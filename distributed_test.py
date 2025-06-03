def wait_for_completion(self, handler, timeout_minutes):
        """Wait for all instances to complete"""
        timeout = time.time() + (timeout_minutes * 60)
        
        while time.time() < timeout:
            if self.cleanup_in_progress:
                return False
            if len(handler.completion_status) >= self.total_instance_count:
                return True
            time.sleep(COMPLETION_CHECK_INTERVAL)
        
        return False#!/usr/bin/env python3
"""
Enhanced BitTorrent Network Deployment Script
Now includes CSV file collection from the BitTorrent client
"""

# Constants
# File Paths and Names
DEFAULT_CONFIG_PATH = "config.yaml"
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
    run_name = None
    last_display_time = 0
    
    # Status stages
    STATUS_STARTING = "starting"
    STATUS_UPDATING = "updating"
    STATUS_INSTALLING = "installing"
    STATUS_DOWNLOADING = "downloading"
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

# Function to upload CSV files to controller
upload_csv_files() {{
    echo "=== Searching for CSV files ==="
    send_log_update "Collecting CSV files from project directory..."
    
    CSV_COUNT=0
    
    # Search for CSV files in the project directory and subdirectories
    find {BITTORRENT_PROJECT_DIR} -name "*.csv" -type f | while read csv_file; do
        if [ -f "$csv_file" ]; then
            csv_filename=$(basename "$csv_file")
            csv_size=$(stat -f%z "$csv_file" 2>/dev/null || stat -c%s "$csv_file" 2>/dev/null || echo "unknown")
            
            echo "Found CSV file: $csv_file (size: $csv_size bytes)"
            send_log_update "Found CSV file: $csv_filename ($csv_size bytes)"
            
            # Upload the CSV file
            curl -X POST \\
                -F "instance_id={instance_id}" \\
                -F "csv_filename=$csv_filename" \\
                -F "csv_file=@$csv_file" \\
                http://{controller_ip}:{controller_port}{CSV_ENDPOINT} || true
            
            CSV_COUNT=$((CSV_COUNT + 1))
        fi
    done
    
    if [ $CSV_COUNT -eq 0 ]; then
        echo "No CSV files found in {BITTORRENT_PROJECT_DIR}"
        send_log_update "No CSV files found in project directory"
    else
        echo "Uploaded $CSV_COUNT CSV files"
        send_log_update "Successfully uploaded $CSV_COUNT CSV files"
    fi
}}

# Function to send final logs on exit
send_final_logs() {{
    echo "=== Sending emergency/final logs to controller ==="
    send_log_update "Instance {instance_id} is shutting down (potentially interrupted)"
    
    # Try to collect CSV files even during emergency shutdown
    upload_csv_files
    
    if [ -f {LOG_FILE_PATH} ]; then
        echo "Sending final BitTorrent logs..."
        curl -X POST -F "instance_id={instance_id}" -F "logfile=@{LOG_FILE_PATH}" http://{controller_ip}:{controller_port}{LOGS_ENDPOINT} || true
    else
        echo "Creating emergency log file..."
        cp /tmp/startup.log {LOG_FILE_PATH} 2>/dev/null || echo "Emergency log from {instance_id}" > {LOG_FILE_PATH}
        curl -X POST -F "instance_id={instance_id}" -F "logfile=@{LOG_FILE_PATH}" http://{controller_ip}:{controller_port}{LOGS_ENDPOINT} || true
    fi
    
    curl -X POST -H "Content-Type: application/json" -d '{{"instance_id": "{instance_id}", "status": "interrupted"}}' http://{controller_ip}:{controller_port}{COMPLETION_ENDPOINT} || true
}}

# Set up trap to send logs on any exit
trap 'send_final_logs' EXIT TERM INT

# Function to stream log file changes
start_log_streaming() {{
    {{
        tail -f /tmp/startup.log | while read line; do
            send_log_update "STARTUP: $line"
            sleep 0.5
        done &
        
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
send_log_update "System update completed"

echo "=== Network Configuration and Diagnostics ==="
send_log_update "Configuring network settings for BitTorrent..."

# Get public IP and network info
PUBLIC_IP=$(curl -s https://api.ipify.org || echo "unknown")
PRIVATE_IP=$(hostname -I | awk '{{print $1}}' || echo "unknown")

echo "Public IP: $PUBLIC_IP"
echo "Private IP: $PRIVATE_IP"
send_log_update "Network - Public IP: $PUBLIC_IP, Private IP: $PRIVATE_IP"

# Configure iptables to be more permissive for BitTorrent
echo "Configuring iptables for BitTorrent..."
iptables -F 2>/dev/null || true
iptables -X 2>/dev/null || true
iptables -t nat -F 2>/dev/null || true
iptables -t nat -X 2>/dev/null || true
iptables -P INPUT ACCEPT 2>/dev/null || true
iptables -P FORWARD ACCEPT 2>/dev/null || true
iptables -P OUTPUT ACCEPT 2>/dev/null || true

# Test network connectivity
echo "Testing network connectivity..."
ping -c 3 8.8.8.8 > /dev/null 2>&1 && echo "Internet connectivity: OK" || echo "Internet connectivity: FAILED"
curl -s http://{controller_ip}:{controller_port}/stream > /dev/null 2>&1 && echo "Controller connectivity: OK" || echo "Controller connectivity: FAILED"

# Test network connectivity and ports
echo "Testing network connectivity..."
ping -c 3 8.8.8.8 > /dev/null 2>&1 && echo "Internet connectivity: OK" || echo "Internet connectivity: FAILED"
curl -s http://{controller_ip}:{controller_port}/stream > /dev/null 2>&1 && echo "Controller connectivity: OK" || echo "Controller connectivity: FAILED"

# Test if we can bind to BitTorrent ports
echo "Testing port availability..."
netstat -tuln | grep -q ":6881 " && echo "Port 6881: Already in use" || echo "Port 6881: Available"

# Show current network configuration
echo "Network interface configuration:"
ip addr show | grep -E "(inet |UP|DOWN)" || ifconfig | grep -E "(inet |UP|DOWN)" || true

send_log_update "Network configuration completed - Public: $PUBLIC_IP, Private: $PRIVATE_IP"

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

echo "=== Installing Python Dependencies ==="
send_log_update "Starting Python dependencies installation..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt --verbose --timeout 300
PIP_EXIT_CODE=$?
echo "pip install completed with exit code: $PIP_EXIT_CODE"
send_log_update "Python dependencies installation completed"

if [ $PIP_EXIT_CODE -ne 0 ]; then
    echo "ERROR: pip install failed!"
    send_log_update "ERROR: pip install failed"
    exit 1
fi

# Create necessary directories
mkdir -p {TORRENT_TEMP_DIR}
mkdir -p {SEED_TEMP_DIR}

echo "=== Downloading torrent file ==="
send_log_update "Downloading torrent file..."
curl -L -o {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} {torrent_url}
CURL_EXIT_CODE=$?
echo "curl completed with exit code: $CURL_EXIT_CODE"
send_log_update "Torrent file download completed"

# Role-specific setup
if [ "{role}" == "{ROLE_SEEDER}" ]; then
    echo "=== Seeder Setup: Downloading actual file ==="
    send_log_update "Seeder downloading actual file for seeding..."
    curl -L -o {SEED_TEMP_DIR}/{SEED_FILENAME} {seed_fileurl}
    SEED_CURL_EXIT_CODE=$?
    echo "Seed file download completed with exit code: $SEED_CURL_EXIT_CODE"
    send_log_update "Seed file download completed"
    
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
export PUBLIC_IP="$PUBLIC_IP"
export PRIVATE_IP="$PRIVATE_IP"
echo "{instance_id}" > /tmp/instance_id.txt

# BitTorrent specific environment variables for better connectivity
export BITTORRENT_PORT=6881
export BITTORRENT_BIND_IP="0.0.0.0"
export BITTORRENT_ANNOUNCE_IP="$PUBLIC_IP"

echo "BitTorrent Environment:"
echo "  Role: {role}"
echo "  Port: $BITTORRENT_PORT"
echo "  Public IP: $PUBLIC_IP"
echo "  Private IP: $PRIVATE_IP"

send_log_update "BitTorrent environment configured - Role: {role}, Port: $BITTORRENT_PORT"

# Start log streaming in background
start_log_streaming

echo "=== Starting BitTorrent Client Immediately ==="
send_log_update "Starting BitTorrent client immediately after setup..."

if [ "{role}" == "{ROLE_SEEDER}" ]; then
    send_log_update "Starting BitTorrent client as SEEDER"
    echo "Command: python3 -m main -s {TORRENT_TEMP_DIR}/{TORRENT_FILENAME}"
    python3 -m main -s {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} > {LOG_FILE_PATH} 2>&1
else
    send_log_update "Starting BitTorrent client as LEECHER"
    echo "Command: python3 -m main {TORRENT_TEMP_DIR}/{TORRENT_FILENAME}"
    python3 -m main {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} > {LOG_FILE_PATH} 2>&1
fi

BITTORRENT_EXIT_CODE=$?
echo "BitTorrent client completed with exit code: $BITTORRENT_EXIT_CODE"
send_log_update "BitTorrent client finished"

echo "=== BitTorrent client finished ==="

# Stop log streaming
pkill -f "tail -f" 2>/dev/null || true

echo "=== Collecting CSV files from project directory ==="
send_log_update "Collecting CSV files from project directory..."
upload_csv_files

# Append startup log to main log for debugging
echo "" >> {LOG_FILE_PATH}
echo "=======================================" >> {LOG_FILE_PATH}
echo "=== STARTUP LOG ===" >> {LOG_FILE_PATH}
echo "=======================================" >> {LOG_FILE_PATH}
cat /tmp/startup.log >> {LOG_FILE_PATH}

echo "=== Sending final logs to controller ==="
send_log_update "Sending final logs to controller..."
curl -X POST -F "instance_id={instance_id}" -F "logfile=@{LOG_FILE_PATH}" http://{controller_ip}:{controller_port}{LOGS_ENDPOINT}

curl -X POST -H "Content-Type: application/json" -d '{{"instance_id": "{instance_id}", "status": "{STATUS_COMPLETE}"}}' http://{controller_ip}:{controller_port}{COMPLETION_ENDPOINT}

echo "=== Instance setup completed ==="
send_log_update "Instance setup completed, shutting down..."

# Remove the trap since we're exiting normally
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
        self.total_instance_count = 0
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
    
    def deploy_seeders_only(self, region_config, torrent_url, seed_fileurl, ami_id):
        """Deploy only seeders for this region"""
        region_name = region_config['name']
        instance_ids = []
        
        if region_config['seeders'] == 0:
            return region_name, []
        
        # Create simple All-All security group for this region (matching the image)
        security_group_id, sg_error = self.aws_manager.create_simple_security_group(region_name)
        if sg_error:
            print(f"{COLOR_RED}✗ Failed to create security group in {region_name}: {sg_error}{COLOR_RESET}")
            return region_name, []
        
        print(f"{COLOR_GREEN}✓ Created All-All security group {security_group_id} in {region_name}{COLOR_RESET}")
        
        # Deploy only seeders
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
        
        return region_name, instance_ids
    
    def deploy_leechers_only(self, region_config, torrent_url, seed_fileurl, ami_id):
        """Deploy only leechers for this region"""
        region_name = region_config['name']
        instance_ids = []
        
        if region_config['leechers'] == 0:
            return region_name, []
        
        # Use existing security group (should already be created during seeder phase)
        if region_name not in self.aws_manager.region_security_groups:
            # Fallback: create security group if not exists
            security_group_id, sg_error = self.aws_manager.create_simple_security_group(region_name)
            if sg_error:
                print(f"{COLOR_RED}✗ Failed to create security group in {region_name}: {sg_error}{COLOR_RESET}")
                return region_name, []
        else:
            security_group_id = self.aws_manager.region_security_groups[region_name]
        
        print(f"{COLOR_BLUE}📥 Deploying leechers in {region_name} using security group {security_group_id}{COLOR_RESET}")
        
        # Deploy only leechers
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
    
    def wait_for_all_seeders_ready(self, handler, timeout_minutes):
        """Wait for all seeders to reach STATUS_RUNNING"""
        print(f"\n{COLOR_BOLD}=== Waiting for All Seeders to be Ready ==={COLOR_RESET}")
        print(f"🌱 Waiting for {self.total_seeder_count} seeders to start BitTorrent...")
        print(f"⏱️  Timeout: {timeout_minutes} minutes")
        
        timeout = time.time() + (timeout_minutes * 60)
        
        while time.time() < timeout:
            if self.cleanup_in_progress:
                return False
            
            # Count running seeders
            running_seeders = 0
            total_seeders = 0
            
            for instance_id, status_info in handler.instance_status.items():
                if 'seeder' in instance_id:
                    total_seeders += 1
                    if status_info['status'] in [handler.STATUS_RUNNING, handler.STATUS_COMPLETED]:
                        running_seeders += 1
            
            # Update display
            if total_seeders > 0:
                print(f"\r🌱 Seeders ready: {running_seeders}/{total_seeders} ({(running_seeders/total_seeders)*100:.1f}%)", end='', flush=True)
            
            # Check if all seeders are ready
            if running_seeders >= self.total_seeder_count and running_seeders > 0:
                print(f"\n{COLOR_GREEN}✅ All {running_seeders} seeders are ready and running BitTorrent!{COLOR_RESET}")
                print(f"{COLOR_CYAN}⏳ Waiting 30 seconds for seeders to fully establish connections...{COLOR_RESET}")
                time.sleep(30)  # Buffer time for seeders to be fully operational
                return True
            
            time.sleep(5)  # Check every 5 seconds
        
        print(f"\n{COLOR_YELLOW}⚠ Timeout: Only {running_seeders}/{self.total_seeder_count} seeders ready{COLOR_RESET}")
        return False
    
    def run(self):
        try:
            print(f"{COLOR_BOLD}{COLOR_MAGENTA}🚀 Enhanced BitTorrent Network Deployment with CSV Collection{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_YELLOW}📁 Run Name: {self.run_name}{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_BLUE}💾 Logs Directory: {LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_CYAN}📊 CSV Files Directory: {LOGS_DIR}/{self.run_name}/csv_files/{COLOR_RESET}")
            print(f"{COLOR_YELLOW}💡 Press Ctrl+C at any time for graceful cleanup{COLOR_RESET}")
            print(f"{COLOR_GREEN}🌱 Phase 1: Deploy seeders first and wait for them to be ready{COLOR_RESET}")
            print(f"{COLOR_BLUE}📥 Phase 2: Deploy leechers after seeders are serving{COLOR_RESET}")
            
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
            print(f"{COLOR_YELLOW}🔄 Two-phase deployment: Seeders first, then leechers{COLOR_RESET}")
            
            # =================================================================
            # PHASE 1: DEPLOY ALL SEEDERS FIRST
            # =================================================================
            print(f"\n{COLOR_BOLD}{COLOR_GREEN}=== Phase 1: Deploying All Seeders ==={COLOR_RESET}")
            print(f"🌱 Deploying {self.total_seeder_count} seeders across {len(self.config.get_regions())} regions...")
            
            seeder_futures = []
            with ThreadPoolExecutor() as executor:
                for region in self.config.get_regions():
                    if region['seeders'] > 0:  # Only deploy if there are seeders
                        ami_id = region_ami_map[region['name']]
                        seeder_futures.append(
                            executor.submit(
                                self.deploy_seeders_only,
                                region,
                                torrent_url,
                                seed_fileurl,
                                ami_id
                            )
                        )
                
                # Collect seeder instance IDs
                for future in seeder_futures:
                    if self.cleanup_in_progress:
                        break
                    region_name, seeder_instance_ids = future.result()
                    if region_name not in self.region_instances:
                        self.region_instances[region_name] = []
                    self.region_instances[region_name].extend(seeder_instance_ids)
                    if seeder_instance_ids:
                        print(f"{COLOR_GREEN}✓ Launched {len(seeder_instance_ids)} seeders in {region_name}{COLOR_RESET}")
            
            if self.cleanup_in_progress:
                return {}
            
            if self.total_seeder_count > 0:
                print(f"{COLOR_GREEN}✅ Phase 1 Complete: All {self.total_seeder_count} seeders deployed{COLOR_RESET}")
                
                # Wait for all seeders to be ready
                seeders_ready = self.wait_for_all_seeders_ready(self.handler, 
                                                             max(10, self.config.get_timeout_minutes() // 2))
                
                if not seeders_ready:
                    print(f"{COLOR_RED}💥 Phase 1 Failed: Seeders not ready in time{COLOR_RESET}")
                    if not self.cleanup_in_progress:
                        self._emergency_cleanup()
                    return {}
                
                print(f"{COLOR_GREEN}🎉 Phase 1 Success: All seeders are ready and serving!{COLOR_RESET}")
            else:
                print(f"{COLOR_YELLOW}⚠ No seeders to deploy, proceeding to leechers...{COLOR_RESET}")
            
            # =================================================================
            # PHASE 2: DEPLOY ALL LEECHERS 
            # =================================================================
            print(f"\n{COLOR_BOLD}{COLOR_BLUE}=== Phase 2: Deploying All Leechers ==={COLOR_RESET}")
            print(f"📥 Deploying {self.total_leecher_count} leechers across {len(self.config.get_regions())} regions...")
            print(f"🌱 Leechers will connect to {self.total_seeder_count} ready seeders")
            
            leecher_futures = []
            with ThreadPoolExecutor() as executor:
                for region in self.config.get_regions():
                    if region['leechers'] > 0:  # Only deploy if there are leechers
                        ami_id = region_ami_map[region['name']]
                        leecher_futures.append(
                            executor.submit(
                                self.deploy_leechers_only,
                                region,
                                torrent_url,
                                seed_fileurl,
                                ami_id
                            )
                        )
                
                # Collect leecher instance IDs
                for future in leecher_futures:
                    if self.cleanup_in_progress:
                        break
                    region_name, leecher_instance_ids = future.result()
                    if region_name not in self.region_instances:
                        self.region_instances[region_name] = []
                    self.region_instances[region_name].extend(leecher_instance_ids)
                    if leecher_instance_ids:
                        print(f"{COLOR_BLUE}✓ Launched {len(leecher_instance_ids)} leechers in {region_name}{COLOR_RESET}")
            
            if self.cleanup_in_progress:
                return {}
            
            if self.total_leecher_count > 0:
                print(f"{COLOR_BLUE}✅ Phase 2 Complete: All {self.total_leecher_count} leechers deployed{COLOR_RESET}")
            else:
                print(f"{COLOR_YELLOW}⚠ No leechers to deploy{COLOR_RESET}")
            
            print(f"{COLOR_BOLD}{COLOR_MAGENTA}🚀 Both phases complete! Total: {self.total_instance_count} instances running{COLOR_RESET}")
            
            # Wait for completion
            print(f"\n{COLOR_BOLD}=== Live Status Dashboard ==={COLOR_RESET}")
            print("🌱 Seeders are ready and serving")
            print("📥 Leechers are now downloading from established seeders")  
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
            
            print(f"\n{COLOR_BOLD}{COLOR_MAGENTA}🎉 Two-Phase BitTorrent Network Test Completed!{COLOR_RESET}")
            print(f"{COLOR_GREEN}🌱 Phase 1: {self.total_seeder_count} seeders deployed and ready{COLOR_RESET}")
            print(f"{COLOR_BLUE}📥 Phase 2: {self.total_leecher_count} leechers deployed after seeders ready{COLOR_RESET}")
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