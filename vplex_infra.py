#!/usr/bin/python
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.log import lg, info
from mininet.node import OVSController
from mininet.cli import CLI

class DelayedTopo(Topo):
    def build(self):
        # Create two hosts and one switch
        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        s1 = self.addSwitch('s1')
        
        # Add links with delay
        self.addLink(h1, s1, cls=TCLink, delay='100ms')
        self.addLink(h2, s1, cls=TCLink, delay='100ms')

def main():
    lg.setLogLevel('info')
    
    # Instantiate the topology and pass TCLink to enable link options
    topo = DelayedTopo()
    net = Mininet(topo=topo, controller=OVSController, link=TCLink)
    net.start()

    h1 = net.get('h1')
    h2 = net.get('h2')

    # Start server on h1
    p1 = h1.popen('python myServer.py -i %s' % h1.IP())

    # Run client on h2
    h2.cmd('python myClient.py -i %s -m "hello world"' % h1.IP())

    # Clean up
    p1.terminate()
    net.stop()

if __name__ == '__main__':
    main()
