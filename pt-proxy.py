"""
In client mode, this code pretends to be a local proxy (SOCKS or otherwise) 
and communicates all TCP traffic via a Tor Pluggable Transport (e.g., obfs4). 

by Micah Sherr <msherr@cs.georgetown.edu>


Note: the Tor PT spec is at https://gitweb.torproject.org/torspec.git/tree/pt-spec.txt
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

    # arguments for both client and server mode
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
        '-t', '--pttype',
        dest='pttype',
        help='pluggable transport type (defaults to obfs4)',
        default='obfs4'
        )
    parser.add_argument(
        '-d', '--ptdir',
        dest='ptdir',
        help='directory where PT can keep its state',
        required=True
        )
    
    subparsers = parser.add_subparsers(help='sub-command help', dest='command')
    parser_client = subparsers.add_parser('client', help='client help')
    parser_server = subparsers.add_parser('server', help='server help')

    # client-mode arguments
    parser_client.add_argument(
        '-B', '--bridge',
        dest='bridge',
        help='IP and port of a remote bridge (e.g., 1.2.3.4:443)',
        required=True
    )
    parser_client.add_argument(
        '-i', '--info',
        dest='bridgeinfo',
        help='bridge-specific information (e.g., cert=ssH+9rP8dG2NLDN2XuFw63hIO/9MNNinLmxQDpVa+7kTOa9/m+tGWT1SmSYpQ9uTBGa6Hw;iat-mode=0).  You should probably escape this argument.',
        )
    parser_client.add_argument(
        '-p', '--port',
        dest='port',
        help='local proxy port to spin up (this is what you point your browser, etc., towards)',
        type=int,
        default=9999,
        )

    # server-mode arguments
    parser_server.add_argument(
        '-S', '--bind',
        dest='bind',
        help='IP and port to bind to (e.g., 1.2.3.4:443)',
        )
    parser_server.add_argument(
        '-p', '--port',
        dest='port',
        help='port of locally running proxy (e.g., tinyproxy)',
        type=int,
        default=8080,
        )

    args = parser.parse_args()
    return args



class PTConnectError(Exception):
    def __init__(self, message):
        self.message = message



"""
launches the Tor Pluggable Transport.
if running in client mode, returns the address (probably always localhost)
and port to use to connect to the PT's SOCKS instance
"""
def launch_pt_binary( args ):
    global proc
    logger = logging.getLogger('pt-proxy')        

    logger.info( 'launch PT client' )
    
    if args.command == 'client':
        os.environ['TOR_PT_CLIENT_TRANSPORTS'] = args.pttype
    if args.command == 'server':
        os.environ['TOR_PT_SERVER_TRANSPORTS'] = args.pttype
        os.environ['TOR_PT_SERVER_BINDADDR'] = "%s-%s" % (args.pttype,args.bind)
        os.environ['TOR_PT_ORPORT'] = '127.0.0.1:%d' % args.port

    os.environ['TOR_PT_MANAGED_TRANSPORT_VER'] = '1'
    os.environ['TOR_PT_EXIT_ON_STDIN_CLOSE'] = '0'
    os.environ['TOR_PT_STATE_LOCATION'] = args.ptdir
    logger.info( 'PT will keep state in %s', args.ptdir )

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
            )

        if args.command == 'server':
            logger.info( 'spawned PT client in server mode.  you may want to look in the "%s" directory for the cert' % args.ptdir )
            return (None,None)
            
        if args.command == 'client':
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
                exit(1)
        
            logger.info( 'PT is running %s on %s:%d' % (proto,addr,port) )
            return (addr, port)
        
    except FileNotFoundError as e:
        logger.error( 'error launching PT: %s', e )
        exit(1)
        

        
"""
connects to an already running local PT (via its SOCKS5 protocol)
"""
def connect_to_client_pt( addr, port, args ):
    logger = logging.getLogger('pt-proxy')        
    s = socks.socksocket()
    try:
        # authenticate to PT bridge
        (bridge_ip,bridge_port) = args.bridge.split(':')
        s.set_proxy(socks.SOCKS5, addr, port, username=args.bridgeinfo, password='\0')
        logger.debug( 'authenticated to PT bridge' )
        logger.debug( 'connecting to bridge (%s,%s)' % (bridge_ip,bridge_port) )
        s.connect((bridge_ip, int(bridge_port))) 
    except socks.ProxyConnectionError as e:
        logger.error( 'cannot connect to proxy: %s' % e )
        proc.kill()
        return None
    except socks.GeneralProxyError as e:
        logger.error( 'cannot connect to proxy: %s' % e )
        proc.kill()
        return None

    logger.debug( 'connected to bridge (%s,%s)' % (bridge_ip,bridge_port) )
    return s                          # all's good


    
"""
listen on a local port, and relay all communication sent to/from
this port to our PT
"""
def launch_client_listener_service( pt_addr, pt_port, args ):
    logger = logging.getLogger('pt-proxy')        
    try:
        server_socket = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
        server_socket.bind( ('localhost', args.port))
        logger.info( 'pt-proxy.py is bound on port %d (set your proxy to be localhost:%d)' % (args.port,args.port) )
        server_socket.listen(1)

        pt_socks = []
        client_socks = []
        client_to_PT_map = dict()
        PT_to_client_map = dict()
        
        while True:
            # wait until something happens
            rlist = [server_socket] + pt_socks + client_socks
            (rready, _, _) = select.select( rlist, [], [] )

            if server_socket in rready:   # a new connection to our local "server"
                (client_socket, address) = server_socket.accept()        
                logger.debug( 'connection opened from %s' % str(address) )
                # open a new connection to the PT
                pt_sock = connect_to_client_pt( pt_addr, pt_port, args )
                # associate the client socket to the PT socket
                client_to_PT_map[client_socket] = pt_sock
                PT_to_client_map[pt_sock] = client_socket
                client_socks += [client_socket]
                pt_socks += [pt_sock]

            # check if we have anything arriving from the PT
            for pt_sock in pt_socks:
                if pt_sock in rready:
                    client_sock = PT_to_client_map[pt_sock]
                    data = pt_sock.recv(512)
                    if len(data) == 0:
                        logger.debug( 'PT closed its connection' )
                        client_sock.close()
                        pt_sock.close()
                        client_socks.remove(client_sock)
                        pt_socks.remove(pt_sock)
                        del client_to_PT_map[client_sock]
                        del PT_to_client_map[pt_sock]
                    else:
                        client_sock.send(data)

            # check if we have anything arriving from our local "server"
            for client_sock in client_socks:
                if client_sock in rready:
                    pt_sock = client_to_PT_map[client_sock]
                    try:
                        data = client_sock.recv(512)
                        if len(data) == 0:
                            logger.debug( 'local process closed its connection' )                        
                            client_sock.close()
                            pt_sock.close()
                            client_socks.remove(client_sock)
                            pt_socks.remove(pt_sock)
                            del client_to_PT_map[client_sock]
                            del PT_to_client_map[pt_sock]
                        else:
                            pt_sock.send(data)
                    except ConnectionResetError:
                            logger.debug( 'local process reset its connection' )                        
                            pt_sock.close()
                            client_socks.remove(client_sock)
                            pt_socks.remove(pt_sock)
                            del client_to_PT_map[client_sock]
                            del PT_to_client_map[pt_sock]

                        
    except KeyboardInterrupt:
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
    logger = logging.getLogger('pt-proxy')
    logging.Formatter.converter = time.gmtime   # use GMT

    logger.info( "running with arguments: %s" % args )
    
    (pt_addr,pt_port) = launch_pt_binary(args)
    if args.command == 'client':
        launch_client_listener_service( pt_addr, pt_port, args )
    elif args.command == 'server':
        logger.info( 'server mode activated. will wait here indefinitely.' )
        while True: time.sleep(1)

    proc.kill()
    exit( 0 )                             # all's well that ends well

    
if __name__== "__main__":
    main(parse_args())
    
