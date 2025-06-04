#!/usr/bin/env python3
"""
Enhanced BitTorrent Network Deployment Script with Two-Phase Deployment and Branch Distribution
- Phase 1: Deploy all instances first and wait for them to be ready
- Phase 2: Deploy leechers after instances are serving
- Uses SCP to collect stripped project directories from BitTorrent clients
- Supports proportional distribution of different BitTorrent branches among leechers
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
TORRENT_FILENAME = "thetorrentfile.torrent"
SEED_FILENAME = "seed_file"
SSH_KEY_PATH = "/tmp/bittorrent_key"
STRIPPED_DIR_NAME = "stripped_project"

# API Endpoints
LOGS_ENDPOINT = '/logs'
STREAM_ENDPOINT = '/stream'
COMPLETION_ENDPOINT = '/completion'
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
INSTALL_PACKAGES_CMD = "apt-get install -y git python3 python3-pip python3-dev python3-venv build-essential libssl-dev libffi-dev openssh-server"
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
import subprocess
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

    def get_propshare_branch(self):
        return self.data['bittorrent'].get('propshare_branch', 'feat/proportional-share')
    
    def get_baseline_branch(self):
        return self.data['bittorrent'].get('baseline_branch', 'baseline-logging')
    
    def get_proportion_propshare(self):
        return self.data['bittorrent'].get('proportion_propshare', 0.5)

class LogHandler(BaseHTTPRequestHandler):
    logs_dir = LOGS_DIR
    completion_status = {}
    instance_status = {}
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
    STATUS_COLLECTING_FILES = "collecting_files"
    STATUS_COMPLETED = "completed"
    STATUS_ERROR = "error"
    
    @classmethod
    def set_run_name(cls, run_name):
        cls.run_name = run_name
        run_dir = os.path.join(cls.logs_dir, run_name)
        files_dir = os.path.join(run_dir, "project_files")
        os.makedirs(run_dir, exist_ok=True)
        os.makedirs(files_dir, exist_ok=True)
    
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
                    print(f"    {status_emoji} {instance_id}: {status_text}")
            
            if roles['leechers']:
                print(f"  {COLOR_BLUE}📥 Leechers:{COLOR_RESET}")
                for instance_id, info in roles['leechers']:
                    status_emoji, status_text = cls._get_status_display(info['status'], info.get('progress'))
                    branch_indicator = ""
                    if "propshare" in instance_id:
                        branch_indicator = f" {COLOR_GREEN}[PS]{COLOR_RESET}"
                    elif "baseline" in instance_id:
                        branch_indicator = f" {COLOR_BLUE}[BL]{COLOR_RESET}"
                    print(f"    {status_emoji} {instance_id}: {status_text}{branch_indicator}")
        
        # Summary
        total_instances = len(cls.instance_status)
        completed_count = len([i for i in cls.instance_status.values() if i['status'] == cls.STATUS_COMPLETED])
        running_count = len([i for i in cls.instance_status.values() if i['status'] == cls.STATUS_RUNNING])
        
        print(f"\n{COLOR_BOLD}📊 Summary:{COLOR_RESET}")
        print(f"  Total: {total_instances} | Running: {running_count} | Completed: {completed_count}")
        print(f"  {COLOR_GREEN}[PS] = Proportional Share{COLOR_RESET} | {COLOR_BLUE}[BL] = Baseline{COLOR_RESET}")
    
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
            cls.STATUS_COLLECTING_FILES: ("📊", "Collecting project files"),
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
            
            # Add branch name to log filename for leechers
            log_filename = f"{instance_id}.log"
            if 'leecher' in instance_id:
                if 'propshare' in instance_id:
                    log_filename = f"{instance_id}-feat-proportional-share.log"
                elif 'baseline' in instance_id:
                    log_filename = f"{instance_id}-baseline-logging.log"
            
            log_path = os.path.join(run_dir, log_filename)
            with open(log_path, 'wb') as f:
                f.write(log_data)
            print(f"{COLOR_GREEN}📝 Final log received from {instance_id} -> {log_filename}{COLOR_RESET}")
        
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
                
                # Add branch name to streaming log filename for leechers
                log_filename = f"{instance_id}_stream.log"
                if 'leecher' in instance_id:
                    if 'propshare' in instance_id:
                        log_filename = f"{instance_id}-feat-proportional-share_stream.log"
                    elif 'baseline' in instance_id:
                        log_filename = f"{instance_id}-baseline-logging_stream.log"
                
                log_path = os.path.join(run_dir, log_filename)
                
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
        elif 'collecting project files' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_COLLECTING_FILES)
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

class SSHKeyManager:
    """Manages SSH key generation and distribution for SCP transfers"""
    
    def __init__(self, key_path=SSH_KEY_PATH):
        self.key_path = key_path
        self.public_key_path = f"{key_path}.pub"
        self.generate_key_pair()
    
    def generate_key_pair(self):
        """Generate SSH key pair for instance communication"""
        if os.path.exists(self.key_path):
            os.remove(self.key_path)
        if os.path.exists(self.public_key_path):
            os.remove(self.public_key_path)
        
        try:
            subprocess.run([
                'ssh-keygen', '-t', 'rsa', '-b', '2048', '-f', self.key_path, 
                '-N', '', '-C', 'bittorrent-controller'
            ], check=True, capture_output=True)
            print(f"{COLOR_GREEN}✓ SSH key pair generated: {self.key_path}{COLOR_RESET}")
        except subprocess.CalledProcessError as e:
            print(f"{COLOR_RED}✗ Failed to generate SSH key pair: {e}{COLOR_RESET}")
            raise
    
    def get_public_key(self):
        """Get the public key content"""
        with open(self.public_key_path, 'r') as f:
            return f.read().strip()
    
    def cleanup(self):
        """Clean up SSH key files"""
        for key_file in [self.key_path, self.public_key_path]:
            if os.path.exists(key_file):
                os.remove(key_file)
                print(f"{COLOR_GREEN}✓ Removed SSH key: {key_file}{COLOR_RESET}")

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
    
    def determine_leecher_branch(self, region_config, leecher_index, proportion_propshare, propshare_branch, baseline_branch):
        """
        Determine which branch a specific leecher should use based on proportion
        
        Args:
            region_config: Region configuration with leecher count
            leecher_index: Index of the current leecher (0-based)
            proportion_propshare: Float between 0-1 for proportion using propshare
            propshare_branch: Name of the proportional share branch
            baseline_branch: Name of the baseline branch
        
        Returns:
            str: Branch name to use for this leecher
        """
        total_leechers = region_config['leechers']
        propshare_count = round(total_leechers * proportion_propshare)
        
        # First propshare_count leechers use propshare branch, rest use baseline
        if leecher_index < propshare_count:
            return propshare_branch
        else:
            return baseline_branch
    
    def generate_user_data(self, github_repo, torrent_url, seed_fileurl, role, controller_ip, controller_port, instance_id, public_key, branch="vplex-final"):
        script = f"""#!/bin/bash
