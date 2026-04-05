#!/usr/bin/env python3
"""
12-Switch Dual-Path Topology with Failover Testing
Two completely separate paths between hosts for accurate failover measurement

Topology:
    Path A (Primary):   h1 - s1 - s2 - s3 - s4 - s5 - s6 - s7 - s8 - s9 - s10 - s11 - s12 - h2
    Path B (Backup):    h1 - s1 - s13 - s14 - s15 - s16 - s17 - s18 - s19 - s20 - s21 - s22 - s23 - s24 - h2

Total switches: 24 (12 per path) + 2 core switches? Actually let's make it clean:
- 2 host switches (s1 and s12 for path A, s1 and s24 for path B - but s1 is shared at ingress)
- Better: Shared ingress s1, then two separate 12-switch paths, shared egress s24

Let me create a proper 12+12 switch topology:
- s1 (ingress) connects to h1
- s24 (egress) connects to h2
- Path A: s1 -> s2 -> s3 -> s4 -> s5 -> s6 -> s7 -> s8 -> s9 -> s10 -> s11 -> s12 -> s24
- Path B: s1 -> s13 -> s14 -> s15 -> s16 -> s17 -> s18 -> s19 -> s20 -> s21 -> s22 -> s23 -> s24
"""

from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info, error
from mininet.cli import CLI
import time
import threading
import subprocess
import os
import signal
from datetime import datetime
import re

class TwelveSwitchTopology(Topo):
    """
    12-switch dual-path topology for failover testing
    
    Path A (Primary): 12 switches (s2-s13)
    Path B (Backup):  12 switches (s14-s25)
    Total switches: 25 (s1 + 12 path A + 12 path B + s26 egress? Let me recalc)
    
    Better organization:
    - s1: ingress switch (connects to h1)
    - s26: egress switch (connects to h2)
    - Path A: s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12, s13 (12 switches)
    - Path B: s14, s15, s16, s17, s18, s19, s20, s21, s22, s23, s24, s25 (12 switches)
    
    Total: 1 + 12 + 12 + 1 = 26 switches
    """
    
    def __init__(self, **params):
        super(TwelveSwitchTopology, self).__init__(**params)
        
        # Add hosts with specific MAC addresses
        h1 = self.addHost('h1', 
                          ip='10.0.0.1/24', 
                          mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', 
                          ip='10.0.0.2/24', 
                          mac='00:00:00:00:00:02')
        
        # Create all switches with OpenFlow 1.3 support
        switches = {}
        
        # Ingress switch (connects to h1)
        switches['s1'] = self.addSwitch('s1', 
                                        dpid='0000000000000001',
                                        protocols='OpenFlow13')
        
        # Egress switch (connects to h2)
        switches['s5'] = self.addSwitch('s5', 
                                         dpid='0000000000000005',  # 26 in hex
                                         protocols='OpenFlow13')
        
        # Path A switches (s2-s13) - 12 switches
        path_a_names = ['s2', 's3', 's4', 's26', 's6', 's7', 
                        's8', 's9', 's10', 's11', 's12', 's13']
        for i, name in enumerate(path_a_names, start=2):
            switches[name] = self.addSwitch(name, 
                                            dpid=f'00000000000000{int(name[1:]):02x}',
                                            protocols='OpenFlow13')
        
        # Path B switches (s14-s25) - 12 switches
        path_b_names = ['s14', 's15', 's16', 's17', 's18', 's19',
                        's20', 's21', 's22', 's23', 's24', 's25']
        for i, name in enumerate(path_b_names, start=14):
            switches[name] = self.addSwitch(name, 
                                            dpid=f'00000000000000{int(name[1:]):02x}',
                                            protocols='OpenFlow13')
        
        # Connect h1 to ingress switch s1 (port 1)
        self.addLink(h1, switches['s1'], port1=1, port2=1,  delay='1ms')
        
        # Connect h2 to egress switch s26 (port 1)
        self.addLink(h2, switches['s5'], port1=1, port2=1, delay='1ms')
        
        # Build Path A: s1 -> s2 -> s3 -> ... -> s13 -> s26
        # Connect s1 to first switch in path A (s2)
        self.addLink(switches['s1'], switches['s2'], 
                    port1=2, port2=1, delay='5ms')
        
        # Connect switches in path A sequentially
        for i in range(len(path_a_names) - 1):
            curr = switches[path_a_names[i]]
            nxt = switches[path_a_names[i + 1]]
            self.addLink(curr, nxt, port1=2, port2=1, delay='5ms')
        
        # Connect last switch in path A (s13) to egress switch s26
        self.addLink(switches['s13'], switches['s5'], 
                    port1=2, port2=2, delay='5ms')
        
        # Build Path B: s1 -> s14 -> s15 -> ... -> s25 -> s26
        # Connect s1 to first switch in path B (s14)
        self.addLink(switches['s1'], switches['s14'], 
                    port1=3, port2=1, delay='5ms')
        
        # Connect switches in path B sequentially
        for i in range(len(path_b_names) - 1):
            curr = switches[path_b_names[i]]
            nxt = switches[path_b_names[i + 1]]
            self.addLink(curr, nxt, port1=2, port2=1, delay='5ms')
        
        # Connect last switch in path B (s25) to egress switch s26
        self.addLink(switches['s25'], switches['s5'], 
                    port1=2, port2=3, delay='5ms')
        
        # Store path information for reference
        self.path_a_switches = ['s1'] + path_a_names + ['s5']
        self.path_b_switches = ['s1'] + path_b_names + ['s5']
        
    def get_path_info(self):
        """Return path information for documentation"""
        return {
            'primary_path': {
                'name': 'Path A (Primary)',
                'switches': self.path_a_switches,
                'switch_count': len(self.path_a_switches),
                'hop_count': len(self.path_a_switches) - 1,
                'vlan': 100
            },
            'backup_path': {
                'name': 'Path B (Backup)',
                'switches': self.path_b_switches,
                'switch_count': len(self.path_b_switches),
                'hop_count': len(self.path_b_switches) - 1,
                'vlan': 200
            }
        }

