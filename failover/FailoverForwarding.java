package net.floodlightcontroller.failover;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedList;
import java.util.Queue;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

import net.floodlightcontroller.core.FloodlightContext;
import net.floodlightcontroller.core.IFloodlightProviderService;
import net.floodlightcontroller.core.IOFMessageListener;
import net.floodlightcontroller.core.IOFSwitch;
import net.floodlightcontroller.core.module.FloodlightModuleContext;
import net.floodlightcontroller.core.module.FloodlightModuleException;
import net.floodlightcontroller.core.module.IFloodlightModule;
import net.floodlightcontroller.core.module.IFloodlightService;
import net.floodlightcontroller.core.internal.IOFSwitchService;

import net.floodlightcontroller.routing.IRoutingService;
import net.floodlightcontroller.topology.ITopologyService;
import net.floodlightcontroller.topology.ITopologyListener;
import net.floodlightcontroller.linkdiscovery.ILinkDiscovery.LDUpdate;
import net.floodlightcontroller.linkdiscovery.ILinkDiscoveryService;
import net.floodlightcontroller.linkdiscovery.Link;
import net.floodlightcontroller.packet.ARP;
import net.floodlightcontroller.packet.Ethernet;
import net.floodlightcontroller.packet.IPv4;

import org.checkerframework.checker.nullness.qual.NonNull;
import org.projectfloodlight.openflow.protocol.OFBucket;
import org.projectfloodlight.openflow.protocol.OFFactory;
import org.projectfloodlight.openflow.protocol.OFFlowAdd;
import org.projectfloodlight.openflow.protocol.OFFlowMod;
import org.projectfloodlight.openflow.protocol.OFGroupMod;
import org.projectfloodlight.openflow.protocol.OFGroupType;
import org.projectfloodlight.openflow.protocol.OFMessage;
import org.projectfloodlight.openflow.protocol.OFPacketIn;
import org.projectfloodlight.openflow.protocol.OFPacketOut;
import org.projectfloodlight.openflow.protocol.OFType;
import org.projectfloodlight.openflow.protocol.action.OFAction;
import org.projectfloodlight.openflow.protocol.action.OFActionGroup;
import org.projectfloodlight.openflow.protocol.action.OFActionOutput;
import org.projectfloodlight.openflow.protocol.match.Match;
import org.projectfloodlight.openflow.protocol.match.MatchField;
import org.projectfloodlight.openflow.types.DatapathId;
import org.projectfloodlight.openflow.types.EthType;
import org.projectfloodlight.openflow.types.IPv4Address;
import org.projectfloodlight.openflow.types.MacAddress;
import org.projectfloodlight.openflow.types.OFGroup;
import org.projectfloodlight.openflow.types.OFPort;
import org.projectfloodlight.openflow.types.OFVlanVidMatch;
import org.projectfloodlight.openflow.types.OFVlanVidMatchWithMask;
import org.projectfloodlight.openflow.types.VlanVid;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;


public class FailoverForwarding implements IFloodlightModule, IOFMessageListener, ITopologyListener {
    
    protected IFloodlightProviderService floodlightProvider;
    protected IOFSwitchService switchService;
    protected ITopologyService topologyService;
    protected ILinkDiscoveryService linkDiscovery;
    
    private static final MacAddress HOST1_MAC = MacAddress.of("00:00:00:00:00:01");
    private static final MacAddress HOST2_MAC = MacAddress.of("00:00:00:00:00:02");
    private static final IPv4Address HOST1_IP = IPv4Address.of("10.0.0.1");
    private static final IPv4Address HOST2_IP = IPv4Address.of("10.0.0.2");
    
