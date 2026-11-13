"""A scripted model for Tracekit #698's recording: an OpenAI-compatible server (Responses and Chat Completions) that
answers each request with the next tool call of a fixed plan, chosen from the tools the request offers, then "done".

Every request body is appended to $REC_DIR/requests.jsonl, so the tool schemas each surface offers are recorded too.
Usage: python3 mock_llm.py PORT WORKDIR"""
import json, os, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, WORK = int(sys.argv[1]), sys.argv[2]
LOG = os.path.join(os.environ.get("REC_DIR", "."), "requests.jsonl")
NOTES = os.path.join(WORK, "notes.txt")

# (intent, candidate tool names in order of preference); a step whose tools the request doesn't offer is skipped
PLAN = [
    ("shell", "echo rec698"),
    ("write", None), ("edit", None), ("read", None), ("list", None), ("glob", None), ("grep", None),
    ("shell", "echo deny-me"),      # the hook exits 2: blocked?
    ("shell", "echo fail-me"),      # the hook exits 1: runs?
    ("shell", "echo slow-me"),      # the hook outlives its timeout: runs?
    ("shell", "echo json-deny"),    # the hook answers permissionDecision deny on stdout, exit 0
    ("mcp", None), ("fetch", None), ("delete", None),
]
CANDIDATES = {
    "shell": ["Bash", "exec_command", "shell_command", "shell", "local_shell", "Shell"],
    "write": ["Write", "write_file", "WriteFile", "apply_patch"],
    "edit": ["Edit", "edit_file", "StrReplaceFile", "apply_patch"],
    "read": ["Read", "read_file", "ReadFile"],
    "list": ["LS", "list_dir"],
    "glob": ["Glob", "glob_files", "file_search"],
    "grep": ["Grep", "grep_files"],
    "mcp": [],   # any tool whose name ends with echo_text
    "fetch": ["WebFetch", "web_fetch", "FetchUrl"],
    "delete": ["apply_patch"],
}


def patch(intent):
    if intent == "write":
        return "*** Begin Patch\n*** Add File: notes.txt\n+one\n*** End Patch\n"
    if intent == "edit":
        return "*** Begin Patch\n*** Update File: notes.txt\n@@\n-one\n+uno\n*** End Patch\n"
    return "*** Begin Patch\n*** Delete File: notes.txt\n*** End Patch\n"


def args_for(intent, value, name, schema):
    props = (schema or {}).get("properties", {}) if isinstance(schema, dict) else {}
    if name == "apply_patch":
        return {"input": patch(intent)}
    if intent == "shell":
        if name == "exec_command":
            return {"cmd": value}
        if name == "shell":
            return {"command": ["bash", "-lc", value]}
        return {"command": value, "description": "recording step"} if "description" in props else {"command": value}
    if intent == "write":
        k = "file_path" if "file_path" in props or not props else "path"
        return {k: NOTES, "content": "one\n"}
    if intent == "edit":
        if name == "StrReplaceFile":
            return {"path": NOTES, "edit": {"old": "one", "new": "uno"}}
        return {"file_path": NOTES, "old_string": "one", "new_string": "uno"}
    if intent == "read":
        k = "file_path" if "file_path" in props or not props else "path"
        return {k: NOTES}
    if intent == "list":
        return {"dir_path": WORK} if "dir_path" in props else {"path": WORK}
    if intent == "glob":
        return {"pattern": "*.txt", "path": WORK}
    if intent == "grep":
        return {"pattern": "uno", "path": WORK}
    if intent == "mcp":
        return {"text": "hello-mcp"}
    if intent == "fetch":
        out = {"url": "https://example.com"}
        if "prompt" in props:
            out["prompt"] = "Say what the page is."
        return out
    return {}


