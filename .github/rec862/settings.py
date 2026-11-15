"""Write the recording's Claude Code settings: settings.py KIT OUT. Every hook event runs rec_hook.py."""
import json, os, sys

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
settings = {"hooks": hooks}
extra = os.environ.get("EXTRA_SETTINGS")   # JSON merged into the settings, e.g. {"env": {...}}
if extra:
    settings.update(json.loads(extra))
with open(out, "w") as f:
    json.dump(settings, f, indent=2)
