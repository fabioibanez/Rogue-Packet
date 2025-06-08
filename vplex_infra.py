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
import re


class Colors:
    """ANSI color codes for terminal output."""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    END = '\033[0m'

    @classmethod
    def colorize(cls, text, color):
        """Add color to text."""
        return f"{color}{text}{cls.END}"

    @classmethod
    def success(cls, text):
        return cls.colorize(f"✓ {text}", cls.GREEN)
    
    @classmethod
    def warning(cls, text):
        return cls.colorize(f"⚠ {text}", cls.YELLOW)
    
    @classmethod
    def error(cls, text):
        return cls.colorize(f"❌ {text}", cls.RED)
    
    @classmethod
    def info(cls, text):
        return cls.colorize(f"ℹ {text}", cls.BLUE)
    
    @classmethod
    def network(cls, text):
        return cls.colorize(text, cls.CYAN)
    
    @classmethod
    def file_op(cls, text):
        return cls.colorize(text, cls.MAGENTA)


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
                 auto_install=True, interpreter="python3"):
        self.torrent_file = os.path.abspath(torrent_file)
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
        self.interpreter = interpreter

    def _install_requirements(self):
        """Install packages from requirements.txt if it exists."""
        if not self.auto_install:
            print(Colors.info("Auto-install disabled, skipping package installation"))
            return
            
        if not os.path.exists(self.REQUIREMENTS_PATH):
            print(Colors.warning(f"Requirements file not found at {self.REQUIREMENTS_PATH}"))
            return
        
        print(Colors.info(f"Installing packages from {self.REQUIREMENTS_PATH}..."))
        
        try:
            result = subprocess.run([
                'sudo', 'pip3', 'install', '-r', self.REQUIREMENTS_PATH
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                print(Colors.success("Packages installed successfully with pip3"))
                if self.verbose:
                    print(f"Installation output: {result.stdout}")
            else:
                print(Colors.warning("pip3 installation had issues, trying pip..."))
                if self.verbose:
                    print(f"pip3 stderr: {result.stderr}")
                
                result = subprocess.run([
                    'sudo', 'pip', 'install', '-r', self.REQUIREMENTS_PATH
                ], capture_output=True, text=True, timeout=300)
                
                if result.returncode == 0:
                    print(Colors.success("Packages installed successfully with pip"))
                else:
                    print(Colors.warning("Package installation failed - continuing anyway"))
                    if self.verbose:
                        print(f"Error: {result.stderr}")
                    
        except subprocess.TimeoutExpired:
            print(Colors.warning("Package installation timed out - continuing anyway"))
        except Exception as e:
            print(Colors.warning(f"Error during package installation: {e} - continuing anyway"))
    
    def _create_log_directory(self):
        """Create a unique log directory for this run."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        torrent_name = os.path.splitext(os.path.basename(self.torrent_file))[0]
        
        host_log_dir = os.path.abspath(f"logs/{torrent_name}_{timestamp}")
        os.makedirs(host_log_dir, exist_ok=True)
        
        print(Colors.file_op(f"📁 Created log directory: {host_log_dir}"))
        print(Colors.info("📡 Logs will stream in real-time"))
        
        self.host_log_dir = host_log_dir
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
        print(Colors.network(f"🌐 Setting up {self.topology_name} topology: {self.num_hosts} hosts, {self.delay} delay"))
        
        topo = self._create_topology()
        self.net = Mininet(topo=topo, controller=OVSController, link=TCLink)
        self.net.start()
        
        print(Colors.success("Network started"))
        return self.net
    
    def _create_mock_tracker(self):
        """Create a mock tracker file containing all peer information."""
        if not self.net:
            raise RuntimeError("Network must be created before generating mock tracker")
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.mock_tracker_path = f"/tmp/mock_tracker_{timestamp}.json"
        return self.mock_tracker_path
    
    # add a parameter for the parent working directory
    def _build_bittorrent_command(self, host_ip, is_seeder=False, working_dir=None):
        """Build the command string for running the BitTorrent client."""
        # Use just the filename since the torrent file will be copied to the working directory
        
        if working_dir is not None:
            if os.path.exists(working_dir): shutil.rmtree(working_dir)
            os.makedirs(working_dir, mode=0o777, exist_ok=True)
            os.chmod(working_dir, 0o777)

        torrent_filename = self.torrent_file
        main_path = os.path.join(os.path.dirname(__file__), "main.py")
        cmd_parts = [sys.executable, main_path, torrent_filename]
        
        # Add required arguments
        cmd_parts.extend(['--local-ip', host_ip])
        
        # Add mock tracker if it exists
        if self.mock_tracker_path:
            cmd_parts.extend(['--mock-tracker', self.mock_tracker_path])
        
        # Add optional flags
        if self.verbose:
            cmd_parts.append('-v')
        if self.delete_torrent:
            cmd_parts.append('-d')
        if self.seed or is_seeder:
            cmd_parts.append('-s')
        
        command = ' '.join(cmd_parts)
        if working_dir:
            return f'cd {working_dir} && {command}'
        else:
            return f'cd {self.MAIN_SCRIPT_PATH} && {command}'

    
    def _copy_files_to_hosts(self):
        """Copy all necessary files to hosts."""
        print(Colors.file_op("📋 Copying files to hosts..."))
        
        files_copied = {'torrent': 0, 'mock_tracker': 0, 'seeder_file': 0}
        
        # Copy torrent file and mock tracker to ALL hosts
        for i in range(1, self.num_hosts + 1):
            host = self.net.get(f'h{i}')
            if host:
                host.cmd(f'mkdir -p {self.MAIN_SCRIPT_PATH}')
                host.cmd(f'cp {self.torrent_file} {self.MAIN_SCRIPT_PATH}/')
                files_copied['torrent'] += 1
                
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
        
        # Print summary
        print(Colors.success(f"Torrent file → {files_copied['torrent']} hosts"))
        if files_copied['mock_tracker'] > 0:
            print(Colors.success(f"Mock tracker → {files_copied['mock_tracker']} hosts"))
        if files_copied['seeder_file'] > 0:
            print(Colors.success(f"Complete file → {files_copied['seeder_file']} seeder(s) only"))
    
    def _run_seeders(self):
        """Run seeders on the first num_seeders hosts."""
        if self.num_seeders == 0:
            print(Colors.info("No seeders to start"))
            return []
            
        print(Colors.colorize(f"🌱 Starting {self.num_seeders} seeder(s)...", Colors.GREEN))
        
        seeder_processes = []
        for i in range(1, self.num_seeders + 1):
            host = self.net.get(f'h{i}')
            if host:
                seeder_cmd = self._build_bittorrent_command(host.IP(), is_seeder=True)
                seeder_log = os.path.join(self.host_log_dir, f"h{i}_seeder.log")
                
                print(f"  {Colors.network(f'h{i}')} ({host.IP()}) → {Colors.file_op(f'h{i}_seeder.log')}")
                if self.verbose:
                    print(f"    Command: {seeder_cmd}")
                
                full_cmd = f'cd {self.MAIN_SCRIPT_PATH} && {seeder_cmd} > {seeder_log} 2>&1 &'
                host.cmd(full_cmd)
                seeder_processes.append((f'h{i}', None, seeder_log))
        
        print(Colors.info("Waiting 10 seconds for seeder(s) to initialize..."))
        time.sleep(10)
        return seeder_processes
    
    def _run_leechers(self):
        """Run leechers on the remaining hosts after seeders."""
        if self.num_leechers == 0:
            print(Colors.info("No leechers to start"))
            return []
            
        print(Colors.colorize(f"📥 Starting {self.num_leechers} leecher(s)...", Colors.BLUE))
        
        leecher_processes = []
        for i in range(self.num_seeders + 1, self.num_hosts + 1):
            host = self.net.get(f'h{i}')
            if host:
                working_dir = f'/tmp/leecher_{i}'

                leecher_cmd = self._build_bittorrent_command(host.IP(), is_seeder=False, working_dir=working_dir)

                leecher_log = os.path.join(self.host_log_dir, f"h{i}_leecher.log")
                
                print(f"  {Colors.network(f'h{i}')} ({host.IP()}) → {Colors.file_op(f'h{i}_leecher.log')}")
                if self.verbose:
                    print(f"    Command: {leecher_cmd}")
                
                full_cmd = f'{leecher_cmd} > {leecher_log} 2>&1'
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
            print(Colors.warning("Mock tracker creation failed - clients may not work properly"))
        
        # Show host assignments
        print(Colors.colorize("\n🏠 Host assignments:", Colors.BOLD))
        for i in range(1, self.num_hosts + 1):
            host = self.net.get(f'h{i}')
            if host:
                role = "seeder" if i <= self.num_seeders else "leecher"
                role_color = Colors.GREEN if role == "seeder" else Colors.BLUE
                print(f"  {Colors.network(f'h{i}')} ({role_color}{role}{Colors.END}): {host.IP()}")
        print()
        
        self._copy_files_to_hosts()
        
        # Start processes
        seeder_processes = []
        if self.num_seeders > 0 and self.seeder_file:
            seeder_processes = self._run_seeders()
        elif self.num_seeders > 0:
            print(Colors.warning("Seeders specified but no seeder file provided"))
        
        leecher_processes = self._run_leechers()
        all_processes = seeder_processes + leecher_processes
        
        # Monitor simulation
        try:
            print(Colors.colorize(f"\n🚀 BitTorrent simulation running...", Colors.BOLD))
            print(Colors.file_op(f"📁 Real-time logs: {self.host_log_dir}"))
            print(Colors.info(f"💡 Monitor logs: tail -f {self.host_log_dir}/*.log"))
            print(Colors.info("Press Ctrl+C to stop\n"))
            
            while True:
                time.sleep(2)
                active_leechers = [name for name, proc, log_file in leecher_processes 
                                 if proc and proc.poll() is None]
                
                if self.num_leechers > 0 and not active_leechers:
                    print(Colors.success("All leechers completed!"))
                    break
                elif self.num_leechers == 0:
                    print(Colors.info("Only seeders running (press Ctrl+C to stop)"))
                    time.sleep(8)
                    
            print(Colors.colorize(f"\n🎉 Simulation completed!", Colors.BOLD + Colors.GREEN))
            print(Colors.file_op(f"📁 Logs: {self.host_log_dir}"))
            self._print_log_summary()
            
        except KeyboardInterrupt:
            print(Colors.colorize("\n🛑 Stopping simulation...", Colors.YELLOW))
            for name, proc, log_file in leecher_processes:
                if proc and proc.poll() is None:
                    proc.terminate()
                    print(f"  {Colors.warning(f'Stopped {name}')}")
            
            print(Colors.file_op(f"📁 Logs saved: {self.host_log_dir}"))
    
    def _parse_leecher_log(self, log_file):
        """Parse a leecher log file and extract the last progress line.
        
        Returns:
            dict: Dictionary containing node, bytes, and seconds, or None if no valid line found
        """
        last_progress = None
        node = os.path.basename(log_file).split('_')[0]  # Extract h1, h2, etc.
        
        try:
            with open(log_file, 'r') as f:
                for line in f:
                    # Match lines like: Connected peers: 2 - 84.49% completed | 991/1173 pieces | X bytes | XXXs elapsed
                    match = re.search(r'Connected peers:.+\| (\d+) bytes \| (\d+)s elapsed', line)
                    if match:
                        bytes_transferred = int(match.group(1))
                        seconds_elapsed = int(match.group(2))
                        last_progress = {
                            "node": node,
                            "bytes": bytes_transferred,
                            "seconds": seconds_elapsed
                        }
        except Exception as e:
            print(Colors.warning(f"Could not parse log file {log_file}: {e}"))
            return None
            
        return last_progress

    def _print_log_summary(self):
        """Print a summary of available log files and generate JSON summary."""
        print(f"\n📋 Log files in {self.host_log_dir}:")
        
        # Print seeder logs
        for i in range(1, self.num_seeders + 1):
            seeder_log = os.path.join(self.host_log_dir, f"h{i}_seeder.log")
            if os.path.exists(seeder_log):
                print(f"  📄 h{i}_seeder.log")
        
        # Print leecher logs and collect progress data
        progress_data = []
        for i in range(self.num_seeders + 1, self.num_hosts + 1):
            leecher_log = os.path.join(self.host_log_dir, f"h{i}_leecher.log")
            if os.path.exists(leecher_log):
                print(f"  📄 h{i}_leecher.log")
                progress = self._parse_leecher_log(leecher_log)
                if progress:
                    progress_data.append(progress)
        
        # Save progress data as JSON
        if progress_data:
            json_file = os.path.join(self.host_log_dir, "progress_summary.json")
            try:
                with open(json_file, 'w') as f:
                    json.dump(progress_data, f, indent=2)
                print(f"  📄 progress_summary.json")
            except Exception as e:
                print(Colors.warning(f"Could not save progress summary: {e}"))


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
                print(f"  ✓ Removed mock tracker: {self.mock_tracker_path}")
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
    parser.add_argument('--interpreter', type=str, help='Python interpreter to use for hosts')
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = _parse_arguments()
    
    # Validate arguments
    if args.seeders < 0 or args.leechers < 0:
        print(Colors.error("Number of seeders and leechers must be non-negative"))
        sys.exit(1)
    
    if args.seeders == 0 and args.leechers == 0:
        print(Colors.error("Must have at least one seeder or leecher"))
        sys.exit(1)
    
    if args.seeders > 0 and not args.seeder_file:
        print(Colors.warning("Seeders specified but no seeder file provided"))
        print(Colors.info("Seeders may not function properly without complete file"))
    
    # Welcome message
    print(Colors.colorize(f"🚀 BitTorrent Mininet Simulation", Colors.BOLD + Colors.CYAN))
    print(Colors.info(f"Seeders: {args.seeders}, Leechers: {args.leechers}, Delay: {args.delay}"))
    print()
    
    # Create and run simulation
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
        auto_install=not args.no_auto_install,
        interpreter=args.interpreter or "python3"
    )
    
    bt_mininet.run()


if __name__ == '__main__':
    main()
