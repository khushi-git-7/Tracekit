"""Stand-in hook for Tracekit #698's recording: append what Open Interpreter sends a hook to $REC_DIR/events.jsonl.

argv[1] is the event this command was registered for. A PreToolUse whose input holds deny-me exits 2 (reason on
stderr), fail-me exits 1, slow-me outlives the hook's timeout, json-deny answers permissionDecision deny on stdout."""
import json, os, sys, time

raw = sys.stdin.buffer.read()
try:
    payload = json.loads(raw.decode("utf-8"))
except ValueError:
    payload = None
rec = {"t": time.time(), "argv": sys.argv[1:], "payload": payload,
       "raw": None if payload is not None else raw.decode("utf-8", "replace"),
       "env": {k: v for k, v in os.environ.items() if k.upper().startswith(("INTERPRETER", "CODEX", "OPENINTERPRETER"))}}
with open(os.path.join(os.environ["REC_DIR"], "events.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps(rec) + "\n")

if sys.argv[1:2] != ["PreToolUse"] or not isinstance(payload, dict):
    sys.exit(0)
text = json.dumps(payload.get("tool_input"))
if "deny-me" in text:
    print("Blocked by the recording hook (exit 2).", file=sys.stderr)
    sys.exit(2)
if "fail-me" in text:
    print("The recording hook failed on purpose (exit 1).", file=sys.stderr)
    sys.exit(1)
if "slow-me" in text:
    time.sleep(20)
    sys.exit(0)
if "json-deny" in text:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": "Denied by the recording hook (JSON)."}}))
sys.exit(0)
