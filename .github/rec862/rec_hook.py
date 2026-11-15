"""Stand-in hook for Tracekit #862's recording: append what Claude Code sends a hook to $REC_DIR/events.jsonl.

argv[1] is the event this command was registered for. A PreToolUse whose input holds deny-me exits 2, slow-me
sleeps $SLOW_S seconds first, and every PreToolUse sleeps $PRE_DELAY_S seconds (default 0)."""
import json, os, sys, time

t0 = time.time()
raw = sys.stdin.buffer.read()
try:
    payload = json.loads(raw.decode("utf-8"))
except ValueError:
    payload = None
pre = sys.argv[1:2] == ["PreToolUse"]
text = json.dumps(payload.get("tool_input")) if isinstance(payload, dict) else ""
if pre:
    time.sleep(float(os.environ.get("PRE_DELAY_S") or 0))
    if "slow-me" in text:
        time.sleep(float(os.environ.get("SLOW_S") or 20))
rec = {"t": t0, "t_end": time.time(), "pid": os.getpid(), "argv": sys.argv[1:], "payload": payload,
       "raw": None if payload is not None else raw.decode("utf-8", "replace"),
       "env": {k: v for k, v in os.environ.items() if k.upper().startswith("CLAUDE")}}
with open(os.path.join(os.environ["REC_DIR"], "events.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps(rec) + "\n")
if pre and "deny-me" in text:
    print("Blocked by the recording hook (exit 2).", file=sys.stderr)
    sys.exit(2)
sys.exit(0)
