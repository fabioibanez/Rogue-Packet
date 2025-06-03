"""
Constants for BitTorrent Network Deployment
"""

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
IP_API_URL = 'https://api.ipify.org'

# HTTP Constants
HTTP_OK = 200
HTTP_NOT_FOUND = 404

# AWS Constants
DEFAULT_INSTANCE_TYPE = "t2.micro"
DEFAULT_REGION = "us-east-1"
EC2_SERVICE_NAME = 'ec2'

# AMI Constants
UBUNTU_OWNER_ID = '099720109477'  # Canonical (Ubuntu) owner ID
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