    private static final DatapathId SWITCH1 = DatapathId.of("00:00:00:00:00:00:00:01");
    private static final DatapathId SWITCH2 = DatapathId.of("00:00:00:00:00:00:00:05");
    private HostInfo host1 = new  HostInfo(HOST1_MAC, HOST1_IP, SWITCH1, OFPort.of(1));
    private HostInfo host2 = new  HostInfo(HOST2_MAC, HOST2_IP, SWITCH2, OFPort.of(1));
    private static final int primaryVlan = 100 ;
    private static final int backupVlan = 200;  
    private static Logger log = LoggerFactory.getLogger(FailoverForwarding.class);
    private final Map<MacAddress, HostInfo> learnedHosts = new ConcurrentHashMap<>();
    private final Map<IPv4Address, MacAddress> ipToMac = new ConcurrentHashMap<>();
    private final Map<String, Long> seenBroadcasts = new ConcurrentHashMap<>();
    private static final long BROADCAST_TTL_MS = 500;
    


    private BFS path; 
    private boolean isEnabled = true;
    private PheromoneTable pheromoneTable =  new PheromoneTable();


    private static class HostInfo {
        MacAddress mac;
        IPv4Address ip;
        DatapathId switchId;
        OFPort port;
        
        HostInfo(MacAddress mac, IPv4Address ip, DatapathId switchId, OFPort port) {
            this.mac = mac;
            this.ip = ip;
            this.switchId = switchId;
            this.port = port;
            
        }
        
        @Override
        public String toString() {
            return String.format("Host[MAC=%s, IP=%s, Switch=%s, Port=%s]",
                    mac, ip, switchId, port);
        }
    }
    


    @Override
    public String getName() {
        return "FailoverForwarding";
    }
    
    @Override
    public boolean isCallbackOrderingPrereq(OFType type, String name) {
        return false;
    }
    
    @Override
    public boolean isCallbackOrderingPostreq(OFType type, String name) {
        return false;
    }
    
    @Override
    public Collection<Class<? extends IFloodlightService>> getModuleServices() {
        return null;
    }
    
    @Override
    public Map<Class<? extends IFloodlightService>, IFloodlightService> getServiceImpls() {
        return null;
    }
    
    @Override
    public Collection<Class<? extends IFloodlightService>> getModuleDependencies() {
        Collection<Class<? extends IFloodlightService>> deps = 
            new ArrayList<Class<? extends IFloodlightService>>();
        deps.add(IFloodlightProviderService.class);
        deps.add(IOFSwitchService.class);
        deps.add(ITopologyService.class);
        deps.add(IRoutingService.class);
        deps.add(ILinkDiscoveryService.class) ; 
        return deps;
    }
    
    @Override
    public void init(FloodlightModuleContext context) throws FloodlightModuleException {
        try {
            log.info("=== Initializing FailoverForwarding Module ===");
            
            floodlightProvider = context.getServiceImpl(IFloodlightProviderService.class);
            switchService = context.getServiceImpl(IOFSwitchService.class);
            topologyService = context.getServiceImpl(ITopologyService.class);
            linkDiscovery = context.getServiceImpl(ILinkDiscoveryService.class); 
     
            
            log.info("FailoverForwarding initialized successfully");
        } catch (Exception e) {
            log.error("Failed to initialize FailoverForwarding: {}");
            isEnabled = false;
        }
    }
    
    @Override
    public void startUp(FloodlightModuleContext context) throws FloodlightModuleException {
        try {
            log.info("=== Starting FailoverForwarding Module === ");
            floodlightProvider.addOFMessageListener(OFType.PACKET_IN, this);
            topologyService.addListener(this);

        } catch (Exception e) {
            log.error("Failed to start FailoverForwarding: {}");
            isEnabled = false;
        }
    }
    
    // ==================== IOFMessageListener Implementation ====================
    
    @Override
    public Command receive(IOFSwitch sw, OFMessage msg, FloodlightContext cntx) {
        if (!isEnabled) {
            return Command.CONTINUE;
        }
           
                return handlePacketIn(sw, (OFPacketIn) msg, cntx);

        // try {
        //     if (msg.getType() == OFType.PACKET_IN) {
          //      return handlePacketIn(sw, (OFPacketIn) msg, cntx);
        //      
        //     }
        //     } catch (Exception e) {
        //         log.error("Error processing packet: {}" + e.getMessage());
        //     }
        //     return Command.CONTINUE;
    }
    
    // ==================== ITopologyListener Implementation ====================
    
