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

# Function to update VM state locally and notify controller
update_vm_state() {{
    local state="$1"
    echo "$state" > /tmp/vm_state.txt
    curl -s -X POST -H "Content-Type: application/json" \\
        -d '{{"instance_id": "{instance_id}", "state": "'"$state"'", "timestamp": '$(date +%s)'}}' \\
        http://{controller_ip}:{controller_port}/state > /dev/null 2>&1 || true
}}

# Function to send log chunks to controller
send_log_chunk() {{
    local phase="$1"
    local log_file="$2"
    curl -s -X POST -H "Content-Type: application/json" \\
        -d '{{"instance_id": "{instance_id}", "phase": "'"$phase"'", "log_chunk": "'"$(cat $log_file | tail -n 20 | sed 's/"/\\"/g')"'", "timestamp": '$(date +%s)'}}' \\
        http://{controller_ip}:{controller_port}{STREAM_ENDPOINT} > /dev/null 2>&1 || true
}}

# Function to send final logs on exit
send_final_logs() {{
    echo "=== Sending final logs to controller ==="
    update_vm_state "error"
    
    # Send startup logs if they exist
    if [ -f /tmp/startup.log ]; then
        curl -X POST -F "instance_id={instance_id}" -F "phase=startup" -F "logfile=@/tmp/startup.log" http://{controller_ip}:{controller_port}{LOGS_ENDPOINT} || true
    fi
    
    # Send core-run logs if they exist
    if [ -f {LOG_FILE_PATH} ]; then
        curl -X POST -F "instance_id={instance_id}" -F "phase=core-run" -F "logfile=@{LOG_FILE_PATH}" http://{controller_ip}:{controller_port}{LOGS_ENDPOINT} || true
    fi
    
    curl -X POST -H "Content-Type: application/json" -d '{{"instance_id": "{instance_id}", "status": "interrupted"}}' http://{controller_ip}:{controller_port}{COMPLETION_ENDPOINT} || true
}}

# Set up trap to send logs on any exit
trap 'send_final_logs' EXIT TERM INT

# Function to stream logs periodically
start_log_streaming() {{
    # Stream startup logs every 10 seconds
    {{
        while [ -f /tmp/startup.log ] && [ "$(cat /tmp/vm_state.txt 2>/dev/null)" = "startup" ]; do
            send_log_chunk "startup" "/tmp/startup.log"
            sleep 10
        done
        
        # Stream core-run logs every 10 seconds  
        while [ -f {LOG_FILE_PATH} ] && [ "$(cat /tmp/vm_state.txt 2>/dev/null)" = "core-run" ]; do
            send_log_chunk "core-run" "{LOG_FILE_PATH}"
            sleep 10
        done
    }} &
}}

echo "=== Starting instance setup for {instance_id} ==="
update_vm_state "startup"

echo "Role: {role}"
echo "Torrent URL: {torrent_url}"
echo "Controller: {controller_ip}:{controller_port}"
echo "Timestamp: $(date)"

echo "=== System Update ==="
{UPDATE_CMD}
echo "System update completed with exit code: $?"

echo "=== Installing System Packages ==="
{INSTALL_PACKAGES_CMD}
echo "System packages installed with exit code: $?"

echo "=== Python and pip versions ==="
python3 --version
pip3 --version

echo "=== Cloning Repository ==="
git clone -b feat/distribed {github_repo} {BITTORRENT_PROJECT_DIR}
echo "Git clone completed with exit code: $?"

cd {BITTORRENT_PROJECT_DIR}
echo "Current directory: $(pwd)"
echo "Directory contents:"
ls -la

echo "=== Installing Python Dependencies ==="
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt --verbose --timeout 300
PIP_EXIT_CODE=$?
echo "pip install completed with exit code: $PIP_EXIT_CODE"

if [ $PIP_EXIT_CODE -ne 0 ]; then
    echo "ERROR: pip install failed!"
    update_vm_state "error"
    exit 1
fi

# Create necessary directories
mkdir -p {TORRENT_TEMP_DIR}
mkdir -p {SEED_TEMP_DIR}

echo "=== Downloading torrent file ==="
curl -L -o {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} {torrent_url}
CURL_EXIT_CODE=$?
echo "curl completed with exit code: $CURL_EXIT_CODE"

# Role-specific setup
if [ "{role}" == "{ROLE_SEEDER}" ]; then
    echo "=== Seeder Setup: Downloading actual file ==="
    curl -L -o {SEED_TEMP_DIR}/{SEED_FILENAME} {seed_fileurl}
    SEED_CURL_EXIT_CODE=$?
    echo "Seed file download completed with exit code: $SEED_CURL_EXIT_CODE"
    
    if [ $SEED_CURL_EXIT_CODE -ne 0 ]; then
        echo "ERROR: Failed to download seed file!"
        update_vm_state "error"
        exit 1
    fi
else
    echo "=== Leecher Setup: No seed file needed ==="
fi

export BITTORRENT_ROLE="{role}"
export INSTANCE_ID="{instance_id}"
echo "{instance_id}" > /tmp/instance_id.txt

# Start log streaming in background
start_log_streaming

echo "=== Startup Complete - Starting BitTorrent Core ==="
# Send final startup logs
send_log_chunk "startup" "/tmp/startup.log"

# Transition to core-run phase
update_vm_state "core-run"

if [ "{role}" == "{ROLE_SEEDER}" ]; then
    echo "Starting BitTorrent client as SEEDER"
    echo "Command: python3 -m main -s {TORRENT_TEMP_DIR}/{TORRENT_FILENAME}"
    python3 -m main -s {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} > {LOG_FILE_PATH} 2>&1
else
    echo "Starting BitTorrent client as LEECHER"
    echo "Command: python3 -m main {TORRENT_TEMP_DIR}/{TORRENT_FILENAME}"
    python3 -m main {TORRENT_TEMP_DIR}/{TORRENT_FILENAME} > {LOG_FILE_PATH} 2>&1
fi

BITTORRENT_EXIT_CODE=$?
echo "BitTorrent client completed with exit code: $BITTORRENT_EXIT_CODE"

echo "=== BitTorrent client finished ==="
update_vm_state "completed"

# Stop log streaming
pkill -f "send_log_chunk" 2>/dev/null || true

echo "=== Sending final logs to controller ==="
# Send final startup logs
curl -X POST -F "instance_id={instance_id}" -F "phase=startup" -F "logfile=@/tmp/startup.log" http://{controller_ip}:{controller_port}{LOGS_ENDPOINT}

# Send final core-run logs  
curl -X POST -F "instance_id={instance_id}" -F "phase=core-run" -F "logfile=@{LOG_FILE_PATH}" http://{controller_ip}:{controller_port}{LOGS_ENDPOINT}

curl -X POST -H "Content-Type: application/json" -d '{{"instance_id": "{instance_id}", "status": "{STATUS_COMPLETE}"}}' http://{controller_ip}:{controller_port}{COMPLETION_ENDPOINT}

echo "=== Instance setup completed ==="

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