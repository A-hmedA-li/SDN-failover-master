package net.floodlightcontroller.failover;

import org.projectfloodlight.openflow.types.DatapathId;
import org.projectfloodlight.openflow.types.OFPort;


public class connection {
    public DatapathId sw;
    public OFPort port; 
    public OFPort ingress; 

    connection(DatapathId sw , OFPort port, OFPort ingress){
        this.sw = sw; 
        this.port = port; 
        this.ingress = ingress;

    }

    @Override
    public boolean equals(Object o){
        connection con = (connection) o ;
        if (con.sw == this.sw)
            return true; 
        else
            return false ; 
    }

    @Override
    public String toString(){
        String s = sw.toString() + " port: " + port.toString() + " ingress: " + ingress.toString();
        return s;
    }

}
