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


PLOT_INTERVAL: float = 0.5  # Time between plot updates in seconds

def export_conda() -> None:
    """Export conda environment without prefix."""
    os.system("conda env export | grep -v \"^prefix: \" > environment.yml")
    print("\033[1;32m[UTILITY] Exported conda environment to environment.yml\033[0m")

def print_torrent(data: Dict) -> None:
    """Print torrent data with pieces count instead of binary content."""
    if 'info' in data and 'pieces' in data['info']:
        data = {**data, 'info': {**data['info'], 'pieces': f"<{len(data['info']['pieces'])} bytes>"}}
    print("\033[1;32m[UTILITY] TORRENT FILE CONTENT:\n" + pprint.pformat(data) + "\033[0m")

def get_dir_size(path: str) -> int:
    """Get total directory size in bytes."""
    return sum(
        os.path.getsize(os.path.join(dirpath, f))
        for dirpath, _, filenames in os.walk(path)
        for f in filenames
        if not os.path.islink(os.path.join(dirpath, f))
    )

def plot_dirsize_overtime(dir_path: str, stop_event: threading.Event, save_path: str) -> None:
    """Plot directory size growth over time."""
    times, sizes = [], []
    start_time = time.time()
    
    while not stop_event.is_set():
        current_time = time.time() - start_time
        times.append(current_time)
        sizes.append(get_dir_size(dir_path))
        
        plt.figure()
        plt.plot(times, sizes)
        plt.xlabel('Time (s)')
        plt.ylabel('Size (bytes)')
        plt.title(f'Directory Size Over Time: {os.path.basename(dir_path)}')
        
        plt.savefig(save_path)
        plt.close()
        
        time.sleep(PLOT_INTERVAL)

def save_download_progress(dir_path: str, stop_event: threading.Event, save_path: str) -> None:
    """Save download progress to CSV file."""
    while not stop_event.is_set():
        with open(save_path, 'a') as f:
            # # f.write(f"{dir_path},{get_dir_size(dir_path)},{time.time()}\n")
            # # write the size of all files / folders in the directory
            # for root, dirs, files in os.walk(dir_path):
            #     for name in files:
            #         file_path = os.path.join(root, name)
            #         if not os.path.islink(file_path):
            #             size = os.path.getsize(file_path)
            #             f.write(f"{file_path},{size},{time.time()}\n")
            
            # Open the /tmp/bittorrent-project/torrent_1/ file and check how big it is
            # Check if ""/tmp/bittorrent-project/torrent_1/" exists
            if os.path.exists("/tmp/bittorrent-project/torrent_1/"):
                # Get the size of the directory
                # and write it to the file
                f.write(f"{dir_path},{get_dir_size(dir_path)},{time.time()}\n")
            else:
                # If the directory does not exist, write 0
                f.write(f"{dir_path},-1,{time.time()}\n")    
        
        time.sleep(PLOT_INTERVAL)

def cleanup_torrent_download(torrent_file: str) -> None:
    """Deletes all files in the current directory that match the pattern of the torrent file name."""
    shutil.rmtree(_target := os.path.splitext(os.path.basename(torrent_file))[0], ignore_errors=True)
    print(f"\033[1;32m[UTILITY] Attempted cleanup of torrent folder @ '{_target}'\033[0m")