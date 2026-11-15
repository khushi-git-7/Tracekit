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
    ("mcp", None), ("fetch", None), ("other", None), ("delete", None),
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
    "other": ["get_goal", "TodoWrite"],   # a tool that is neither shell, file nor MCP: does PreToolUse fire?
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
    if intent == "other":
        return {"todos": [{"content": "record", "status": "pending", "activeForm": "Recording"}]}             if name == "TodoWrite" else {}
    if intent == "fetch":
        out = {"url": "https://example.com"}
        if "prompt" in props:
            out["prompt"] = "Say what the page is."
        return out
    return {}


# Code Mode: the model gets one `exec` tool (JavaScript) whose code calls the real tools; one step per exec call
CODE_MODE = [
    'await tools.exec_command({cmd: "echo rec698"});',
    r'await tools.apply_patch("*** Begin Patch\n*** Add File: notes.txt\n+one\n*** End Patch\n");',
    'await tools.exec_command({cmd: "echo deny-me"});',
    'await tools.mcp__rec_server__echo_text({text: "hello-mcp"});',
    'await tools.get_goal({});',
    # #698 review: what exec's JavaScript can reach without a tool. fetch aims at this mock (the code-mode port), so a
    # request that left the isolate would be logged here as a GET
    ('const r = {fetch: typeof fetch, require: typeof require, process: typeof process, Deno: typeof Deno, '
     'XMLHttpRequest: typeof XMLHttpRequest, WebSocket: typeof WebSocket, '
     'globals: Object.getOwnPropertyNames(globalThis).sort()};'
     ' try { await fetch("http://127.0.0.1:8707/probe-fetch"); r.fetch_call = "ran"; } catch (e) { r.fetch_call = String(e); }'
     ' try { await import("node:fs"); r.import_fs = "ran"; } catch (e) { r.import_fs = String(e); }'
     ' try { await import("http://127.0.0.1:8707/probe-import.js"); r.import_url = "ran"; } catch (e) { r.import_url = String(e); }'
     ' text("PROBE " + JSON.stringify(r));'),
]


def offered(body):
    """{name: (kind, schema)} of the tools in a Responses or Chat request (Responses' additional_tools input items
    too, where Code Mode puts its namespaced tools)."""
    out = {}
    extra = [t for i in body.get("input") or [] if isinstance(i, dict) and i.get("type") == "additional_tools"
             for t in i.get("tools") or []]
    for t in extra:
        for sub in t.get("tools") or []:
            out[t["name"] + "__" + sub["name"]] = (("namespace-" + sub.get("type", ""), t["name"], sub["name"]),
                                                   sub.get("parameters"))
    for t in body.get("tools") or []:
        if t.get("type") == "function" and "function" in t:   # chat
            out[t["function"]["name"]] = ("function", t["function"].get("parameters"))
        elif t.get("type") == "function":
            out[t["name"]] = ("function", t.get("parameters"))
        elif t.get("type") == "namespace":   # Responses: an MCP server's tools, called by name and namespace
            for sub in t.get("tools") or []:
                out[t["name"] + "__" + sub["name"]] = (("namespace", t["name"], sub["name"]), sub.get("parameters"))
        elif t.get("type") == "custom":
            out[t["name"]] = ("custom", None)
        elif "input_schema" in t:   # Anthropic Messages
            out[t["name"]] = ("function", t["input_schema"])
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
    if "messages" in body:   # Chat's tool messages, or Messages' tool_result blocks
        return sum(1 for m in body["messages"] if m.get("role") == "tool") + sum(
            1 for m in body["messages"] if isinstance(m.get("content"), list)
            for c in m["content"] if isinstance(c, dict) and c.get("type") == "tool_result")
    return sum(1 for i in body.get("input") or [] if isinstance(i, dict) and
               i.get("type") in ("function_call_output", "custom_tool_call_output"))


TASK = "SUBAGENT-TASK: run echo from-subagent"


def subagent_call(body, tools):
    """Round 6 (MOCK_MODE=subagent, Chat): the main agent spawns a sub-agent with a local_image item, then waits; the
    sub-agent (its first message is TASK, and its own history has no spawn) runs one command. Do its calls fire hooks?"""
    text = json.dumps(body)
    spawned = any(tc.get("function", {}).get("name", "").endswith("spawn_agent")
                  for m in body.get("messages") or [] for tc in m.get("tool_calls") or [])
    n = done_count(body)
    if TASK in text and not spawned:   # the sub-agent
        return None if n else ("exec_command", tools["exec_command"][0], {"cmd": "echo from-subagent"}, n)
    spawn = next((t for t in tools if t.endswith("spawn_agent")), None)
    if n == 0 and spawn:
        # message or items, not both (0.0.61): the task goes in as a text item, beside a local image
        return spawn, tools[spawn][0], {"items": [
            {"type": "text", "text": TASK}, {"type": "local_image", "path": os.path.join(WORK, "pic.png")}]}, n
    if n == 1:
        return "exec_command", tools["exec_command"][0], {"cmd": "sleep 15"}, n
    return None


