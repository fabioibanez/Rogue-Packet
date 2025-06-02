#!/usr/bin/python
from mininet.topo import Topo, SingleSwitchTopo
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.log import lg, info
from mininet.node import OVSController
import argparse
import time
import os


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
    
    def __init__(self, torrent_file, verbose=False, delete_torrent=False, seed=False, 
                 num_hosts=3, topology='single', delay='0ms'):
        self.torrent_file = torrent_file
        self.verbose = verbose
        self.delete_torrent = delete_torrent
        self.seed = seed
        self.num_hosts = num_hosts
        self.topology_name = topology
        self.delay = delay
        self.net = None
    
    def _validate_torrent_file(self):
        """Check if the torrent file exists."""
        if not os.path.exists(self.torrent_file):
            raise FileNotFoundError(f"Torrent file '{self.torrent_file}' not found")
    
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
    
    def _build_bittorrent_command(self):
        """Build the command string for running the BitTorrent client."""
        cmd_parts = ['python', 'main.py', self.torrent_file]
        
        if self.verbose:
            cmd_parts.append('-v')
        if self.delete_torrent:
            cmd_parts.append('-d')
        if self.seed:
            cmd_parts.append('-s')
        
        return ' '.join(cmd_parts)
    
    def _run_bittorrent_client(self):
        """Run the BitTorrent client on the primary host."""
        if not self.net:
            raise RuntimeError("Network not created. Call create_network() first.")
        
        # Get primary host
        h1 = self.net.get('h1')
        print(f"Primary host h1: {h1.IP()}")
        
        # Show all host IPs for reference
        print("Available hosts:")
        for i in range(1, self.num_hosts + 1):
            host = self.net.get(f'h{i}')
            if host:
                print(f"  h{i}: {host.IP()}")
        
        # Build and execute command
        bittorrent_cmd = self._build_bittorrent_command()
        print(f"Running BitTorrent client: {bittorrent_cmd}")
        
        h1.cmd(bittorrent_cmd)
    
    def _cleanup(self):
        """Stop the network and cleanup resources."""
        if self.net:
            print("Stopping network...")
            self.net.stop()
            self.net = None
    
    def run(self):
        """Complete workflow: validate, create network, run client, cleanup."""
        try:
            self._validate_torrent_file()
            self._validate_topology()
            self._create_network()
            self._run_bittorrent_client()
            
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
        delay=args.delay
    )
    
    bt_mininet.run()


if __name__ == '__main__':
    main()