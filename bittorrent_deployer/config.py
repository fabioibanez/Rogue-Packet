"""
Configuration management for BitTorrent Network Deployment
"""

import yaml
from .constants import DEFAULT_CONFIG_PATH


class Config:
    """Handles loading and accessing configuration from YAML file"""
    
    def __init__(self, config_path=DEFAULT_CONFIG_PATH):
        """
        Load configuration from YAML file
        
        Args:
            config_path (str): Path to the configuration YAML file
        """
        with open(config_path, "r") as f:
            self.data = yaml.safe_load(f)
    
    def get_aws_config(self):
        """Get AWS configuration section"""
        return self.data['aws']
    
    def get_regions(self):
        """Get list of regions with seeder/leecher counts"""
        return self.data['regions']
    
    def get_controller_port(self):
        """Get controller server port"""
        return self.data['controller']['port']
    
    def get_bittorrent_config(self):
        """Get BitTorrent configuration (repo, URLs, etc.)"""
        return self.data['bittorrent']
    
    def get_timeout_minutes(self):
        """Get deployment timeout in minutes"""
        return self.data['timeout_minutes']