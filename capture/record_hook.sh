#!/bin/sh
# Fork-only capture helper: saves the payload Cline hands a hook, with the event and the directory it was found in,
# and lets the call run.
dir=$(cd "$(dirname "$0")" && pwd)
event=$(basename "$0")
n=$(date +%s%N)
cat > "${CAPTURE_DIR:-/tmp/capture}/hook-$event-$n.json"
printf '%s\t%s\t%s\n' "$n" "$event" "$dir" >> "${CAPTURE_DIR:-/tmp/capture}/hooks.tsv"
printf '{}\n'
