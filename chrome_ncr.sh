#!/bin/bash
# This script is used to make Chrome use ww.google.com instead of
# www.google.com.hk as search engine base url. Make sure to quit Chrome
# before running this.

if [ -n "$TEST_CHROME_NCR" ]; then
    confpath="fake-google-preferences.txt"
    sedoptions=""
else
    confpath="$HOME/Library/Application Support/Google/Chrome/Default/Preferences"
    sedoptions="-i"
fi

orig="google\.com\.hk"
repl="google\.com"

echo "> Show matches of $orig"
grep -onH "$orig" "$confpath"
echo

echo "> Backup Preferences"
backuppath="/tmp/Preferences-$(date "+%Y-%m-%d-%H%M%S")"
cp "$confpath" "$backuppath"
echo "Backed up to $backuppath"
echo

echo "> Run sed to replace"
sed $sedoptions -e "s/$orig/$repl/g" "$confpath" >/dev/null
echo

echo "> Show matches after replace"
grep -onH "$orig" "$confpath"
echo
