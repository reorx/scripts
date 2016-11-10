#!/bin/bash

LOCATIONS=(
    /Library/StartupItems
    /System/Library/StartupItems
    # load when your Mac starts up, and run as the root user.
    /Library/LaunchDaemons
    /System/Library/LaunchDaemons
    # load when any user logs in, and run as that user.
    /Library/LaunchAgents
    /System/Library/LaunchAgents
    # load only when you logs in, and run as you.
    ~/Library/LaunchAgents
)

for location in ${LOCATIONS[@]}; do
    echo "-- $location"
    ls "$location"
    #grep -ir upload $location
done