def offered(body):
    """{name: (kind, schema)} of the tools in a Responses or Chat request."""
    out = {}
    for t in body.get("tools") or []:
        if t.get("type") == "function" and "function" in t:   # chat
            out[t["function"]["name"]] = ("function", t["function"].get("parameters"))
        elif t.get("type") == "function":
            out[t["name"]] = ("function", t.get("parameters"))
        elif t.get("type") == "custom":
            out[t["name"]] = ("custom", None)
        elif "name" in t:
            out[t["name"]] = (t.get("type"), None)
    return out


def plan(tools):
    steps = []
    for intent, value in PLAN:
        names = [n for n in tools if n.endswith("echo_text")] if intent == "mcp" else \
            [n for n in CANDIDATES[intent] if n in tools]
        if names:
            steps.append((intent, value, names[0]))
    return steps


def done_count(body):
    if "messages" in body:
        return sum(1 for m in body["messages"] if m.get("role") == "tool")
    return sum(1 for i in body.get("input") or [] if isinstance(i, dict) and
               i.get("type") in ("function_call_output", "custom_tool_call_output"))


def next_call(body):
    tools = offered(body)
    if not tools:
        return None
    steps = plan(tools)
    n = done_count(body)
    if n >= len(steps):
        return None
    intent, value, name = steps[n]
    kind, schema = tools[name]
    return name, kind, args_for(intent, value, name, schema), n


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"object": "list", "data": [{"id": "mock", "object": "model"}], "models": []}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def sse(self, events):
        self.send_response(200); self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache"); self.end_headers()
        for ev, data in events:
            line = (f"event: {ev}\n" if ev else "") + "data: " + (data if isinstance(data, str) else json.dumps(data))
            self.wfile.write((line + "\n\n").encode()); self.wfile.flush()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"_raw": raw.decode("utf-8", "replace")}
        call = next_call(body) if isinstance(body, dict) else None
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "path": self.path, "body": body,
                                "answer": call and {"name": call[0], "kind": call[1], "args": call[2]}}) + "\n")
        cid = f"call_{int(time.time() * 1000) % 10**9}"
        if self.path.endswith("/responses"):
            evs = [("response.created", {"type": "response.created", "response": {"id": "resp_" + cid}})]
            if call:
                name, kind, args, n = call
                item = ({"type": "custom_tool_call", "id": "ctc_" + cid, "call_id": cid, "name": name,
                         "input": args["input"], "status": "completed"} if kind == "custom" else
                        {"type": "function_call", "id": "fc_" + cid, "call_id": cid, "name": name,
                         "arguments": json.dumps(args), "status": "completed"})
            else:
                item = {"type": "message", "role": "assistant", "id": "msg_" + cid, "status": "completed",
                        "content": [{"type": "output_text", "text": "done", "annotations": []}]}
            evs.append(("response.output_item.done", {"type": "response.output_item.done", "output_index": 0,
                                                       "item": item}))
            evs.append(("response.completed", {"type": "response.completed", "response": {
                "id": "resp_" + cid, "usage": {"input_tokens": 10, "input_tokens_details": {"cached_tokens": 0},
                                               "output_tokens": 5, "output_tokens_details": {"reasoning_tokens": 0},
                                               "total_tokens": 15}}}))
            return self.sse(evs)
        # chat completions
        if call:
            name, kind, args, n = call
            delta = {"role": "assistant", "content": None, "tool_calls": [{
                "index": 0, "id": cid, "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)}}]}
            fin = "tool_calls"
        else:
            delta, fin = {"role": "assistant", "content": "done"}, "stop"
        base = {"id": "chatcmpl-" + cid, "object": "chat.completion.chunk", "created": int(time.time()),
                "model": body.get("model", "mock") if isinstance(body, dict) else "mock"}
        if isinstance(body, dict) and body.get("stream") is False:
            msg = {k: v for k, v in delta.items()}
            out = json.dumps({**base, "object": "chat.completion", "choices": [
                {"index": 0, "message": msg, "finish_reason": fin}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
            return
        self.sse([(None, {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}),
                  (None, {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": fin}],
                          "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}),
                  (None, "[DONE]")])


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
