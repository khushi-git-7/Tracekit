"""Stand-in hook for #869: appends each payload Qwen Code sends it to $HOOK_LOG, as one JSON line, and lets the call
run (exit 0, no output)."""
import json, os, sys
raw = sys.stdin.read()
try:
    p = json.loads(raw)
except ValueError:
    p = {"_raw": raw}
with open(os.environ.get("HOOK_LOG", "/tmp/hooks869.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "payload": p}) + "\n")