set -x
exec > >(tee -a /tmp/startup.log) 2>&1

send_log() {{
    curl -s -X POST -H "Content-Type: application/json" -d '{{"instance_id": "{instance_id}", "log_chunk": "'"$1"'", "timestamp": '$(date +%s)'}}' http://{controller_ip}:{controller_port}{STREAM_ENDPOINT} || true
}}

strip_and_transfer_files() {{
    send_log "Collecting project files with 'torrent' in name..."
    
    # Create stripped directory
    STRIPPED_DIR="/tmp/{STRIPPED_DIR_NAME}"
    mkdir -p "$STRIPPED_DIR"
    
    # Change to project directory
    cd {BITTORRENT_PROJECT_DIR}
    
    # Remove the torrents folder from the repo if it exists
    if [ -d "torrents" ]; then
        rm -rf torrents
        send_log "Removed torrents folder from repository"
    fi
    
    # Find and copy files containing 'torrent' in their name
    find . -type f -name "*torrent*" -exec cp --parents {{}} "$STRIPPED_DIR/" \\; 2>/dev/null || true
    
    # Also copy any .csv files that might contain results
    find . -type f -name "*.csv" -exec cp --parents {{}} "$STRIPPED_DIR/" \\; 2>/dev/null || true
    
    # Create a summary of what we're transferring
    echo "=== Stripped Directory Contents ===" > "$STRIPPED_DIR/transfer_summary.txt"
    find "$STRIPPED_DIR" -type f >> "$STRIPPED_DIR/transfer_summary.txt"
    
    send_log "Files prepared for transfer: $(find "$STRIPPED_DIR" -type f | wc -l) files"
    
    # Transfer via SCP with retry logic
    MAX_RETRIES=3
    RETRY_COUNT=0
    
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        send_log "Attempting SCP transfer (attempt $((RETRY_COUNT + 1))/$MAX_RETRIES)..."
        
        if scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=30 -r "$STRIPPED_DIR" ubuntu@{controller_ip}:/tmp/{instance_id}_files/; then
            send_log "SCP transfer successful"
            break
        else
            RETRY_COUNT=$((RETRY_COUNT + 1))
            if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
                send_log "SCP transfer failed, retrying in 5 seconds..."
                sleep 5
            else
                send_log "SCP transfer failed after $MAX_RETRIES attempts"
            fi
        fi
    done
}}

