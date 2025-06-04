#!/usr/bin/env python3
"""
Log File Monitor Script

Monitors a directory for the appearance of new non-streaming log files
and records the time it takes for each file to appear.

Usage: python log_monitor.py <directory_path>
"""

import os
import time
import json
import argparse
import signal
import sys
from pathlib import Path

def parse_filename(filename):
    """
    Parse log filename to extract region, type, and create simplified key.
    
    Example: 'us-west-1-leecher-0-propshare-feat-proportional-share.log'
    Returns: ('us-west-1-leecher-0.log', 'leecher', 'us-west-1')
    """
    if not filename.endswith('.log'):
        return None, None, None
    
    # Remove .log extension
    name_without_ext = filename.replace('.log', '')
    parts = name_without_ext.split('-')
    
    if len(parts) >= 4:
        # Extract region (e.g., 'us-west-1')
        region = f"{parts[0]}-{parts[1]}-{parts[2]}"
        
        # Extract type (e.g., 'leecher', 'seeder')
        file_type = parts[3]
        
        # Extract instance number
        instance_num = parts[4] if len(parts) > 4 else "0"
        
        # Create simplified key
        simplified_key = f"{region}-{file_type}-{instance_num}.log"
        
        return simplified_key, file_type, region
    
    return None, None, None

def monitor_directory(directory_path):
    """Monitor directory for new non-streaming log files."""
    results = {}
    start_time = time.time()
    
    # Get initial snapshot of files to avoid counting existing ones
    initial_files = set()
    if os.path.exists(directory_path):
        try:
            initial_files = set(os.listdir(directory_path))
        except PermissionError:
            print(f"Error: Permission denied accessing {directory_path}")
            sys.exit(1)
    
    seen_files = initial_files.copy()
    
    def signal_handler(sig, frame):
        print("\n\nInterrupted! Saving results...")
        save_results(results)
        print(f"Monitored for {time.time() - start_time:.2f} seconds total.")
        sys.exit(0)
    
    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    
    print(f"Monitoring directory: {directory_path}")
    print(f"Initial files found: {len([f for f in initial_files if f.endswith('.log') and not f.endswith('_stream.log')])}")
    print("Watching for new non-streaming log files...")
    print("Press Ctrl+C to stop and save results...\n")
    
    while True:
        try:
            if not os.path.exists(directory_path):
                print(f"Warning: Directory {directory_path} no longer exists")
                time.sleep(1)
                continue
                
            current_files = set(os.listdir(directory_path))
            
            # Find new files that weren't there at startup
            new_files = current_files - seen_files
            
            for filename in new_files:
                # Only process non-streaming log files
                if (filename.endswith('.log') and 
                    not filename.endswith('_stream.log') and
                    os.path.isfile(os.path.join(directory_path, filename))):
                    
                    elapsed = time.time() - start_time
                    simplified_key, file_type, region = parse_filename(filename)
                    
                    if simplified_key and file_type and region:
                        results[simplified_key] = {
                            "elapsed_seconds": round(elapsed, 2),
                            "type": file_type,
                            "region": region
                        }
                        print(f"✓ Found: {filename} after {elapsed:.2f} seconds")
                    else:
                        print(f"? Found unrecognized log file: {filename}")
                    
                    seen_files.add(filename)
            
            # Tight loop - check every 50ms for quick detection
            time.sleep(0.05)
            
        except PermissionError:
            print(f"Permission error accessing {directory_path}")
            time.sleep(1)
        except Exception as e:
            print(f"Error during monitoring: {e}")
            time.sleep(1)

def save_results(results):
    """Save results to JSON file."""
    if not results:
        print("No new log files were detected.")
        return
        
    output_file = "log_timing_results.json"
    try:
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, sort_keys=True)
        print(f"Results saved to {output_file}")
        print(f"Detected {len(results)} new log files:")
        for key, data in sorted(results.items()):
            print(f"  {key}: {data['elapsed_seconds']}s ({data['type']}, {data['region']})")
    except Exception as e:
        print(f"Error saving results: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="Monitor directory for new log file appearances",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python log_monitor.py /path/to/logs/
  python log_monitor.py ~/Rogue-Packet/logs/bravo_20250604_142814/

The script will monitor for non-streaming log files (files ending in .log 
but not _stream.log) and record when they appear relative to script startup.
        """
    )
    parser.add_argument("directory", help="Path to the directory to monitor")
    
    args = parser.parse_args()
    
    # Validate directory path
    directory_path = os.path.abspath(args.directory)
    if not os.path.exists(directory_path):
        print(f"Error: Directory '{directory_path}' does not exist")
        sys.exit(1)
    
    if not os.path.isdir(directory_path):
        print(f"Error: '{directory_path}' is not a directory")
        sys.exit(1)
    
    try:
        # Test if we can read the directory
        os.listdir(directory_path)
    except PermissionError:
        print(f"Error: Permission denied accessing '{directory_path}'")
        sys.exit(1)
    
    monitor_directory(directory_path)

if __name__ == "__main__":
    main()
