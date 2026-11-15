#!/usr/bin/env bash
# One Codex recording scenario: run.sh LABEL PORT EVENTS(full|min) [EXEC FLAG...]
# Codex is driven by mock_llm.py (MOCK_MODE=codex) over Responses; every hook event goes to $OUT/LABEL/events.jsonl
set -u
LABEL=$1 PORT=$2 EVENTS=$3
shift 3
KIT=$(cd "$(dirname "$0")" && pwd)
export REC_DIR=$OUT/$LABEL CODEX_HOME=$RUNNER_TEMP/codex-$LABEL MOCK_API_KEY=mock MOCK_MODE=codex
WORK=$RUNNER_TEMP/work-$LABEL
mkdir -p "$REC_DIR" "$CODEX_HOME" "$WORK"
git -C "$WORK" init -q
python3 -c "import base64,sys; open(sys.argv[1],'wb').write(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='))" "$WORK/pic.png"
python3 - "$KIT" "$EVENTS" <<'PY'
import json, os, sys
kit, which = sys.argv[1:3]
events = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]
if which == "full":
    events += ["PermissionRequest", "SubagentStart", "SubagentStop", "PreCompact", "PostCompact", "SessionEnd"]
hooks = {ev: [{"hooks": [{"type": "command", "command": f"python3 {kit}/rec_hook.py {ev}",
                          "timeout": 5 if ev == "PreToolUse" else 30}]}] for ev in events}
with open(os.path.join(os.environ["CODEX_HOME"], "hooks.json"), "w") as f:
    json.dump({"hooks": hooks}, f, indent=2)
PY
{
  echo 'model_provider = "mockp"'
  echo 'model = "gpt-5.1-codex"'
  echo 'approval_policy = "never"'
  echo 'sandbox_mode = "danger-full-access"'
  echo 'check_for_update_on_startup = false'
  echo '[model_providers.mockp]'
  echo 'name = "mock"'
  echo "base_url = \"http://127.0.0.1:$PORT/v1\""
  echo 'env_key = "MOCK_API_KEY"'
  echo 'wire_api = "responses"'
} > "$CODEX_HOME/config.toml"
# trust each hook with the hash Tracekit computes for Codex (doctor._codex_hash), as a person trusting it at /hooks would
python3 - <<'PY' >> "$CODEX_HOME/config.toml"
import json, os, re
from tracekit.doctor import _codex_hash
path = os.path.join(os.environ["CODEX_HOME"], "hooks.json")
for ev, groups in json.load(open(path))["hooks"].items():
    for g, group in enumerate(groups):
        for h, hook in enumerate(group["hooks"]):
            key = f"{os.path.realpath(path)}:{re.sub(r'(?<!^)(?=[A-Z])', '_', ev).lower()}:{g}:{h}"
            print(f'[hooks.state."{key}"]\ntrusted_hash = "{_codex_hash(ev, group, hook)}"')
PY
cp "$CODEX_HOME/config.toml" "$CODEX_HOME/hooks.json" "$REC_DIR/"
python3 "$KIT/mock_llm.py" "$PORT" "$WORK" > "$REC_DIR/mock.log" 2>&1 &
MOCK=$!
sleep 1
timeout "${REC_TIMEOUT:-240}" codex exec --json --skip-git-repo-check -C "$WORK" "$@" "Run the recording plan." \
  > "$REC_DIR/exec.jsonl" 2> "$REC_DIR/exec.stderr"
echo "exit $?" > "$REC_DIR/exit"
kill $MOCK 2>/dev/null
echo "=== $LABEL: $(cat "$REC_DIR/exit"), $(wc -l < "$REC_DIR/requests.jsonl" 2>/dev/null || echo 0) model requests, $(wc -l < "$REC_DIR/events.jsonl" 2>/dev/null || echo 0) hook events"
python3 "$KIT/summary.py" "$REC_DIR"
tail -15 "$REC_DIR/exec.stderr"
