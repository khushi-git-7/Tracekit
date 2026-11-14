"""Forward Open Interpreter's Chat Completions requests to Gemini's OpenAI-compatible endpoint, dropping the top-level
fields Gemini rejects (it answers 400 to `store`), and handing back each tool call's thought signature, which Gemini 3
requires on the next turn and Open Interpreter's Chat client doesn't keep. Logs which fields it dropped, never values.
Fork-only, #698 live run.
    python shim.py PORT"""
import http.server
import json
import os
import sys
import urllib.error
import urllib.request

UPSTREAM = "https://generativelanguage.googleapis.com"
KEEP = {"model", "messages", "tools", "tool_choice", "stream", "stream_options", "temperature", "top_p", "n", "stop",
        "max_tokens", "max_completion_tokens", "response_format", "reasoning_effort", "seed"}
LOG = os.path.join(os.environ.get("OUT", "."), "shim.log")
SIGS = {}   # tool call id -> its extra_content (Gemini's thought_signature)


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def forward(self, method, body=None):
        req = urllib.request.Request(UPSTREAM + self.path, data=body, method=method, headers={
            "Authorization": "Bearer " + os.environ["GEMINI_API_KEY"], "Content-Type": "application/json",
            "User-Agent": "tracekit-698-live"})
        try:
            r = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            r = e
        self.send_response(r.status if hasattr(r, "status") else r.code)
        for k, v in r.headers.items():
            if k.lower() in ("content-type", "cache-control"):
                self.send_header(k, v)
        self.send_header("Connection", "close")
        self.end_headers()
        buf = b""
        while True:
            chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for line in lines:
                self.remember(line)
        self.remember(buf)

    @staticmethod
    def remember(line):
        line = line.strip()
        if not line.startswith(b"data:"):
            try:   # a reply that isn't streamed
                body = json.loads(line)
            except ValueError:
                return
        else:
            try:
                body = json.loads(line[5:])
            except ValueError:
                return
        for choice in body.get("choices") or [] if isinstance(body, dict) else []:
            msg = choice.get("delta") or choice.get("message") or {}
            for tc in msg.get("tool_calls") or []:
                if tc.get("id") and tc.get("extra_content"):
                    SIGS[tc["id"]] = tc["extra_content"]

    def do_GET(self):
        self.forward("GET")

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = json.loads(raw)
        dropped = sorted(k for k in body if k not in KEEP)
        for k in dropped:
            body.pop(k)
        restored = 0
        for m in body.get("messages") or []:
            for tc in m.get("tool_calls") or [] if m.get("role") == "assistant" else []:
                if tc.get("id") in SIGS and "extra_content" not in tc:
                    tc["extra_content"] = SIGS[tc["id"]]
                    restored += 1
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"path": self.path, "model": body.get("model"), "dropped": dropped, "restored": restored,
                                "tools": [t.get("function", {}).get("name") for t in body.get("tools") or []]}) + "\n")
        self.forward("POST", json.dumps(body).encode())


http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
