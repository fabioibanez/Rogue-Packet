"""
AWS Management for BitTorrent Network Deployment
"""

import boto3
import base64
import os
from .constants import (
    EC2_SERVICE_NAME, DEFAULT_INSTANCE_TYPE, UBUNTU_OWNER_ID,
    UBUNTU_AMI_NAME_PATTERN, AMI_ARCHITECTURE, AMI_STATE_AVAILABLE,
    TORRENT_TEMP_DIR, SEED_TEMP_DIR, BITTORRENT_PROJECT_DIR,
    LOG_FILE_PATH, TORRENT_FILENAME, SEED_FILENAME
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
        Generate user data script for EC2 instance by loading external bash script
        
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
        
        # Get the directory where this Python file is located
        script_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(script_dir, 'ec2_user_data.sh')
        
        # Load the bash script template
        try:
            with open(script_path, 'r') as f:
                script_template = f.read()
        except FileNotFoundError:
            raise Exception(f"Could not find ec2_user_data.sh at {script_path}. Make sure the file exists.")
        
        # Define template substitutions
        substitutions = {
            'INSTANCE_ID': instance_id,
            'CONTROLLER_IP': controller_ip,
            'CONTROLLER_PORT': str(controller_port),
            'ROLE': role,
            'TORRENT_URL': torrent_url,
            'SEED_FILEURL': seed_fileurl,
            'GITHUB_REPO': github_repo,
            'LOG_FILE_PATH': LOG_FILE_PATH,
            'TORRENT_TEMP_DIR': TORRENT_TEMP_DIR,
            'SEED_TEMP_DIR': SEED_TEMP_DIR,
            'BITTORRENT_PROJECT_DIR': BITTORRENT_PROJECT_DIR,
            'TORRENT_FILENAME': TORRENT_FILENAME,
            'SEED_FILENAME': SEED_FILENAME
        }
        
        # Perform template substitution
        script = script_template
        for key, value in substitutions.items():
            placeholder = f'{{{{{key}}}}}'  # Creates {{KEY}} pattern
            script = script.replace(placeholder, value)
        
        # Debug: Print first few lines to verify substitution worked
        print(f"Generated user data script preview for {instance_id}:")
        lines = script.split('\n')[:10]  # First 10 lines
        for i, line in enumerate(lines, 1):
            print(f"  {i:2d}: {line}")
        print(f"  ... (script continues for {len(script.split())} total lines)")
        
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