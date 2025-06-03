"""
Utility functions for BitTorrent Network Deployment
"""

import requests
import random
import signal
import sys
from datetime import datetime
from .constants import IP_API_URL, RUN_WORDS, COLOR_YELLOW, COLOR_RESET


def get_public_ip():
    """
    Get the public IP address of the current machine
    
    Returns:
        str: Public IP address
    """
    response = requests.get(IP_API_URL)
    return response.text.strip()


def generate_run_name():
    """
    Generate a unique run name with timestamp and random word
    
    Returns:
        str: Unique run name in format 'word_YYYYMMDD_HHMMSS'
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    random_word = random.choice(RUN_WORDS)
    return f"{random_word}_{timestamp}"


def setup_signal_handlers(cleanup_callback):
    """
    Set up signal handlers for graceful shutdown
    
    Args:
        cleanup_callback (callable): Function to call for cleanup on interrupt
    """
    def signal_handler(signum, frame):
        """Handle keyboard interrupt (Ctrl+C) gracefully"""
        print(f"\n\n{COLOR_YELLOW}🛑 Keyboard interrupt received! Starting graceful cleanup...{COLOR_RESET}")
        cleanup_callback()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)