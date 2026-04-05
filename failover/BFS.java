package net.floodlightcontroller.failover;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedList;
import java.util.List;
import java.util.Map;
import java.util.Queue;

import org.projectfloodlight.openflow.types.DatapathId;
import org.projectfloodlight.openflow.types.OFPort;

import net.floodlightcontroller.linkdiscovery.ILinkDiscoveryService;
import net.floodlightcontroller.linkdiscovery.Link;
import net.floodlightcontroller.linkdiscovery.internal.LinkInfo;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class DFS {
    
    public boolean[] visited;         
    public Map<DatapathId , List<connection>> adj; 
    public Map<Link, LinkInfo> links;
    public DatapathId srcsw;
    public DatapathId dstsw ; 
    public OFPort dstPort;  
    public connection lasthop; 
    public List<connection> path ;     
    public List<List<connection>> pathCollection; 
    private static Logger log = LoggerFactory.getLogger(FailoverForwarding.class);

    private class BFSState {
        DatapathId current;
        List<connection> pathSoFar;
        
        BFSState(DatapathId current, List<connection> pathSoFar) {
            this.current = current;
            this.pathSoFar = pathSoFar;
        }
    }

    DFS(ILinkDiscoveryService linkDiscoveryService) {
        pathCollection = new ArrayList<List<connection>>(); 
        path = new ArrayList<connection>();
        
        this.links = linkDiscoveryService.getLinks();
        log.info("link size is: " + links.size());
        visited = new boolean[200]; 
        adj = new HashMap<DatapathId , List<connection>>();
        
        if (links.size() != 0) {
            for (Map.Entry<Link, LinkInfo> entry : links.entrySet()) {
                Link link = entry.getKey();
                DatapathId srcSw = link.getSrc();
                OFPort srcPort = link.getSrcPort();
                DatapathId dstSw = link.getDst();
          
                OFPort dstPort = link.getDstPort(); 
                if (!adj.containsKey(srcSw)) {                    if (!isSwitchInPath(con.sw, currentPath)) {

                    adj.put(srcSw, new ArrayList<connection>()); 
                }
    
                connection dst = new connection(dstSw, srcPort , dstPort);
                adj.get(srcSw).add(dst);
            }
            
        }
    }

    public void setSrc(DatapathId src) {
        this.srcsw = src; 
        path.clear();
        pathCollection.clear();
    }

    public void setDst(DatapathId dst , OFPort port) {
        this.dstsw = dst ;
        this.dstPort = port;
        path = new ArrayList<connection>();
    }


    public List<List<connection>> findtwoPaths(DatapathId sw) {
 
        pathCollection.clear();
        
    
        Queue<BFSState> queue = new LinkedList<>();
        

        queue.add(new BFSState(sw, new ArrayList<connection>()));
        
        while (!queue.isEmpty()) {
            if (pathCollection.size() > 2)
                break;
            BFSState state = queue.poll();
            DatapathId current = state.current;
            List<connection> currentPath = state.pathSoFar;
           
            if (current.equals(dstsw)) {
                List<connection> copypath = new ArrayList<connection>();
             
                                    if (!isSwitchInPath(con.sw, currentPath)) {


                copypath.add(currentPath.get(0));
         
                for (int i = 1 ; i< currentPath.size() ; i ++){
     
                    
                    connection con = new connection(currentPath.get(i).sw , currentPath.get(i).port, currentPath.get(i-1).ingress);
                    copypath.add(con);
       
                }
                lasthop = new connection(this.dstsw, this.dstPort , copypath.get(copypath.size() -1).ingress );
                log.info("----------------");
                copypath.add(lasthop);
                pathCollection.add(copypath);
                
                continue; 
            }
            

            List<connection> neighbors = adj.get(current);
            if (neighbors != null) {
                for (connection con : neighbors) {
                    if (!isSwitchInPath(con.sw, currentPath)) {
                        List<connection> newPath = new ArrayList<connection>(currentPath);
                        newPath.add(new connection(current, con.port , con.ingress));
                        queue.add(new BFSState(con.sw, newPath));
                    }
                }
            }
        }
        
        return pathCollection;
    }
    

    private boolean isSwitchInPath(DatapathId targetSw, List<connection> path) {
        if (targetSw.equals(srcsw)) return true;
        
        for (connection conn : path) {
            if (conn.sw.equals(targetSw)) {
                return true;
            }
        }
        return false;
    }

    public int getDPNumber(DatapathId sw) {
        String s = sw.toString();
        String[] swlist = s.split(":");
        int swNumber = Integer.parseInt(swlist[swlist.length - 1]);
        return swNumber;
    }
}
