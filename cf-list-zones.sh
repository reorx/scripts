#!/bin/bash
set -eu

curl -X GET "https://api.cloudflare.com/client/v4/zones" \
    -H "Authorization: Bearer $CLOUDFLARE_TOKEN"
