#!/usr/bin/env python3

import functools
import os
import argparse
import yaml
import hashlib
from bcoding import bencode
import subprocess

DEFAULT_TEMPLATE = '''aws:
  instance_type: "t2.micro"
  security_group: "default"

controller:
  port: 8080

bittorrent:
  github_repo: "https://github.com/fabioibanez/Rogue-Packet.git"
  torrent_url: ""
  seed_fileurl: ""

regions:
  - name: "us-east-1"
    seeders: 2
    leechers: 5
  - name: "eu-west-1"
    seeders: 1
    leechers: 3
  - name: "ap-southeast-1"
    seeders: 1
    leechers: 2

timeout_minutes: 30'''

@functools.cache
def get_current_branch() -> str:
    """Get the current git branch name."""
    try:
        result = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], 
                              capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        print("Warning: Could not determine git branch. Using 'main' as default.")
        return 'main'

def generate_random_file(path: str, size: int, index: int) -> str:
    """Generate a random file of specified size with a sequential name."""
    # Create a sequential filename
    filename = f'torrent_{index}.dat'
    filepath = os.path.join(path, filename)
    
    # Ensure directory exists
    os.makedirs(path, exist_ok=True)
    
    # Generate random content
    with open(filepath, 'wb') as f:
        remaining = size
        chunk_size = min(1024 * 1024, size)  # Write in 1MB chunks
        while remaining > 0:
            to_write = min(chunk_size, remaining)
            f.write(os.urandom(to_write))
            remaining -= to_write
    
    return filepath

def calculate_pieces(file_path: str, piece_length: int = 16384) -> tuple[bytes, int]:
    """Calculate piece hashes for a file."""
    pieces = b''
    file_size = 0
    
    with open(file_path, 'rb') as f:
        while True:
            piece_data = f.read(piece_length)
            if not piece_data:
                break
            pieces += hashlib.sha1(piece_data).digest()
            file_size += len(piece_data)
    
    return pieces, file_size

def create_torrent(source_path: str, output_dir: str, tracker_url: str) -> str:
    """Create a torrent file for the given source file."""
    # Calculate piece length (conventionally a power of 2)
    # Use 16KB for small files, increase for larger files
    file_size = os.path.getsize(source_path)
    piece_length = 16384  # Start with 16KB
    while file_size / piece_length > 2000:  # Keep number of pieces reasonable
        piece_length *= 2
    
    # Calculate pieces and get file size
    pieces, file_size = calculate_pieces(source_path, piece_length)
    
    # Create torrent metadata
    info = {
        'piece length': piece_length,
        'pieces': pieces,
        'name': os.path.basename(source_path),
        'length': file_size,
        'private': 0
    }
    
    metadata = {
        'announce': tracker_url,
        'created by': 'generate_sources.py',
        'creation date': int(os.path.getctime(source_path)),
        'info': info
    }
    
    # Generate the torrent file
    torrent_filename = os.path.basename(source_path) + '.torrent'
    torrent_path = os.path.join(output_dir, torrent_filename)
    
    # Ensure directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Save the torrent file
    with open(torrent_path, 'wb') as f:
        f.write(bencode(metadata))
    
    return torrent_path

def generate_config(template_path: str, output_path: str, torrent_path: str, source_path: str) -> None:
    """Generate a configuration file based on the template."""
    # Load template or use default
    if template_path and os.path.exists(template_path):
        with open(template_path, 'r') as f:
            config = yaml.safe_load(f.read())
    else:
        config = yaml.safe_load(DEFAULT_TEMPLATE)
    
    # Update the torrent and source URLs using current branch
    branch = get_current_branch()
    base_url = f'https://raw.githubusercontent.com/fabioibanez/Rogue-Packet/{branch}'
    config['bittorrent']['torrent_url'] = f"{base_url}/torrents/{os.path.basename(torrent_path)}"
    config['bittorrent']['seed_fileurl'] = f"{base_url}/seeder_sources/{os.path.basename(source_path)}"
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Save the configuration
    with open(output_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

def main():
    # clear && python3 generate_sources.py --source-dir seeder_sources --torrents-dir torrents --config-dir --template bittorent_deployer/config.yaml --count 10
    
    parser = argparse.ArgumentParser(description='Generate torrent files and configurations')
    parser.add_argument('--source-dir', default='seeder_sources', help='Directory for source files')
    parser.add_argument('--torrents-dir', default='torrents', help='Directory for torrent files')
    parser.add_argument('--config-dir', default='configs', help='Directory for configuration files')
    parser.add_argument('--template', help='Template configuration file')
    parser.add_argument('--size', type=int, default=16*1024*1024, help='Size of source files in bytes')
    parser.add_argument('--count', type=int, default=10, help='Number of files to generate')
    parser.add_argument('--tracker-url', default='udp://tracker.opentrackr.org:1337/announce',
                      help='Tracker URL for torrent files')
    
    args = parser.parse_args()
    
    for i in range(args.count):
        index = i + 1  # Use 1-based indexing for files
        
        # Generate source file
        source_path = generate_random_file(args.source_dir, args.size, index)
        print(f"Generated source file: {source_path}")
        
        # Create torrent
        torrent_path = create_torrent(source_path, args.torrents_dir, args.tracker_url)
        print(f"Generated torrent file: {torrent_path}")
        
        # Generate config
        config_path = os.path.join(args.config_dir, f"config_{index}.yaml")
        generate_config(args.template, config_path, torrent_path, source_path)
        print(f"Generated config file: {config_path}")

if __name__ == '__main__':
    main()