    @Override
    public void topologyChanged(List<LDUpdate> linkUpdates) {
        log.info("=== Topology Change Detected ===");
        path = new BFS(this.linkDiscovery);
        pheromoneTable.updateTopology(linkDiscovery.getLinks());
    }
    
    // ==================== Packet Processing ====================
    
    private OFPort getIngressPort(OFPacketIn pi) {
        if (pi.getMatch() != null) {
            OFPort port = pi.getMatch().get(MatchField.IN_PORT);
            if (port != null) {
                return port;
            }
        }
        try {
            return OFPort.of(pi.getInPort().getPortNumber());
        } catch (Exception e) {
            return OFPort.TABLE;
        }
    }


    private void learnHost(IOFSwitch sw, OFPort inPort, Ethernet eth) {
    MacAddress srcMac = eth.getSourceMACAddress();
    IPv4Address srcIp = null;

    if (eth.getEtherType() == EthType.IPv4) {
        IPv4 ip = (IPv4) eth.getPayload();
        srcIp = ip.getSourceAddress();
    } else if (eth.getEtherType() == EthType.ARP) {
        ARP arp = (ARP) eth.getPayload();
        
        srcIp = IPv4Address.of(arp.getSenderProtocolAddress().getBytes());
    }

    HostInfo info = new HostInfo(srcMac, srcIp, sw.getId(), inPort);
    learnedHosts.put(srcMac, info);

    if (srcIp != null) {
        ipToMac.put(srcIp, srcMac);
    }
}

private HostInfo getKnownHost(MacAddress mac, IPv4Address ip) {
    if (mac != null) {
        HostInfo byMac = learnedHosts.get(mac);
        if (byMac != null) return byMac;
    }

    if (ip != null) {
        MacAddress learnedMac = ipToMac.get(ip);
        if (learnedMac != null) {
            HostInfo byIp = learnedHosts.get(learnedMac);
            if (byIp != null) return byIp;
        }
    }

    if (HOST1_MAC.equals(mac) || HOST1_IP.equals(ip)) return host1;
    if (HOST2_MAC.equals(mac) || HOST2_IP.equals(ip)) return host2;

    return null;
}

private boolean isDuplicateBroadcast(Ethernet eth) {
    if (eth.getEtherType() != EthType.ARP) {
        return false;
    }

    ARP arp = (ARP) eth.getPayload();
    String key = eth.getSourceMACAddress().toString() + "|" +
                 IPv4Address.of(arp.getSenderProtocolAddress().asCidrMaskLength()) + "|" +
                 IPv4Address.of(arp.getTargetProtocolAddress().asCidrMaskLength()) + "|" +
                 arp.getOpCode();

    long now = System.currentTimeMillis();
    Long old = seenBroadcasts.put(key, now);

    // simple cleanup
    seenBroadcasts.entrySet().removeIf(e -> (now - e.getValue()) > BROADCAST_TTL_MS);

    return old != null && (now - old) < BROADCAST_TTL_MS;
}



private void floodPacket(IOFSwitch sw, OFPacketIn pi, OFPort inPort) {
    OFPacketOut.Builder pob = sw.getOFFactory().buildPacketOut();
    pob.setData(pi.getData());
    pob.setInPort(OFPort.CONTROLLER);

    List<OFAction> actions = new ArrayList<>();
    actions.add(sw.getOFFactory().actions().buildOutput()
            .setPort(OFPort.FLOOD)
            .build());

    pob.setActions(actions);
    sw.write(pob.build());
}
    
    private Command handlePacketIn(IOFSwitch sw, OFPacketIn pi, FloodlightContext cntx) {
    Ethernet eth = IFloodlightProviderService.bcStore.get(
            cntx, IFloodlightProviderService.CONTEXT_PI_PAYLOAD);

    if (eth == null) {
        return Command.CONTINUE;
    }

    OFPort inPort = getIngressPort(pi);

    learnHost(sw, inPort, eth);

    if (eth.getEtherType() == EthType.ARP) {
        return handleARP(sw, pi, eth, inPort, cntx);
    }

    if (eth.getEtherType() == EthType.IPv4) {
        log.info(" ............ IPv4 ..........");
        return handleIPv4(sw, pi, eth, inPort, cntx);
    }

    return Command.CONTINUE;
}
    
