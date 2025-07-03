#!/bin/bash

services=$(networksetup -listnetworkserviceorder | grep 'Hardware Port')

while read line; do
    sname=$(echo $line | awk -F  "(, )|(: )|[)]" '{print $2}')
    sdev=$(echo $line | awk -F  "(, )|(: )|[)]" '{print $4}')
    #echo "Current service: $sname, $sdev, $currentservice"
    if [ -n "$sdev" ]; then
        ifout="$(ifconfig $sdev 2>/dev/null)"
        sip=$(echo "$ifout" | awk '/^[[:space:]]*inet /{print $2}')
        smac=$(echo "$ifout" | awk '/ether/{print $2}')

        echo "$ifout" | grep 'status: active' > /dev/null 2>&1
        rc="$?"
        if [ "$rc" -eq 0 ]; then
            echo "Active Service: $sname"
            echo "  device: $sdev"
            echo "  ip: $sip"
            echo "  mac: $smac"
            currentservice="$sname"
        fi
    fi
done <<< "$(echo "$services")"

if [ -z "$currentservice" ]; then
    >&2 echo "Could not find current service"
    exit 1
fi
