# Constants
# File Paths and Names
DEFAULT_CONFIG_PATH = "config.yaml"  # Used in Config and BitTorrentDeployer initialization
LOGS_DIR = "logs"  # Directory for storing log files from instances
TORRENT_TEMP_DIR = "/tmp/torrents"  # Directory for storing torrent files on instances
BITTORRENT_PROJECT_DIR = "/tmp/bittorrent-project"  # Directory for cloning GitHub repo on instances
LOG_FILE_PATH = "/tmp/bittorrent.log"  # Path to store BitTorrent client logs on instances
INSTANCE_ID_FILE = "/tmp/instance_id.txt"  # File to store instance ID on instances
TORRENT_FILENAME = "file.torrent"  # Default filename for downloaded torrent files
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"  # Format for logging

# API Endpoints
LOGS_ENDPOINT = '/logs'  # Endpoint for sending logs (LogHandler.do_POST and generate_user_data)
COMPLETION_ENDPOINT = '/completion'  # Endpoint for completion notification (LogHandler.do_POST and generate_user_data)
IP_API_URL = 'https://api.ipify.org'  # API for getting public IP (used in _get_public_ip)

# HTTP Constants
HTTP_OK = 200  # HTTP status for successful responses (used in LogHandler methods)
HTTP_NOT_FOUND = 404  # HTTP status for not found (used in LogHandler.do_POST)
CONTENT_TYPE_JSON = "Content-Type: application/json"  # Content type header (used in generate_user_data)

# AWS Constants
DEFAULT_INSTANCE_TYPE = "t2.micro"  # Default EC2 instance type if not specified in config
DEFAULT_REGION = "us-east-1"  # Default AWS region if not specified in config
DEFAULT_AMI_UBUNTU = "ami-0123456789abcdef"  # Default Ubuntu AMI if not specified in config
EC2_SERVICE_NAME = 'ec2'  # EC2 service name for boto3 (used in get_ec2_client)

# Timing Constants
DEFAULT_TIMEOUT_MINUTES = 30  # Default timeout if not specified in config
COMPLETION_CHECK_INTERVAL = 10  # Seconds between completion checks (used in wait_for_completion)
DEFAULT_CONTROLLER_PORT = 8080  # Default port for controller server if not specified in config

# Installation Commands
UPDATE_CMD = "apt-get update"  # Update package lists command (used in generate_user_data)
INSTALL_PACKAGES_CMD = "apt-get install -y git python3 python3-pip"  # Install required packages (used in generate_user_data)
INSTALL_DEPS_CMD = "pip3 install -r requirements.txt"  # Install Python dependencies (used in generate_user_data)
SHUTDOWN_CMD = "shutdown -h now"  # Command to shutdown instance (used in generate_user_data)

# Role Constants
ROLE_SEEDER = "seeder"  # Role identifier for seeders (used in deploy_region)
ROLE_LEECHER = "leecher"  # Role identifier for leechers (used in deploy_region)

# Status Constants
STATUS_COMPLETE = "complete"  # Status indicating completion (used in generate_user_data)