    private Command handleARP(IOFSwitch sw, OFPacketIn pi, Ethernet eth, OFPort inPort, FloodlightContext cntx) {
    ARP arp = (ARP) eth.getPayload();

    MacAddress senderMac = MacAddress.of(arp.getSenderHardwareAddress().getBytes());
    IPv4Address senderIp = IPv4Address.of(arp.getSenderProtocolAddress().getBytes());
    IPv4Address targetIp = IPv4Address.of(arp.getTargetProtocolAddress().getBytes());

    HostInfo sender = getKnownHost(senderMac, senderIp);
    HostInfo target = getKnownHost(null, targetIp);


    // ARP request for unknown target: controlled flood, not dual-path install
    if (arp.getOpCode().equals(ARP.OP_REQUEST) && target == null) {
        if (isDuplicateBroadcast(eth)) {
            return Command.STOP;
        }

        floodPacket(sw, pi, inPort);
        return Command.STOP;
    }

    // Known ARP target: use a single path install, not ARP over both paths
    if (sender != null && target != null) {

        path.setSrc(sender.switchId);
        path.setDst(target.switchId, target.port);
        List<List<connection>> multipath = path.findtwoPaths(sender.switchId);

        if (multipath != null && !multipath.isEmpty()) {
            List<connection> selectedPath = multipath.get(0);
            for (connection con : selectedPath) {
                IOFSwitch pathsw = switchService.getSwitch(con.sw);
                if (pathsw != null) {
                    installArpMatch(pathsw, senderMac, con.port);
                }
            }
        }

        return Command.STOP;
    }

    // fallback: flood once if we still cannot resolve both ends
    if (!isDuplicateBroadcast(eth)) {
        floodPacket(sw, pi, inPort);
    }

    return Command.STOP;
}

    private Command handleIPv4(IOFSwitch sw, OFPacketIn pi, Ethernet eth, OFPort inPort, FloodlightContext cntx) {
        MacAddress senderMac = eth.getSourceMACAddress();
        MacAddress targetMac = eth.getDestinationMACAddress();

        HostInfo sender = getKnownHost(senderMac, null);
        HostInfo target = getKnownHost(targetMac, null);

        // fallback to fixed host behavior if dynamic learning has not resolved both ends yet
        if (sender == null || target == null) {
            log.info("Falling back to fixed host mapping for IPv4");
            if (senderMac.equals(host1.mac)) {
                sender = host1;
                target = host2;
            } else {
                sender = host2;
                target = host1;
            }
        }

        log.info("IPv4 sender {} target {}", sender.mac, target.mac);
        findAndInstall(sender, target);
        return Command.STOP;
    }

    private void findAndInstall(HostInfo sender , HostInfo target){
        path.setSrc(sender.switchId);
        path.setDst(target.switchId , target.port);
        List<List<connection>> multipath = path.findtwoPaths(sender.switchId);
        if (multipath.size() ==1 ){
            log.info("there is only one path");
            return;
        }
        log.info("There Are " + multipath.size() + " paths in the Topology");
        List<connection> pathPrimary = multipath.get(0); 
        List<connection> pathSecondery = multipath.get(1);
        IOFSwitch ingressSwitch = switchService.getSwitch(pathPrimary.get(0).sw); 
        printPath(pathPrimary);
        printPath(pathSecondery);
         
        installFailoverGroup(ingressSwitch, sender.mac, target.mac,
            pathPrimary.get(0).port, primaryVlan, pathSecondery.get(0).port, backupVlan);
     
        intallFirst(ingressSwitch, sender.mac, target.mac,
            pathSecondery.get(0).port, backupVlan);
        for (int i = 1 ; i < pathPrimary.size() -1 ; i ++){
            

            IOFSwitch pathsw = switchService.getSwitch(pathPrimary.get(i).sw); 
            installFailoverInterMadiete(pathsw, sender.mac, target.mac, pathPrimary.get(i).port, primaryVlan , pathPrimary.get(i).ingress , backupVlan);


        }

             for (int i = 1 ; i < pathSecondery.size() -1  ; i ++){
            

            IOFSwitch pathsw = switchService.getSwitch(pathSecondery.get(i).sw); 
            installFailoverInterMadiete(pathsw, sender.mac,target.mac, pathSecondery.get(i).port, backupVlan , pathSecondery.get(i).ingress , primaryVlan);
        }

        IOFSwitch egressSwitch = switchService.getSwitch(pathPrimary.get(pathPrimary.size()-1).sw); 
        // installFailoverGroup(egressSwitch, inPort , 
         //    pathPrimary.get(pathPrimary.size() - 1).port, primaryVlan , pathSecondery.get(pathSecondery.size() - 1).port, backupVlan);
         installEgressFlow(egressSwitch, sender.mac, target.mac, target.port );

    }