cleanup() {{
    send_log "Instance {instance_id} shutting down"
    
    # Only transfer files for leechers (they download and generate results)
    if [ "{role}" == "{ROLE_LEECHER}" ]; then
        strip_and_transfer_files
    fi
    
    [ -f {LOG_FILE_PATH} ] && curl -X POST -F "instance_id={instance_id}" -F "logfile=@{LOG_FILE_PATH}" http://{controller_ip}:{controller_port}{LOGS_ENDPOINT} || true
    curl -X POST -H "Content-Type: application/json" -d '{{"instance_id": "{instance_id}", "status": "interrupted"}}' http://{controller_ip}:{controller_port}{COMPLETION_ENDPOINT} || true
}}

trap cleanup EXIT TERM INT

echo "=== Starting {instance_id} ({role}) ==="
send_log "Instance {instance_id} starting setup (Role: {role}, Branch: {branch})"

echo "=== System Update ==="
send_log "Starting system update..."
{UPDATE_CMD}
send_log "System update completed"

echo "=== Installing Packages ==="
send_log "Installing system packages..."
{INSTALL_PACKAGES_CMD} tree
send_log "System packages installation completed"

echo "=== SSH Setup ==="
send_log "Setting up SSH access..."
systemctl start ssh
systemctl enable ssh

# Set up SSH key for controller access
mkdir -p /home/ubuntu/.ssh
echo "{public_key}" >> /home/ubuntu/.ssh/authorized_keys
chmod 600 /home/ubuntu/.ssh/authorized_keys
chmod 700 /home/ubuntu/.ssh
chown -R ubuntu:ubuntu /home/ubuntu/.ssh
send_log "SSH access configured"

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
send_log "Cloning repository from {github_repo} (branch: {branch})"
git clone -b {branch} {github_repo} {BITTORRENT_PROJECT_DIR}
send_log "Repository cloned successfully from branch: {branch}"

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
send_log "BitTorrent environment configured - Role: {role}, Port: 6881, Branch: {branch}"

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

# Transfer files only for leechers
if [ "{role}" == "{ROLE_LEECHER}" ]; then
    strip_and_transfer_files
