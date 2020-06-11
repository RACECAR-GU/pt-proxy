"""
In client mode, this code pretends to be a local proxy (SOCKS or otherwise) 
and communicates all TCP traffic via a Tor Pluggable Transport (e.g., obfs4). 

by Micah Sherr <msherr@cs.georgetown.edu>

"""

import logging
import os
import sys
import time
import socket
import select
import argparse
import tempfile
import subprocess
import re
import socks



def parse_args():
    parser = argparse.ArgumentParser()

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-c', '--client', dest='clientmode', action='store_true')
    group.add_argument('-s', '--server', dest='servermode', action='store_false')
    
    parser.add_argument(
        '-b', '--binary',
        dest="ptbinary",
        help="path to PT proxy (e.g., /usr/bin/obfs4proxy)",
        required = True
        )
    parser.add_argument(
        '-p', '--pttype',
        dest='pttype',
        help='pluggable transport type (defaults to obfs4)',
        default='obfs4'
        )
    parser.add_argument(
        '-l', '--logfile',
        dest="logfile",
        help="log file",
        required = True
        )

    args = parser.parse_args()
    return args



"""
launches the Tor Pluggable Transport and returns a filehandle to be
used to communicate with the other endpoint
"""
def launch_pt_binary( args ):
    global proc
    logger = logging.getLogger('pt-proxy-client')        
    logger.info( 'launch PT client' )

    tmpdir = tempfile.mkdtemp()
    logger.info( 'PT will keep state in %s', tmpdir )
    
    os.environ['TOR_PT_MANAGED_TRANSPORT_VER'] = '1'
    os.environ['TOR_PT_STATE_LOCATION'] = tmpdir
    os.environ['TOR_PT_EXIT_ON_STDIN_CLOSE'] = '1'
    os.environ['TOR_PT_CLIENT_TRANSPORTS'] = args.pttype

    try:
        proc = subprocess.Popen(
            [args.ptbinary],
            stdin = subprocess.PIPE,
            stdout = subprocess.PIPE,
            stderr = sys.stdout
            )
        outs, errs = proc.communicate(timeout=15)

        # parse output to get correct port
        m = re.search(b'CMETHOD (.*) (.*) (.*):([0-9]+)\n', outs, re.MULTILINE)
        if not m:
            logger.error( 'could not find proxy port and IP from PT' )
            proc.kill()
            return
        transport = m.group(1).decode()
        proto = m.group(2).decode()
        addr = m.group(3).decode()
        port = int(m.group(4).decode())
        if proto != "socks5":
            logger.error( 'doh! I only know how to speak socks5, not %s' % proto )
            proc.kill()
            return
        if transport != args.pttype:
            logger.error( 'invalid PT type: %s vs %s', transport, args.pttype )
            proc.kill()
            return
        
        logger.info( 'PT is running %s on %s:%d' % (proto,addr,port) )
        
        # TODO: authenticate to it
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, addr, port, username='cert=sjVM7v2cpvtw4GLWaP+TEVUeEhld07iGa8AqEYQk3IHIbtr0Rpiqw6weoKMcnZEZ1+pmFQ;iat-mode=0')
        # Can be treated identical to a regular socket object
        s.connect(("209.148.46.65", 443))   # TODO: DONT HARDCODE THIS
        #s.sendall("GET / HTTP/1.1 ...")
        #print(s.recv(4096))

        return s
#        proc.kill()
        
    except FileNotFoundError as e:
        logger.error( 'error launching PT: %s', e )
        exit(1)
        


    
"""
listen on a local port, and relay all communication sent to/from
this port to our PT
"""
def launch_client_listener_service( pt_sock ):
    logger = logging.getLogger('pt-proxy-client')        
    try:
        s = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
        s.bind( ('localhost', 0))
        port = s.getsockname()[1]
        logger.info( 'bound on port %d' % port )

        connected_clients = []
        
        while True:
            rlist = [s] + connected_clients
            (rready, _, _) = select.select( rlist, _, _ )
            if s in rready:
                (clientsocket, address) = s.accept()
                logger.info( 'connection opened from %s' % address )
                connected_clients += [clientsocket]
            for c in connected_clients:
                if c in rready:
                    data = c.read()
                    pt_sock.write(data)
                    
    except KeyboardInterrupt:
        s.close()
        return

  
def main( args ):
    global proc
    
    # set up logging
    FORMAT = '%(asctime)-15s %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        format=FORMAT,
        level=logging.INFO,
        handlers=[
            logging.FileHandler(args.logfile),
            logging.StreamHandler()]
        )
    logger = logging.getLogger('pt-proxy-client')
    logging.Formatter.converter = time.gmtime   # use GMT

    logger.info( "running with arguments: %s" % args )
    
    pt_sock = launch_pt_binary(args)
    if pt_sock != None:
        if args.clientmode is True:
            launch_client_listener_service( pt_sock )

    proc.kill()
    exit( 0 )                             # all's well that ends well

    
if __name__== "__main__":
    main(parse_args())
    
