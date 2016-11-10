#!/bin/bash

GOLINT_PATH="/Users/reorx/Code/go/bin/golint"
EXIT_CODE=85
if [ -z "$1" ]
then
    $GOLINT_PATH -h
    exit $EXIT_CODE
fi

$GOLINT_PATH "$@" | egrep -v -e "(should have comment|returns unexported type)"
#$GOLINT_PATH "$@"
