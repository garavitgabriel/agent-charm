#!/bin/sh
# usage: shot.sh <html> <out.png> <W> <H>
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu --hide-scrollbars --allow-file-access-from-files --virtual-time-budget=4000 --window-size=$3,$4 --screenshot=$2 file://$1 >/dev/null 2>&1