import yaml
import time
import requests
import os
import base64
import threading
import json
import boto3
import cgi
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
    
    def do_POST(self):
        if self.path == LOGS_ENDPOINT:
            self._handle_logs()
        elif self.path == COMPLETION_ENDPOINT:
            self._handle_completion()
        else:
            self.send_response(HTTP_NOT_FOUND)
            self.end_headers()
    
    def _handle_logs(self):
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={'REQUEST_METHOD': 'POST'}
        )
        
        instance_id = form.getvalue('instance_id')
        fileitem = form['logfile']
        
        if fileitem.file:
            os.makedirs(self.logs_dir, exist_ok=True)
            with open(f"{self.logs_dir}/{instance_id}.log", 'wb') as f:
                f.write(fileitem.file.read())
        
        self.send_response(HTTP_OK)
        self.end_headers()
    
    def _handle_completion(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data.decode())
        
        instance_id = data.get('instance_id')
        status = data.get('status')
        
        if instance_id:
            self.completion_status[instance_id] = status
        
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
    
    def get_ec2_client(self, region):
        if region not in self.region_clients:
            self.region_clients[region] = boto3.client(
                EC2_SERVICE_NAME,
                region_name=region,
                aws_access_key_id=self.aws_config['access_key'],
                aws_secret_access_key=self.aws_config['secret_key']
            )
        return self.region_clients[region]
    
    def generate_user_data(self, github_repo, torrent_url, role, controller_ip, controller_port, instance_id):
        script = f"""#!/bin/bash
# Debug: Log all commands and outputs
set -x
exec > >(tee -a /tmp/startup.log) 2>&1

echo "=== Starting instance setup for {instance_id} ==="
echo "Role: {role}"
echo "Torrent URL: {torrent_url}"
echo "Controller: {controller_ip}:{controller_port}"

{UPDATE_CMD}
{INSTALL_PACKAGES_CMD}
git clone -b feat/aut-testbed {github_repo} {BITTORRENT_PROJECT_DIR}
cd {BITTORRENT_PROJECT_DIR}
{INSTALL_DEPS_CMD}

mkdir -p {TORRENT_TEMP_DIR}

echo "=== Downloading torrent file ==="
echo "URL: {torrent_url}"
curl -v -o {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} {torrent_url}

echo "=== Torrent file info ==="
ls -la {TORRENT_TEMP_DIR}/{TORRENT_FILENAME}
file {TORRENT_TEMP_DIR}/{TORRENT_FILENAME}
head -c 100 {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} | hexdump -C

export BITTORRENT_ROLE="{role}"
export INSTANCE_ID="{instance_id}"
echo "{instance_id}" > {INSTANCE_ID_FILE}

echo "=== Running BitTorrent client ==="
echo "Command: python3 -m main {TORRENT_TEMP_DIR}/{TORRENT_FILENAME}"
python3 -m main {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} > {LOG_FILE_PATH} 2>&1

echo "=== BitTorrent client finished ==="
echo "Log file size: $(wc -l < {LOG_FILE_PATH}) lines"

# Append startup log to main log for debugging
echo "=== STARTUP LOG ===" >> {LOG_FILE_PATH}
cat /tmp/startup.log >> {LOG_FILE_PATH}

curl -X POST -F "instance_id={instance_id}" -F "logfile=@{LOG_FILE_PATH}" http://{controller_ip}:{controller_port}{LOGS_ENDPOINT}
curl -X POST -H "{CONTENT_TYPE_JSON}" -d '{{"instance_id": "{instance_id}", "status": "{STATUS_COMPLETE}"}}' http://{controller_ip}:{controller_port}{COMPLETION_ENDPOINT}
{SHUTDOWN_CMD}
"""
        return base64.b64encode(script.encode()).decode()
    
    def launch_instance(self, region, user_data):
        ec2_client = self.get_ec2_client(region)
        
        response = ec2_client.run_instances(
            ImageId=self.aws_config['ami_id'],
            InstanceType=self.aws_config['instance_type'],
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
    
    def _get_public_ip(self):
        response = requests.get(IP_API_URL)
        return response.text
    
    def deploy_region(self, region_config, torrent_url):
        region_name = region_config['name']
        instance_ids = []
        
        # Deploy seeders
        for i in range(region_config['seeders']):
            instance_id = f"{region_name}-{ROLE_SEEDER}-{i}"
            user_data = self.aws_manager.generate_user_data(
                self.config.get_bittorrent_config()['github_repo'],
                torrent_url,
                ROLE_SEEDER,
                self.controller_ip,
                self.config.get_controller_port(),
                instance_id
            )
            
            ec2_id = self.aws_manager.launch_instance(region_name, user_data)
            instance_ids.append(ec2_id)
        
        # Deploy leechers
        for i in range(region_config['leechers']):
            instance_id = f"{region_name}-{ROLE_LEECHER}-{i}"
            user_data = self.aws_manager.generate_user_data(
                self.config.get_bittorrent_config()['github_repo'],
                torrent_url,
                ROLE_LEECHER,
                self.controller_ip,
                self.config.get_controller_port(),
                instance_id
            )
            
            ec2_id = self.aws_manager.launch_instance(region_name, user_data)
            instance_ids.append(ec2_id)
        
        return region_name, instance_ids
    
    def wait_for_completion(self, handler, timeout_minutes):
        timeout = time.time() + (timeout_minutes * 60)
        
        while time.time() < timeout:
            if len(handler.completion_status) >= self.total_instance_count:
                return True
            time.sleep(COMPLETION_CHECK_INTERVAL)
        
        return False
    
    def run(self):
        print("Starting BitTorrent network deployment...")
        
        # Start log server
        handler = self.log_server.start()
        print(f"Log server started on port {self.config.get_controller_port()}")
        print(f"Controller IP: {self.controller_ip}")
        
        # Get torrent URL from GitHub
        torrent_url = self.config.get_bittorrent_config()['torrent_url']
        github_repo = self.config.get_bittorrent_config()['github_repo']
        
        print(f"\n=== Configuration ===")
        print(f"GitHub repo: {github_repo}")
        print(f"Torrent URL: {torrent_url}")
        print(f"Command to be run on each instance: python3 -m main /tmp/torrents/file.torrent")
        
        # Test torrent URL accessibility
        print(f"\n=== Testing torrent URL ===")
        try:
            import requests
            response = requests.head(torrent_url)
            print(f"Torrent URL status: {response.status_code}")
            if response.status_code == 200:
                print(f"✓ Torrent file accessible ({response.headers.get('content-length', 'unknown')} bytes)")
            else:
                print(f"✗ Torrent URL returned {response.status_code} - this will cause failures!")
        except Exception as e:
            print(f"✗ Could not test torrent URL: {e}")
        
        # Calculate total instance count
        for region in self.config.get_regions():
            self.total_instance_count += region['seeders'] + region['leechers']
        
        print(f"\n=== Deployment Plan ===")
        for region in self.config.get_regions():
            print(f"Region {region['name']}: {region['seeders']} seeders, {region['leechers']} leechers")
        print(f"Total instances: {self.total_instance_count}")
        
        # Deploy instances
        print(f"\n=== Launching Instances ===")
        with ThreadPoolExecutor() as executor:
            futures = []
            
            for region in self.config.get_regions():
                futures.append(
                    executor.submit(
                        self.deploy_region,
                        region,
                        torrent_url
                    )
                )
            
            for future in futures:
                region_name, instance_ids = future.result()
                self.region_instances[region_name] = instance_ids
                print(f"✓ Launched {len(instance_ids)} instances in {region_name}")
        
        print(f"✓ Deployed {self.total_instance_count} instances across {len(self.config.get_regions())} regions")
        
        # Wait for completion
        print(f"\n=== Waiting for Completion ===")
        print("Instances are now:")
        print("1. Booting up (1-2 minutes)")
        print("2. Installing dependencies (2-3 minutes)")
        print("3. Running BitTorrent clients")
        print("4. Sending logs back when complete")
        print(f"Will wait up to {self.config.get_timeout_minutes()} minutes...")
        
        completed = self.wait_for_completion(handler, self.config.get_timeout_minutes())
        
        if completed:
            print("✓ All instances completed successfully")
        else:
            print("⚠ Timeout reached, some instances may not have completed")
        
        # Process logs
        print(f"\n=== Log Summary ===")
        for instance_id, status in handler.completion_status.items():
            log_path = f"logs/{instance_id}.log"
            if os.path.exists(log_path):
                print(f"✓ {instance_id}: {status} (log collected)")
            else:
                print(f"✗ {instance_id}: {status} (no log collected)")
        
        # Cleanup resources
        print(f"\n=== Cleanup ===")
        for region_name, instance_ids in self.region_instances.items():
            self.aws_manager.terminate_instances(region_name, instance_ids)
            print(f"✓ Terminated {len(instance_ids)} instances in {region_name}")
        
        # Stop log server
        self.log_server.stop()
        print("✓ Log server stopped")
        
        return handler.completion_status

if __name__ == "__main__":
    deployer = BitTorrentDeployer()
    deployer.run()