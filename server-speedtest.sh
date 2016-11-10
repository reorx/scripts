#!/bin/bash
#
#	server-speedtest - An utility to test network quality and speeds on a server
#	https://github.com/iceTwy/server-speedtest
#

function download_benchmark() {
	DOWNLOAD_SPEED=`wget -O /dev/null $2 2>&1 | awk '/\/dev\/null/ {speed=$3 $4} END {gsub(/\(|\)/,"",speed); print speed}'`
	echo "$1: $DOWNLOAD_SPEED ($2)"
}

function do_traceroute() {
	TRACEROUTE=`traceroute $2 2>&1`
	echo "Traceroute to $1..."
	echo "$TRACEROUTE"
	echo
}

function do_ping() {
	echo "Pinging $1..."
	PING=`ping -c 10 $2 2>&1`
	echo "$PING"
	echo
}

echo
echo               "####################################"
echo               "#        Bandwidth Benchmark       #"
echo               "####################################"
echo
echo               '------------------------------------'
echo               '            Global (CDN)            '
echo               '------------------------------------'
download_benchmark 'Cachefly' 'http://cachefly.cachefly.net/100mb.test'

echo
echo               '------------------------------------'
echo               '          Northern America          '
echo               '------------------------------------'
download_benchmark 'OVH, Montreal, Canada' 'http://proof.ovh.ca/files/100Mio.dat'
download_benchmark 'Linode, Atlanta, GA, USA' 'http://speedtest.atlanta.linode.com/100MB-atlanta.bin'
download_benchmark 'Linode, Dallas, TX, USA' 'http://speedtest.dallas.linode.com/100MB-dallas.bin'
download_benchmark 'CDN77 Chicago, USA' 'http://793343545.r.cdn77.net/design/swf/testfile100.bin'
download_benchmark 'Softlayer, Seattle, WA, USA' 'http://speedtest.sea01.softlayer.com/downloads/test100.zip'
download_benchmark 'Softlayer, San Jose, CA, USA' 'http://speedtest.sjc01.softlayer.com/downloads/test100.zip'
download_benchmark 'Softlayer, Washington, DC, USA' 'http://speedtest.wdc01.softlayer.com/downloads/test100.zip'
download_benchmark 'Leaseweb, Manassas, VA, USA' 'http://mirror.us.leaseweb.net/speedtest/100mb.bin'

echo
echo               '------------------------------------'
echo               '      Western & Southern Europe     '
echo               '------------------------------------'
download_benchmark 'OVH, Paris, France' 'http://proof.ovh.net/files/100Mio.dat'
download_benchmark 'Linode, London, UK' 'http://speedtest.london.linode.com/100MB-london.bin'
download_benchmark 'Leaseweb, Haarlem, NL' 'http://mirror.nl.leaseweb.net/speedtest/100mb.bin'
download_benchmark 'SmartDC, Rotterdam, NL' 'http://mirror.i3d.net/100mb.bin'
download_benchmark 'Hetzner, Nuernberg, DE' 'http://hetzner.de/100MB.iso'
download_benchmark 'Nessus, Vienna, AT' 'http://lg.as47692.net/tools/100MB.test'
download_benchmark 'SeFlow (MIX), Milan, IT' 'http://www.seflow.it/infrastruttura/100MB.test'
download_benchmark 'EDIS (Colt), Madrid, ES' 'http://es.edis.at/100mb.bin'
download_benchmark 'GinerNet (iDataGreen), Barcelona, ES' 'http://bcn.ginernet.com/100MB.test'
download_benchmark 'OTENet, Greece' 'http://speedtest.ftp.otenet.gr/files/test100Mb.db'

echo
echo               '------------------------------------'
echo               '      Central & Eastern Europe      '
echo               '------------------------------------'
download_benchmark 'EDIS (PLIX), Warsaw, PL' 'http://pl.edis.at/100MB.test'
download_benchmark 'EDIS (AdNet), Bucharest, RO' 'http://ro.edis.at/100MB.test'
download_benchmark 'Hosthink (Radore), Istanbul, TR' 'http://hosthink.org/100mb.test'
download_benchmark 'EDIS (Anders), Moscow, RU' 'http://ru.edis.at/100MB.test'
#download_benchmark 'Voxility, Bucharest, RO (10GB)' 'http://buc.voxility.net/10GB.bin'

echo
echo               '------------------------------------'
echo               '              Oceania               '
echo               '------------------------------------'                      
download_benchmark 'iiNet, Perth, WA, AUS' 'http://ftp.iinet.net.au/test100MB.dat'
#download_benchmark 'MammothVPS, Sydney, AUS' 'http://www.mammothvpscustomer.com/test100MB.dat'

echo
echo               '------------------------------------'
echo               '                Asia                '
echo               '------------------------------------'               
#download_benchmark 'VPS Hosting (Equinix), Hong Kong' 'http://www.vpshosting.com.hk/speedtest/100MBvideo.zip'
download_benchmark 'Linode, Tokyo, JP' 'http://speedtest.tokyo.linode.com/100MB-tokyo.bin'
download_benchmark 'Softlayer, Singapore' 'http://speedtest.sng01.softlayer.com/downloads/test100.zip'
download_benchmark 'Digital Ocean, Singapore' 'http://speedtest-sgp1.digitalocean.com/100mb.test'

echo
echo               "####################################"
echo               "#        speedtest.net CLI         #"
echo               "####################################"
wget --quiet --no-check-certificate https://raw.github.com/sivel/speedtest-cli/master/speedtest_cli.py
python speedtest_cli.py
rm speedtest_cli.py

echo               "####################################"
echo               "#            Traceroute            #"
echo               "####################################"
echo
echo               '------------------------------------'
echo               '            Global (CDN)            '
echo               '------------------------------------'
echo
do_traceroute 'CacheFly' 'cachefly.cachefly.net'

echo
echo               "###################################"
echo               "#               Ping              #"
echo               "###################################"
echo
echo               '------------------------------------'
echo               '            Global (CDN)            '
echo               '------------------------------------'
echo
do_traceroute 'CacheFly' 'cachefly.cachefly.net'

