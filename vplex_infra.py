#!/usr/bin/python
from mininet.topo import Topo, SingleSwitchTopo
from mininet.net import Mininet
from mininet.log import lg, info
from mininet.cli import CLI
from mininet.node import OVSController

def main():
    lg.setLogLevel('info')
    # Use OVS controller
    net = Mininet(SingleSwitchTopo(k=2), controller=OVSController)
    net.start()
    
    h1 = net.get('h1')
    p1 = h1.popen('python myServer.py -i %s &' % h1.IP())
    
    h2 = net.get('h2')
    h2.cmd('python myClient.py -i %s -m "hello world"' % h1.IP())
    
    # CLI(net)
    p1.terminate()
    net.stop()

if __name__ == '__main__':
    main()