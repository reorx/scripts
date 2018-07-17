#!/bin/bash

: ${DID_PATH:="~/Dropbox/did.txt"}
IFS=$'\n'
SEP="❧"
startline="$(date +"%Y-%m-%d %H:%M:%S")"
nvim \
    +"normal ggO${startline}${IFS}${IFS}${IFS}${SEP}${IFS}" \
    +"normal kkka- " \
    +"startinsert!" \
    "$DID_PATH"
