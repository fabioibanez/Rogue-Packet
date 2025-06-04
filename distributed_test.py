#!/usr/bin/env python3
"""
Optimized BitTorrent Network Deployment Script with Custom AMI Creation
- Creates custom AMIs with pre-installed dependencies for ultra-fast deployment
- Dramatically reduces instance setup time from minutes to seconds
- Includes AMI creation, caching, and automated updates
"""

# Timing Constants for Coordinated Startup
SETUP_COMPLETION_WAIT_SECONDS = 10
LEECHER_START_INTERVAL_SECONDS = 5
POST_LEECHERS_WAIT_SECONDS = 10

# Constants
LOGS_DIR = "logs"
TORRENT_TEMP_DIR = "/tmp/torrents"
SEED_TEMP_DIR = "/tmp/seed"
BITTORRENT_PROJECT_DIR = "/tmp/bittorrent-project"
LOG_FILE_PATH = "/tmp/bittorrent.log"
TORRENT_FILENAME = "thetorrentfile.torrent"
SEED_FILENAME = "seed_file"

# AMI Constants
CUSTOM_AMI_NAME_PREFIX = "bittorrent-optimized"
AMI_DESCRIPTION = "BitTorrent deployment AMI with pre-installed dependencies"
AMI_CACHE_FILE = "ami_cache.json"

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
AMI_BUILD_INSTANCE_TYPE = "t3.medium"  # Faster for building
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
AMI_CREATION_TIMEOUT_MINUTES = 20

# Installation Commands
UPDATE_CMD = "apt-get update"
INSTALL_PACKAGES_CMD = "apt-get install -y git python3 python3-pip python3-dev python3-venv build-essential libssl-dev libffi-dev tree curl"
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
import hashlib
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