    private void printPath(List<connection> path){
        for (connection con: path){
            log.info("switch: " +  con.sw.toString() + " port: " +  con.port + " ingress: " + con.ingress + " ->");
            
        }
        log.info("======= end  of path ========");
    }
    private void intallFirst(IOFSwitch sw, MacAddress mac,MacAddress target, OFPort outPort, int vlanID ){


        OFFactory ARPfac = sw.getOFFactory();

    
        Match match = ARPfac.buildMatch()

           
            .setExact(MatchField.ETH_TYPE , EthType.IPv4)
            .setExact(MatchField.ETH_SRC, mac)
            .setExact(MatchField.ETH_DST, target)
            .setExact(MatchField.VLAN_VID, OFVlanVidMatch.ofVlanVid(VlanVid.ofVlan(vlanID)))

            .build();

        OFAction action = ARPfac.actions().buildOutput()
        .setPort(outPort)
        .build();

        List<OFAction> actions = new ArrayList<>();
        actions.add(action);
        OFFlowAdd flowAdd = ARPfac.buildFlowAdd()
            .setMatch(match)
            .setActions(actions)
            .setPriority(50) 
            .build();

       
        sw.write(flowAdd);
    }
    private void installArpMatch(IOFSwitch sw, MacAddress mac, OFPort outPort ){


        OFFactory ARPfac = sw.getOFFactory();

    
        Match match = ARPfac.buildMatch()

           
            .setExact(MatchField.ETH_TYPE , EthType.ARP)
            .setExact(MatchField.ETH_SRC, mac)
            
            .build();

        OFAction action = ARPfac.actions().buildOutput()
        .setPort(outPort)
        .build();

        List<OFAction> actions = new ArrayList<>();
        actions.add(action);
        OFFlowAdd flowAdd = ARPfac.buildFlowAdd()
            .setMatch(match)
            .setActions(actions)
            .setPriority(100) 
            .build();

       
        sw.write(flowAdd);
    }


private Match createMatch(OFFactory factory , MacAddress sender , MacAddress target, int vlanID){
    return  factory.buildMatch()
        .setExact(MatchField.ETH_TYPE, EthType.IPv4)
        .setExact(MatchField.ETH_SRC, sender)
        .setExact(MatchField.ETH_DST, target)
        .setExact(MatchField.VLAN_VID, OFVlanVidMatch.ofVlanVid(VlanVid.ofVlan(vlanID)))
        // .setExact(MatchField.IP_PROTO, IpProtocol.ICMP)

        .build();
}
    private void installEgressFlow(IOFSwitch sw, MacAddress sender , MacAddress target, OFPort outPort) {
        
        OFFactory factory = sw.getOFFactory(); 
        Match match = factory.buildMatch()
            .setExact(MatchField.ETH_TYPE, EthType.IPv4)
            .setExact(MatchField.ETH_SRC, sender)
            .setMasked(MatchField.VLAN_VID, OFVlanVidMatchWithMask.ANY_TAGGED)

            .setExact(MatchField.ETH_DST, target).build();
        
        List<OFAction> actions = new ArrayList<>();
        actions.add(sw.getOFFactory().actions().popVlan());
        actions.add(sw.getOFFactory().actions().buildOutput().setPort(outPort).build());
        
        OFFlowMod flowMod = sw.getOFFactory().buildFlowAdd()
            .setMatch(match)
            .setActions(actions)
            .setPriority(100)
            .build();
        sw.write(flowMod);
    }
private void installVlanCheck(IOFSwitch sw, MacAddress sender,  MacAddress target,
                                   OFPort inPort, int backupVlan){

            OFFactory factory = sw.getOFFactory();
            Match.Builder matchBuilder = factory.buildMatch()
            .setExact(MatchField.ETH_TYPE, EthType.IPv4)
            .setExact(MatchField.ETH_SRC, sender)
            .setExact(MatchField.ETH_DST, target)
            .setExact(MatchField.VLAN_VID, OFVlanVidMatch.ofVlan(backupVlan));
            Match match = matchBuilder.build();
            OFActionOutput outputAction = factory.actions().buildOutput()
            .setPort(inPort)
            .build();
            List<OFAction> actions = new ArrayList<>();
            actions.add(outputAction);
            OFFlowMod flowMod = factory.buildFlowAdd()
            .setMatch(match)
            .setActions(actions)
            .setPriority(90)  
            .setIdleTimeout(0)
            .setHardTimeout(0)
            .build();
    
            sw.write(flowMod);

                        
            }

private void installFailoverInterMadiete(IOFSwitch sw, MacAddress sender,  MacAddress target,
                                   OFPort primaryOutPort, int primaryVlan,
                                   OFPort backupOutPort, int backupVlan) {

    log.info(sw.getId().toString());

    OFFactory factory = sw.getOFFactory(); 
  
    int groupId = (sw.getId().hashCode() + (int) sender.getLong() + new Random().ints(1, 10, 50).findFirst().getAsInt()) & 0xFFFF;
    OFGroupMod deleteGroup = sw.getOFFactory().buildGroupDelete()
        .setGroupType(OFGroupType.FF) 
        .setGroup(OFGroup.of(groupId))
        .build();
    sw.write(deleteGroup);
    OFAction outputPrimary = sw.getOFFactory().actions().buildOutput().setPort(primaryOutPort).build();
    List<OFAction> primaryActions = new ArrayList<>();
;
    primaryActions.add(outputPrimary);
    OFBucket primaryBucket = sw.getOFFactory().buildBucket()
        .setActions(primaryActions)
        .setWatchPort(primaryOutPort)
        .build();
    

    OFAction outputBackup = sw.getOFFactory().actions().buildOutput().setPort(OFPort.IN_PORT).build();

  
    OFAction setVlanBackup = sw.getOFFactory().actions().buildSetField().setField( sw.getOFFactory()
    .oxms().buildVlanVid().setValue(OFVlanVidMatch.ofVlan(backupVlan )).build()).build();
    List<OFAction> backupActions = new ArrayList<>(); 

    backupActions.add(setVlanBackup); 
    backupActions.add(outputBackup); 

 
    OFBucket backupBucket = sw.getOFFactory().buildBucket()
        .setActions(backupActions)
        .setWatchPort(backupOutPort)
        .build();
    
    OFGroupMod groupMod = sw.getOFFactory().buildGroupAdd()
        .setGroup(OFGroup.of(groupId))
        .setGroupType(OFGroupType.FF) 
        .setBuckets(Arrays.asList(primaryBucket, backupBucket))
        .build();
    sw.write(groupMod);
    
    // Flow that sends to this group
    Match match = createMatch(factory, sender, target , primaryVlan);
    OFActionGroup groupAction = sw.getOFFactory().actions().buildGroup()
        .setGroup(OFGroup.of(groupId))
        .build();
    List<OFAction> groupActions = new ArrayList<>(); 
    groupActions.add(groupAction); 
    OFFlowMod flowMod = sw.getOFFactory().buildFlowAdd()
        .setMatch(match)
        .setActions(groupActions)
        .setPriority(100)
        .build();
    sw.write(flowMod);
    installVlanCheck(sw , sender, target, backupOutPort , backupVlan);
}


private void installFailoverGroup(IOFSwitch sw, MacAddress sender, MacAddress target,
                                   OFPort primaryOutPort, int primaryVlan,
                                   OFPort backupOutPort, int backupVlan) {

    log.info(sw.getId().toString());

    
    int groupId = (sw.getId().hashCode() + (int)sender.getLong() + new Random().ints(1, 10, 50).findFirst().getAsInt()) & 0xFFFF;
    OFGroupMod deleteGroup = sw.getOFFactory().buildGroupDelete()
        .setGroupType(OFGroupType.FF) 
        .setGroup(OFGroup.of(groupId))
        .build();
    sw.write(deleteGroup);

    OFFactory factory = sw.getOFFactory();
    OFAction pushVlanPrimary = sw.getOFFactory().actions().pushVlan(EthType.of(0x8100));
    OFAction setVlanPrimary = sw.getOFFactory().actions().buildSetField().setField( sw.getOFFactory()
    .oxms().buildVlanVid().setValue(OFVlanVidMatch.ofVlan(primaryVlan )).build()).build();
    OFAction outputPrimary = sw.getOFFactory().actions().buildOutput().setPort(primaryOutPort).build();
    List<OFAction> primaryActions = new ArrayList<>();
    primaryActions.add(pushVlanPrimary);
    primaryActions.add(setVlanPrimary);
    primaryActions.add(outputPrimary);
    OFBucket primaryBucket = sw.getOFFactory().buildBucket()
        .setActions(primaryActions)
        .setWatchPort(primaryOutPort)
        .build();
    
    OFAction pushVlanBackup = sw.getOFFactory().actions().pushVlan(EthType.of(0x8100));
    OFAction setVlanBackup = sw.getOFFactory().actions().buildSetField().setField( sw.getOFFactory()
    .oxms().buildVlanVid().setValue(OFVlanVidMatch.ofVlan(backupVlan )).build()).build();
    OFAction outputBackup = sw.getOFFactory().actions().buildOutput().setPort(backupOutPort).build();

    
    List<OFAction> backupActions = new ArrayList<>(); 
    backupActions.add(pushVlanBackup); 
    backupActions.add(setVlanBackup); 
    backupActions.add(outputBackup); 
    
    OFBucket backupBucket = sw.getOFFactory().buildBucket()
        .setActions(backupActions)
        .setWatchPort(backupOutPort)
        .build();
    
    OFGroupMod groupMod = sw.getOFFactory().buildGroupAdd()
        .setGroup(OFGroup.of(groupId))
        .setGroupType(OFGroupType.FF) 
        .setBuckets(Arrays.asList(primaryBucket, backupBucket))
        .build();
    sw.write(groupMod);
    
     Match match = factory.buildMatch()
        .setExact(MatchField.ETH_TYPE, EthType.IPv4)
        .setExact(MatchField.ETH_SRC, sender)
        .setExact(MatchField.ETH_DST, target)
        .setExact(MatchField.VLAN_VID, OFVlanVidMatch.UNTAGGED)

        // .setExact(MatchField.IP_PROTO, IpProtocol.ICMP)

        .build();
    OFActionGroup groupAction = sw.getOFFactory().actions().buildGroup()
        .setGroup(OFGroup.of(groupId))
        .build();
    List<OFAction> groupActions = new ArrayList<>(); 
    groupActions.add(groupAction); 
    OFFlowMod flowMod = sw.getOFFactory().buildFlowAdd()
        .setMatch(match)
        .setActions(groupActions)
        .setPriority(100)
        .build();
    sw.write(flowMod);
}
    private void forwardPacket(IOFSwitch sw, OFPacketIn pi, OFPort outPort) {
        OFPacketOut.Builder pob = sw.getOFFactory().buildPacketOut();
        pob.setData(pi.getData());
        pob.setInPort(OFPort.CONTROLLER);
        
        List<OFAction> actions = new ArrayList<>();
        actions.add(sw.getOFFactory().actions().buildOutput()
            .setPort(outPort)
            .build());
        pob.setActions(actions);
        
        sw.write(pob.build());
    }
}


