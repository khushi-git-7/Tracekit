"""Write the recording's Claude Code settings: settings.py KIT OUT. Every hook event runs rec_hook.py."""
import json, sys

kit, out = sys.argv[1], sys.argv[2]
events = ["PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "UserPromptSubmit", "SessionStart",
          "SessionEnd", "Stop", "SubagentStart", "SubagentStop", "Notification", "PreCompact"]
tool_events = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"}
hooks = {}
for ev in events:
    group = {"hooks": [{"type": "command", "command": f"python3 {kit}/rec_hook.py {ev}", "timeout": 30}]}
    if ev in tool_events:
        group["matcher"] = "*"
    hooks[ev] = [group]
with open(out, "w") as f:
    json.dump({"hooks": hooks}, f, indent=2)