class AMICache:
    """Manages custom AMI caching and creation"""
    
    def __init__(self, cache_file=AMI_CACHE_FILE):
        self.cache_file = cache_file
        self.cache = self._load_cache()
    
    def _load_cache(self):
        """Load AMI cache from file"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_cache(self):
        """Save AMI cache to file"""
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f, indent=2)
    
    def get_config_hash(self, github_repo, requirements_content=None):
        """Generate hash of configuration for cache key"""
        config_str = f"{github_repo}"
        if requirements_content:
            config_str += requirements_content
        return hashlib.md5(config_str.encode()).hexdigest()[:12]
    
    def get_cached_ami(self, region, config_hash):
        """Get cached AMI ID for region and config"""
        cache_key = f"{region}_{config_hash}"
        return self.cache.get(cache_key)
    
    def cache_ami(self, region, config_hash, ami_id, ami_name):
        """Cache AMI information"""
        cache_key = f"{region}_{config_hash}"
        self.cache[cache_key] = {
            'ami_id': ami_id,
            'ami_name': ami_name,
            'created': datetime.now().isoformat(),
            'region': region,
            'config_hash': config_hash
        }
        self._save_cache()
    
    def list_cached_amis(self):
        """List all cached AMIs"""
        return list(self.cache.values())

# [Previous LogHandler class remains the same - keeping it for brevity]
class LogHandler(BaseHTTPRequestHandler):
    logs_dir = LOGS_DIR
    completion_status = {}
    instance_status = {}
    csv_files = {}
    setup_completions = {}
    start_signals = {}
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
        cls.instance_status[instance_id] = {
            'status': status,
            'progress': progress,
            'message': message or '',
            'timestamp': time.time()
        }
        
        current_time = time.time()
        if current_time - cls.last_display_time > 1.0:
            cls.display_status_dashboard()
            cls.last_display_time = current_time
    
    @classmethod
    def display_status_dashboard(cls):
        print('\033[2J\033[H', end='')
        
        print(f"{COLOR_BOLD}{COLOR_MAGENTA}🚀 BitTorrent Network Status Dashboard{COLOR_RESET}")
        print(f"{COLOR_BOLD}{COLOR_YELLOW}📁 Run: {cls.run_name}{COLOR_RESET}")
        print("=" * 80)
        
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
        
        total_instances = len(cls.instance_status)
        completed_count = len([i for i in cls.instance_status.values() if i['status'] == cls.STATUS_COMPLETED])
        running_count = len([i for i in cls.instance_status.values() if i['status'] == cls.STATUS_RUNNING])
        csv_count = len(cls.csv_files)
        
        print(f"\n{COLOR_BOLD}📊 Summary:{COLOR_RESET}")
        print(f"  Total: {total_instances} | Running: {running_count} | Completed: {completed_count} | CSV Files: {csv_count}")
    
    @classmethod
    def _get_csv_info(cls, instance_id):
        if instance_id in cls.csv_files:
            csv_count = len(cls.csv_files[instance_id])
            return f" {COLOR_CYAN}[{csv_count} CSV]{COLOR_RESET}"
        return ""
    
    @classmethod 
    def _get_status_display(cls, status, progress=None):
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
            run_dir = os.path.join(self.logs_dir, self.run_name)
            csv_dir = os.path.join(run_dir, "csv_files")
            os.makedirs(csv_dir, exist_ok=True)
            
            csv_path = os.path.join(csv_dir, f"{instance_id}_{csv_filename}")
            with open(csv_path, 'wb') as f:
                f.write(csv_data)
            
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
        from urllib.parse import urlparse, parse_qs
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)
        instance_id = query_params.get('instance_id', [None])[0]
        
        if instance_id:
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
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode())
            instance_id = data.get('instance_id')
            log_chunk = data.get('log_chunk', '').strip()
            timestamp = data.get('timestamp', time.time())
            
            if instance_id and log_chunk:
                run_dir = os.path.join(self.logs_dir, self.run_name)
                os.makedirs(run_dir, exist_ok=True)
                log_path = os.path.join(run_dir, f"{instance_id}_stream.log")
                
                with open(log_path, 'a') as f:
                    f.write(f"[{datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')}] {log_chunk}\n")
                
                self._parse_log_for_status(instance_id, log_chunk)
                
        except json.JSONDecodeError:
            pass
        
        self.send_response(HTTP_OK)
        self.end_headers()
    
    def _parse_log_for_status(self, instance_id, log_chunk):
        log_lower = log_chunk.lower()
        is_seeder = 'seeder' in instance_id
        
        if 'starting setup' in log_lower:
            self.update_instance_status(instance_id, self.STATUS_STARTING)
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
        import re
        
        percent_match = re.search(r'(\d+(?:\.\d+)?)\s*%', log_chunk)
        if percent_match:
            return float(percent_match.group(1))
        
        return None
    
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

class OptimizedAWSManager:
    def __init__(self, aws_config):
        self.aws_config = aws_config
        self.region_clients = {}
        self.region_security_groups = {}
        self.ami_cache = AMICache()
    
    def get_ec2_client(self, region):
        if region not in self.region_clients:
            self.region_clients[region] = boto3.client(
                EC2_SERVICE_NAME,
                region_name=region,
            )
        return self.region_clients[region]
    
    def create_simple_security_group(self, region):
        if region in self.region_security_groups:
            return self.region_security_groups[region], None
            
        try:
            ec2_client = self.get_ec2_client(region)
            
            group_name = f"bittorrent-all-{int(time.time())}"
            group_description = "All traffic allowed - BitTorrent testing"
            
            response = ec2_client.create_security_group(
                GroupName=group_name,
                Description=group_description
            )
            
            security_group_id = response['GroupId']
            
            ec2_client.authorize_security_group_ingress(
                GroupId=security_group_id,
                IpPermissions=[
                    {
                        'IpProtocol': '-1',
                        'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                    }
                ]
            )
            
            try:
                sg_info = ec2_client.describe_security_groups(GroupIds=[security_group_id])
                default_egress = sg_info['SecurityGroups'][0]['IpPermissionsEgress']
                
                if default_egress:
                    ec2_client.revoke_security_group_egress(
                        GroupId=security_group_id,
                        IpPermissions=default_egress
                    )
            except Exception:
                pass
            
            ec2_client.authorize_security_group_egress(
                GroupId=security_group_id,
                IpPermissions=[
                    {
                        'IpProtocol': '-1',
                        'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                    }
                ]
            )
            
            self.region_security_groups[region] = security_group_id
            return security_group_id, None
            
        except Exception as e:
            return None, f"Failed to create security group in {region}: {str(e)}"
    
    def cleanup_security_groups(self):
        for region, sg_id in self.region_security_groups.items():
            try:
                ec2_client = self.get_ec2_client(region)
                ec2_client.delete_security_group(GroupId=sg_id)
                print(f"{COLOR_GREEN}✓ Deleted security group {sg_id} in {region}{COLOR_RESET}")
            except Exception as e:
                print(f"{COLOR_YELLOW}⚠ Could not delete security group {sg_id} in {region}: {e}{COLOR_RESET}")
    
    def get_latest_ubuntu_ami(self, region):
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
            
            return latest_ami['ImageId'], None
            
        except Exception as e:
            return None, f"Failed to lookup AMI in {region}: {str(e)}"
    
    def create_ami_build_script(self, github_repo):
        """Generate script for building optimized AMI"""
        return f"""#!/bin/bash
set -ex

echo "=== Starting AMI Build Process ==="
echo "AMI build started at $(date)"

echo "=== System Update ==="
{UPDATE_CMD}

echo "=== Installing System Packages ==="
{INSTALL_PACKAGES_CMD}

echo "=== Installing Python Dependencies ==="
# Clone repo to get requirements.txt
mkdir -p /tmp/build
cd /tmp/build
git clone -b vplex-hopeful {github_repo} repo
cd repo