# Round 7 (#853 review): calls sent by name whether or not the request offers them, as a model may
PIC = os.path.join(WORK, "pic.png")
SCRIPTS = {
    # harness = "claude-code" over Messages: the alias tools add_harness_alias_tools registers, and filePath
    "aliases": [
        ("bash", {"command": "echo rec-bash"}),
        ("Write", {"filePath": NOTES, "content": "one\n"}),
        ("write", {"filePath": NOTES, "content": "one\n"}),
        ("Edit", {"filePath": NOTES, "old_string": "one", "new_string": "uno"}),
        ("edit", {"path": NOTES, "oldString": "uno", "newString": "one"}),
        ("Read", {"filePath": NOTES}),
        ("read", {"path": NOTES}),
        ("glob", {"pattern": "*.txt", "path": WORK}),
        ("grep", {"pattern": "one", "path": WORK}),
        ("Agent", {"description": "rec7", "prompt": "SUBAGENT-TASK: run echo from-agent"}),
        ("Bash", {"command": "sleep 12", "timeout": 20000}),
    ],
    # harness = "deepseek-tui" over Chat: its own shell and file tools
    "deepseek": [
        ("exec_shell", {"command": "echo rec-exec-shell"}),
        ("write_file", {"path": NOTES, "content": "one\n"}),
        ("edit_file", {"path": NOTES, "search": "one", "replace": "uno"}),
        ("read_file", {"path": NOTES}),
    ],
    # harness = "kimi-code" over Chat: ReadMediaFile
    "kimi": [("ReadMediaFile", {"path": PIC})],
}
SUB_IDS, TURNS = set(), {"n": 0}


def last_message(body):
    msgs = body.get("messages") or []
    return msgs[-1] if msgs else {}


def is_sub_start(body, marker):
    """The sub-agent's first request: its last message is the user text that carries the marker, not a tool result."""
    m = last_message(body)
    c = m.get("content")
    text = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
    results = [x for x in c or [] if isinstance(x, dict) and x.get("type") == "tool_result"] if isinstance(c, list) \
        else []
    return m.get("role") == "user" and marker in text and not results


def last_result_id(body):
    m = last_message(body)
    if m.get("role") == "tool":
        return m.get("tool_call_id")
    c = m.get("content")
    ids = [x.get("tool_use_id") for x in c or [] if isinstance(x, dict) and x.get("type") == "tool_result"] \
        if isinstance(c, list) else []
    return ids[-1] if ids else None


def scripted_call(body, tools, mode):
    if mode == "aliases" and "AskUserQuestion" not in tools:   # the Agent's sub-agent (round 7: no AskUserQuestion)
        return ("Bash", "function", {"command": "echo from-agent"}, "sub") if done_count(body) == 0 else None
    if last_result_id(body) in SUB_IDS:
        return None
    steps = SCRIPTS[mode]
    n = done_count(body)
    if n >= len(steps):
        return None
    name, args = steps[n]
    return name, "function", args, n


def sendinput_call(body, tools):
    """Native over Chat: spawn a sub-agent with a plain message, send it input with a local_image item, wait."""
    text = json.dumps(body)
    spawned = any(tc.get("function", {}).get("name", "").endswith("spawn_agent")
                  for m in body.get("messages") or [] for tc in m.get("tool_calls") or [])
    if "SUBAGENT-IDLE" in text and not spawned:
        return None
    n = done_count(body)
    agent = next((json.loads(m["content"]).get("agent_id") for m in body.get("messages") or []
                  if m.get("role") == "tool" and isinstance(m.get("content"), str) and '"agent_id"' in m["content"]),
                 None)
    if n == 0:
        return "multi_agent_v1_spawn_agent", "function", {"message": "SUBAGENT-IDLE: reply done"}, n
    if n == 1 and agent:
        return "multi_agent_v1_send_input", "function", {"target": agent, "items": [
            {"type": "text", "text": "SUBAGENT-IDLE: look"}, {"type": "local_image", "path": PIC}]}, n
    if n == 2 and agent:
        return "multi_agent_v1_wait_agent", "function", {"targets": [agent], "timeout_ms": 10000}, n
    return None


