#!/bin/bash
#
# check for runaway distnoted, kill if necessary
# http://apple.stackexchange.com/a/234478/74719
#

ps -reo '%cpu,uid,pid,command' | 
    awk -v UID=$UID '
    /distnoted agent$/ && $1 > 100.0 && $2 == UID { 
        system("kill -9 " $3) 
    }
    '