class WiresharkCapture:
    """
    Manages Wireshark packet captures for latency measurement
    """
    
    def __init__(self, interface='any', output_dir='captures'):
        self.interface = interface
        self.output_dir = output_dir
        self.tshark_process = None
        self.capture_file = None
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
    
    def start_capture(self, name):
        """Start a packet capture using tshark"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.capture_file = f"{self.output_dir}/{name}_{timestamp}.pcap"
        
        # Start tshark capture
        cmd = [
            'tshark',
            '-i', self.interface,
            '-w', self.capture_file,
            '-f', 'icmp or arp',  # Capture only ICMP and ARP
            '-F', 'pcap'
        ]
        
        self.tshark_process = subprocess.Popen(cmd, 
                                               stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL)
        info(f'*** Started Wireshark capture: {self.capture_file}\n')
        return self.capture_file
    
    def stop_capture(self):
        """Stop the packet capture"""
        if self.tshark_process:
            self.tshark_process.send_signal(signal.SIGINT)
            self.tshark_process.wait(timeout=5)
            info(f'*** Stopped Wireshark capture: {self.capture_file}\n')
            return self.capture_file
        return None
    
    def analyze_capture(self, pcap_file, fail_time):
        """
        Analyze the capture file to calculate failover latency
        Returns the failover delay in milliseconds
        """
        if not os.path.exists(pcap_file):
            return None
        
        # Use tshark to extract timestamps of ICMP requests and replies
        cmd = [
            'tshark',
            '-r', pcap_file,
            '-Y', 'icmp',
            '-T', 'fields',
            '-e', 'frame.time_epoch',
            '-e', 'icmp.seq',
            '-e', 'icmp.type'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # Parse output
        packets = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                timestamp = float(parts[0])
                seq = int(parts[1])
                icmp_type = parts[2] if len(parts) > 2 else '8'
                packets.append({
                    'timestamp': timestamp,
                    'seq': seq,
                    'type': 'request' if icmp_type == '8' else 'reply',
                    'latency': None
                })
        
        # Match requests with replies
        seq_times = {}
        rtts = []
        
        for p in packets:
            if p['type'] == 'request':
                seq_times[p['seq']] = p['timestamp']
            elif p['seq'] in seq_times:
                rtt = (p['timestamp'] - seq_times[p['seq']]) * 1000
                rtts.append({
                    'seq': p['seq'],
                    'timestamp': p['timestamp'],
                    'rtt': rtt
                })
        
        # Find failure point
        fail_time_abs = fail_time
        failed_seq = None
        recovery_seq = None
        
        for i, rtt in enumerate(rtts):
            if rtt['timestamp'] >= fail_time_abs:
                if i > 0 and rtts[i-1]['rtt'] < 100:  # Normal RTT
                    failed_seq = rtt['seq']
                    break
        
        if failed_seq:
            # Find when RTT returns to normal
            for rtt in rtts:
                if rtt['seq'] > failed_seq and rtt['rtt'] < 100:
                    recovery_seq = rtt['seq']
                    break
        
        if failed_seq and recovery_seq:
            # Calculate failover delay
            fail_packet = next(r for r in rtts if r['seq'] == failed_seq)
            recover_packet = next(r for r in rtts if r['seq'] == recovery_seq)
            failover_delay = (recover_packet['timestamp'] - fail_packet['timestamp']) * 1000
            return failover_delay
        
        return None

class FailoverTest:
    """
    Comprehensive failover test with 12-switch dual-path topology
    """
    
    def __init__(self, controller_ip='127.0.0.1', controller_port=6653):
        self.controller_ip = controller_ip
        self.controller_port = controller_port
        self.net = None
        self.wireshark = WiresharkCapture(interface='any')
        self.ping_results = []
        self.stop_event = None
        self.monitor_thread = None
        
    def build_network(self):
        """Create and configure the Mininet network"""
        info('*** Creating 12-Switch Dual-Path Topology\n')
        topo = TwelveSwitchTopology()
        
        # Display path information
        paths = topo.get_path_info()
        info('\n' + '='*80 + '\n')
        info('Topology Information:\n')
        info('='*80 + '\n')
        for path_name, path_info in paths.items():
            info(f'\n{path_info["name"]}:\n')
            info(f'  Switches: {" -> ".join(path_info["switches"])}\n')
            info(f'  Switch count: {path_info["switch_count"]}\n')
            info(f'  Hop count: {path_info["hop_count"]}\n')
            info(f'  VLAN ID: {path_info["vlan"]}\n')
        info('\n' + '='*80 + '\n')
        
        controller = RemoteController('c0', 
                                      ip=self.controller_ip, 
                                      port=self.controller_port,
                                      protocols='OpenFlow13')
        
        self.net = Mininet(topo=topo, 
                          controller=controller,
                          switch=OVSSwitch,
                          link=TCLink,
                          waitConnected=True)
        
        return self.net
    
    def start_network(self):
        """Start the network and wait for flows"""
        if not self.net:
            self.build_network()
        
        info('*** Starting Network\n')
        self.net.start()
        
        # Wait for OpenFlow handshake and flow installation
        # With 26 switches, need more time
        info('*** Waiting for controller to install flows (30 seconds)...\n')
        CLI(self.net)
        
        self.verify_switches_connected()
    
    def verify_switches_connected(self):
        """Verify all switches are connected to the controller"""
        expected_switches = 26
        connected = len(self.net.switches)
        info(f'\n*** Connected switches: {connected}/{expected_switches}\n')
        
        if connected < expected_switches:
            info(f'*** WARNING: Only {connected} switches connected\n')
    
    def start_continuous_ping(self, interval=0.1):
        """
        Start continuous ping from h1 to h2 with detailed logging
        interval: time between pings in seconds (default 0.1 = 10 pings/sec)
        """
        h1 = self.net.get('h1')
        h2 = self.net.get('h2')
        
        self.ping_results = []
        self.stop_event = threading.Event()
        
        def ping_monitor():
            seq = 0
            while not self.stop_event.is_set():
                start_time = time.time()
                result = h1.cmd(f'ping -c 1 -W 1 {h2.IP()}')
                end_time = time.time()
                
                timestamp = time.time()
                
                # Parse ping output
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
                    info(f'Ping {seq}: OK ({latency:.3f} ms)\n')
                else:
                    self.ping_results.append({
                        'timestamp': timestamp,
                        'seq': seq,
                        'latency': None,
                        'success': False
                    })
                    info(f'Ping {seq}: FAILED\n')
                
                # Sleep to maintain interval
                elapsed = time.time() - start_time
                sleep_time = max(0, interval - elapsed)
                time.sleep(sleep_time)
        
        self.monitor_thread = threading.Thread(target=ping_monitor)
        self.monitor_thread.start()
        info(f'*** Continuous ping started (interval={interval}s)\n')
    
    def stop_continuous_ping(self):
        """Stop the continuous ping thread"""
        if self.stop_event:
            self.stop_event.set()
        if self.monitor_thread:
            self.monitor_thread.join()
        info('*** Continuous ping stopped\n')
    
    def fail_link(self, switch, port):
        """Bring down a specific port on a switch"""
        sw = self.net.get(switch)
        sw.cmd(f'ovs-ofctl mod-port {switch} {port} down')
        info(f'\n*** {switch}: port {port} is DOWN\n')
        
        # For inter-switch links, also fail the other side
        link_mappings = {
            ('s1', 2): ('s2', 1),
            ('s2', 2): ('s3', 1),
            ('s3', 2): ('s4', 1),
            ('s4', 2): ('s5', 1),
            ('s5', 2): ('s6', 1),
            ('s6', 2): ('s7', 1),
            ('s7', 2): ('s8', 1),
            ('s8', 2): ('s9', 1),
            ('s9', 2): ('s10', 1),
            ('s10', 2): ('s11', 1),
            ('s11', 2): ('s12', 1),
            ('s12', 2): ('s13', 1),
            ('s13', 2): ('s26', 2),
        }
        
        key = (switch, port)
        if key in link_mappings:
            other_sw, other_port = link_mappings[key]
            self.net.get(other_sw).cmd(f'ovs-ofctl mod-port {other_sw} {other_port} down')
            info(f'*** {other_sw}: port {other_port} is DOWN (other side)\n')
    
    def restore_link(self, switch, port):
        """Bring up a specific port on a switch"""
        sw = self.net.get(switch)
        sw.cmd(f'ovs-ofctl mod-port {switch} {port} up')
        info(f'\n*** {switch}: port {port} is UP\n')
        
        # Restore other side
        link_mappings = {
            ('s1', 2): ('s2', 1),
            ('s2', 2): ('s3', 1),
            ('s3', 2): ('s4', 1),
            ('s4', 2): ('s5', 1),
            ('s5', 2): ('s6', 1),
            ('s6', 2): ('s7', 1),
            ('s7', 2): ('s8', 1),
            ('s8', 2): ('s9', 1),
            ('s9', 2): ('s10', 1),
            ('s10', 2): ('s11', 1),
            ('s11', 2): ('s12', 1),
            ('s12', 2): ('s13', 1),
            ('s13', 2): ('s26', 2),
        }
        
        key = (switch, port)
        if key in link_mappings:
            other_sw, other_port = link_mappings[key]
            self.net.get(other_sw).cmd(f'ovs-ofctl mod-port {other_sw} {other_port} up')
            info(f'*** {other_sw}: port {other_port} is UP (other side)\n')
    
    def fail_primary_path(self):
        """Fail the entire primary path by breaking the first link"""
        info('\n*** FAILING PRIMARY PATH (breaking s1-s2 link)\n')
        self.fail_link('s13', 2)
    
    def restore_primary_path(self):
        """Restore the primary path"""
        info('\n*** RESTORING PRIMARY PATH\n')
        self.restore_link('s13', 2)
    
    def analyze_failover(self, fail_time):
        """
        Analyze ping results to determine failover metrics
        """
        if not self.ping_results:
            return None
        
        # Find the first failure after fail_time
        failure_idx = None
        for i, result in enumerate(self.ping_results):
            if result['timestamp'] >= fail_time and not result['success']:
                failure_idx = i
                break
        
        if failure_idx is None:
            info('No packet loss detected after link failure\n')
            return None
        
        # Find the first successful ping after the failure
        recovery_idx = None
        for i in range(failure_idx + 1, len(self.ping_results)):
            if self.ping_results[i]['success']:
                recovery_idx = i
                break
        
        if recovery_idx is None:
            info('No recovery detected\n')
            return None
        
        fail_timestamp = self.ping_results[failure_idx]['timestamp']
        recover_timestamp = self.ping_results[recovery_idx]['timestamp']
        delay_ms = (recover_timestamp - fail_timestamp) * 1000
        
        # Count lost packets
        lost_count = sum(1 for i in range(failure_idx, recovery_idx) 
                        if not self.ping_results[i]['success'])
        
        # Calculate average RTT before failure
        pre_fail_rtts = [r['latency'] for r in self.ping_results 
                        if r['timestamp'] < fail_time and r['success']][-20:]
        avg_pre_rtt = sum(pre_fail_rtts) / len(pre_fail_rtts) if pre_fail_rtts else 0
        
        # Calculate average RTT after recovery
        post_recovery_rtts = [r['latency'] for r in self.ping_results 
                             if r['timestamp'] > recover_timestamp and r['success']][:20]
        avg_post_rtt = sum(post_recovery_rtts) / len(post_recovery_rtts) if post_recovery_rtts else 0
        
        info('\n' + '='*80 + '\n')
        info('FAILOVER ANALYSIS RESULTS\n')
        info('='*80 + '\n')
        info(f'Link failure time:          {datetime.fromtimestamp(fail_time).strftime("%H:%M:%S.%f")[:-3]}\n')
        info(f'First failure detected:     {datetime.fromtimestamp(fail_timestamp).strftime("%H:%M:%S.%f")[:-3]}\n')
        info(f'Recovery detected:          {datetime.fromtimestamp(recover_timestamp).strftime("%H:%M:%S.%f")[:-3]}\n')
        info(f'\n')
        info(f'Packets lost:               {lost_count}\n')
        info(f'Failover delay:             {delay_ms:.3f} ms\n')
        info(f'\n')
        info(f'Average RTT before failure: {avg_pre_rtt:.3f} ms\n')
        info(f'Average RTT after recovery: {avg_post_rtt:.3f} ms\n')
        info('='*80 + '\n')
        
        return {
            'failover_delay_ms': delay_ms,
            'packets_lost': lost_count,
            'avg_rtt_pre': avg_pre_rtt,
            'avg_rtt_post': avg_post_rtt,
            'fail_timestamp': fail_timestamp,
            'recover_timestamp': recover_timestamp
        }
    
    def test_initial_connectivity(self):
        """Test initial connectivity between hosts"""
        info('\n*** Testing Initial Connectivity\n')
        h1 = self.net.get('h1')
        h2 = self.net.get('h2')
        
        result = h1.cmd(f'ping -c 10 {h2.IP()}')
        
        # Parse results
        loss_match = re.search(r'([\d\.]+)% packet loss', result)
        rtt_match = re.search(r'min/avg/max/mdev = ([\d\.]+)/([\d\.]+)/([\d\.]+)/([\d\.]+)', result)
        
        info(result)
        
        if loss_match and float(loss_match.group(1)) == 0:
            info('*** Initial connectivity: SUCCESS\n')
            if rtt_match:
                info(f'*** Average RTT: {rtt_match.group(2)} ms\n')
            return True
        else:
            error('*** Initial connectivity: FAILED\n')
            return False
    
    def measure_path_latency(self, path_name, iterations=100):
        """
        Measure latency for a specific path using ping
        """
        info(f'\n*** Measuring latency on {path_name} ({iterations} pings)\n')
        h1 = self.net.get('h1')
        h2 = self.net.get('h2')
        
        result = h1.cmd(f'ping -c {iterations} {h2.IP()}')
        
        # Parse RTT statistics
        rtt_match = re.search(r'min/avg/max/mdev = ([\d\.]+)/([\d\.]+)/([\d\.]+)/([\d\.]+)', result)
        
        if rtt_match:
            return {
                'min_ms': float(rtt_match.group(1)),
                'avg_ms': float(rtt_match.group(2)),
                'max_ms': float(rtt_match.group(3)),
                'mdev_ms': float(rtt_match.group(4))
            }
        return None
    
    def run_failover_test(self):
        """Execute the main failover test with Wireshark capture"""
        info('\n' + '='*80 + '\n')
        info('Starting 12-Switch Failover Test\n')
        info('='*80 + '\n')
        
        # Test 1: Initial connectivity
        if not self.test_initial_connectivity():
            error('Initial connectivity failed. Exiting.\n')
            return
        
        # Test 2: Measure baseline latency on primary path
        baseline = self.measure_path_latency('Primary Path (A)', 50)
        if baseline:
            info(f'\nBaseline Latency (Primary Path):\n')
            info(f'  Min: {baseline["min_ms"]:.3f} ms\n')
            info(f'  Avg: {baseline["avg_ms"]:.3f} ms\n')
            info(f'  Max: {baseline["max_ms"]:.3f} ms\n')
        
        # Start Wireshark capture
        capture_file = self.wireshark.start_capture('failover_test')
        
        # Start continuous ping
        self.start_continuous_ping(interval=0.005)  # 20 pings per second
        
        # Let ping run for 10 seconds to establish baseline
        info('\n*** Establishing baseline (10 seconds)...\n')
        time.sleep(10)  
        
        # Record fail time and fail the primary link
        fail_time = time.time()
        info(f'\n*** FAILING PRIMARY LINK at {datetime.fromtimestamp(fail_time).strftime("%H:%M:%S.%f")[:-3]}\n')
        self.fail_primary_path()
        
        # Continue monitoring for 15 seconds to capture failover
        info('\n*** Monitoring failover (15 seconds)...\n')
        time.sleep(15)
        
        # Stop ping monitoring
        self.stop_continuous_ping()
        
        # Stop Wireshark capture
        self.wireshark.stop_capture()
        
        # Analyze results
        failover_metrics = self.analyze_failover(fail_time)
        
        # Test connectivity after failover
        info('\n*** Testing Connectivity After Failover\n')
        self.test_initial_connectivity()
        
        # Measure latency on backup path after failover
        backup_latency = self.measure_path_latency('Backup Path (B)', 50)
        if backup_latency:
            info(f'\nLatency on Backup Path After Failover:\n')
            info(f'  Min: {backup_latency["min_ms"]:.3f} ms\n')
            info(f'  Avg: {backup_latency["avg_ms"]:.3f} ms\n')
            info(f'  Max: {backup_latency["max_ms"]:.3f} ms\n')
        
        # Analyze Wireshark capture
        if capture_file:
            ws_delay = self.wireshark.analyze_capture(capture_file, fail_time)
            if ws_delay:
                info(f'\n*** Wireshark-based failover delay: {ws_delay:.3f} ms\n')
        
        # Save results to file
        self.save_results(fail_time, failover_metrics, baseline, backup_latency, capture_file)
        
        # Return to CLI for manual inspection
        info('\n*** Test complete. Dropping to CLI for manual inspection.\n')
        info('Commands to try:\n')
        info('  h1 ping h2                    - Test connectivity\n')
        info('  net.dump_flows()              - Show flow tables\n')
        info('  net.dump_flows("s1")          - Show flows on s1\n')
        info('  net.restore_primary_path()    - Restore primary link\n')
        info('  net.measure_path_latency()    - Measure current latency\n')
        info('  exit                          - Quit\n')
        
        CLI(self.net)
    
    def save_results(self, fail_time, metrics, baseline, backup_latency, capture_file):
        """Save test results to a file for documentation"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"failover_results_{timestamp}.txt"
        
        with open(filename, 'w') as f:
            f.write("="*80 + "\n")
            f.write("12-Switch Failover Test Results\n")
            f.write("="*80 + "\n\n")
            f.write(f"Test date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Capture file: {capture_file}\n\n")
            
            f.write("Baseline Latency (Primary Path):\n")
            if baseline:
                f.write(f"  Min: {baseline['min_ms']:.3f} ms\n")
                f.write(f"  Avg: {baseline['avg_ms']:.3f} ms\n")
                f.write(f"  Max: {baseline['max_ms']:.3f} ms\n\n")
            
            f.write("Failover Metrics:\n")
            if metrics:
                f.write(f"  Link failure time: {datetime.fromtimestamp(fail_time).strftime('%H:%M:%S.%f')[:-3]}\n")
                f.write(f"  Failover delay: {metrics['failover_delay_ms']:.3f} ms\n")
                f.write(f"  Packets lost: {metrics['packets_lost']}\n")
                f.write(f"  RTT before failure: {metrics['avg_rtt_pre']:.3f} ms\n")
                f.write(f"  RTT after recovery: {metrics['avg_rtt_post']:.3f} ms\n\n")
            
            f.write("Backup Path Latency After Failover:\n")
            if backup_latency:
                f.write(f"  Min: {backup_latency['min_ms']:.3f} ms\n")
                f.write(f"  Avg: {backup_latency['avg_ms']:.3f} ms\n")
                f.write(f"  Max: {backup_latency['max_ms']:.3f} ms\n")
        
        info(f'\n*** Results saved to: {filename}\n')
    
    def dump_flows(self, switch=None):
        """Dump flow tables for debugging"""
        info('\n*** Dumping Flow Tables\n')
        
        if switch:
            switches = [switch]
        else:
            switches = [f's{i}' for i in range(1, 27)]  # s1 to s26
        
        for sw_name in switches:
            try:
                sw = self.net.get(sw_name)
                info(f'\n{sw_name} flows:\n')
                flows = sw.cmd(f'ovs-ofctl dump-flows {sw_name}')
                # Filter to show only relevant flows
                for line in flows.split('\n'):
                    if 'priority=100' in line or 'vlan' in line or 'NORMAL' not in line:
                        info(f'  {line}\n')
            except:
                pass
    
    def dump_groups(self, switch=None):
        """Dump group tables for debugging"""
        info('\n*** Dumping Group Tables\n')
        
        if switch:
            switches = [switch]
        else:
            switches = ['s1']  # Only s1 should have groups
        
        for sw_name in switches:
            try:
                sw = self.net.get(sw_name)
                info(f'\n{sw_name} groups:\n')
                groups = sw.cmd(f'ovs-ofctl dump-groups {sw_name}')
                info(groups)
            except:
                pass
    
    def cleanup(self):
        """Stop the network and clean up"""
        if self.net:
            info('\n*** Stopping network\n')
            self.net.stop()
            info('*** Network stopped\n')

def run_test():
    """Main entry point for the test"""
    setLogLevel('info')
    
    test = FailoverTest()
    
    try:
        test.build_network()
        test.start_network()
        test.run_failover_test()
    except KeyboardInterrupt:
        info('\n*** Test interrupted by user\n')
    finally:
        test.cleanup()

if __name__ == '__main__':
    run_test()