def text_turn(body, mode):
    """swe-agent and terminus-2 read the action from the model's text: a fenced bash block, or Terminus' JSON."""
    TURNS["n"] += 1
    if mode == "swe":
        return ("TEXT", "DISCUSSION\nRecord one command.\n\n```bash\necho rec-swe\n```" if TURNS["n"] == 1
                else "DISCUSSION\nDone.\n\n```bash\nsubmit\n```")
    if TURNS["n"] == 1:
        return ("TEXT", json.dumps({"analysis": "a", "plan": "p",
                                    "commands": [{"keystrokes": "echo rec-term\n", "duration": 0.1}]}))
    return ("TEXT", json.dumps({"analysis": "a", "plan": "p", "commands": [], "task_complete": True}))


def next_call(body):
    tools = offered(body)
    mode = os.environ.get("MOCK_MODE")
    if mode in ("swe", "terminus") and body.get("messages"):
        return text_turn(body, mode)
    if not tools:
        return None
    if mode in SCRIPTS:
        return scripted_call(body, tools, mode)
    if mode == "sendinput":
        return sendinput_call(body, tools)
    if os.environ.get("MOCK_MODE") == "subagent":
        return subagent_call(body, tools)
    if "functions__exec" in tools:
        n = done_count(body)
        return None if n >= len(CODE_MODE) else ("exec", tools["functions__exec"][0], {"input": CODE_MODE[n]}, n)
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
        if "probe" in self.path:   # anything from inside Code Mode's exec that reached the network
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "path": self.path, "body": {"_get": True}, "answer": None}) + chr(10))
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
        reply = "done"
        if call and call[0] == "TEXT":
            reply, call = call[1], None
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "path": self.path, "body": body,
                                "answer": call and {"name": call[0], "kind": call[1], "args": call[2]}}) + "\n")
        cid = f"call_{int(time.time() * 1000) % 10**9}"
        if call and call[3] == "sub":
            SUB_IDS.update({cid, "toolu_" + cid})
        if self.path.endswith("/messages"):   # Anthropic Messages, streamed
            msg = {"id": "msg_" + cid, "type": "message", "role": "assistant", "model": body.get("model", "mock"),
                   "content": [], "stop_reason": None, "stop_sequence": None,
                   "usage": {"input_tokens": 10, "output_tokens": 1}}
            evs = [("message_start", {"type": "message_start", "message": msg})]
            if call:
                name, kind, args, n = call
                evs += [("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {
                            "type": "tool_use", "id": "toolu_" + cid, "name": name, "input": {}}}),
                        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {
                            "type": "input_json_delta", "partial_json": json.dumps(args)}})]
                stop = "tool_use"
            else:
                evs += [("content_block_start", {"type": "content_block_start", "index": 0,
                                                 "content_block": {"type": "text", "text": ""}}),
                        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                 "delta": {"type": "text_delta", "text": reply}})]
                stop = "end_turn"
            evs += [("content_block_stop", {"type": "content_block_stop", "index": 0}),
                    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                                       "usage": {"output_tokens": 5}}),
                    ("message_stop", {"type": "message_stop"})]
            return self.sse(evs)
        if self.path.endswith("/responses"):
            evs = [("response.created", {"type": "response.created", "response": {"id": "resp_" + cid}})]
            if call:
                name, kind, args, n = call
                item = ({"type": "custom_tool_call", "id": "ctc_" + cid, "call_id": cid, "name": kind[2],
                         "namespace": kind[1], "input": args["input"], "status": "completed"}
                        if isinstance(kind, tuple) and kind[0] == "namespace-custom" else
                        {"type": "custom_tool_call", "id": "ctc_" + cid, "call_id": cid, "name": name,
                         "input": args["input"], "status": "completed"} if kind == "custom" else
                        {"type": "function_call", "id": "fc_" + cid, "call_id": cid, "name": kind[2],
                         "namespace": kind[1], "arguments": json.dumps(args), "status": "completed"}
                        if isinstance(kind, tuple) else
                        {"type": "function_call", "id": "fc_" + cid, "call_id": cid, "name": name,
                         "arguments": json.dumps(args), "status": "completed"})
            else:
                item = {"type": "message", "role": "assistant", "id": "msg_" + cid, "status": "completed",
                        "content": [{"type": "output_text", "text": reply, "annotations": []}]}
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
            delta, fin = {"role": "assistant", "content": reply}, "stop"
        base = {"id": "chatcmpl-" + cid, "object": "chat.completion.chunk", "created": int(time.time()),
                "model": body.get("model", "mock") if isinstance(body, dict) else "mock"}
        if isinstance(body, dict) and not body.get("stream"):
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
