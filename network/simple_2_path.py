#!/usr/bin/env python3
"""

    h1 -- s1 -- s2 -- s5 -- h2  
              \         /
               s3 -- s4          
"""

from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info, error
from mininet.cli import CLI
import time
import threading
import re
from datetime import datetime

class FailoverTopology(Topo):

    
    def __init__(self, **params):
        super(FailoverTopology, self).__init__(**params)
        
        # Add hosts with specific MAC addresses (matching Floodlight module)
        h1 = self.addHost('h1', 
                          ip='10.0.0.1/24', 
                          mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', 
                          ip='10.0.0.2/24', 
                          mac='00:00:00:00:00:02')
        
        # Add switches with specific DPIDs
        # DPIDs must end with 01 (for host1 switch) and 05 (for host2 switch)
        s1 = self.addSwitch('s1', 
                           dpid='0000000000000001',  # ends with 01
                           protocols='OpenFlow13')
        s2 = self.addSwitch('s2', 
                           dpid='0000000000000002',
                           protocols='OpenFlow13')
        s3 = self.addSwitch('s3', 
                           dpid='0000000000000003',
                           protocols='OpenFlow13')
        s4 = self.addSwitch('s4', 
                           dpid='0000000000000004',
                           protocols='OpenFlow13')
        s5 = self.addSwitch('s5', 
                           dpid='0000000000000005',  # ends with 05
                           protocols='OpenFlow13')
        
        # Connect hosts to edge switches (port 1 on switches)
        self.addLink(h1, s1, port1=1, port2=1, delay='2ms')
        self.addLink(h2, s5, port1=1, port2=1,  delay='2ms')
        
        # Primary path: s1 -> s2 -> s5
        self.addLink(s1, s2, 
                    port1=2, port2=1, 
                     delay='5ms')
        self.addLink(s2, s5, 
                    port1=2, port2=2, 
                   delay='5ms')
        
        # Backup path: s1 -> s3 -> s4 -> s5
        self.addLink(s1, s3, 
                    port1=3, port2=1, 
                    delay='5ms')
        self.addLink(s3, s4, 
                    port1=2, port2=1, 
                  delay='5ms')
        self.addLink(s4, s5, 
                    port1=2, port2=3, 
                    delay='5ms')
        


