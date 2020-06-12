# pt-proxy
A socks5-based proxy that uses Tor Pluggible Transports, without Tor


## Usage

```
usage: pt-proxy.py [-h] -l LOGFILE -b PTBINARY [-t PTTYPE] -d PTDIR {client,server} ...

positional arguments:
  {client,server}       sub-command help
    client              client help
    server              server help

optional arguments:
  -h, --help            show this help message and exit
  -l LOGFILE, --logfile LOGFILE
                        log file
  -b PTBINARY, --binary PTBINARY
                        path to PT proxy (e.g., /usr/bin/obfs4proxy)
  -t PTTYPE, --pttype PTTYPE
                        pluggable transport type (defaults to obfs4)
  -d PTDIR, --ptdir PTDIR
                        directory where PT can keep its state
```


## Examples

* *"bridge"-side:* spawn obfs4, listen on port 9876 for incoming obfs
connections, and forward to a proxy (e.g., tinyproxy) running locally on port 8080:
```
python pt-proxy.py -d state -l log.log -b /usr/bin/obfs4proxy server -S 0.0.0.0:9876 -p 8080
```
  Note that this assumes that tinyproxy or whatever is already running
  locally on port 8080.
* *client-side:* spawn obfs4, connect to a obfs4proxy instance running
at 35.206.90.25 on port 9876, using the certificate listed after the
"-i" option:
```
python pt-proxy.py -d /tmp/micah -l log.log -t obfs4 -b
/usr/bin/obfs4proxy client -B 35.206.90.25:9876 -p 9999 -i 'cert=5LwMm3/A7yX48ZnAMSBP7cAyVboB+Id/+IEoPajJLU4qe7ocy2YVvqd85BL1H8xh/KpkHQ;iat-mode=0'
```


## Step-by-step instructions

* Create a VM or whatever.  Call this your "bridge".  Install
  obfs4proxy or whatever PT you want, as well as an actual proxy
  (e.g., tinyproxy or squid).

* Configure tinyproxy or whatever proxy technique you want on the
bridge.  It only needs to accept connections from localhost.

* Run the above "bridge-side" example, substituting in the correct IP
  addresses and ports.  Make sure that your firewall is open to
  whatever you set the -S option to.  That's where the remote
  connections will arrive.

* On a client (e.g., a desktop), install obfs4proxy.  Then, run the
above "client-side" command.

* On the client, set the proxy in your client-side software (e.g., firefox) to use
localhost and whatever port was specified in the -p option.

* Enjoy!
