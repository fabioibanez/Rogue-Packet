import yaml
from .constants import DEFAULT_CONFIG_PATH

class Config:
    def __init__(self, config_path=DEFAULT_CONFIG_PATH):
        with open(config_path) as f:
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
