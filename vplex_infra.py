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
        self.mock_tracker_path = None  # Will store the path to mock tracker file
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
    
    def _create_mock_tracker(self):
        """Create a mock tracker file containing all peer information."""
        if not self.net:
            raise RuntimeError("Network must be created before generating mock tracker")
        
        # Create timestamp for unique filename
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        mock_tracker_filename = f"mock_tracker_{timestamp}.json"
        self.mock_tracker_path = os.path.join(self.MAIN_SCRIPT_PATH, mock_tracker_filename)
        
        # Collect all peer information
        peers = []
        for i in range(1, self.num_hosts + 1):
            host = self.net.get(f'h{i}')
            if host:
                peer_info = {
                    "peer_id": f"peer_{i}",
                    "ip": host.IP(),
                    "port": 6881,
                    "host_name": f"h{i}",
                    "is_seeder": i <= self.num_seeders
                }
                peers.append(peer_info)
        
        # Create mock tracker data structure
        mock_tracker_data = {
            "tracker_info": {
                "experiment_id": timestamp,
                "created_at": datetime.datetime.now().isoformat(),
                "total_peers": len(peers),
                "seeders": self.num_seeders,
                "leechers": self.num_leechers
            },
            "peers": peers,
            "announce_list": [f"{peer['ip']}:{peer['port']}" for peer in peers]
        }
        
        # Write mock tracker file
        try:
            with open(self.mock_tracker_path, 'w') as f:
                json.dump(mock_tracker_data, f, indent=4)
            
            print(f"✓ Created mock tracker: {self.mock_tracker_path}")
            print(f"  - Total peers: {len(peers)}")
            print(f"  - Seeders: {self.num_seeders}, Leechers: {self.num_leechers}")
            
            return mock_tracker_filename  # Return just the filename for copying
            
        except Exception as e:
            print(f"⚠ Failed to create mock tracker file: {e}")
            return None
    
    def _build_bittorrent_command(self, host_ip, is_seeder=False):
        """Build the command string for running the BitTorrent client."""
        # Use just the filename since the torrent file will be copied to the working directory
        torrent_filename = os.path.basename(self.torrent_file)
        cmd_parts = ['python3', '-m', 'main', torrent_filename]
        
        # Add required arguments
        cmd_parts.extend(['--local-ip', host_ip])
        
        # Add mock tracker if it exists
        if self.mock_tracker_path:
            mock_tracker_filename = os.path.basename(self.mock_tracker_path)
            cmd_parts.extend(['--mock-tracker', mock_tracker_filename])
        
        # Add optional flags
        if self.verbose:
            cmd_parts.append('-v')
        if self.delete_torrent:
            cmd_parts.append('-d')
        if self.seed or is_seeder:
            cmd_parts.append('-s')
        
        return ' '.join(cmd_parts)
    
    def _copy_files_to_hosts(self):
        """Copy all necessary files to hosts."""
        print("Copying files to hosts...")
        
        files_copied = {
            'torrent': 0,
            'mock_tracker': 0,
            'seeder_file': 0
        }
        
        # Copy torrent file and mock tracker to ALL hosts
        for i in range(1, self.num_hosts + 1):
            host = self.net.get(f'h{i}')
            if host:
                # Ensure directory exists
                host.cmd(f'mkdir -p {self.MAIN_SCRIPT_PATH}')
                
                # Copy torrent file
                host.cmd(f'cp {self.torrent_file} {self.MAIN_SCRIPT_PATH}/')
                files_copied['torrent'] += 1
                
                # Copy mock tracker file if it exists
                if self.mock_tracker_path and os.path.exists(self.mock_tracker_path):
                    host.cmd(f'cp {self.mock_tracker_path} {self.MAIN_SCRIPT_PATH}/')
                    files_copied['mock_tracker'] += 1
        
        # Copy complete file ONLY to seeder hosts
        if self.seeder_file:
            for i in range(1, self.num_seeders + 1):
                host = self.net.get(f'h{i}')
                if host:
                    host.cmd(f'cp {self.seeder_file} {self.MAIN_SCRIPT_PATH}/')
                    files_copied['seeder_file'] += 1
                    print(f"  ✓ Seeder file copied to h{i}")
        
        # Print summary
        print(f"  ✓ Torrent file copied to {files_copied['torrent']} hosts")
        if files_copied['mock_tracker'] > 0:
            print(f"  ✓ Mock tracker copied to {files_copied['mock_tracker']} hosts")
        if files_copied['seeder_file'] > 0:
            print(f"  ✓ Complete file copied to {files_copied['seeder_file']} seeder(s) only")
    
    def _run_seeders(self):
        """Run seeders on the first num_seeders hosts."""
        if self.num_seeders == 0:
            print("No seeders to start")
            return []
            
        print(f"Starting {self.num_seeders} seeder(s)...")
        
        seeder_processes = []
        for i in range(1, self.num_seeders + 1):
            host = self.net.get(f'h{i}')
            if host:
                seeder_cmd = self._build_bittorrent_command(host.IP(), is_seeder=True)
                print(f"  Starting seeder h{i} ({host.IP()})")
                if self.verbose:
                    print(f"    Command: {seeder_cmd}")
                
                # Create log file for seeder
                seeder_log = os.path.join(self.mininet_log_dir, f"h{i}_seeder.log")
                
                # Run seeder in background with output redirection
                full_cmd = f'cd {self.MAIN_SCRIPT_PATH} && {seeder_cmd} > {seeder_log} 2>&1 &'
                host.cmd(full_cmd)
                
                seeder_processes.append((f'h{i}', None, seeder_log))
        
        print(f"Waiting 10 seconds for seeder(s) to initialize...")
        time.sleep(10)
        return seeder_processes
    
    def _run_leechers(self):
        """Run leechers on the remaining hosts after seeders."""
        if self.num_leechers == 0:
            print("No leechers to start")
            return []
            
        print(f"Starting {self.num_leechers} leecher(s)...")
        
        leecher_processes = []
        for i in range(self.num_seeders + 1, self.num_hosts + 1):
            host = self.net.get(f'h{i}')
            if host:
                leecher_cmd = self._build_bittorrent_command(host.IP(), is_seeder=False)
                print(f"  Starting leecher h{i} ({host.IP()})")
                if self.verbose:
                    print(f"    Command: {leecher_cmd}")
                
                # Create log file for leecher
                leecher_log = os.path.join(self.mininet_log_dir, f"h{i}_leecher.log")
                
                # Run leecher with output redirection
                full_cmd = f'cd {self.MAIN_SCRIPT_PATH} && {leecher_cmd} > {leecher_log} 2>&1'
                process = host.popen(full_cmd, shell=True)
                leecher_processes.append((f'h{i}', process, leecher_log))
        
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
                print(f"  Copied {filename}")
    
    def _run_bittorrent_clients(self):
        """Run BitTorrent seeders and leechers."""
        if not self.net:
            raise RuntimeError("Network not created. Call _create_network() first.")
        
        # Create mock tracker file first
        mock_tracker_filename = self._create_mock_tracker()
        if not mock_tracker_filename:
            print("⚠ Warning: Mock tracker creation failed, clients may not work properly")
        
        # Show all host IPs for reference
        print("\nHost assignments:")
        for i in range(1, self.num_hosts + 1):
            host = self.net.get(f'h{i}')
            if host:
                role = "seeder" if i <= self.num_seeders else "leecher"
                print(f"  h{i} ({role}): {host.IP()}")
        print()
        
        # Copy all files to hosts
        self._copy_files_to_hosts()
        
        # Start seeders first (if any)
        seeder_processes = []
        if self.num_seeders > 0 and self.seeder_file:
            seeder_processes = self._run_seeders()
        elif self.num_seeders > 0:
            print("⚠ Warning: Seeders specified but no seeder file provided")
        
        # Start leechers
        leecher_processes = self._run_leechers()
        
        # Combine all processes for monitoring
        all_processes = seeder_processes + leecher_processes
        
        # Wait for completion or interruption
        try:
            print(f"\n🚀 BitTorrent simulation running...")
            print(f"📁 Logs: {self.host_log_dir}")
            print("Press Ctrl+C to stop\n")
            
            while True:
                time.sleep(2)
                
                # Count active leechers
                active_leechers = [name for name, proc, log_file in leecher_processes 
                                 if proc and proc.poll() is None]
                
                if self.num_leechers > 0 and not active_leechers:
                    print("✅ All leechers completed!")
                    break
                elif self.num_leechers == 0:
                    # Only seeders running
                    print("🌱 Only seeders running (press Ctrl+C to stop)")
                    time.sleep(8)
                    
            # Copy logs and create summary
            self._copy_logs_to_host()
            self._create_summary_log(all_processes)
            
            print(f"\n🎉 Simulation completed! Logs: {self.host_log_dir}")
            self._print_log_summary()
            
        except KeyboardInterrupt:
            print("\n🛑 Stopping simulation...")
            for name, proc, log_file in leecher_processes:
                if proc and proc.poll() is None:
                    proc.terminate()
                    print(f"  Stopped {name}")
            
            self._copy_logs_to_host()
            self._create_summary_log(all_processes, interrupted=True)
            print(f"📁 Logs saved: {self.host_log_dir}")
    
    def _create_summary_log(self, all_processes, interrupted=False):
        """Create a summary log with run information."""
        summary_file = os.path.join(self.host_log_dir, "run_summary.log")
        
        with open(summary_file, 'w') as f:
            f.write(f"BitTorrent Mininet Simulation Summary\n")
            f.write(f"{'='*60}\n")
            f.write(f"Timestamp: {datetime.datetime.now()}\n")
            f.write(f"Status: {'INTERRUPTED' if interrupted else 'COMPLETED'}\n\n")
            
            f.write(f"Configuration:\n")
            f.write(f"  Torrent file: {self.torrent_file}\n")
            f.write(f"  Seeder file: {self.seeder_file or 'None'}\n")
            f.write(f"  Mock tracker: {os.path.basename(self.mock_tracker_path) if self.mock_tracker_path else 'None'}\n")
            f.write(f"  Topology: {self.topology_name}\n")
            f.write(f"  Network delay: {self.delay}\n")
            f.write(f"  Verbose mode: {self.verbose}\n\n")
            
            f.write(f"Network Setup:\n")
            f.write(f"  Seeders: {self.num_seeders}\n")
            f.write(f"  Leechers: {self.num_leechers}\n")
            f.write(f"  Total hosts: {self.num_hosts}\n\n")
            
            f.write(f"Host Information:\n")
            for i in range(1, self.num_hosts + 1):
                host = self.net.get(f'h{i}') if self.net else None
                role = "seeder" if i <= self.num_seeders else "leecher"
                f.write(f"  h{i} ({role}): {host.IP() if host else 'N/A'}\n")
            
            f.write(f"\nLog Files:\n")
            for name, proc, log_file in all_processes:
                log_filename = os.path.basename(log_file)
                f.write(f"  {log_filename}\n")
    
    def _print_log_summary(self):
        """Print a summary of available log files."""
        print(f"\n📋 Log files in {self.host_log_dir}:")
        
        # Print seeder logs
        for i in range(1, self.num_seeders + 1):
            seeder_log = os.path.join(self.host_log_dir, f"h{i}_seeder.log")
            if os.path.exists(seeder_log):
                print(f"  📄 h{i}_seeder.log")
        
        # Print leecher logs
        for i in range(self.num_seeders + 1, self.num_hosts + 1):
            leecher_log = os.path.join(self.host_log_dir, f"h{i}_leecher.log")
            if os.path.exists(leecher_log):
                print(f"  📄 h{i}_leecher.log")
        
        summary_file = os.path.join(self.host_log_dir, "run_summary.log")
        if os.path.exists(summary_file):
            print(f"  📄 run_summary.log")
    
    def _cleanup_processes(self, leecher_processes):
        """Clean up any remaining processes."""
        for name, proc, log_file in leecher_processes:
            if proc and proc.poll() is None:
                proc.terminate()
                print(f"Cleaned up {name}")
    
    def _cleanup(self):
        """Stop the network and cleanup resources."""
        print("🧹 Cleaning up...")
        
        if self.net:
            self.net.stop()
            self.net = None
            print("  ✓ Network stopped")
        
        # Clean up mock tracker file
        if self.mock_tracker_path and os.path.exists(self.mock_tracker_path):
            try:
                os.remove(self.mock_tracker_path)
                print(f"  ✓ Removed mock tracker: {os.path.basename(self.mock_tracker_path)}")
            except Exception as e:
                print(f"  ⚠ Could not remove mock tracker: {e}")
        
        # Clean up temporary mininet log directory
        if hasattr(self, 'mininet_log_dir') and os.path.exists(self.mininet_log_dir):
            try:
                shutil.rmtree(self.mininet_log_dir)
                print(f"  ✓ Removed temp logs: {self.mininet_log_dir}")
            except Exception as e:
                print(f"  ⚠ Could not remove temp logs: {e}")
    
    def run(self):
        """Complete workflow: validate, create network, run clients, cleanup."""
        try:
            # Install required packages first
            self._install_requirements()
            
            # Validate inputs
            self._validate_torrent_file()
            self._validate_seeder_file()
            self._validate_topology()
            
            # Create network and run simulation
            self._create_network()
            self._run_bittorrent_clients()
            
        except KeyboardInterrupt:
            print("\n⚠ Interrupted by user")
        except Exception as e:
            print(f"❌ Error: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
        finally:
            self._cleanup()


def _parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Run BitTorrent clients in Mininet simulation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic simulation with 1 seeder and 2 leechers
  python3 script.py torrent.torrent --seeder-file complete.txt
  
  # Custom peer counts with network delay
  python3 script.py torrent.torrent --seeders 2 --leechers 4 --delay 100ms --seeder-file complete.txt
  
  # Verbose mode
  python3 script.py torrent.torrent --seeder-file complete.txt -v
        """
    )
    
    parser.add_argument('torrent_file', help='Path to the torrent file')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose logging')
    parser.add_argument('-d', '--deletetorrent', action='store_true',
                        help='Delete any existing torrent folder (speeds up testing)')
    parser.add_argument('-s', '--seed', action='store_true',
                        help='Seed the torrent after downloading it')
    parser.add_argument('--seeders', type=int, default=1,
                        help='Number of seeder hosts (default: 1)')
    parser.add_argument('--leechers', type=int, default=2,
                        help='Number of leecher hosts (default: 2)')
    parser.add_argument('-t', '--topology', choices=['single'], 
                        default='single', help='Network topology (default: single)')
    parser.add_argument('--delay', default='0ms', 
                        help='Link delay, e.g., 10ms, 100ms, 1s (default: 0ms)')
    parser.add_argument('--seeder-file', 
                        help='Path to the complete file for seeding (required for seeders)')
    parser.add_argument('--no-auto-install', action='store_true',
                        help='Disable automatic package installation')
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = _parse_arguments()
    
    # Validate arguments
    if args.seeders < 0 or args.leechers < 0:
        print("❌ Error: Number of seeders and leechers must be non-negative")
        sys.exit(1)
    
    if args.seeders == 0 and args.leechers == 0:
        print("❌ Error: Must have at least one seeder or leecher")
        sys.exit(1)
    
    if args.seeders > 0 and not args.seeder_file:
        print("⚠ Warning: Seeders specified but no seeder file provided")
        print("   Seeders may not function properly without complete file")
    
    print(f"🚀 Starting BitTorrent Mininet Simulation")
    print(f"   Seeders: {args.seeders}, Leechers: {args.leechers}")
    print(f"   Network delay: {args.delay}")
    print()
    
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