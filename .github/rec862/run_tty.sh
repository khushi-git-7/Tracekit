#!/usr/bin/env bash
# Code Mode's own verdict in an interactive session: run_tty.sh LABEL PORT MODEL BASE(mock|anthropic)
# Runs claude in a pseudo-terminal (script), with CI unset and the variable at 1 in ~/.claude/settings.json, and keeps
# the screen and the --debug log, so the reason Claude Code gives for Code Mode being on or off is its own.
set -u
LABEL=$1 PORT=$2 MODEL=$3 BASE=$4
KIT=$(cd "$(dirname "$0")" && pwd)
export REC_DIR=$OUT/$LABEL
WORK=$RUNNER_TEMP/work-$LABEL CFG=$RUNNER_TEMP/cfg-$LABEL
mkdir -p "$REC_DIR" "$WORK" "$CFG"
git -C "$WORK" init -q
python3 "$KIT/settings.py" "$KIT" "$REC_DIR/settings.json"
python3 - "$CFG" "$REC_DIR/settings.json" <<'PY'
import json, sys
cfg, hooks = sys.argv[1], sys.argv[2]
s = json.load(open(hooks))
s["env"] = {"CLAUDE_CODE_EXPERIMENTAL_CODE_MODE": "1"}
json.dump(s, open(f"{cfg}/settings.json", "w"), indent=2)
PY
# first-run screens done ahead, so the session gets as far as Code Mode's own check; CAVEATS=1 also marks Code Mode's
# caveats as read
python3 - "$CFG" "$WORK" <<'PY'
import json, os, sys
cfg, work = sys.argv[1], os.path.realpath(sys.argv[2])
key = "sk-ant-rec862-not-a-key"
state = {"hasCompletedOnboarding": True, "theme": "dark", "numStartups": 5, "bypassPermissionsModeAccepted": True,
         "customApiKeyResponses": {"approved": [key[-20:]], "rejected": []},
         "projects": {work: {"hasTrustDialogAccepted": True, "hasCompletedProjectOnboarding": True}}}
if os.environ.get("CAVEATS") == "1":
    state.update(codeModeCaveatsAcceptedV1=True)
json.dump(state, open(f"{cfg}/.claude.json", "w"), indent=2)
PY
python3 "$KIT/mock.py" "$PORT" > "$REC_DIR/mock.log" 2>&1 &
MOCK=$!
sleep 1
ENVS=(ANTHROPIC_API_KEY=sk-ant-rec862-not-a-key CLAUDE_CONFIG_DIR="$CFG" TERM=xterm-256color COLUMNS=160 LINES=50)
[ "$BASE" = mock ] && ENVS+=(ANTHROPIC_BASE_URL="http://127.0.0.1:$PORT")
( cd "$WORK" && env -u CI -u GITHUB_ACTIONS "${ENVS[@]}" timeout -s INT 60 \
    script -qfec "claude --debug --model $MODEL --permission-mode bypassPermissions 'Run the recording plan.'" \
    "$REC_DIR/screen.raw" < /dev/null > /dev/null 2>&1 )
echo "exit $?" > "$REC_DIR/exit"
kill $MOCK 2>/dev/null
cp -r "$CFG/debug" "$REC_DIR/debug" 2>/dev/null
python3 - "$REC_DIR" <<'PY'
import glob, re, sys
d = sys.argv[1]
screen = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[()][0-9A-B]|\r", "", open(f"{d}/screen.raw", errors="replace").read())
open(f"{d}/screen.txt", "w").write(screen)
print(f"=== {d}: {open(d + '/exit').read().strip()}")
for line in screen.splitlines():
    if re.search(r"Code Mode|isn't available|experimental|REPL", line):
        print("  screen:", line.strip()[:400])
for f in glob.glob(f"{d}/debug/*"):
    for line in open(f, errors="replace"):
        if re.search(r"(?i)code.?mode|repl_mode|repl|opt.?in", line):
            print("  debug:", line.strip()[:400])
PY
