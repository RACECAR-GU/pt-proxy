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
        '-l', '--logfile',
        dest="logfile",
        help="log file",
        required = True
        )
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
        '-B', '--bridge',
        dest='bridge',
        help='IP and port of a bridge (e.g., 1.2.3.4:443)',
        )
    parser.add_argument(
        '-i', '--info',
        dest='bridgeinfo',
        help='bridge-specific information (e.g., cert=ssH+9rP8dG2NLDN2XuFw63hIO/9MNNinLmxQDpVa+7kTOa9/m+tGWT1SmSYpQ9uTBGa6Hw;iat-mode=0).  You should probably escape this argument.',
        required=True
        )


    args = parser.parse_args()

    if args.clientmode is True and args.bridge is None:
        print( 'client mode requires bridge (--bridge) to be specified' )
        exit(1)

    return args



class PTConnectError(Exception):
    """Exception raised for errors in the input.

    Attributes:
        message -- explanation of the error
    """

    def __init__(self, message):
        self.message = message



"""
launches the Tor Pluggable Transport and returns a filehandle to be
used to communicate with the other endpoint
"""
def launch_pt_binary( args ):
    global proc
    logger = logging.getLogger('pt-proxy-client')        

    (bridge_ip,bridge_port) = args.bridge.split(':')

    logger.info( 'launch PT client' )
    tmpdir = tempfile.mkdtemp()
    logger.info( 'PT will keep state in %s', tmpdir )
    
    os.environ['TOR_PT_MANAGED_TRANSPORT_VER'] = '1'
    os.environ['TOR_PT_STATE_LOCATION'] = tmpdir
    os.environ['TOR_PT_EXIT_ON_STDIN_CLOSE'] = '0'

    if args.clientmode:
        os.environ['TOR_PT_CLIENT_TRANSPORTS'] = args.pttype
    if args.servermode:
        os.environ['TOR_PT_SERVER_TRANSPORTS'] = args.pttype
        os.environ['TOR_PT_SERVER_TRANSPORT_OPTIONS'] = '%s:%s' % (args.pttype,args.bridgeinfo)
        # TODO: more work here.

    try:
        proc = subprocess.Popen(
            [
                args.ptbinary,
                "-enableLogging",
                "-logLevel", "DEBUG",
            ],
            stdin = subprocess.DEVNULL,
            stdout = subprocess.PIPE,
            stderr = subprocess.PIPE,
            bufsize = 1                   # line buffered
            )

        try:
            # read from PT to get CMETHOD output (written to its stdout)
            # and then parse output to get correct port
            if b'VERSION 1' not in proc.stdout.readline(): raise PTConnectError('wrong version')
            method = proc.stdout.readline()
            m = re.search(b'CMETHOD (.*) (.*) (.*):([0-9]+)\n', method, re.MULTILINE)
            if not m: raise PTConnectError('could not find proxy port and IP from PT: %s' % out )
            transport = m.group(1).decode()
            proto = m.group(2).decode()
            addr = m.group(3).decode()
            port = int(m.group(4).decode())
            if proto != "socks5": raise PTConnectError( 'I only know how to speak socks5, not %s' % proto )
            if transport != args.pttype: raise PTConnectError( 'invalid PT type: %s vs %s', transport, args.pttype )
        except PTConnectError as e:
            logger.error( 'could not connect to PT SOCKS proxy: %s' % e )
            proc.kill()
            return
        
        logger.info( 'PT is running %s on %s:%d' % (proto,addr,port) )
        
        s = socks.socksocket()
        try:
            # authenticate to PT bridge
            s.set_proxy(socks.SOCKS5, addr, port, username=args.bridgeinfo, password='\0')
            logger.info( 'authenticated to PT bridge' )
            logger.info( 'connecting to bridge (%s,%s)' % (bridge_ip,bridge_port) )
            s.connect((bridge_ip, int(bridge_port))) 
        except socks.ProxyConnectionError as e:
            logger.error( 'cannot connect to proxy: %s' % e )
            time.sleep(200)
            proc.kill()
            return None
        except socks.GeneralProxyError as e:
            logger.error( 'cannot connect to proxy: %s' % e )
            time.sleep(200)
            proc.kill()
            return None

        logger.info( 'connected to bridge (%s,%s)' % (bridge_ip,bridge_port) )
        
        return s                          # all's good
        
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
        logger.info( 'pt-proxy.py is bound on port %d (set your proxy to be localhost:%d)' % (port,port) )

        connected_clients = []
        
        while True:
            rlist = [s,pt_sock] + connected_clients
            (rready, _, _) = select.select( rlist, [], [] )
            if s in rready:               # we have a connecting client
                (clientsocket, address) = s.accept()
                logger.info( 'connection opened from %s' % address )
                connected_clients += [clientsocket]
            if pt_sock in rready:         # there's data from the PT
                data = pt_sock.read()
                c.write(data)
            for c in connected_clients:
                if c in rready:           # there's data from the browser
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
        elif args.servermode is True:
            logger.warn( 'server mode is not yet implemented' )   # TODO

    proc.kill()
    exit( 0 )                             # all's well that ends well

    
if __name__== "__main__":
    main(parse_args())
    
