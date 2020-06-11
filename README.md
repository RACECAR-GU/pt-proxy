# pt-proxy
A socks5-based proxy that uses Tor Pluggible Transports, without Tor


```
usage: pt-proxy.py [-h] -l LOGFILE -b PTBINARY [-t PTTYPE] {client,server} ...

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
```


Example:

* spawn obfs4, listen on port 9876 for incoming obfs connections, and forward to a proxy running locally on port 8888:
```
python pt-proxy.py -l log.log -b /usr/bin/obfs4proxy server -S 0.0.0.0:9876 -p 8888
```

