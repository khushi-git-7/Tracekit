"""Forward Open Interpreter's Chat Completions requests to Gemini's OpenAI-compatible endpoint, dropping the top-level
fields Gemini rejects (it answers 400 to `store`). Logs which fields it dropped, never values. Fork-only, #698 live run.
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
        while True:
            chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()

    def do_GET(self):
        self.forward("GET")

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = json.loads(raw)
        dropped = sorted(k for k in body if k not in KEEP)
        for k in dropped:
            body.pop(k)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"path": self.path, "model": body.get("model"), "dropped": dropped,
                                "tools": [t.get("function", {}).get("name") for t in body.get("tools") or []]}) + "\n")
        self.forward("POST", json.dumps(body).encode())


http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
