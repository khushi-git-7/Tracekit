#!/usr/bin/env bash
# one recorded Qwen Code session: run.sh LABEL PORT PLAN [extra qwen args...]
set -u
LABEL=$1 PORT=$2 PLAN=$3; shift 3
export REC_DIR="$OUT/$LABEL"; mkdir -p "$REC_DIR"
python3 .github/rec869/mock.py "$PORT" "$WORK" "$PLAN" & MOCK=$!
sleep 1
export OPENAI_API_KEY=rec869-not-a-key OPENAI_BASE_URL="http://127.0.0.1:$PORT/v1" OPENAI_MODEL=rec-model
( cd "$WORK" && timeout "${REC_TIMEOUT:-180}" qwen "$@" > "$REC_DIR/stdout.txt" 2> "$REC_DIR/stderr.txt" < /dev/null )
echo "exit=$?" > "$REC_DIR/exit.txt"
kill $MOCK 2>/dev/null
echo "== $LABEL $(cat "$REC_DIR/exit.txt")"; tail -20 "$REC_DIR/stdout.txt"; tail -20 "$REC_DIR/stderr.txt"
echo "requests: $(wc -l < "$REC_DIR/requests.jsonl" 2>/dev/null)"
