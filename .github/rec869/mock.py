"""A scripted model for Tracekit #869's recording: an OpenAI-compatible Chat Completions server (streamed or not) that
answers each turn with the next tool call of a fixed plan, chosen from the tools the request offers, then a short text.
Any request with no tools (a side request) gets a small JSON text. Every request body goes to $REC_DIR/requests.jsonl.
Usage: python3 mock.py PORT WORKDIR PLAN   (PLAN: comma-separated steps: write,read,edit,shell,shell2)"""
import json, os, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, WORK, PLAN = int(sys.argv[1]), sys.argv[2], sys.argv[3].split(",")
LOG = os.path.join(os.environ.get("REC_DIR", "."), "requests.jsonl")
NOTES = os.path.join(WORK, "notes.txt")
NAMES = {"write": ["write_file", "WriteFile"], "read": ["read_file", "ReadFile"],
         "edit": ["edit", "replace", "edit_file"], "shell": ["run_shell_command"], "shell2": ["run_shell_command"]}
COUNT = [0]


def fill(step, schema):
    props = (schema or {}).get("properties", {}) or {}
    a = {}
    for k in props:
        lk = k.lower()
        if "path" in lk:
            a[k] = NOTES
        elif k == "content":
            a[k] = "one\n"
        elif k == "old_string":
            a[k] = "one"
        elif k == "new_string":
            a[k] = "uno"
        elif k == "command":
            a[k] = "echo rec869" if step == "shell" else "echo resumed869"
        elif k == "description":
            a[k] = "recording step"
    return a


def reply(body):
    tools = {t["function"]["name"]: t["function"].get("parameters") for t in body.get("tools") or []
             if isinstance(t, dict) and t.get("function")}
    msgs = body.get("messages") or []
    if not tools:
        return {"content": json.dumps({"next_speaker": "user", "reasoning": "recording done"})}
    last_user = max([i for i, m in enumerate(msgs) if m.get("role") == "user"] or [0])
    done = sum(1 for m in msgs[last_user:] if m.get("role") == "tool")
    while done < len(PLAN):
        step = PLAN[done]
        name = next((n for n in NAMES[step] if n in tools), None)
        if name:
            COUNT[0] += 1
            return {"tool_calls": [{"id": f"call_rec869_{os.getpid()}_{COUNT[0]}", "type": "function",
                                    "function": {"name": name, "arguments": json.dumps(fill(step, tools[name]))}}]}
        done += 1   # a step whose tool isn't offered is skipped
    return {"content": "done"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"object": "list", "data": [{"id": "rec-model", "object": "model"}]}).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        with open(LOG, "a") as f:
            f.write(json.dumps({"path": self.path, "body": body}) + "\n")
        r = reply(body)
        model, now = body.get("model", "rec-model"), int(time.time())
        finish = "tool_calls" if "tool_calls" in r else "stop"
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if body.get("stream"):
            self.send_response(200); self.send_header("content-type", "text/event-stream"); self.end_headers()
            delta = {"role": "assistant"}
            if "tool_calls" in r:
                delta["tool_calls"] = [dict(r["tool_calls"][0], index=0)]
            else:
                delta["content"] = r["content"]
            for ch in ({"index": 0, "delta": delta, "finish_reason": None},
                       {"index": 0, "delta": {}, "finish_reason": finish}):
                self.wfile.write(("data: " + json.dumps({"id": "c1", "object": "chat.completion.chunk", "created": now,
                                                         "model": model, "choices": [ch]}) + "\n\n").encode())
            self.wfile.write(("data: " + json.dumps({"id": "c1", "object": "chat.completion.chunk", "created": now,
                                                     "model": model, "choices": [], "usage": usage}) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            msg = {"role": "assistant", "content": r.get("content")}
            if "tool_calls" in r:
                msg["tool_calls"] = r["tool_calls"]
            out = {"id": "c1", "object": "chat.completion", "created": now, "model": model,
                   "choices": [{"index": 0, "message": msg, "finish_reason": finish}], "usage": usage}
            data = json.dumps(out).encode()
            self.send_response(200); self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
