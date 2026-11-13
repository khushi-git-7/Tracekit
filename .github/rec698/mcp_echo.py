"""A minimal stdio MCP server for Tracekit #698's recording: one tool, echo_text."""
import json, sys

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()

for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    mid, method = msg.get("id"), msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": msg["params"].get("protocolVersion", "2024-11-05"),
              "capabilities": {"tools": {}}, "serverInfo": {"name": "rec_server", "version": "0.1"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [{"name": "echo_text", "description": "Echo the text back.",
              "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}]}})
    elif method == "tools/call":
        text = (msg.get("params", {}).get("arguments") or {}).get("text", "")
        send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}})
    elif mid is not None:
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
