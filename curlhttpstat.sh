#!/bin/bash

curl -Ss -w'Timeline:
|
|--NAMELOOKUP %{time_namelookup}
|--|--CONNECT %{time_connect}
|--|--|--APPCONNECT %{time_appconnect}
|--|--|--|--PRETRANSFER %{time_pretransfer}
|--|--|--|--|--STARTTRANSFER %{time_starttransfer}
|--|--|--|--|--|--TOTAL %{time_total}
|--|--|--|--|--|--REDIRECT %{time_redirect}

Speed: %{speed_download} Bytes/s
' -o /dev/null $1
