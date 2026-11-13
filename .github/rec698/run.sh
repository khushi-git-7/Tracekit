#!/usr/bin/env bash
# One recording scenario: run.sh LABEL PORT WIRE_API HARNESS MODEL TRUST(bypass|none|tracekit) [EXEC FLAG...]
set -u
LABEL=$1 PORT=$2 WIRE=$3 HARNESS=$4 MODEL=$5 TRUST=$6
shift 6
KIT=$(cd "$(dirname "$0")" && pwd)
export REC_DIR=$OUT/$LABEL INTERPRETER_HOME=$RUNNER_TEMP/oi-$LABEL MOCK_API_KEY=mock
WORK=$RUNNER_TEMP/work-$LABEL
mkdir -p "$REC_DIR" "$INTERPRETER_HOME" "$WORK"
git -C "$WORK" init -q
python3 - "$KIT" <<'EOF'
import json, os, sys
kit = sys.argv[1]
events = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest", "PostToolUse", "PreCompact",
          "PostCompact", "SubagentStart", "SubagentStop", "Stop", "SessionEnd"]
hooks = {ev: [{"hooks": [{"type": "command", "command": f"python3 {kit}/rec_hook.py {ev}",
                          "timeout": 5 if ev == "PreToolUse" else 30}]}] for ev in events}
with open(os.path.join(os.environ["INTERPRETER_HOME"], "hooks.json"), "w") as f:
    json.dump({"hooks": hooks}, f, indent=2)
EOF
{
  echo "model_provider = \"mockp\""
  echo "model = \"$MODEL\""
  [ "$HARNESS" != none ] && echo "harness = \"$HARNESS\""
  echo 'approval_policy = "never"'
  echo 'sandbox_mode = "danger-full-access"'
  echo 'check_for_update_on_startup = false'
  echo '[model_providers.mockp]'
  echo 'name = "mock"'
  echo "base_url = \"http://127.0.0.1:$PORT/v1\""
  echo 'env_key = "MOCK_API_KEY"'
  echo "wire_api = \"$WIRE\""
  echo '[mcp_servers.rec_server]'
  echo 'command = "python3"'
  echo "args = [\"$KIT/mcp_echo.py\"]"
} > "$INTERPRETER_HOME/config.toml"
if [ "$TRUST" = tracekit ]; then   # trust each hook with the hash Tracekit computes for Codex (doctor._codex_hash)
  python3 - <<'EOF' >> "$INTERPRETER_HOME/config.toml"
import json, os, re
from tracekit.doctor import _codex_hash
path = os.path.join(os.environ["INTERPRETER_HOME"], "hooks.json")
for ev, groups in json.load(open(path))["hooks"].items():
    for g, group in enumerate(groups):
        for h, hook in enumerate(group["hooks"]):
            key = f"{os.path.realpath(path)}:{re.sub(r'(?<!^)(?=[A-Z])', '_', ev).lower()}:{g}:{h}"
            print(f'[hooks.state."{key}"]\ntrusted_hash = "{_codex_hash(ev, group, hook)}"')
EOF
fi
cp "$INTERPRETER_HOME/config.toml" "$INTERPRETER_HOME/hooks.json" "$REC_DIR/"
python3 "$KIT/mock_llm.py" "$PORT" "$WORK" > "$REC_DIR/mock.log" 2>&1 &
MOCK=$!
sleep 1
FLAGS=(exec --json --skip-git-repo-check -C "$WORK")
[ "$TRUST" = bypass ] && FLAGS+=(--dangerously-bypass-hook-trust)
FLAGS+=("$@")
timeout 300 interpreter "${FLAGS[@]}" "Run the recording plan." > "$REC_DIR/exec.jsonl" 2> "$REC_DIR/exec.stderr"
echo "exit $?" > "$REC_DIR/exit"
kill $MOCK 2>/dev/null
ls -la "$WORK" > "$REC_DIR/workdir.txt"
echo "=== $LABEL: $(cat "$REC_DIR/exit"), $(wc -l < "$REC_DIR/requests.jsonl" 2>/dev/null || echo 0) model requests, $(wc -l < "$REC_DIR/events.jsonl" 2>/dev/null || echo 0) hook events"
python3 - <<'EOF'
import json, os
d = os.environ["REC_DIR"]
try:
    reqs = [json.loads(l) for l in open(os.path.join(d, "requests.jsonl"))]
except FileNotFoundError:
    reqs = []
tools = []
for r in reqs:
    for t in (r["body"].get("tools") or []) if isinstance(r["body"], dict) else []:
        n = t.get("name") or (t.get("function") or {}).get("name") or t.get("type")
        if n not in tools:
            tools.append(n)
print("offered tools:", tools)
print("answers:", [r["answer"] and r["answer"]["name"] for r in reqs])
try:
    for l in open(os.path.join(d, "events.jsonl")):
        e = json.loads(l); p = e["payload"] or {}
        print(" ", e["argv"], p.get("tool_name", ""), json.dumps(p.get("tool_input"))[:160] if "tool_input" in p else "",
              "| keys:", sorted(p))
except FileNotFoundError:
    print("  no hook events")
EOF
tail -5 "$REC_DIR/exec.stderr"