fi

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
        self.ssh_manager = SSHKeyManager()
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
                            # Show branch type in emergency log summary
                            branch_info = ""
                            if "feat-proportional-share" in file:
                                branch_info = f" {COLOR_GREEN}[feat/proportional-share]{COLOR_RESET}"
                            elif "baseline-logging" in file:
                                branch_info = f" {COLOR_BLUE}[baseline-logging]{COLOR_RESET}"
                            print(f"{COLOR_GREEN}📝 {file} ({file_size} bytes){branch_info}{COLOR_RESET}")
                
                # Show project files collected
                files_dir = os.path.join(run_dir, "project_files")
                if os.path.exists(files_dir):
                    project_dirs = [d for d in os.listdir(files_dir) if os.path.isdir(os.path.join(files_dir, d))]
                    if project_dirs:
                        print(f"\n{COLOR_BOLD}=== Project Files Collected ==={COLOR_RESET}")
                        for project_dir in project_dirs:
                            project_path = os.path.join(files_dir, project_dir)
                            file_count = len([f for f in os.listdir(project_path) if os.path.isfile(os.path.join(project_path, f))])
                            print(f"{COLOR_CYAN}📁 {project_dir} ({file_count} files){COLOR_RESET}")
                
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
            
            if self.ssh_manager:
                self.ssh_manager.cleanup()
                
        except Exception as e:
            print(f"{COLOR_RED}⚠ Error during instance cleanup: {e}{COLOR_RESET}")
        
        print(f"\n{COLOR_BOLD}{COLOR_YELLOW}🛑 Emergency cleanup completed{COLOR_RESET}")
        print(f"{COLOR_BOLD}{COLOR_BLUE}📁 Partial logs saved in: {LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
        if os.path.exists(os.path.join(LOGS_DIR, self.run_name, "project_files")):
            print(f"{COLOR_BOLD}{COLOR_CYAN}📁 Project files saved in: {LOGS_DIR}/{self.run_name}/project_files/{COLOR_RESET}")
    
    def _get_public_ip(self):
        response = requests.get(IP_API_URL)
        return response.text
    
    def _setup_scp_collection(self):
        """Set up directories for SCP file collection"""
        run_dir = os.path.join(LOGS_DIR, self.run_name)
        files_dir = os.path.join(run_dir, "project_files")
        os.makedirs(files_dir, exist_ok=True)
        
        # Create individual directories for each leecher instance (with branch tags)
        propshare_branch = self.config.get_propshare_branch()
        baseline_branch = self.config.get_baseline_branch()
        proportion_propshare = self.config.get_proportion_propshare()
        
        for region in self.config.get_regions():
            for i in range(region['leechers']):
                # Determine branch for this leecher
                total_leechers = region['leechers']
                propshare_count = round(total_leechers * proportion_propshare)
                
                if i < propshare_count:
                    branch_tag = "propshare"
                else:
                    branch_tag = "baseline"
                
                instance_id_with_branch = f"{region['name']}-{ROLE_LEECHER}-{i}-{branch_tag}"
                instance_dir = os.path.join("/tmp", f"{instance_id_with_branch}_files")
                os.makedirs(instance_dir, exist_ok=True)
        
        print(f"{COLOR_GREEN}✓ SCP collection directories prepared{COLOR_RESET}")
    
    def _collect_transferred_files(self):
        """Collect files that were transferred via SCP"""
        print(f"\n{COLOR_BOLD}=== Collecting Transferred Files ==={COLOR_RESET}")
        
        run_dir = os.path.join(LOGS_DIR, self.run_name)
        files_dir = os.path.join(run_dir, "project_files")
        
        propshare_branch = self.config.get_propshare_branch()
        baseline_branch = self.config.get_baseline_branch()
        proportion_propshare = self.config.get_proportion_propshare()
        
        total_files = 0
        for region in self.config.get_regions():
            for i in range(region['leechers']):
                # Determine branch for this leecher (same logic as deployment)
                total_leechers = region['leechers']
                propshare_count = round(total_leechers * proportion_propshare)
                
                if i < propshare_count:
                    branch_tag = "propshare"
                else:
                    branch_tag = "baseline"
                
                instance_id_with_branch = f"{region['name']}-{ROLE_LEECHER}-{i}-{branch_tag}"
                temp_dir = f"/tmp/{instance_id_with_branch}_files"
                
                if os.path.exists(temp_dir):
                    # Move to permanent location
                    final_dir = os.path.join(files_dir, instance_id_with_branch)
                    if not os.path.exists(final_dir):
                        subprocess.run(['mv', temp_dir, final_dir], check=False)
                        
                        # Count files
                        if os.path.exists(final_dir):
                            file_count = len([f for f in os.listdir(final_dir) if os.path.isfile(os.path.join(final_dir, f))])
                            total_files += file_count
                            print(f"{COLOR_GREEN}✓ Collected {file_count} files from {instance_id_with_branch}{COLOR_RESET}")
        
        print(f"{COLOR_CYAN}📁 Total files collected: {total_files}{COLOR_RESET}")
        return total_files
    
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
    
    def deploy_region(self, region_config, torrent_url, seed_fileurl, ami_id, public_key):
        """Deploy all instances (seeders and leechers) for this region with branch distribution"""
        region_name = region_config['name']
        instance_ids = []
        
        # Get branch configuration
        propshare_branch = self.config.get_propshare_branch()
        baseline_branch = self.config.get_baseline_branch()
        proportion_propshare = self.config.get_proportion_propshare()
        github_repo = self.config.get_bittorrent_config()['github_repo']
        
        # Create simple All-All security group for this region
        security_group_id, sg_error = self.aws_manager.create_simple_security_group(region_name)
        if sg_error:
            print(f"{COLOR_RED}✗ Failed to create security group in {region_name}: {sg_error}{COLOR_RESET}")
            return region_name, []
        
        print(f"{COLOR_GREEN}✓ Created All-All security group {security_group_id} in {region_name}{COLOR_RESET}")
        
        # Deploy seeders (always use vplex-final branch)
        for i in range(region_config['seeders']):
            instance_id = f"{region_name}-{ROLE_SEEDER}-{i}"
            user_data = self.aws_manager.generate_user_data(
                github_repo,
                torrent_url,
                seed_fileurl,
                ROLE_SEEDER,
                self.controller_ip,
                self.config.get_controller_port(),
                instance_id,
                public_key,
                branch="vplex-final"  # Seeders always use the main branch
            )
            
            ec2_id = self.aws_manager.launch_instance(region_name, user_data, ami_id, security_group_id)
            instance_ids.append(ec2_id)
        
        # Deploy leechers with branch distribution
        total_leechers = region_config['leechers']
        propshare_count = round(total_leechers * proportion_propshare)
        baseline_count = total_leechers - propshare_count
        
        print(f"{COLOR_CYAN}📊 Leecher branch distribution in {region_name}:{COLOR_RESET}")
        print(f"  {COLOR_GREEN}🔀 Proportional Share ({propshare_branch}): {propshare_count}/{total_leechers} leechers{COLOR_RESET}")
        print(f"  {COLOR_BLUE}📊 Baseline ({baseline_branch}): {baseline_count}/{total_leechers} leechers{COLOR_RESET}")
        
        for i in range(region_config['leechers']):
            # Determine which branch this leecher should use
            branch = self.aws_manager.determine_leecher_branch(
                region_config, i, proportion_propshare, propshare_branch, baseline_branch
            )
            
            instance_id = f"{region_name}-{ROLE_LEECHER}-{i}"
            branch_tag = "propshare" if branch == propshare_branch else "baseline"
            instance_id_with_branch = f"{region_name}-{ROLE_LEECHER}-{i}-{branch_tag}"
            
            user_data = self.aws_manager.generate_user_data(
                github_repo,
                torrent_url,
                seed_fileurl,
                ROLE_LEECHER,
                self.controller_ip,
                self.config.get_controller_port(),
                instance_id_with_branch,  # Include branch info in instance ID
                public_key,
                branch=branch  # Use the determined branch
            )
            
            ec2_id = self.aws_manager.launch_instance(region_name, user_data, ami_id, security_group_id)
            instance_ids.append(ec2_id)
            
            print(f"  {COLOR_CYAN}📥 {instance_id_with_branch}: using branch '{branch}'{COLOR_RESET}")
        
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
            
            branch_info = ""
            if "propshare" in leecher_id:
                branch_info = f" {COLOR_GREEN}[Propshare]{COLOR_RESET}"
            elif "baseline" in leecher_id:
                branch_info = f" {COLOR_BLUE}[Baseline]{COLOR_RESET}"
            
            print(f"{COLOR_BLUE}📥 Starting leecher {i+1}/{len(leecher_instances)}: {leecher_id}{branch_info}{COLOR_RESET}")
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
        
        print(f"{COLOR_BOLD}{COLOR_MAGENTA}🚀 Staggered startup complete! Leechers started first (both branches), then seeders in parallel.{COLOR_RESET}")
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
            print(f"{COLOR_BOLD}{COLOR_MAGENTA}🚀 Enhanced BitTorrent Network Deployment with Branch Distribution{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_YELLOW}📁 Run Name: {self.run_name}{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_BLUE}💾 Logs Directory: {LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_CYAN}📁 Project Files Directory: {LOGS_DIR}/{self.run_name}/project_files/{COLOR_RESET}")
            print(f"{COLOR_YELLOW}💡 Press Ctrl+C at any time for graceful cleanup{COLOR_RESET}")
            print(f"{COLOR_CYAN}⚙️  Phase 1: All instances complete setup in parallel{COLOR_RESET}")
            print(f"{COLOR_BLUE}📥 Phase 2: Start leechers first with staggered timing (proportional branch distribution){COLOR_RESET}")
            print(f"{COLOR_GREEN}🌱 Phase 3: Start seeders in parallel after leechers{COLOR_RESET}")
            print(f"{COLOR_MAGENTA}📁 Phase 4: SCP collect project files from leechers for branch comparison{COLOR_RESET}")
            
            # Look up AMIs FIRST - before using region_ami_map
            region_ami_map, ami_error = self._lookup_and_validate_amis()
            if ami_error:
                print(f"\n{COLOR_RED}💥 AMI validation failed: {ami_error}{COLOR_RESET}")
                return {}
            
            # Set up SCP collection
            self._setup_scp_collection()
            
            # Start log server
            self.handler = self.log_server.start()
            print(f"\n{COLOR_GREEN}🌐 Log server started on port {self.config.get_controller_port()}{COLOR_RESET}")
            print(f"{COLOR_GREEN}🌍 Controller IP: {self.controller_ip}{COLOR_RESET}")
            print(f"{COLOR_CYAN}🔑 SSH key generated for SCP transfers{COLOR_RESET}")
            
            # Get URLs
            torrent_url = self.config.get_bittorrent_config()['torrent_url']
            seed_fileurl = self.config.get_bittorrent_config()['seed_fileurl']
            github_repo = self.config.get_bittorrent_config()['github_repo']
            public_key = self.ssh_manager.get_public_key()
            
            # Get branch configuration for display
            propshare_branch = self.config.get_propshare_branch()
            baseline_branch = self.config.get_baseline_branch()
            proportion_propshare = self.config.get_proportion_propshare()
            
            print(f"\n{COLOR_BOLD}=== Configuration ==={COLOR_RESET}")
            print(f"📂 GitHub repo: {github_repo}")
            print(f"📁 Torrent URL: {torrent_url}")
            print(f"🌱 Seed file URL: {seed_fileurl}")
            print(f"🔒 Security: Creating All-All security groups (matching your setup)")
            print(f"📁 File Collection: SCP transfer of stripped project directories")
            print(f"🗑️  Strip Criteria: Files with 'torrent' in name, remove 'torrents' folder")
            
            print(f"\n{COLOR_BOLD}=== Branch Distribution Configuration ==={COLOR_RESET}")
            print(f"🔀 Proportional Share Branch: {COLOR_GREEN}{propshare_branch}{COLOR_RESET}")
            print(f"📊 Baseline Branch: {COLOR_BLUE}{baseline_branch}{COLOR_RESET}")
            print(f"📈 Proportion using Propshare: {COLOR_YELLOW}{proportion_propshare:.1%}{COLOR_RESET}")
            print(f"🌱 Seeders: Always use vplex-final branch")
            
            print(f"\n{COLOR_BOLD}=== Deployment Plan with Branch Distribution ==={COLOR_RESET}")
            for region in self.config.get_regions():
                ami_id = region_ami_map[region['name']]
                total_leechers = region['leechers']
                propshare_count = round(total_leechers * proportion_propshare)
                baseline_count = total_leechers - propshare_count
                
                print(f"🌍 Region {region['name']}: {COLOR_GREEN}{region['seeders']} seeders{COLOR_RESET}, {COLOR_BLUE}{total_leechers} leechers{COLOR_RESET} (AMI: {ami_id})")
                print(f"  📥 Leecher branches: {COLOR_GREEN}{propshare_count} propshare{COLOR_RESET}, {COLOR_BLUE}{baseline_count} baseline{COLOR_RESET}")
            
            print(f"📊 Total: {COLOR_GREEN}{self.total_seeder_count} seeders{COLOR_RESET}, {COLOR_BLUE}{self.total_leecher_count} leechers{COLOR_RESET} = {COLOR_BOLD}{self.total_instance_count} instances{COLOR_RESET}")
            print(f"{COLOR_YELLOW}🔄 Coordinated startup timing:{COLOR_RESET}")
            print(f"  • Setup completion wait: {SETUP_COMPLETION_WAIT_SECONDS}s")
            print(f"  • Leecher start interval: {LEECHER_START_INTERVAL_SECONDS}s (leechers start first)")
            print(f"  • Post-leechers wait: {POST_LEECHERS_WAIT_SECONDS}s")
            print(f"  • Seeders: All start in parallel (after leechers)")
            print(f"{COLOR_MAGENTA}📁 File Collection: Only leechers transfer project files via SCP{COLOR_RESET}")
            
            # =================================================================
            # DEPLOY ALL INSTANCES (SETUP ONLY)
            # =================================================================
            print(f"\n{COLOR_BOLD}{COLOR_CYAN}=== Deploying All Instances for Setup ==={COLOR_RESET}")
            print(f"⚙️  Deploying {self.total_instance_count} instances across {len(self.config.get_regions())} regions...")
            print(f"📦 All instances will complete setup in parallel, then wait for coordinated start signals")
            print(f"🔑 SSH access configured for SCP file transfers")
            print(f"🔀 Leechers will be deployed with proportional branch distribution")
            
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
                            ami_id,
                            public_key
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
            print("📥 Leechers started first with staggered timing (proportional branch distribution)")
            print("🌱 Seeders started in parallel after leechers were established")  
            print("📁 Project files will be automatically collected via SCP after BitTorrent completion")
            print(f"⏱️  Will wait up to {self.config.get_timeout_minutes()} minutes for all to complete...")
            print(f"📝 Logs being saved to: {COLOR_YELLOW}{LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
            print(f"📁 Project files being saved to: {COLOR_CYAN}{LOGS_DIR}/{self.run_name}/project_files/{COLOR_RESET}")
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
            
            # Wait a bit for SCP transfers to complete
            print(f"\n{COLOR_CYAN}⏳ Waiting for final SCP transfers to complete...{COLOR_RESET}")
            time.sleep(30)
            
            # Collect transferred files
            total_files = self._collect_transferred_files()
            
            # Process logs and project files
            print(f"\n{COLOR_BOLD}=== Results Summary ==={COLOR_RESET}")
            run_dir = os.path.join(LOGS_DIR, self.run_name)
            files_dir = os.path.join(run_dir, "project_files")
            
            for instance_id, status in self.handler.completion_status.items():
                # Determine log filenames based on instance type
                if 'leecher' in instance_id:
                    if 'propshare' in instance_id:
                        final_log_name = f"{instance_id}-feat-proportional-share.log"
                        stream_log_name = f"{instance_id}-feat-proportional-share_stream.log"
                    elif 'baseline' in instance_id:
                        final_log_name = f"{instance_id}-baseline-logging.log"  
                        stream_log_name = f"{instance_id}-baseline-logging_stream.log"
                    else:
                        final_log_name = f"{instance_id}.log"
                        stream_log_name = f"{instance_id}_stream.log"
                else:
                    # Seeders use standard naming
                    final_log_name = f"{instance_id}.log"
                    stream_log_name = f"{instance_id}_stream.log"
                
                final_log = os.path.join(run_dir, final_log_name)
                stream_log = os.path.join(run_dir, stream_log_name)
                
                if os.path.exists(final_log):
                    print(f"{COLOR_GREEN}✓ {instance_id}: {status} (final log: {final_log_name}){COLOR_RESET}")
                else:
                    print(f"{COLOR_RED}✗ {instance_id}: {status} (no final log){COLOR_RESET}")
                
                if os.path.exists(stream_log):
                    print(f"  {COLOR_CYAN}📡 Stream log: {stream_log_name}{COLOR_RESET}")
                
                # Show project files for this instance (leechers only)
                if 'leecher' in instance_id:
                    instance_files_dir = os.path.join(files_dir, instance_id)
                    if os.path.exists(instance_files_dir):
                        file_count = len([f for f in os.listdir(instance_files_dir) if os.path.isfile(os.path.join(instance_files_dir, f))])
                        branch_type = "feat/proportional-share" if "propshare" in instance_id else "baseline-logging"
                        branch_color = COLOR_GREEN if "propshare" in instance_id else COLOR_BLUE
                        print(f"  {COLOR_CYAN}📁 Project files: {file_count} files in {instance_files_dir} {branch_color}[{branch_type}]{COLOR_RESET}")
            
            # Project Files Summary
            if total_files > 0:
                print(f"\n{COLOR_BOLD}=== Project Files Summary ==={COLOR_RESET}")
                print(f"{COLOR_CYAN}📁 Total project files collected: {total_files}{COLOR_RESET}")
                print(f"{COLOR_CYAN}📂 Project files location: {files_dir}{COLOR_RESET}")
                print(f"{COLOR_YELLOW}🗑️  Files filtered: Only files with 'torrent' in name, 'torrents' folder removed{COLOR_RESET}")
                
                # Show detailed breakdown with branch information
                if os.path.exists(files_dir):
                    propshare_files = 0
                    baseline_files = 0
                    propshare_instances = 0
                    baseline_instances = 0
                    
                    for instance_dir in os.listdir(files_dir):
                        instance_path = os.path.join(files_dir, instance_dir)
                        if os.path.isdir(instance_path):
                            file_count = len([f for f in os.listdir(instance_path) if os.path.isfile(os.path.join(instance_path, f))])
                            branch_type = "feat/proportional-share" if "propshare" in instance_dir else "baseline-logging"
                            branch_color = COLOR_GREEN if "propshare" in instance_dir else COLOR_BLUE
                            
                            if "propshare" in instance_dir:
                                propshare_files += file_count
                                propshare_instances += 1
                            else:
                                baseline_files += file_count
                                baseline_instances += 1
                            
                            print(f"  📁 {instance_dir}: {file_count} files {branch_color}[{branch_type}]{COLOR_RESET}")
                    
                    print(f"\n{COLOR_BOLD}=== Branch Comparison Summary ==={COLOR_RESET}")
                    print(f"🔀 {COLOR_GREEN}feat/proportional-share: {propshare_instances} instances, {propshare_files} files{COLOR_RESET}")
                    print(f"📊 {COLOR_BLUE}baseline-logging: {baseline_instances} instances, {baseline_files} files{COLOR_RESET}")
                    print(f"🎯 {COLOR_BOLD}Ready for performance comparison analysis!{COLOR_RESET}")
            else:
                print(f"\n{COLOR_YELLOW}⚠ No project files were collected{COLOR_RESET}")
            
            # Cleanup resources
            print(f"\n{COLOR_BOLD}=== Cleanup ==={COLOR_RESET}")
            for region_name, instance_ids in self.region_instances.items():
                self.aws_manager.terminate_instances(region_name, instance_ids)
                print(f"{COLOR_GREEN}✓ Terminated {len(instance_ids)} instances in {region_name}{COLOR_RESET}")
            
            # Wait a bit for instances to terminate before cleaning up security groups
            print(f"{COLOR_YELLOW}⏳ Waiting for instances to terminate before cleaning up security groups...{COLOR_RESET}")
            time.sleep(30)
            
            self.aws_manager.cleanup_security_groups()
            self.ssh_manager.cleanup()
            
            self.log_server.stop()
            print(f"{COLOR_GREEN}✓ Log server stopped{COLOR_RESET}")
            print(f"{COLOR_GREEN}✓ SSH keys cleaned up{COLOR_RESET}")
            
            print(f"\n{COLOR_BOLD}{COLOR_MAGENTA}🎉 BitTorrent Network Test with Branch Comparison Completed!{COLOR_RESET}")
            print(f"{COLOR_CYAN}⚙️  All instances completed setup in parallel{COLOR_RESET}")
            print(f"{COLOR_BLUE}📥 {self.total_leecher_count} leechers started first with staggered timing and branch distribution{COLOR_RESET}")
            print(f"   {COLOR_GREEN}🔀 {proportion_propshare:.0%} used feat/proportional-share branch{COLOR_RESET}")
            print(f"   {COLOR_BLUE}📊 {(1-proportion_propshare):.0%} used baseline-logging branch{COLOR_RESET}")
            print(f"{COLOR_GREEN}🌱 {self.total_seeder_count} seeders started in parallel after leechers{COLOR_RESET}")
            print(f"{COLOR_MAGENTA}📁 Project files collected via SCP from both branch types{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_YELLOW}📝 All logs saved in: {LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
            print(f"{COLOR_CYAN}📊 Log files include branch names: *-feat-proportional-share.log, *-baseline-logging.log{COLOR_RESET}") 
            if total_files > 0:
                print(f"{COLOR_BOLD}{COLOR_CYAN}📁 {total_files} project files saved in: {LOGS_DIR}/{self.run_name}/project_files/{COLOR_RESET}")
                print(f"{COLOR_BOLD}🎯 Ready for feat/proportional-share vs baseline-logging performance comparison!{COLOR_RESET}")
            
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