class FailoverTest:
 

    
    def __init__(self, controller_ip='127.0.0.1', controller_port=6653):
        self.controller_ip = controller_ip
        self.controller_port = controller_port
        self.net = None
        self.ping_results = []
        self.stop_event = None
        self.monitor_thread = None
        
    def build_network(self):

        
        # Create topology
        topo = FailoverTopology()
        
        # Create controller
        controller = RemoteController('c0', 
                                      ip=self.controller_ip, 
                                      port=self.controller_port,
                                      protocols='OpenFlow13')
        
        # Create network
        self.net = Mininet(topo=topo, 
                          controller=controller,
                          switch=OVSSwitch,
                          link=TCLink,
                          waitConnected=True)
        
        return self.net
    
    def start_network(self):
        if not self.net:
            self.build_network()
        
        info('*** Starting Network\n')
        self.net.start()
        
    
        CLI(self.net)
        self.print_network_info()
        
    def print_network_info(self):
        info('\n' + '='*70 + '\n')
        info('Network Topology Information\n')
        info('='*70 + '\n')
        
        info('Hosts:\n')
        info('  h1: IP=10.0.0.1, MAC=00:00:00:00:00:01 (Switch s1, Port 1)\n')
        info('  h2: IP=10.0.0.2, MAC=00:00:00:00:00:02 (Switch s5, Port 1)\n')
        
        info('\nSwitches:\n')
        info('  s1 (DPID: 00:00:00:00:00:00:00:01) - Host1 switch\n')
        info('  s2 (DPID: 00:00:00:00:00:00:00:02)\n')
        info('  s3 (DPID: 00:00:00:00:00:00:00:03)\n')
        info('  s4 (DPID: 00:00:00:00:00:00:00:04)\n')
        info('  s5 (DPID: 00:00:00:00:00:00:00:05) - Host2 switch\n')
        
        info('\nPaths:\n')
        info('  Primary: h1 -> s1:2 -> s2:1 -> s2:2 -> s5:2 -> h2\n')
        info('  Backup:  h1 -> s1:3 -> s3:1 -> s3:2 -> s4:1 -> s4:2 -> s5:3 -> h2\n')
        info('='*70 + '\n')
    
    def start_continuous_ping(self):
        h1 = self.net.get('h1')
        h2 = self.net.get('h2')
        
        self.ping_results = []
        self.stop_event = threading.Event()
        
        def ping_monitor():
            seq = 0
            while not self.stop_event.is_set():
                result = h1.cmd('ping -c 1 -W 1 {0}'.format(h2.IP()))
                timestamp = time.time()
                
                # Parse ping output
                # Success: "64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.123 ms"
                # Failure: "Destination Host Unreachable" or timeout
                success_match = re.search(r'icmp_seq=(\d+).*time=([\d\.]+) ms', result)
                loss_match = re.search(r'([\d\.]+)% packet loss', result)
                
                if success_match:
                    seq = int(success_match.group(1))
                    latency = float(success_match.group(2))
                    self.ping_results.append({
                        'timestamp': timestamp,
                        'seq': seq,
                        'latency': latency,
                        'success': True
                    })
                    info(f'Ping {seq}: OK ({latency:.2f} ms)\n')
                else:
                    self.ping_results.append({
                        'timestamp': timestamp,
                        'seq': seq,
                        'latency': None,
                        'success': False
                    })
                    info(f'Ping {seq}: FAILED\n')
                
                time.sleep(0.2)  # 5 pings per second
        
        self.monitor_thread = threading.Thread(target=ping_monitor)
        self.monitor_thread.start()
        info('*** Continuous ping started\n')
    
    def stop_continuous_ping(self):
        """Stop the continuous ping thread."""
        if self.stop_event:
            self.stop_event.set()
        if self.monitor_thread:
            self.monitor_thread.join()
        info('*** Continuous ping stopped\n')
    
    def fail_link(self, switch, port):
        """Bring down a specific port on a switch."""
        sw = self.net.get(switch)
        sw.cmd('ovs-ofctl mod-port {0} {1} down'.format(switch, port))
        info(f'\n*** {switch}: port {port} is DOWN\n')
        
        # Also fail the other side of the link if it's an inter-switch link
        # This ensures the watch port on the group table detects the failure
        if switch == 's1' and port == 2:
            self.net.get('s2').cmd('ovs-ofctl mod-port s2 1 down')
            info('*** s2: port 1 is DOWN (other side of the link)\n')
        elif switch == 's2' and port == 2:
            self.net.get('s5').cmd('ovs-ofctl mod-port s5 2 down')
            info('*** s5: port 2 is DOWN (other side of the link)\n')
    
    def restore_link(self, switch, port):
        """Bring up a specific port on a switch."""
        sw = self.net.get(switch)
        sw.cmd('ovs-ofctl mod-port {0} {1} up'.format(switch, port))
        info(f'\n*** {switch}: port {port} is UP\n')
        
        if switch == 's1' and port == 2:
            self.net.get('s2').cmd('ovs-ofctl mod-port s2 1 up')
            info('*** s2: port 1 is UP\n')
        elif switch == 's2' and port == 2:
            self.net.get('s5').cmd('ovs-ofctl mod-port s5 2 up')
            info('*** s5: port 2 is UP\n')
    
    def analyze_failover(self, fail_time):
        """
        Analyze ping results to determine failover delay.
        Returns failover delay in milliseconds, or None if not detected.
        """
        # Find the first failure after fail_time
        failure_index = None
        for i, result in enumerate(self.ping_results):
            if result['timestamp'] >= fail_time and not result['success']:
                failure_index = i
                break
        
        if failure_index is None:
            info('No packet loss detected after link failure\n')
            return None
        
        # Find the first successful ping after the failure
        recovery_index = None
        for i in range(failure_index + 1, len(self.ping_results)):
            if self.ping_results[i]['success']:
                recovery_index = i
                break
        
        if recovery_index is None:
            info('No recovery detected (all pings failed after failure)\n')
            return None
        
        fail_timestamp = self.ping_results[failure_index]['timestamp']
        recover_timestamp = self.ping_results[recovery_index]['timestamp']
        delay_ms = (recover_timestamp - fail_timestamp) * 1000
        
        # Count lost packets
        lost_count = 0
        for i in range(failure_index, recovery_index):
            if not self.ping_results[i]['success']:
                lost_count += 1
        

        return delay_ms
    
    def test_initial_connectivity(self):
        """Test initial connectivity between hosts."""
        info('\n*** Testing Initial Connectivity\n')
        h1 = self.net.get('h1')
        h2 = self.net.get('h2')
        
        result = h1.cmd('ping -c 5 {}'.format(h2.IP()))
        info(result)
        
        if '0% packet loss' in result:
            info('*** Initial connectivity: SUCCESS\n')
            return True
        else:
            error('*** Initial connectivity: FAILED\n')
            return False
    
    def test_bandwidth(self, duration=5):
        """Test bandwidth between hosts using iperf."""
        info(f'\n*** Testing Bandwidth (iperf for {duration} seconds)\n')
        h1 = self.net.get('h1')
        h2 = self.net.get('h2')
        
        # Start iperf server on h2
        h2.cmd('iperf -s &')
        time.sleep(1)
        
        # Run iperf client on h1
        result = h1.cmd('iperf -c {} -t {}'.format(h2.IP(), duration))
        info(result)
        
        # Kill iperf server
        h2.cmd('killall iperf')
        
        return result
    
    def dump_flows(self, switch='all'):
        """Dump flow tables for debugging."""
        info('\n*** Dumping Flow Tables\n')
        
        switches = ['s1', 's2', 's3', 's4', 's5'] if switch == 'all' else [switch]
        
        for sw_name in switches:
            sw = self.net.get(sw_name)
            info(f'\n{sw_name} flows:\n')
            flows = sw.cmd('ovs-ofctl dump-flows {} -O OpenFlow13'.format(sw_name))
            # Filter to show only relevant flows (optional)
            for line in flows.split('\n'):
                if 'priority=100' in line or 'vlan' in line:
                    info(f'  {line}\n')
    
    def dump_groups(self, switch='all'):
        """Dump group tables for debugging."""
        info('\n*** Dumping Group Tables\n')
        
        switches = ['s1', 's2', 's3', 's4', 's5'] if switch == 'all' else [switch]
        
        for sw_name in switches:
            sw = self.net.get(sw_name)
            info(f'\n{sw_name} groups:\n')
            groups = sw.cmd('ovs-ofctl dump-groups {} -O OpenFlow13'.format(sw_name))
            info(groups)
    
    def run_failover_test(self):
        """Execute the main failover test."""
        info('\n' + '='*70 + '\n')
        info('Starting Failover Test\n')
        info('='*70 + '\n')
    
        if not self.test_initial_connectivity():
            error('Initial connectivity failed. Exiting.\n')
            return
        
        self.test_bandwidth(3)
        
        self.start_continuous_ping()
        
        info('\n*** Establishing baseline (5 seconds)...\n')
        time.sleep(5)
        
        fail_time = time.time()
        info(f'\n*** FAILING PRIMARY LINK at {datetime.fromtimestamp(fail_time).strftime("%H:%M:%S.%f")[:-3]}\n')
        self.fail_link('s2', 2)  
        
        info('\n*** Monitoring failover (10 seconds)...\n')
        time.sleep(10)
        
        self.stop_continuous_ping()
        
        failover_delay = self.analyze_failover(fail_time)
        
        info('\n*** Testing Connectivity After Failover\n')
        h1 = self.net.get('h1')
        h2 = self.net.get('h2')
        result = h1.cmd('ping -c 5 {}'.format(h2.IP()))
        info(result)
        
        self.dump_flows()
        self.dump_groups()

        CLI(self.net)
    
    def cleanup(self):
        """Stop the network and clean up."""
        if self.net:
            info('\n*** Stopping network\n')
            self.net.stop()
            info('*** Network stopped\n')

def run_test():
    """Main entry point for the test."""
    setLogLevel('info')
    
    test = FailoverTest()
    
    try:
        test.start_network()
        test.run_failover_test()
    except KeyboardInterrupt:
        info('\n*** Test interrupted by user\n')
    finally:
        test.cleanup()

if __name__ == '__main__':
    run_test()
