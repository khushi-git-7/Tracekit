#!/usr/bin/env bash
# #698 done-when: a real Open Interpreter session (Gemini, free tier) with Tracekit's v2 hooks: an allowed call, a denied
# one, a held one approved and retried, then tracekit last. Fork-only; the key comes from the GEMINI_API_KEY secret.
set -u
export INTERPRETER_HOME=$RUNNER_TEMP/oi-home WORK=$RUNNER_TEMP/work
mkdir -p "$INTERPRETER_HOME" "$WORK"
cd "$WORK" && git init -q && cd - >/dev/null

echo "== the key works (status only)"
python3 - <<'EOF'
import json, os, urllib.request
r = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=5",
                           headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"], "User-Agent": "tracekit-698-live"})
print("models list:", urllib.request.urlopen(r, timeout=30).status)
EOF

echo "== a local shim for Gemini's OpenAI-compatible endpoint, which rejects Open Interpreter's \`store\` field"
python3 .github/live698/shim.py 8790 > "$OUT/shim.stderr" 2>&1 &
export SHIM_KEY=unused
sleep 1

echo "== tracekit init --dev --v2 --agent interpreter"
tracekit init --dev --v2 --agent interpreter
cat > "$INTERPRETER_HOME/config.toml" <<EOF
model_provider = "gemini"
model = "$MODEL"
approval_policy = "never"
sandbox_mode = "danger-full-access"
check_for_update_on_startup = false

[model_providers.gemini]
name = "Gemini (free tier)"
base_url = "http://127.0.0.1:8790/v1beta/openai"
env_key = "SHIM_KEY"
wire_api = "chat"
EOF

echo "== doctor before trust"
tracekit doctor --json 2>/dev/null | python3 -c "import json,sys; [print(r['id'], r['status'], r['detail'][:200]) for r in json.load(sys.stdin) if r['id'] in ('D-INTERPRETER-HOOK-TRUST', 'D-HOOKS-EVENT', 'D-HOOKS-TIMEOUT')]"

echo "== trust Tracekit's hooks as a person does in /hooks: Open Interpreter's trusted_hash for each, as they are"
python3 - <<'EOF' >> "$INTERPRETER_HOME/config.toml"
import json, os, re
from tracekit.doctor import _codex_hash
path = os.path.realpath(os.path.join(os.environ["INTERPRETER_HOME"], "hooks.json"))
for ev, groups in json.load(open(path))["hooks"].items():
    for g, group in enumerate(groups):
        for h, hook in enumerate(group["hooks"]):
            key = f"{path}:{re.sub(r'(?<!^)(?=[A-Z])', '_', ev).lower()}:{g}:{h}"
            print(f'\n[hooks.state."{key}"]\ntrusted_hash = "{_codex_hash(ev, group, hook)}"')
EOF
tracekit doctor --json 2>/dev/null | python3 -c "import json,sys; [print(r['id'], r['status'], r['detail'][:200]) for r in json.load(sys.stdin) if r['id'] == 'D-INTERPRETER-HOOK-TRUST']"

PROMPT='This is a test of a tool-call recorder. Use your shell tool. Do exactly these three steps, one shell command each, in order, and do not retry or work around anything that is blocked:
1) run: echo hello-from-open-interpreter > notes.txt
2) run: sudo echo hi
3) run: mkdir -p .openinterpreter && echo "{}" > .openinterpreter/probe.json
Then report, for each step, whether it ran, was blocked or was held and then ran, quoting any message you got.'

echo "== session 1, with TRACEKIT_APPROVAL_WAIT: a held call's hook waits while a person answers (interpreter exec
# ends the run at SessionEnd, so a call held there can't be approved once the session is over)"
export TRACEKIT_APPROVAL_WAIT=180
( for _ in $(seq 1 120); do   # the person: approve the first held call as soon as it is listed
    APR=$(tracekit approvals list 2>/dev/null | grep -o 'apr-[0-9a-f]*  requested' | head -1 | cut -d' ' -f1)
    if [ -n "$APR" ]; then echo "== a person approves $APR"; tracekit approvals show "$APR" | head -8; tracekit approvals approve "$APR"; break; fi
    sleep 2
  done ) > "$OUT/person.txt" 2>&1 &
PERSON=$!
timeout 300 interpreter exec --json --skip-git-repo-check -C "$WORK" "$PROMPT" > "$OUT/session1.jsonl" 2> "$OUT/session1.stderr"
echo "exit $?"
wait $PERSON; cat "$OUT/person.txt"
python3 .github/live698/show.py "$OUT/session1.jsonl"
ls -la "$WORK" "$WORK/.openinterpreter" 2>&1; cat "$WORK/.openinterpreter/probe.json" 2>&1

echo "== what the shim dropped from each request (field names only)"
python3 -c "import json,collections; c=collections.Counter(tuple(json.loads(l)['dropped']) for l in open('$OUT/shim.log')); print(dict(c)); print('signatures handed back:', sum(json.loads(l).get('restored', 0) for l in open('$OUT/shim.log')))" 2>&1
tail -3 "$OUT/shim.stderr"
echo "== Gemini responses (status, type, bytes, seconds, start)"; cut -c1-500 "$OUT/shim.log.resp" 2>&1

echo "== tracekit last"
cd "$OUT" && tracekit last --open -o last.tkb; tracekit last -o last-closed.tkb 2>&1 | tail -3
python3 - <<'EOF'
import json, zipfile
z = zipfile.ZipFile("last.tkb")
for line in z.read([n for n in z.namelist() if n.startswith("runs/")][0]).decode().splitlines():
    e = json.loads(line)["event"]; d = e["data"]
    print(e["seq"], e["type"], d.get("tool", ""), d.get("decision", ""), d.get("rule_ids", ""),
          d.get("agent", {}).get("name", "") if isinstance(d.get("agent"), dict) else "", d.get("source", ""))
EOF
