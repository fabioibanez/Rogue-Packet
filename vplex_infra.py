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
    
    def __init__(self, torrent_file, verbose=False, delete_torrent=False, seed=False, 
                 num_hosts=3, topology='single', delay='0ms', seeder_file=None):
        self.torrent_file = torrent_file
        self.verbose = verbose
        self.delete_torrent = delete_torrent
        self.seed = seed
        self.num_hosts = num_hosts
        self.topology_name = topology
        self.delay = delay
        self.seeder_file = seeder_file
        self.net = None
        self.venv_path = f"{self.MAIN_SCRIPT_PATH}/venv"
        self.log_dir = self._create_log_directory()  # Keep for backward compatibility
    
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
    
    def _setup_host_environment(self, host, host_name):
        """Set up a virtual environment on a host and install requirements."""
        print(f"Setting up virtual environment on {host_name}...")
        
        # Ensure main script directory exists
        host.cmd(f'mkdir -p {self.MAIN_SCRIPT_PATH}')
        
        # Create virtual environment
        print(f"Creating venv on {host_name}...")
        venv_result = host.cmd(f'cd {self.MAIN_SCRIPT_PATH} && python3 -m venv venv')
        
        # Check if venv was created successfully
        venv_check = host.cmd(f'[ -f {self.venv_path}/bin/python ] && echo "venv_ok" || echo "venv_failed"')
        if 'venv_failed' in venv_check:
            print(f"✗ Failed to create venv on {host_name}")
            return False
        
        print(f"✓ Virtual environment created on {host_name}")
        
        # Upgrade pip in venv
        host.cmd(f'{self.venv_path}/bin/python -m pip install --upgrade pip --quiet')
        
        # Install requirements.txt if it exists
        requirements_path = f"{self.MAIN_SCRIPT_PATH}/requirements.txt"
        req_check = host.cmd(f'[ -f {requirements_path} ] && echo "req_exists" || echo "req_missing"')
        
        if 'req_exists' in req_check:
            print(f"Installing requirements.txt on {host_name}...")
            install_result = host.cmd(f'{self.venv_path}/bin/pip install -r {requirements_path} --quiet')
            print(f"✓ Requirements installed on {host_name}")
        else:
            print(f"⚠ No requirements.txt found at {requirements_path}")
        
        # Test critical imports
        test_result = host.cmd(f'{self.venv_path}/bin/python -c "import sys; print(\\"Python:\\", sys.version)" 2>&1')
        print(f"✓ Environment setup completed for {host_name}: {test_result.strip()}")
        
        return True
    
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
    
    def _build_bittorrent_command(self, host_ip, is_seeder=False):
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
        
        base_cmd = ' '.join(cmd_parts)
        
        # Add environment activation if conda environment is detected
        env_cmd = self._build_environment_command()
        if env_cmd:
            return f"{env_cmd} && {base_cmd}"
        else:
            return base_cmd
    
    def _copy_files_to_hosts(self):
        """Copy torrent file to all hosts, seeder file to seeder host, and set up virtual environments."""
        print("Copying files to hosts and setting up virtual environments...")
        
        # Copy torrent file to the main script directory for all hosts and set up venv
        for i in range(1, self.num_hosts + 1):
            host = self.net.get(f'h{i}')
            if host:
                host_name = f'h{i}'
                print(f"Setting up {host_name}...")
                
                # Set up virtual environment and install requirements
                success = self._setup_host_environment(host, host_name)
                if not success:
                    print(f"⚠ Environment setup failed for {host_name}, but continuing...")
                
                # Copy torrent file
                host.cmd(f'cp {self.torrent_file} {self.MAIN_SCRIPT_PATH}/')
                print(f"✓ Copied torrent file to {host_name}")
        
        # Copy seeder file to seeder host (h1) if specified
        if self.seeder_file:
            h1 = self.net.get('h1')
            h1.cmd(f'cp {self.seeder_file} {self.MAIN_SCRIPT_PATH}/')
            print(f"✓ Copied seeder file '{self.seeder_file}' to seeder host h1")
        
        print("✓ File copying and virtual environment setup completed.")
    
    def _run_seeder(self):
        """Run the seeder on h1."""
        h1 = self.net.get('h1')
        seeder_cmd = self._build_bittorrent_command(h1.IP(), is_seeder=True)
        
        print(f"Starting seeder on h1 ({h1.IP()}): {seeder_cmd}")
        
        # Create log file for seeder (accessible to Mininet host)
        seeder_log = os.path.join(self.mininet_log_dir, "h1_seeder.log")
        
        # Change to main script directory and run seeder in background with output redirection
        full_cmd = f'cd {self.MAIN_SCRIPT_PATH} && {seeder_cmd} > {seeder_log} 2>&1 &'
        h1.cmd(full_cmd)
        
        print(f"Seeder output will be logged to: {seeder_log}")
        print("Waiting 10 seconds for seeder to initialize...")
        time.sleep(10)
    
    def _run_leechers(self):
        """Run leechers on remaining hosts."""
        print("Starting leechers...")
        
        leecher_processes = []
        for i in range(2, self.num_hosts + 1):
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
        """Run BitTorrent seeder and leechers."""
        if not self.net:
            raise RuntimeError("Network not created. Call _create_network() first.")
        
        # Show all host IPs for reference
        print("Available hosts:")
        for i in range(1, self.num_hosts + 1):
            host = self.net.get(f'h{i}')
            if host:
                role = "seeder" if i == 1 else "leecher"
                print(f"  h{i} ({role}): {host.IP()}")
        
        # Copy necessary files to hosts
        self._copy_files_to_hosts()
        
        # Show environment information
        print(f"Using virtual environment: {self.venv_path}")
        
        # Start seeder first
        if self.seeder_file:
            self._run_seeder()
        
        # Start leechers after delay
        leecher_processes = self._run_leechers()
        
        # Wait for leechers to complete (or user interruption)
        try:
            print("BitTorrent clients running. Press Ctrl+C to stop.")
            print(f"All logs are being written to: {self.host_log_dir}")
            
            while True:
                time.sleep(1)
                # Check if any leechers are still running
                active_leechers = [name for name, proc, log_file in leecher_processes if proc.poll() is None]
                if not active_leechers:
                    print("All leechers completed.")
                    self._copy_logs_to_host()
                    self._create_summary_log(leecher_processes)
                    break
                    
            # Show completion status
            print(f"\nRun completed. Logs available in: {self.host_log_dir}")
            self._print_log_summary()
            
        except KeyboardInterrupt:
            print("\nStopping all processes...")
            for name, proc, log_file in leecher_processes:
                if proc.poll() is None:
                    proc.terminate()
                    print(f"Stopped {name}")
            self._copy_logs_to_host()
            self._create_summary_log(leecher_processes, interrupted=True)
    
    def _create_summary_log(self, leecher_processes, interrupted=False):
        """Create a summary log with run information."""
        summary_file = os.path.join(self.host_log_dir, "run_summary.log")
        
        with open(summary_file, 'w') as f:
            f.write(f"BitTorrent Mininet Run Summary\n")
            f.write(f"{'='*50}\n")
            f.write(f"Timestamp: {datetime.datetime.now()}\n")
            f.write(f"Torrent file: {self.torrent_file}\n")
            f.write(f"Seeder file: {self.seeder_file or 'None'}\n")
            f.write(f"Topology: {self.topology_name}\n")
            f.write(f"Number of hosts: {self.num_hosts}\n")
            f.write(f"Network delay: {self.delay}\n")
            f.write(f"Verbose mode: {self.verbose}\n")
            f.write(f"Status: {'INTERRUPTED' if interrupted else 'COMPLETED'}\n")
            f.write(f"\nHost Information:\n")
            f.write(f"h1 (seeder): {self.net.get('h1').IP() if self.net else 'N/A'}\n")
            
            for i in range(2, self.num_hosts + 1):
                host = self.net.get(f'h{i}') if self.net else None
                f.write(f"h{i} (leecher): {host.IP() if host else 'N/A'}\n")
            
            f.write(f"\nLog Files:\n")
            f.write(f"Seeder log: h1_seeder.log\n")
            for name, proc, log_file in leecher_processes:
                log_filename = os.path.basename(log_file)
                f.write(f"Leecher log: {log_filename}\n")
    
    def _print_log_summary(self):
        """Print a summary of available log files."""
        print(f"\nLog files created in {self.host_log_dir}:")
        if os.path.exists(os.path.join(self.host_log_dir, "h1_seeder.log")):
            print(f"  - h1_seeder.log (seeder output)")
        
        for i in range(2, self.num_hosts + 1):
            log_file = os.path.join(self.host_log_dir, f"h{i}_leecher.log")
            if os.path.exists(log_file):
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
        
        # Clean up temporary mininet log directory
        if hasattr(self, 'mininet_log_dir') and os.path.exists(self.mininet_log_dir):
            shutil.rmtree(self.mininet_log_dir)
            print(f"Cleaned up temporary log directory: {self.mininet_log_dir}")
    
    def run(self):
        """Complete workflow: validate, create network, run clients, cleanup."""
        try:
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
    parser.add_argument('-k', '--hosts', type=int, default=3,
                        help='Number of hosts in the network (default: 3)')
    parser.add_argument('-t', '--topology', choices=['single'], 
                        default='single', help='Network topology (default: single)')
    parser.add_argument('--delay', default='0ms', 
                        help='Link delay (e.g., 10ms, 100ms, 1s) (default: 0ms)')
    parser.add_argument('--seeder-file', 
                        help='Path to the complete file for seeding (seeder will have this file)')
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = _parse_arguments()
    
    # Create and run BitTorrent Mininet instance
    bt_mininet = BitTorrentMininet(
        torrent_file=args.torrent_file,
        verbose=args.verbose,
        delete_torrent=args.deletetorrent,
        seed=args.seed,
        num_hosts=args.hosts,
        topology=args.topology,
        delay=args.delay,
        seeder_file=args.seeder_file
    )
    
    bt_mininet.run()


if __name__ == '__main__':
    main()