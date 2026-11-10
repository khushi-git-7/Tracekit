#!/bin/sh
# Fork-only capture helper: saves the payload Cline hands a hook, with the event and the directory it was found in.
# Lets the call run, unless $CAPTURE_DIR/cancel-run_commands exists and this is a run_commands PreToolUse.
dir=$(cd "$(dirname "$0")" && pwd)
event=$(basename "$0")
n=$(date +%s%N)
cap=${CAPTURE_DIR:-/tmp/capture}
out="$cap/hook-$event-$n.json"
cat > "$out"
printf '%s\t%s\t%s\n' "$n" "$event" "$dir" >> "$cap/hooks.tsv"
if [ "$event" = PreToolUse ] && [ -f "$cap/cancel-run_commands" ] && grep -q '"toolName":"run_commands"' "$out"; then
  printf '{"cancel": true, "errorMessage": "blocked by the capture hook"}\n'
else
  printf '{}\n'
fi
