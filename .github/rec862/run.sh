#!/usr/bin/env bash
# One recording scenario: run.sh LABEL PORT MODEL CODE_MODE(1|0); MOCK_PLAN (JSON) scripts the model.
set -u
LABEL=$1 PORT=$2 MODEL=$3 CM=$4
KIT=$(cd "$(dirname "$0")" && pwd)
export REC_DIR=$OUT/$LABEL
WORK=$RUNNER_TEMP/work-$LABEL
mkdir -p "$REC_DIR" "$WORK"
git -C "$WORK" init -q
echo "hello from a.txt" > "$WORK/a.txt"
echo "hello from b.txt" > "$WORK/b.txt"
python3 "$KIT/settings.py" "$KIT" "$REC_DIR/settings.json"
python3 "$KIT/mock.py" "$PORT" > "$REC_DIR/mock.log" 2>&1 &
MOCK=$!
sleep 1
ENVS=(ANTHROPIC_BASE_URL="http://127.0.0.1:$PORT" ANTHROPIC_API_KEY=mock-key
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_TELEMETRY=1 DISABLE_AUTOUPDATER=1 DISABLE_ERROR_REPORTING=1
      CLAUDE_CONFIG_DIR="$RUNNER_TEMP/cfg-$LABEL")
[ "$CM" = 1 ] && ENVS+=(CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1)
( cd "$WORK" && env "${ENVS[@]}" timeout "${REC_TIMEOUT:-240}" claude -p "Run the recording plan." \
    --model "$MODEL" --output-format stream-json --verbose --settings "$REC_DIR/settings.json" \
    --permission-mode bypassPermissions > "$REC_DIR/out.jsonl" 2> "$REC_DIR/stderr.txt" )
echo "exit $?" > "$REC_DIR/exit"
kill $MOCK 2>/dev/null
ls -la "$WORK" > "$REC_DIR/workdir.txt"
python3 "$KIT/summary.py" "$REC_DIR" "$LABEL"
tail -5 "$REC_DIR/stderr.txt"
