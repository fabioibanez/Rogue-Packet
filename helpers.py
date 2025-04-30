# helpers.py
# Author: Shounak Ray

import pprint
import shutil
import threading
import time
from typing import Dict
import os

import matplotlib
import matplotlib.pyplot as plt
matplotlib.use('Agg')  # <- Use a non-GUI backend for thread safety
# Disable matplotlib debug logging
matplotlib.set_loglevel('WARNING')  # Only show warning and higher level messages
import os


PLOT_INTERVAL: int = 0.5  # Plot every 5 seconds

def export_conda():
    os.system("conda env export | grep -v \"^prefix: \" > environment.yml")
    print("\033[1;32m")  # Bold green text
    print("[UTILITY] Exported conda environment to environment.yml")
    print("\033[0m")  # Reset text formatting

def print_torrent(data: Dict) -> None:
    """Print torrent data with pieces count instead of binary content."""
    d = data.copy()
    if 'info' in d and isinstance(d['info'], dict):
        if 'pieces' in d['info']:
            d['info'] = d['info'].copy()
            d['info']['pieces'] = f"<{len(d['info']['pieces'])} bytes>"
    
    print("\033[1;32m")  # Bold green text
    print("[UTILITY] TORRENT FILE CONTENT:")
    pprint.pprint(d)
    print("\033[0m")  # Reset text formatting

def get_dir_size(path: str) -> int:
    """Get the total size of a directory in bytes"""
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp):
                total += os.path.getsize(fp)
    return total

def plot_dirsize_overtime(dir_path: str, stop_event: threading.Event, save_path: str) -> None:
    times = []
    sizes = []
    start_time = time.time()

    while not stop_event.is_set():
        current_time = time.time() - start_time
        current_size = get_dir_size(dir_path)
        times.append(current_time)
        sizes.append(current_size)

        # Create and save the plot when stop_event is set
        fig, ax = plt.subplots()
        ax.plot(times, sizes)
        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Size (bytes)')
        ax.set_title(f'Directory Size Over Time: {os.path.basename(dir_path)}')
        fig.savefig(save_path)
        plt.close(fig)
        
        time.sleep(PLOT_INTERVAL)

def cleanup_torrent_download(torrent_file: str) -> None:
    """Deletes all files in the current directory that match the pattern of the torrent file name."""
    shutil.rmtree(_target := os.path.splitext(os.path.basename(torrent_file))[0], ignore_errors=True)
    print(f"\033[1;32m[UTILITY] Attempted cleanup of torrent folder @ '{_target}'\033[0m")