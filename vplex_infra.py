#!/usr/bin/python
from mininet.topo import Topo, SingleSwitchTopo
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.log import lg, info
from mininet.node import OVSController
import argparse
import time
import os
import datetime
import shutil
import subprocess
import sys
import json


class DelayedSingleSwitchTopo(Topo):
    """Single switch topology with configurable delay on all links."""
    
    def __init__(self, k=2, delay='0ms', **opts):
        self.k = k
        self.delay = delay
        super(DelayedSingleSwitchTopo, self).__init__(**opts)
    
    def build(self):
        switch = self.addSwitch('s1')
        
        for i in range(self.k):
            host = self.addHost(f'h{i+1}')
            self.addLink(host, switch, cls=TCLink, delay=self.delay)


class BitTorrentMininet:
    """
    A Mininet wrapper for running BitTorrent clients in a simulated network environment.
    """
    
    TOPOLOGY_MAP = {
        'single': DelayedSingleSwitchTopo
    }
    
    # Absolute path where main.py script should be run from
    MAIN_SCRIPT_PATH = "/home/ubuntu/Rogue-Packet"
    
    # Path to requirements.txt
    REQUIREMENTS_PATH = "/home/ubuntu/Rogue-Packet/requirements.txt"
    
    def __init__(self, torrent_file, verbose=False, delete_torrent=False, seed=False, 
                 num_seeders=1, num_leechers=2, topology='single', delay='0ms', seeder_file=None, 
                 auto_install=True):
        self.torrent_file = torrent_file
        self.verbose = verbose
        self.delete_torrent = delete_torrent
        self.seed = seed
        self.num_seeders = num_seeders
        self.num_leechers = num_leechers
        self.num_hosts = num_seeders + num_leechers  # Total hosts
        self.topology_name = topology
        self.delay = delay
        self.seeder_file = seeder_file
        self.auto_install = auto_install
        self.net = None
        self.mock_tracker_file = None  # Will be set when created
        self.log_dir = self._create_log_directory()  # Keep for backward compatibility
    
    def _install_requirements(self):
        """Install packages from requirements.txt if it exists."""
        if not self.auto_install:
            print("Auto-install disabled, skipping package installation")
            return
            
        if not os.path.exists(self.REQUIREMENTS_PATH):
            print(f"Requirements file not found at {self.REQUIREMENTS_PATH}, skipping package installation")
            return
        
        print(f"Installing packages from {self.REQUIREMENTS_PATH}...")
        
        try:
            # Try pip3 first (most common for Mininet)
            result = subprocess.run([
                'sudo', 'pip3', 'install', '-r', self.REQUIREMENTS_PATH
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                print("✓ Packages installed successfully with pip3")
                if self.verbose:
                    print("Installation output:", result.stdout)
            else:
                print("⚠ pip3 installation had issues, trying pip...")
                if self.verbose:
                    print("pip3 stderr:", result.stderr)
                
                # Fallback to regular pip
                result = subprocess.run([
                    'sudo', 'pip', 'install', '-r', self.REQUIREMENTS_PATH
                ], capture_output=True, text=True, timeout=300)
                
                if result.returncode == 0:
                    print("✓ Packages installed successfully with pip")
                    if self.verbose:
                        print("Installation output:", result.stdout)
                else:
                    print("⚠ Package installation failed")
                    print("Error:", result.stderr)
                    print("Continuing anyway - some functionality may not work")
                    
        except subprocess.TimeoutExpired:
            print("⚠ Package installation timed out after 5 minutes")
            print("Continuing anyway - some functionality may not work")
        except Exception as e:
            print(f"⚠ Error during package installation: {e}")
            print("Continuing anyway - some functionality may not work")
    
    def _create_log_directory(self):
        """Create a unique log directory for this run."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        torrent_name = os.path.splitext(os.path.basename(self.torrent_file))[0]
        
        # Create log directory on host filesystem
        host_log_dir = f"logs/{torrent_name}_{timestamp}"
        os.makedirs(host_log_dir, exist_ok=True)
        
        # Also create log directory accessible to Mininet hosts
        mininet_log_dir = f"/tmp/mininet_logs_{timestamp}"
        os.makedirs(mininet_log_dir, exist_ok=True)
        
        print(f"Created log directory: {host_log_dir}")
        print(f"Mininet log directory: {mininet_log_dir}")
        
        # Store both paths
        self.host_log_dir = host_log_dir
        self.mininet_log_dir = mininet_log_dir
        
        return host_log_dir
    
    def _validate_torrent_file(self):
        """Check if the torrent file exists."""
        if not os.path.exists(self.torrent_file):
            raise FileNotFoundError(f"Torrent file '{self.torrent_file}' not found")
    
    def _validate_seeder_file(self):
        """Check if the seeder file exists when specified."""
        if self.seeder_file and not os.path.exists(self.seeder_file):
            raise FileNotFoundError(f"Seeder file '{self.seeder_file}' not found")
    
    def _validate_topology(self):
        """Validate the topology choice."""
        if self.topology_name not in self.TOPOLOGY_MAP:
            available = ', '.join(self.TOPOLOGY_MAP.keys())
            raise ValueError(f"Invalid topology '{self.topology_name}'. Available: {available}")
    
    def _create_topology(self):
        """Create the specified topology with delay configuration."""
        topology_class = self.TOPOLOGY_MAP[self.topology_name]
        return topology_class(k=self.num_hosts, delay=self.delay)
    
    def _create_network(self):
        """Create and start the Mininet network."""
        lg.setLogLevel('info')
        print(f"Setting up {self.topology_name} topology with {self.num_hosts} hosts (delay: {self.delay})")
        
        topo = self._create_topology()
        self.net = Mininet(topo=topo, controller=OVSController, link=TCLink)
        self.net.start()
        
        print(f"Network started successfully")
        return self.net
    
    def _create_mock_tracker_file(self):
        """Create a mock tracker file with all host IPs for the experiment."""
        if not self.net:
            raise RuntimeError("Network not created. Cannot generate mock tracker file.")
        
        # Create mock tracker file in the main script directory
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        tracker_filename = f"mock_tracker_{timestamp}.json"
        self.mock_tracker_file = os.path.join(self.MAIN_SCRIPT_PATH, tracker_filename)
        
        # Collect all host IPs
        host_ips = []
        for i in range(1, self.num_hosts + 1):
            host = self.net.get(f'h{i}')
            if host:
                host_info = {
                    "host_id": f"h{i}",
                    "ip": host.IP(),
                    "port": 6881,  # Default BitTorrent port
                    "role": "seeder" if i <= self.num_seeders else "leecher"
                }
                host_ips.append(host_info)
        
        # Create mock tracker data
        tracker_data = {
            "experiment_id": timestamp,
            "total_hosts": self.num_hosts,
            "seeders": self.num_seeders,
            "leechers": self.num_leechers,
            "peers": host_ips
        }
        
        # Write tracker file
        with open(self.mock_tracker_file, 'w') as f:
            json.dump(tracker_data, f, indent=2)
        
        print(f"Created mock tracker file: {self.mock_tracker_file}")
        print(f"Mock tracker contains {len(host_ips)} peer(s)")
        
        return self.mock_tracker_file
        """Build the command string for running the BitTorrent client."""
        # Use just the filename since the torrent file will be copied to the working directory
        torrent_filename = os.path.basename(self.torrent_file)
        cmd_parts = ['python3', '-m', 'main', torrent_filename]
        
        # Add local IP argument
        cmd_parts.extend(['--local-ip', host_ip])
        
        if self.verbose:
            cmd_parts.append('-v')
        if self.delete_torrent:
            cmd_parts.append('-d')
        if self.seed or is_seeder:
            cmd_parts.append('-s')
        
        return ' '.join(cmd_parts)
    
    def _copy_files_to_hosts(self):
        """Copy torrent file and mock tracker to all hosts, seeder file only to seeder hosts."""
        print("Copying files to hosts...")
        
        # Copy torrent file to ALL hosts (seeders and leechers)
        for i in range(1, self.num_hosts + 1):
            host = self.net.get(f'h{i}')
            if host:
                # Ensure the main script directory exists and copy torrent file
                host.cmd(f'mkdir -p {self.MAIN_SCRIPT_PATH}')
                host.cmd(f'cp {self.torrent_file} {self.MAIN_SCRIPT_PATH}/')
                
                # Copy mock tracker file to all hosts
                if self.mock_tracker_file and os.path.exists(self.mock_tracker_file):
                    host.cmd(f'cp {self.mock_tracker_file} {self.MAIN_SCRIPT_PATH}/')
        
        # Copy seeder file ONLY to seeder hosts (h1 through h[num_seeders]) if specified
        if self.seeder_file:
            for i in range(1, self.num_seeders + 1):
                host = self.net.get(f'h{i}')
                if host:
                    host.cmd(f'cp {self.seeder_file} {self.MAIN_SCRIPT_PATH}/')
                    print(f"Copied seeder file '{self.seeder_file}' to seeder host h{i} at {self.MAIN_SCRIPT_PATH}")
        
        print(f"Torrent file copied to all {self.num_hosts} hosts")
        if self.mock_tracker_file:
            print(f"Mock tracker file copied to all {self.num_hosts} hosts")
        if self.seeder_file:
            print(f"Complete file copied to {self.num_seeders} seeder host(s) only")
    
    def _run_seeders(self):
        """Run seeders on the first num_seeders hosts."""
        print(f"Starting {self.num_seeders} seeder(s)...")
        
        seeder_processes = []
        for i in range(1, self.num_seeders + 1):
            host = self.net.get(f'h{i}')
            if host:
                seeder_cmd = self._build_bittorrent_command(host.IP(), is_seeder=True)
                print(f"Starting seeder on h{i} ({host.IP()}): {seeder_cmd}")
                
                # Create log file for seeder (accessible to Mininet host)
                seeder_log = os.path.join(self.mininet_log_dir, f"h{i}_seeder.log")
                
                # Change to main script directory and run seeder in background with output redirection
                full_cmd = f'cd {self.MAIN_SCRIPT_PATH} && {seeder_cmd} > {seeder_log} 2>&1 &'
                host.cmd(full_cmd)
                
                print(f"Seeder h{i} output will be logged to: {seeder_log}")
                seeder_processes.append((f'h{i}', None, seeder_log))  # No process handle for background commands
        
        print(f"Waiting 10 seconds for {self.num_seeders} seeder(s) to initialize...")
        time.sleep(10)
        return seeder_processes
    
    def _run_leechers(self):
        """Run leechers on the remaining hosts after seeders."""
        if self.num_leechers == 0:
            print("No leechers to start")
            return []
            
        print(f"Starting {self.num_leechers} leecher(s)...")
        
        leecher_processes = []
        # Leechers start from host number (num_seeders + 1)
        for i in range(self.num_seeders + 1, self.num_hosts + 1):
            host = self.net.get(f'h{i}')
            if host:
                leecher_cmd = self._build_bittorrent_command(host.IP(), is_seeder=False)
                print(f"Starting leecher on h{i} ({host.IP()}): {leecher_cmd}")
                
                # Create log file for this leecher (accessible to Mininet host)
                leecher_log = os.path.join(self.mininet_log_dir, f"h{i}_leecher.log")
                
                # Change to main script directory and run leecher with output redirection
                full_cmd = f'cd {self.MAIN_SCRIPT_PATH} && {leecher_cmd} > {leecher_log} 2>&1'
                process = host.popen(full_cmd, shell=True)
                leecher_processes.append((f'h{i}', process, leecher_log))
                
                print(f"Leecher h{i} output will be logged to: {leecher_log}")
        
        return leecher_processes
    
    def _copy_logs_to_host(self):
        """Copy log files from Mininet directory to host directory."""
        print(f"Copying logs from {self.mininet_log_dir} to {self.host_log_dir}")
        
        # Copy all log files
        for filename in os.listdir(self.mininet_log_dir):
            if filename.endswith('.log'):
                src = os.path.join(self.mininet_log_dir, filename)
                dst = os.path.join(self.host_log_dir, filename)
                shutil.copy2(src, dst)
                print(f"Copied {filename}")
    
    def _run_bittorrent_clients(self):
        """Run BitTorrent seeders and leechers."""
        if not self.net:
            raise RuntimeError("Network not created. Call _create_network() first.")
        
        # Create mock tracker file with all host IPs
        self._create_mock_tracker_file()
        
        # Show all host IPs for reference
        print("Available hosts:")
        for i in range(1, self.num_hosts + 1):
            host = self.net.get(f'h{i}')
            if host:
                if i <= self.num_seeders:
                    role = "seeder"
                else:
                    role = "leecher"
                print(f"  h{i} ({role}): {host.IP()}")
        
        # Copy necessary files to hosts
        self._copy_files_to_hosts()
        
        # Start seeders first
        seeder_processes = []
        if self.seeder_file and self.num_seeders > 0:
            seeder_processes = self._run_seeders()
        
        # Start leechers after delay
        leecher_processes = self._run_leechers()
        
        # Combine all processes for monitoring
        all_processes = seeder_processes + leecher_processes
        
        # Wait for leechers to complete (or user interruption)
        try:
            print("BitTorrent clients running. Press Ctrl+C to stop.")
            print(f"All logs are being written to: {self.host_log_dir}")
            
            while True:
                time.sleep(1)
                # Check if any leechers are still running
                active_leechers = [name for name, proc, log_file in leecher_processes if proc and proc.poll() is None]
                if not active_leechers and self.num_leechers > 0:
                    print("All leechers completed.")
                    self._copy_logs_to_host()
                    self._create_summary_log(all_processes)
                    break
                elif self.num_leechers == 0:
                    # Only seeders running, wait for user interruption
                    print("Only seeders running. Press Ctrl+C to stop.")
                    time.sleep(5)  # Check less frequently
                    
            # Show completion status
            print(f"\nRun completed. Logs available in: {self.host_log_dir}")
            self._print_log_summary()
            
        except KeyboardInterrupt:
            print("\nStopping all processes...")
            for name, proc, log_file in leecher_processes:
                if proc and proc.poll() is None:
                    proc.terminate()
                    print(f"Stopped {name}")
            self._copy_logs_to_host()
            self._create_summary_log(all_processes, interrupted=True)
    
    def _create_summary_log(self, all_processes, interrupted=False):
        """Create a summary log with run information."""
        summary_file = os.path.join(self.host_log_dir, "run_summary.log")
        
        with open(summary_file, 'w') as f:
            f.write(f"BitTorrent Mininet Run Summary\n")
            f.write(f"{'='*50}\n")
            f.write(f"Timestamp: {datetime.datetime.now()}\n")
            f.write(f"Torrent file: {self.torrent_file}\n")
            f.write(f"Seeder file: {self.seeder_file or 'None'}\n")
            f.write(f"Mock tracker file: {self.mock_tracker_file or 'None'}\n")
            f.write(f"Topology: {self.topology_name}\n")
            f.write(f"Number of seeders: {self.num_seeders}\n")
            f.write(f"Number of leechers: {self.num_leechers}\n")
            f.write(f"Total hosts: {self.num_hosts}\n")
            f.write(f"Network delay: {self.delay}\n")
            f.write(f"Verbose mode: {self.verbose}\n")
            f.write(f"Auto-install: {self.auto_install}\n")
            f.write(f"Status: {'INTERRUPTED' if interrupted else 'COMPLETED'}\n")
            f.write(f"\nHost Information:\n")
            
            # List seeders 
            for i in range(1, self.num_seeders + 1):
                host = self.net.get(f'h{i}') if self.net else None
                f.write(f"h{i} (seeder): {host.IP() if host else 'N/A'}\n")
            
            # List leechers
            for i in range(self.num_seeders + 1, self.num_hosts + 1):
                host = self.net.get(f'h{i}') if self.net else None
                f.write(f"h{i} (leecher): {host.IP() if host else 'N/A'}\n")
            
            f.write(f"\nLog Files:\n")
            for name, proc, log_file in all_processes:
                log_filename = os.path.basename(log_file)
                role = "seeder" if "seeder" in log_filename else "leecher"
                f.write(f"{role.capitalize()} log: {log_filename}\n")
    
    def _print_log_summary(self):
        """Print a summary of available log files."""
        print(f"\nLog files created in {self.host_log_dir}:")
        
        # Print seeder logs
        for i in range(1, self.num_seeders + 1):
            seeder_log = os.path.join(self.host_log_dir, f"h{i}_seeder.log")
            if os.path.exists(seeder_log):
                print(f"  - h{i}_seeder.log (seeder output)")
        
        # Print leecher logs
        for i in range(self.num_seeders + 1, self.num_hosts + 1):
            leecher_log = os.path.join(self.host_log_dir, f"h{i}_leecher.log")
            if os.path.exists(leecher_log):
                print(f"  - h{i}_leecher.log (leecher output)")
        
        summary_file = os.path.join(self.host_log_dir, "run_summary.log")
        if os.path.exists(summary_file):
            print(f"  - run_summary.log (run configuration and summary)")
    
    def _cleanup_processes(self, leecher_processes):
        """Clean up any remaining processes."""
        for name, proc, log_file in leecher_processes:
            if proc.poll() is None:
                proc.terminate()
                print(f"Cleaned up {name}")
    
    def _cleanup(self):
        """Stop the network and cleanup resources."""
        if self.net:
            print("Stopping network...")
            self.net.stop()
            self.net = None
        
        # Clean up mock tracker file
        if self.mock_tracker_file and os.path.exists(self.mock_tracker_file):
            os.remove(self.mock_tracker_file)
            print(f"Cleaned up mock tracker file: {self.mock_tracker_file}")
        
        # Clean up temporary mininet log directory
        if hasattr(self, 'mininet_log_dir') and os.path.exists(self.mininet_log_dir):
            shutil.rmtree(self.mininet_log_dir)
            print(f"Cleaned up temporary log directory: {self.mininet_log_dir}")
    
    def run(self):
        """Complete workflow: validate, create network, run clients, cleanup."""
        try:
            # Install required packages first
            self._install_requirements()
            
            self._validate_torrent_file()
            self._validate_seeder_file()
            self._validate_topology()
            self._create_network()
            self._run_bittorrent_clients()
            
        except KeyboardInterrupt:
            print("\nInterrupted by user")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            self._cleanup()


def _parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Run BitTorrent client in Mininet')
    parser.add_argument('torrent_file', help='Path to the torrent file')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose logging for peer selection')
    parser.add_argument('-d', '--deletetorrent', action='store_true',
                        help='Delete any existing, previous torrent folder')
    parser.add_argument('-s', '--seed', action='store_true',
                        help='Seed the torrent after downloading it')
    parser.add_argument('--seeders', type=int, default=1,
                        help='Number of seeder hosts (default: 1)')
    parser.add_argument('--leechers', type=int, default=2,
                        help='Number of leecher hosts (default: 2)')
    parser.add_argument('-t', '--topology', choices=['single'], 
                        default='single', help='Network topology (default: single)')
    parser.add_argument('--delay', default='0ms', 
                        help='Link delay (e.g., 10ms, 100ms, 1s) (default: 0ms)')
    parser.add_argument('--seeder-file', 
                        help='Path to the complete file for seeding (seeders will have this file)')
    parser.add_argument('--no-auto-install', action='store_true',
                        help='Disable automatic package installation from requirements.txt')
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = _parse_arguments()
    
    # Validate arguments
    if args.seeders < 0 or args.leechers < 0:
        print("Error: Number of seeders and leechers must be non-negative")
        sys.exit(1)
    
    if args.seeders == 0 and args.leechers == 0:
        print("Error: Must have at least one seeder or leecher")
        sys.exit(1)
    
    if args.seeders > 0 and not args.seeder_file:
        print("Warning: Seeders specified but no seeder file provided. Seeders may not function properly.")
    
    # Create and run BitTorrent Mininet instance
    bt_mininet = BitTorrentMininet(
        torrent_file=args.torrent_file,
        verbose=args.verbose,
        delete_torrent=args.deletetorrent,
        seed=args.seed,
        num_seeders=args.seeders,
        num_leechers=args.leechers,
        topology=args.topology,
        delay=args.delay,
        seeder_file=args.seeder_file,
        auto_install=not args.no_auto_install
    )
    
    bt_mininet.run()


if __name__ == '__main__':
    main()