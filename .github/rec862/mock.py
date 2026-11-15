"""Scripted Anthropic Messages endpoint for Tracekit #862's recording: mock.py PORT

Logs every request to $REC_DIR/requests.jsonl. MOCK_PLAN is a JSON list of steps; each step is either
{"tool": NAME, "input": {...}} (a tool_use; NAME "@code" means the Code Mode tool found among the offered tools) or
{"text": "..."}. A request's step is the number of tool_result blocks already in its conversation. Requests without
tools (titles, summaries) get a short text, and count_tokens a fixed count."""
import json, os, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1])
LOG = os.path.join(os.environ["REC_DIR"], "requests.jsonl")
PLAN = json.loads(os.environ.get("MOCK_PLAN") or "[]")


def code_tool(tools):
    names = [t.get("name") for t in tools if isinstance(t, dict)]
    for want in (os.environ.get("CODE_TOOL") or "", "REPL", "Code", "CodeMode", "code"):
        if want and want in names:
            return want
    for t in tools:
        if "javascript" in (t.get("description") or "").lower():
            return t.get("name")
    return None


def results(body):
    return sum(1 for m in body.get("messages") or [] if isinstance(m.get("content"), list)
               for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result")


def step_for(body):
    tools = body.get("tools") or []
    if not tools:
        return {"text": "ok"}
    n = results(body)
    if n >= len(PLAN):
        return {"text": "done"}
    s = dict(PLAN[n])
    if s.get("tool") == "@code":
        s["tool"] = code_tool(tools)
        if not s["tool"]:
            return {"text": "no code tool offered"}
    return s


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply_json(self, obj):
        out = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "method": "GET", "path": self.path}) + "\n")
        self.reply_json({"data": [], "has_more": False})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"_raw": raw.decode("utf-8", "replace")}
        if "count_tokens" in self.path:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "path": self.path, "count_tokens": True}) + "\n")
            return self.reply_json({"input_tokens": 10})
        step = step_for(body) if isinstance(body, dict) else {"text": "ok"}
        cid = f"toolu_rec{int(time.time() * 1000) % 10**9}"
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "path": self.path,
                                "headers": {k: v for k, v in self.headers.items()
                                            if k.lower().startswith(("anthropic", "x-"))},
                                "body": body, "answer": step, "id": cid}) + "\n")
        if step.get("tool"):
            block = {"type": "tool_use", "id": cid, "name": step["tool"], "input": step.get("input") or {}}
            stop = "tool_use"
        else:
            block = {"type": "text", "text": step.get("text", "done")}
            stop = "end_turn"
        usage = {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        msg = {"id": "msg_" + cid, "type": "message", "role": "assistant", "model": body.get("model", "mock"),
               "content": [block], "stop_reason": stop, "stop_sequence": None, "usage": usage}
        if not body.get("stream"):
            return self.reply_json(msg)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        start = dict(msg, content=[], stop_reason=None)
        if block["type"] == "tool_use":
            cstart = dict(block, input={})
            delta = {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
        else:
            cstart, delta = {"type": "text", "text": ""}, {"type": "text_delta", "text": block["text"]}
        for ev, data in [("message_start", {"type": "message_start", "message": start}),
                         ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": cstart}),
                         ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": delta}),
                         ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                         ("message_delta", {"type": "message_delta",
                                            "delta": {"stop_reason": stop, "stop_sequence": None},
                                            "usage": {"output_tokens": 5}}),
                         ("message_stop", {"type": "message_stop"})]:
            self.wfile.write(f"event: {ev}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
