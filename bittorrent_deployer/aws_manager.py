"""
AWS Management for BitTorrent Network Deployment
"""

import boto3
import base64
from .constants import (
    EC2_SERVICE_NAME, DEFAULT_INSTANCE_TYPE, UBUNTU_OWNER_ID,
    UBUNTU_AMI_NAME_PATTERN, AMI_ARCHITECTURE, AMI_STATE_AVAILABLE,
    UPDATE_CMD, INSTALL_PACKAGES_CMD, INSTALL_DEPS_CMD, SHUTDOWN_CMD,
    TORRENT_TEMP_DIR, SEED_TEMP_DIR, BITTORRENT_PROJECT_DIR,
    LOG_FILE_PATH, TORRENT_FILENAME, SEED_FILENAME,
    LOGS_ENDPOINT, STREAM_ENDPOINT, COMPLETION_ENDPOINT,
    ROLE_SEEDER, ROLE_LEECHER, STATUS_COMPLETE
)


class AWSManager:
    """Manages AWS operations for BitTorrent network deployment"""
    
    def __init__(self, aws_config):
        """
        Initialize AWS manager with configuration
        
        Args:
            aws_config (dict): AWS configuration from config file
        """
        self.aws_config = aws_config
        self.region_clients = {}
        self.region_amis = {}  # Cache for AMI IDs per region
    
    def get_ec2_client(self, region):
        """
        Get or create EC2 client for specified region
        
        Args:
            region (str): AWS region name
            
        Returns:
            boto3.client: EC2 client for the region
        """
        if region not in self.region_clients:
            self.region_clients[region] = boto3.client(
                EC2_SERVICE_NAME,
                region_name=region,
            )
        return self.region_clients[region]
    
    def get_latest_ubuntu_ami(self, region):
        """
        Get latest Ubuntu 22.04 AMI for the specified region
        
        Args:
            region (str): AWS region name
            
        Returns:
            tuple: (ami_info dict, error_message str or None)
        """
        if region in self.region_amis:
            return self.region_amis[region], None
        
        try:
            ec2_client = self.get_ec2_client(region)
            
            response = ec2_client.describe_images(
                Owners=[UBUNTU_OWNER_ID],  # Canonical (Ubuntu)
                Filters=[
                    {'Name': 'name', 'Values': [UBUNTU_AMI_NAME_PATTERN]},
                    {'Name': 'state', 'Values': [AMI_STATE_AVAILABLE]},
                    {'Name': 'architecture', 'Values': [AMI_ARCHITECTURE]}
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
        """
        Validate that an AMI is available and accessible
        
        Args:
            region (str): AWS region name
            ami_id (str): AMI ID to validate
            
        Returns:
            tuple: (is_valid bool, message str)
        """
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
    
    def generate_user_data(self, github_repo, torrent_url, seed_fileurl, role, 
                          controller_ip, controller_port, instance_id):
        """
        Generate user data script for EC2 instance
        
        Args:
            github_repo (str): GitHub repository URL
            torrent_url (str): URL to torrent file
            seed_fileurl (str): URL to seed file (for seeders)
            role (str): Instance role ('seeder' or 'leecher')
            controller_ip (str): Controller IP address
            controller_port (int): Controller port
            instance_id (str): Instance identifier
            
        Returns:
            str: Base64 encoded user data script
        """
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

# Function to stream log file changes (with recursion prevention)
start_log_streaming() {{
    # Disable debug logging for streaming functions to prevent recursion
    {{ set +x;
        # Stream startup log, but filter out send_log_update commands to prevent loops
        tail -f /tmp/startup.log | grep -v "send_log_update" | while read line; do
            # Re-enable debug briefly for the actual curl call
            {{ set -x; send_log_update "STARTUP: $line"; set +x; }} 2>/dev/null
            sleep 1
        done &
        
        # Wait for BitTorrent log file and stream it
        while [ ! -f {LOG_FILE_PATH} ]; do sleep 2; done
        tail -f {LOG_FILE_PATH} | while read line; do
            {{ set -x; send_log_update "BITTORRENT: $line"; set +x; }} 2>/dev/null
            sleep 1
        done &
    }} 2>/dev/null &
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
echo "{instance_id}" > /tmp/instance_id.txt

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
    
    def launch_instance(self, region, user_data, ami_id):
        """
        Launch EC2 instance with specified configuration
        
        Args:
            region (str): AWS region name
            user_data (str): Base64 encoded user data script
            ami_id (str): AMI ID to use
            
        Returns:
            str: EC2 instance ID
        """
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
        """
        Terminate EC2 instances in specified region
        
        Args:
            region (str): AWS region name
            instance_ids (list): List of EC2 instance IDs to terminate
        """
        if not instance_ids:
            return
        
        ec2_client = self.get_ec2_client(region)
        ec2_client.terminate_instances(InstanceIds=instance_ids)