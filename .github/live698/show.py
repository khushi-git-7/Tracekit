"""Print an `interpreter exec --json` transcript compactly: commands, their status and output, and the model's text."""
import json
import sys

for line in open(sys.argv[1], encoding="utf-8"):
    try:
        e = json.loads(line)
    except ValueError:
        continue
    item = e.get("item") or {}
    kind = item.get("type") or item.get("item_type")
    if e.get("type") == "item.completed" and kind in ("command_execution", "agent_message", "error", "mcp_tool_call",
                                                     "file_change", "reasoning"):
        if kind == "command_execution":
            print(f"[command] {item.get('command')!r} status={item.get('status')} exit={item.get('exit_code')} "
                  f"output={str(item.get('aggregated_output', ''))[:400]!r}")
        elif kind == "agent_message":
            print("[model]", item.get("text", "")[:1500])
        elif kind != "reasoning":
            print(f"[{kind}]", json.dumps(item)[:600])
    elif e.get("type") in ("error", "turn.failed"):
        print("[error]", json.dumps(e)[:600])