# Install Python dependencies globally for faster startup
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt --timeout 300

echo "=== Cleaning Up Build Artifacts ==="
cd /
rm -rf /tmp/build

echo "=== Network Optimization ==="
# Pre-configure network settings
echo 'net.core.rmem_max = 16777216' >> /etc/sysctl.conf
echo 'net.core.wmem_max = 16777216' >> /etc/sysctl.conf
echo 'net.ipv4.tcp_rmem = 4096 87380 16777216' >> /etc/sysctl.conf
echo 'net.ipv4.tcp_wmem = 4096 65536 16777216' >> /etc/sysctl.conf

echo "=== AMI Build Complete ==="
echo "AMI build completed at $(date)"
echo "Ready for instance deployment"
"""
    
    def create_custom_ami(self, region, github_repo, force_rebuild=False):
        """Create or retrieve cached custom AMI"""
        print(f"\n{COLOR_BOLD}=== Custom AMI Management for {region} ==={COLOR_RESET}")
        
        # Generate config hash for caching
        config_hash = self.ami_cache.get_config_hash(github_repo)
        
        # Check cache first
        if not force_rebuild:
            cached_ami = self.ami_cache.get_cached_ami(region, config_hash)
            if cached_ami:
                ami_id = cached_ami['ami_id']
                
                # Verify AMI still exists
                try:
                    ec2_client = self.get_ec2_client(region)
                    response = ec2_client.describe_images(ImageIds=[ami_id])
                    
                    if response['Images'] and response['Images'][0]['State'] == 'available':
                        print(f"{COLOR_GREEN}✓ Using cached AMI: {ami_id}{COLOR_RESET}")
                        print(f"  Created: {cached_ami['created']}")
                        print(f"  Name: {cached_ami['ami_name']}")
                        return ami_id, None
                    else:
                        print(f"{COLOR_YELLOW}⚠ Cached AMI {ami_id} no longer available, rebuilding...{COLOR_RESET}")
                except Exception as e:
                    print(f"{COLOR_YELLOW}⚠ Error checking cached AMI: {e}, rebuilding...{COLOR_RESET}")
        
        print(f"{COLOR_CYAN}🔨 Building new optimized AMI in {region}...{COLOR_RESET}")
        
        try:
            ec2_client = self.get_ec2_client(region)
            
            # Get base Ubuntu AMI
            base_ami_id, error = self.get_latest_ubuntu_ami(region)
            if error:
                return None, error
            
            print(f"📦 Base AMI: {base_ami_id}")
            
            # Create security group for build instance
            sg_id, sg_error = self.create_simple_security_group(region)
            if sg_error:
                return None, sg_error
            
            # Generate build script
            build_script = self.create_ami_build_script(github_repo)
            user_data = base64.b64encode(build_script.encode()).decode()
            
            # Launch build instance
            print(f"🚀 Launching build instance...")
            response = ec2_client.run_instances(
                ImageId=base_ami_id,
                InstanceType=AMI_BUILD_INSTANCE_TYPE,
                MinCount=1,
                MaxCount=1,
                UserData=user_data,
                SecurityGroupIds=[sg_id]
            )
            
            build_instance_id = response['Instances'][0]['InstanceId']
            print(f"🔧 Build instance: {build_instance_id}")
            
            # Wait for instance to be running
            print(f"⏳ Waiting for build instance to start...")
            waiter = ec2_client.get_waiter('instance_running')
            waiter.wait(InstanceIds=[build_instance_id])
            
            # Wait additional time for setup to complete
            print(f"⏳ Waiting for setup to complete (this may take 5-10 minutes)...")
            
            # More sophisticated waiting - check for completion signals
            max_wait_time = AMI_CREATION_TIMEOUT_MINUTES * 60
            start_time = time.time()
            
            while time.time() - start_time < max_wait_time:
                try:
                    # Get instance console output to check for completion
                    output_response = ec2_client.get_console_output(InstanceId=build_instance_id)
                    console_output = output_response.get('Output', '')
                    
                    if 'AMI Build Complete' in console_output:
                        print(f"{COLOR_GREEN}✓ Build process completed!{COLOR_RESET}")
                        break
                    elif 'error' in console_output.lower() or 'failed' in console_output.lower():
                        print(f"{COLOR_RED}✗ Build process failed{COLOR_RESET}")
                        break
                        
                except Exception:
                    pass  # Console output might not be available yet
                
                print(f"🔄 Build in progress... ({int((time.time() - start_time) / 60)}m elapsed)")
                time.sleep(30)
            
            # Additional wait to ensure all processes complete
            print(f"⏳ Final wait to ensure all processes complete...")
            time.sleep(60)
            
            # Stop the instance
            print(f"🛑 Stopping build instance...")
            ec2_client.stop_instances(InstanceIds=[build_instance_id])
            
            waiter = ec2_client.get_waiter('instance_stopped')
            waiter.wait(InstanceIds=[build_instance_id])
            
            # Create AMI
            ami_name = f"{CUSTOM_AMI_NAME_PREFIX}-{config_hash}-{int(time.time())}"
            print(f"📸 Creating AMI: {ami_name}")
            
            ami_response = ec2_client.create_image(
                InstanceId=build_instance_id,
                Name=ami_name,
                Description=f"{AMI_DESCRIPTION} (Config: {config_hash})",
                NoReboot=True
            )
            
            ami_id = ami_response['ImageId']
            print(f"🎯 AMI ID: {ami_id}")
            
            # Wait for AMI to be available
            print(f"⏳ Waiting for AMI to become available...")
            waiter = ec2_client.get_waiter('image_available')
            waiter.wait(ImageIds=[ami_id])
            
            # Terminate build instance
            print(f"🗑️ Cleaning up build instance...")
            ec2_client.terminate_instances(InstanceIds=[build_instance_id])
            
            # Cache the AMI
            self.ami_cache.cache_ami(region, config_hash, ami_id, ami_name)
            
            print(f"{COLOR_GREEN}✅ Custom AMI created successfully: {ami_id}{COLOR_RESET}")
            return ami_id, None
            
        except Exception as e:
            return None, f"Failed to create custom AMI in {region}: {str(e)}"
    
    def generate_optimized_user_data(self, github_repo, torrent_url, seed_fileurl, role, controller_ip, controller_port, instance_id):
        """Generate optimized user data for fast deployment"""
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

echo "=== FAST STARTUP: {instance_id} ({role}) ==="
send_log "OPTIMIZED Instance {instance_id} starting fast setup (Role: {role})"

echo "=== Network Configuration ==="
send_log "Configuring network settings..."
PUBLIC_IP=$(curl -s https://api.ipify.org || echo "unknown")
PRIVATE_IP=$(hostname -I | awk '{{print $1}}' || echo "unknown")
send_log "Network - Public IP: $PUBLIC_IP, Private IP: $PRIVATE_IP"

# Apply network optimizations (sysctl settings already in AMI)
sysctl -p 2>/dev/null || true
send_log "Network optimization applied"

echo "=== Fast Repository Clone ==="
send_log "Fast cloning repository from {github_repo}"
git clone -b vplex-hopeful --depth 1 {github_repo} {BITTORRENT_PROJECT_DIR}
cd {BITTORRENT_PROJECT_DIR}
send_log "Repository cloned successfully (optimized)"

echo "=== Downloading Files ==="
mkdir -p {TORRENT_TEMP_DIR}
send_log "Downloading torrent file..."
curl -L -o {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} {torrent_url}
send_log "Torrent file download completed"

# CRITICAL: Role-specific file handling - ensuring leechers NEVER have the complete file
if [ "{role}" == "{ROLE_SEEDER}" ]; then
    echo "=== SEEDER: Downloading Complete File ==="
    send_log "SEEDER: Downloading seed file to project directory..."
    
    SEED_FILE=$(basename "{seed_fileurl}")
    [ -z "$SEED_FILE" ] && SEED_FILE="{SEED_FILENAME}"
    
    curl -L -o "$SEED_FILE" {seed_fileurl}
    
    if [ ! -f "$SEED_FILE" ]; then
        send_log "ERROR: Failed to download seed file"
        exit 1
    fi
    
    SEED_SIZE=$(stat -c%s "$SEED_FILE" 2>/dev/null || echo "0")
    send_log "SEEDER: Seed file downloaded successfully: $SEED_FILE ($SEED_SIZE bytes)"
    send_log "SEEDER: Working directory: $(pwd)"
    
else
    echo "=== LEECHER: Ensuring No Complete File ==="
    send_log "LEECHER: Setting up for BitTorrent download (NO complete file)"
    
    POTENTIAL_SEED_FILES=("{SEED_FILENAME}" "$(basename "{seed_fileurl}")")
    
    for potential_file in "${{POTENTIAL_SEED_FILES[@]}}"; do
        if [ -f "$potential_file" ]; then
            send_log "WARNING: Found unexpected file '$potential_file' in leecher directory - REMOVING"
            rm -f "$potential_file"
            send_log "LEECHER: Removed unexpected file: $potential_file"
        fi
    done
    
    send_log "LEECHER: Scanning project directory for unexpected large files..."
    find . -type f -size +1M -not -path "./.git/*" -not -name "*.py" -not -name "*.txt" -not -name "requirements.txt" -not -name "*.md" | while read largefile; do
        send_log "WARNING: Found unexpected large file '$largefile' in leecher directory - REMOVING"
        rm -f "$largefile"
        send_log "LEECHER: Removed unexpected large file: $largefile"
    done
    
    send_log "LEECHER: Project directory contents after cleanup:"
    ls -la . | while read line; do
        send_log "LEECHER DIR: $line"
    done
    
    send_log "LEECHER: Confirmed ready for BitTorrent download - NO complete files present"
fi

echo "=== Environment Setup ==="
export BITTORRENT_ROLE="{role}"
export INSTANCE_ID="{instance_id}"
export PUBLIC_IP="$PUBLIC_IP"
export BITTORRENT_PORT=6881
export BITTORRENT_BIND_IP="0.0.0.0"
export BITTORRENT_ANNOUNCE_IP="$PUBLIC_IP"
send_log "BitTorrent environment configured - Role: {role}, Port: 6881"

echo "=== FAST Setup Completed ==="
send_log "OPTIMIZED setup completed in seconds - waiting for coordinated start signal..."
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

# FINAL VERIFICATION before starting BitTorrent
echo "=== FINAL PRE-EXECUTION VERIFICATION ==="
if [ "{role}" == "{ROLE_SEEDER}" ]; then
    send_log "SEEDER VERIFICATION: Checking for seed file before BitTorrent start..."
    SEED_FILE=$(basename "{seed_fileurl}")
    [ -z "$SEED_FILE" ] && SEED_FILE="{SEED_FILENAME}"
    
    if [ -f "$SEED_FILE" ]; then
        SEED_SIZE=$(stat -c%s "$SEED_FILE" 2>/dev/null || echo "0")
        send_log "SEEDER VERIFIED: Seed file present: $SEED_FILE ($SEED_SIZE bytes)"
    else
        send_log "ERROR: SEEDER missing seed file: $SEED_FILE"
        exit 1
    fi
else
    send_log "LEECHER VERIFICATION: Ensuring NO complete files before BitTorrent start..."
    
    POTENTIAL_FILES=("{SEED_FILENAME}" "$(basename "{seed_fileurl}")")
    for check_file in "${{POTENTIAL_FILES[@]}}"; do
        if [ -f "$check_file" ]; then
            send_log "CRITICAL ERROR: Leecher has complete file '$check_file' before BitTorrent start!"
            exit 1
        fi
    done
    
    send_log "LEECHER VERIFIED: No complete files present - ready for BitTorrent download"
fi

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

class OptimizedBitTorrentDeployer:
    def __init__(self, config_path=DEFAULT_CONFIG_PATH):
        self.config = Config(config_path)
        self.aws_manager = OptimizedAWSManager(self.config.get_aws_config())
        self.log_server = LogServer(self.config.get_controller_port())
        self.controller_ip = self._get_public_ip()
        self.region_instances = {}
        self.region_custom_amis = {}
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
        
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        if self.cleanup_in_progress:
            print(f"\n{COLOR_RED}💀 Force terminating... (second Ctrl+C received){COLOR_RESET}")
            sys.exit(1)
        
        print(f"\n\n{COLOR_YELLOW}🛑 Keyboard interrupt received! Starting graceful cleanup...{COLOR_RESET}")
        self.cleanup_in_progress = True
        self._emergency_cleanup()
        sys.exit(0)
    
    def _emergency_cleanup(self):
        print(f"{COLOR_YELLOW}🚨 Emergency cleanup initiated{COLOR_RESET}")
        
        try:
            if self.handler:
                print(f"{COLOR_CYAN}📡 Attempting to collect available logs...{COLOR_RESET}")
                time.sleep(2)
        except Exception as e:
            print(f"{COLOR_RED}⚠ Error during log collection: {e}{COLOR_RESET}")
        
        try:
            print(f"\n{COLOR_BOLD}=== Emergency Instance Termination ==={COLOR_RESET}")
            for region_name, instance_ids in self.region_instances.items():
                if instance_ids:
                    try:
                        self.aws_manager.terminate_instances(region_name, instance_ids)
                        print(f"{COLOR_GREEN}✓ Terminated instances in {region_name}{COLOR_RESET}")
                    except Exception as e:
                        print(f"{COLOR_RED}✗ Error terminating instances in {region_name}: {e}{COLOR_RESET}")
            
            time.sleep(10)
            
            try:
                self.aws_manager.cleanup_security_groups()
            except Exception as e:
                print(f"{COLOR_YELLOW}⚠ Error cleaning up security groups: {e}{COLOR_RESET}")
                        
            if self.log_server:
                self.log_server.stop()
                
        except Exception as e:
            print(f"{COLOR_RED}⚠ Error during instance cleanup: {e}{COLOR_RESET}")
        
        print(f"\n{COLOR_BOLD}{COLOR_YELLOW}🛑 Emergency cleanup completed{COLOR_RESET}")
    
    def _get_public_ip(self):
        response = requests.get(IP_API_URL)
        return response.text
    
    def prepare_custom_amis(self, force_rebuild=False):
        """Create or retrieve custom AMIs for all regions"""
        print(f"\n{COLOR_BOLD}=== Custom AMI Preparation ==={COLOR_RESET}")
        
        github_repo = self.config.get_bittorrent_config()['github_repo']
        all_regions = [region['name'] for region in self.config.get_regions()]
        
        # Show cached AMIs
        cached_amis = self.aws_manager.ami_cache.list_cached_amis()
        if cached_amis and not force_rebuild:
            print(f"\n{COLOR_CYAN}📋 Cached AMIs found:{COLOR_RESET}")
            for ami_info in cached_amis:
                print(f"  🎯 {ami_info['region']}: {ami_info['ami_id']} ({ami_info['ami_name']})")
                print(f"     Created: {ami_info['created']}")
        
        print(f"\n{COLOR_BOLD}🔨 AMI Creation/Verification Process{COLOR_RESET}")
        if force_rebuild:
            print(f"{COLOR_YELLOW}⚠ Force rebuild requested - will create new AMIs{COLOR_RESET}")
        
        ami_futures = []
        with ThreadPoolExecutor(max_workers=3) as executor:  # Limit concurrent AMI builds
            for region_name in all_regions:
                print(f"🚀 Starting AMI process for {region_name}...")
                future = executor.submit(
                    self.aws_manager.create_custom_ami,
                    region_name,
                    github_repo,
                    force_rebuild
                )
                ami_futures.append((region_name, future))
            
            # Collect results
            for region_name, future in ami_futures:
                if self.cleanup_in_progress:
                    break
                
                try:
                    ami_id, error = future.result()
                    if ami_id:
                        self.region_custom_amis[region_name] = ami_id
                        print(f"{COLOR_GREEN}✅ AMI ready for {region_name}: {ami_id}{COLOR_RESET}")
                    else:
                        print(f"{COLOR_RED}❌ AMI creation failed for {region_name}: {error}{COLOR_RESET}")
                        return False, f"AMI creation failed for {region_name}: {error}"
                except Exception as e:
                    print(f"{COLOR_RED}❌ AMI creation error for {region_name}: {e}{COLOR_RESET}")
                    return False, f"AMI creation error for {region_name}: {e}"
        
        if self.cleanup_in_progress:
            return False, "Interrupted"
        
        print(f"\n{COLOR_GREEN}🎉 All custom AMIs ready! Deployment will be ultra-fast.{COLOR_RESET}")
        return True, None
    
    def deploy_region(self, region_config, torrent_url, seed_fileurl):
        """Deploy all instances using optimized AMIs"""
        region_name = region_config['name']
        ami_id = self.region_custom_amis[region_name]
        instance_ids = []
        
        # Create security group
        security_group_id, sg_error = self.aws_manager.create_simple_security_group(region_name)
        if sg_error:
            print(f"{COLOR_RED}✗ Failed to create security group in {region_name}: {sg_error}{COLOR_RESET}")
            return region_name, []
        
        print(f"{COLOR_GREEN}⚡ Using optimized AMI {ami_id} in {region_name}{COLOR_RESET}")
        
        # Deploy seeders
        for i in range(region_config['seeders']):
            instance_id = f"{region_name}-{ROLE_SEEDER}-{i}"
            user_data = self.aws_manager.generate_optimized_user_data(
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
            user_data = self.aws_manager.generate_optimized_user_data(
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
        print(f"\n{COLOR_BOLD}=== Waiting for Ultra-Fast Setup Completion ==={COLOR_RESET}")
        print(f"⚡ Waiting for {self.total_instance_count} instances to complete optimized setup...")
        print(f"🚀 Expected setup time: 10-30 seconds per instance (vs 3-5 minutes with standard deployment)")
        print(f"⏱️  Timeout: {timeout_minutes} minutes")
        
        timeout = time.time() + (timeout_minutes * 60)
        
        while time.time() < timeout:
            if self.cleanup_in_progress:
                return False
            
            setup_complete_count = len(handler.setup_completions)
            elapsed_time = time.time() - (timeout - timeout_minutes * 60)
            
            print(f"\r⚡ Setup completed: {setup_complete_count}/{self.total_instance_count} ({(setup_complete_count/self.total_instance_count)*100:.1f}%) - {elapsed_time:.0f}s elapsed", end='', flush=True)
            
            if setup_complete_count >= self.total_instance_count:
                print(f"\n{COLOR_GREEN}🎉 All {setup_complete_count} instances completed optimized setup in {elapsed_time:.0f} seconds!{COLOR_RESET}")
                return True
            
            time.sleep(2)  # Check more frequently for fast setup
        
        setup_complete_count = len(handler.setup_completions)
        print(f"\n{COLOR_YELLOW}⚠ Timeout: Only {setup_complete_count}/{self.total_instance_count} instances completed setup{COLOR_RESET}")
        return False
    
    def coordinate_staggered_startup(self, handler):
        print(f"\n{COLOR_BOLD}=== Coordinated Staggered Startup ==={COLOR_RESET}")
        
        print(f"{COLOR_CYAN}⏳ Waiting {SETUP_COMPLETION_WAIT_SECONDS} seconds after setup completion...{COLOR_RESET}")
        time.sleep(SETUP_COMPLETION_WAIT_SECONDS)
        
        seeder_instances = []
        leecher_instances = []
        
        for instance_id in handler.setup_completions.keys():
            if 'seeder' in instance_id:
                seeder_instances.append(instance_id)
            elif 'leecher' in instance_id:
                leecher_instances.append(instance_id)
        
        print(f"\n{COLOR_BLUE}📥 Starting {len(leecher_instances)} leechers first with {LEECHER_START_INTERVAL_SECONDS}s intervals...{COLOR_RESET}")
        for i, leecher_id in enumerate(leecher_instances):
            if self.cleanup_in_progress:
                return False
            
            print(f"{COLOR_BLUE}📥 Starting leecher {i+1}/{len(leecher_instances)}: {leecher_id}{COLOR_RESET}")
            handler.start_signals[leecher_id] = time.time()
            
            if i < len(leecher_instances) - 1:
                time.sleep(LEECHER_START_INTERVAL_SECONDS)
        
        print(f"{COLOR_CYAN}⏳ Waiting {POST_LEECHERS_WAIT_SECONDS} seconds for leechers to establish...{COLOR_RESET}")
        time.sleep(POST_LEECHERS_WAIT_SECONDS)
        
        print(f"\n{COLOR_GREEN}🌱 Starting all {len(seeder_instances)} seeders in parallel...{COLOR_RESET}")
        for seeder_id in seeder_instances:
            if self.cleanup_in_progress:
                return False
            
            print(f"{COLOR_GREEN}🌱 Starting seeder: {seeder_id}{COLOR_RESET}")
            handler.start_signals[seeder_id] = time.time()
        
        print(f"{COLOR_BOLD}{COLOR_MAGENTA}🚀 Staggered startup complete!{COLOR_RESET}")
        return True
    
    def wait_for_completion(self, handler, timeout_minutes):
        timeout = time.time() + (timeout_minutes * 60)
        
        while time.time() < timeout:
            if self.cleanup_in_progress:
                return False
            if len(handler.completion_status) >= self.total_instance_count:
                return True
            time.sleep(COMPLETION_CHECK_INTERVAL)
        
        return False
    
    def run(self, force_rebuild_amis=False):
        try:
            print(f"{COLOR_BOLD}{COLOR_MAGENTA}🚀 OPTIMIZED BitTorrent Network Deployment{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_YELLOW}📁 Run Name: {self.run_name}{COLOR_RESET}")
            print(f"⚡ SPEED OPTIMIZATION: Using custom AMIs with pre-installed dependencies")
            print(f"🚀 Expected setup time: 10-30 seconds per instance (vs 3-5 minutes standard)")
            print(f"{COLOR_YELLOW}💡 Press Ctrl+C at any time for graceful cleanup{COLOR_RESET}")
            
            # Prepare custom AMIs
            ami_success, ami_error = self.prepare_custom_amis(force_rebuild_amis)
            if not ami_success:
                print(f"\n{COLOR_RED}💥 AMI preparation failed: {ami_error}{COLOR_RESET}")
                return {}
            
            # Start log server
            self.handler = self.log_server.start()
            print(f"\n{COLOR_GREEN}🌐 Log server started on port {self.config.get_controller_port()}{COLOR_RESET}")
            
            # Get URLs
            torrent_url = self.config.get_bittorrent_config()['torrent_url']
            seed_fileurl = self.config.get_bittorrent_config()['seed_fileurl']
            github_repo = self.config.get_bittorrent_config()['github_repo']
            
            print(f"\n{COLOR_BOLD}=== Configuration ==={COLOR_RESET}")
            print(f"📂 GitHub repo: {github_repo}")
            print(f"📁 Torrent URL: {torrent_url}")
            print(f"🌱 Seed file URL: {seed_fileurl}")
            print(f"⚡ Optimization: Custom AMIs with pre-installed dependencies")
            
            print(f"\n{COLOR_BOLD}=== Deployment Plan ==={COLOR_RESET}")
            for region in self.config.get_regions():
                ami_id = self.region_custom_amis[region['name']]
                print(f"🌍 Region {region['name']}: {COLOR_GREEN}{region['seeders']} seeders{COLOR_RESET}, {COLOR_BLUE}{region['leechers']} leechers{COLOR_RESET}")
                print(f"    ⚡ Custom AMI: {ami_id}")
            
            print(f"📊 Total: {COLOR_GREEN}{self.total_seeder_count} seeders{COLOR_RESET}, {COLOR_BLUE}{self.total_leecher_count} leechers{COLOR_RESET} = {COLOR_BOLD}{self.total_instance_count} instances{COLOR_RESET}")
            
            # Deploy all instances
            print(f"\n{COLOR_BOLD}{COLOR_CYAN}=== Ultra-Fast Instance Deployment ==={COLOR_RESET}")
            print(f"⚡ Deploying {self.total_instance_count} instances with optimized AMIs...")
            
            futures = []
            with ThreadPoolExecutor() as executor:
                for region in self.config.get_regions():
                    futures.append(
                        executor.submit(
                            self.deploy_region,
                            region,
                            torrent_url,
                            seed_fileurl
                        )
                    )
                
                for future in futures:
                    if self.cleanup_in_progress:
                        break
                    region_name, instance_ids = future.result()
                    self.region_instances[region_name] = instance_ids
                    if instance_ids:
                        print(f"{COLOR_GREEN}⚡ Launched {len(instance_ids)} optimized instances in {region_name}{COLOR_RESET}")
            
            if self.cleanup_in_progress:
                return {}
            
            # Wait for setup completion (should be much faster)
            setup_complete = self.wait_for_all_setup_complete(self.handler, 10)  # Much shorter timeout
            
            if not setup_complete:
                print(f"{COLOR_RED}💥 Setup Phase Failed{COLOR_RESET}")
                if not self.cleanup_in_progress:
                    self._emergency_cleanup()
                return {}
            
            # Coordinate startup
            startup_success = self.coordinate_staggered_startup(self.handler)
            
            if not startup_success:
                print(f"{COLOR_RED}💥 Startup Coordination Failed{COLOR_RESET}")
                if not self.cleanup_in_progress:
                    self._emergency_cleanup()
                return {}
            
            # Wait for completion
            print(f"\n{COLOR_BOLD}=== Live Status Dashboard ==={COLOR_RESET}")
            print("⚡ Ultra-fast optimized deployment completed!")
            print("📊 CSV files will be automatically collected after BitTorrent completion")
            print(f"{COLOR_YELLOW}💡 Press Ctrl+C anytime to stop and cleanup{COLOR_RESET}")
            print("\n" + "=" * 80)
            
            LogHandler.display_status_dashboard()
            
            completed = self.wait_for_completion(self.handler, self.config.get_timeout_minutes())
            
            if self.cleanup_in_progress:
                return {}
            
            if completed:
                print(f"\n{COLOR_GREEN}✅ All instances completed successfully{COLOR_RESET}")
            else:
                print(f"\n{COLOR_YELLOW}⚠ Timeout reached{COLOR_RESET}")
            
            # Cleanup
            print(f"\n{COLOR_BOLD}=== Cleanup ==={COLOR_RESET}")
            for region_name, instance_ids in self.region_instances.items():
                self.aws_manager.terminate_instances(region_name, instance_ids)
                print(f"{COLOR_GREEN}✓ Terminated {len(instance_ids)} instances in {region_name}{COLOR_RESET}")
            
            time.sleep(30)
            self.aws_manager.cleanup_security_groups()
            self.log_server.stop()
            
            print(f"\n{COLOR_BOLD}{COLOR_MAGENTA}🎉 OPTIMIZED BitTorrent Network Test Completed!{COLOR_RESET}")
            print(f"⚡ Ultra-fast deployment using custom AMIs")
            print(f"{COLOR_BOLD}{COLOR_YELLOW}📁 All logs saved in: {LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
            
            return self.handler.completion_status
            
        except KeyboardInterrupt:
            self._emergency_cleanup()
            sys.exit(0)
        except Exception as e:
            print(f"\n{COLOR_RED}💥 Unexpected error: {e}{COLOR_RESET}")
            if not self.cleanup_in_progress:
                self._emergency_cleanup()
            raise

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Optimized BitTorrent Network Deployment')
    parser.add_argument('--rebuild-amis', action='store_true', 
                       help='Force rebuild of custom AMIs (slow but ensures latest dependencies)')
    parser.add_argument('--list-amis', action='store_true',
                       help='List cached custom AMIs and exit')
    
    args = parser.parse_args()
    
    if args.list_amis:
        cache = AMICache()
        amis = cache.list_cached_amis()
        if amis:
            print(f"{COLOR_BOLD}Cached Custom AMIs:{COLOR_RESET}")
            for ami in amis:
                print(f"  🎯 {ami['region']}: {ami['ami_id']}")
                print(f"     Name: {ami['ami_name']}")
                print(f"     Created: {ami['created']}")
                print(f"     Config Hash: {ami['config_hash']}")
                print()
        else:
            print("No cached AMIs found.")
        return
    
    try:
        deployer = OptimizedBitTorrentDeployer()
        deployer.run(force_rebuild_amis=args.rebuild_amis)
    except KeyboardInterrupt:
        print(f"\n{COLOR_YELLOW}🛑 Interrupted by user{COLOR_RESET}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{COLOR_RED}💥 Fatal error: {e}{COLOR_RESET}")
        sys.exit(1)

if __name__ == "__main__":
    main()