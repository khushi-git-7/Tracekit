"""Fork-only capture helper: a scripted OpenAI-compatible model for driving the Cline CLI in CI.

Each request is logged to $CAPTURE_DIR/requests.jsonl. The reply depends on how many tool results
the conversation already holds: a run_commands call, then read_files, then an editor create, then a
final text answer. Serves /chat/completions (streamed or not) and /responses.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OUT = os.environ.get("CAPTURE_DIR", ".")
WORK = os.environ.get("CAPTURE_WORK", "/tmp/clinework")
STEPS = [
    ("run_commands", {"commands": ["echo captured-by-tracekit"]}),
    ("read_files", {"files": [{"path": os.path.join(WORK, "notes.txt")}]}),
    ("editor", {"path": os.path.join(WORK, "created.txt"), "new_text": "hello\n"}),
    ("submit_and_exit", {"summary": "captured every hook event", "verified": True}),
]
if os.environ.get("CAPTURE_STEPS"):   # the live runs script their own calls
    STEPS = [tuple(x) for x in json.loads(os.environ["CAPTURE_STEPS"])]


def log(kind, body):
    with open(os.path.join(OUT, "requests.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": kind, "body": body}) + "\n")


def tool_names(body):
    names = []
    for t in body.get("tools") or []:
        names.append((t.get("function") or {}).get("name") or t.get("name"))
    return names


def step_index(body):
    msgs = body.get("messages") or body.get("input") or []
    done = 0
    for m in msgs if isinstance(msgs, list) else []:
        if isinstance(m, dict) and (m.get("role") == "tool" or m.get("type") == "function_call_output"):
            done += 1
    return done


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, payload, stream=False):
        self.send_response(code)
        self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
        self.end_headers()
        if stream:
            for chunk in payload:
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.wfile.write(json.dumps(payload).encode())

    def do_GET(self):
        log("GET " + self.path, {})
        self._send(200, {"object": "list", "data": [{"id": "scripted", "object": "model"}]})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        log("POST " + self.path, body)
        i = step_index(body)
        offered = tool_names(body)
        log("tools offered", offered)
        call = STEPS[i] if i < len(STEPS) and STEPS[i][0] in offered else None   # then a final text answer
        stream = bool(body.get("stream"))
        now = int(time.time())
        if self.path.endswith("/responses"):
            out = [{"type": "function_call", "id": f"fc_{i}", "call_id": f"call_{i}", "name": call[0],
                    "arguments": json.dumps(call[1])}] if call else \
                  [{"type": "message", "id": "msg_end", "role": "assistant",
                    "content": [{"type": "output_text", "text": "done"}]}]
            resp = {"id": f"resp_{i}", "object": "response", "created_at": now, "model": "scripted",
                    "status": "completed", "output": out,
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
            if stream:
                return self._send(200, [{"type": "response.created", "response": {**resp, "status": "in_progress", "output": []}},
                                        *[{"type": "response.output_item.done", "output_index": k, "item": o}
                                          for k, o in enumerate(out)],
                                        {"type": "response.completed", "response": resp}], stream=True)
            return self._send(200, resp)
        base = {"id": f"chatcmpl-{i}", "created": now, "model": "scripted"}
        if call:
            tc = {"index": 0, "id": f"call_{i}", "type": "function",
                  "function": {"name": call[0], "arguments": json.dumps(call[1])}}
            if stream:
                return self._send(200, [
                    {**base, "object": "chat.completion.chunk",
                     "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [tc]}, "finish_reason": None}]},
                    {**base, "object": "chat.completion.chunk",
                     "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                     "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}], stream=True)
            return self._send(200, {**base, "object": "chat.completion", "choices": [
                {"index": 0, "message": {"role": "assistant", "content": None, "tool_calls": [tc]},
                 "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        if stream:
            return self._send(200, [
                {**base, "object": "chat.completion.chunk",
                 "choices": [{"index": 0, "delta": {"role": "assistant", "content": "done"}, "finish_reason": None}]},
                {**base, "object": "chat.completion.chunk",
                 "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}], stream=True)
        return self._send(200, {**base, "object": "chat.completion", "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
