
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
import time
import subprocess

class MultiPathTopo(Topo):

    
    def build(self):
        h1 = self.addHost('h1', 
                          ip='10.0.0.1/24', 
                          mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', 
                          ip='10.0.0.2/24', 
                          mac='00:00:00:00:00:02')
        
        s1 = self.addSwitch('s1',cls=OVSSwitch, protocols='OpenFlow13' ,dpid='0000000000000001' )
        s2 = self.addSwitch('s2', cls=OVSSwitch,protocols='OpenFlow13',dpid='0000000000000002')
        s3 = self.addSwitch('s3',cls=OVSSwitch, protocols='OpenFlow13', dpid='0000000000000003')
        s4 = self.addSwitch('s4', cls=OVSSwitch,protocols='OpenFlow13' , dpid='000000000000004') 
        s5 = self.addSwitch('s5',cls=OVSSwitch, protocols='OpenFlow13', dpid='0000000000000005')
        
        self.addLink(h1, s1, port1=1, port2=1,)
        self.addLink(h2, s5, port1=1, port2=1,)
        
        self.addLink(s1, s2, port1=2, port2=1,)
        self.addLink(s2, s5, port1=2, port2=2, )
        
        self.addLink(s1, s3, port1=3, port2=1,)
        self.addLink(s3, s5, port1=2, port2=3,)
        
        self.addLink(s1, s4, port1=4, port2=1, )
        self.addLink(s4, s5, port1=2, port2=4, )
        
        self.addLink(s3, s4, port1=3, port2=3, )
        
   
        

class MultiPathNetwork:

    def __init__(self, controller_ip='127.0.0.1', controller_port=6653):
        self.controller_ip = controller_ip
        self.controller_port = controller_port
        self.net = None
        self.topo = MultiPathTopo()
        
    def start(self):
        """Start the network"""
        info('*** Creating network with multiple paths\n')
        
        controller = RemoteController('c0', 
                                      ip=self.controller_ip, 
                                      port=self.controller_port,
                                      protocols='OpenFlow13')
        
        self.net = Mininet(topo=self.topo, 
                          controller=controller,
                          switch=OVSSwitch,
                
                          )
        
        self.net.start()
        
    
  
        return self.net


    
    def fail_link(self, switch1, port1, switch2, port2):
   
        info(f'\n*** Failing link: {switch1}:{port1} <-> {switch2}:{port2}\n')
        
        sw1 = self.net.get(switch1)
        sw2 = self.net.get(switch2)
        
        # Bring down the link
        sw1.cmd('ovs-ofctl mod-port {0} {1} down'.format(switch1, port1))
        sw2.cmd('ovs-ofctl mod-port {0} {1} down'.format(switch2, port2))
        
        info(f'*** Link {switch1}:{port1} <-> {switch2}:{port2} is DOWN\n')
    
    def restore_link(self, switch1, port1, switch2, port2):
        
        sw1 = self.net.get(switch1)
        sw2 = self.net.get(switch2)
        
        # Bring up the link
        sw1.cmd('ovs-ofctl mod-port {0} {1} up'.format(switch1, port1))
        sw2.cmd('ovs-ofctl mod-port {0} {1} up'.format(switch2, port2))
        
        info(f'*** Link {switch1}:{port1} <-> {switch2}:{port2} is UP\n')

    def test_link_fail(self, src_name, dst_name, sw1, port1, sw2, port2, duration=10):

        info(f"\n*** Waiting 10 seconds\n")

        time.sleep(10)
        src = self.net.get(src_name)
        dst = self.net.get(dst_name)
        
        info(f"\n*** Starting connectivity test: {src_name} -> {dst_name}\n")
        # Start ping in background, logging to a file
        src.cmd(f'ping -i 0.5 {dst.IP()} > ping_results.txt &')
        
        info("*** Ping running... waiting 3 seconds\n")
        time.sleep(3)
        
        # Cut the link
        self.net.configLinkStatus(sw1, sw2 , 'down')
        
        info("*** Link is DOWN. Monitoring for 5 seconds...\n")
        time.sleep(5)
        
        # Stop the ping
        src.cmd('pkill ping')
        
        # Restore for cleanup
        self.restore_link(sw1, port1, sw2, port2)
        
        # Read and display the results
        info("\n*** Test Results (ping_results.txt):\n")
        results = subprocess.check_output(['cat', 'ping_results.txt']).decode('utf-8')
        print(results)
        
        # Check for gaps in ICMP sequence numbers to see packet loss
        if "time=" in results:
            info("*** Success: Ping recovered or continued.\n")
        else:
            info("*** Alert: Ping stopped completely.\n")



    def cli(self):
        """Start the Mininet CLI"""
        CLI(self.net)
    
    def stop(self):
        """Stop the network"""
        if self.net:
            info('\n*** Stopping network\n')
            self.net.stop()
            info('*** Network stopped\n')



def run_network():
    network = MultiPathNetwork()
    network.start()
    # network.test_link_fail('h1', 'h2', 's4', 2 ,'s5' , 4)

    network.cli()
    network.stop()


if __name__ == '__main__':
    setLogLevel('info')
    
    run_network()
    
