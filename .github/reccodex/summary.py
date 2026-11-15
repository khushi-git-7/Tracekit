"""Print what one recording scenario captured: the tools offered (with the schemas of the ones this recording is
about), the mock's answers, and every hook event with its tool name, call id and input."""
import json, os, sys

d = sys.argv[1]
WANT = ("view_image", "spawn_agent", "send_input", "wait_agent", "wait", "close_agent", "resume_agent")


def lines(name):
    try:
        return [json.loads(l) for l in open(os.path.join(d, name), encoding="utf-8")]
    except FileNotFoundError:
        return []


reqs = lines("requests.jsonl")
seen = {}
for r in reqs:
    b = r["body"] if isinstance(r["body"], dict) else {}
    tools = list(b.get("tools") or [])
    for i in b.get("input") or []:
        if isinstance(i, dict) and i.get("type") == "additional_tools":
            tools += i.get("tools") or []
    for t in tools:
        subs = t.get("tools") if t.get("type") == "namespace" or "tools" in t else None
        for s in subs or [t]:
            n = (t["name"] + "__" if subs else "") + str(s.get("name") or s.get("type"))
            seen.setdefault(n, s)
print("offered tools:", list(seen))
for n, s in seen.items():
    if any(n.endswith(w) for w in WANT):
        print("  schema", n, json.dumps(s.get("parameters"))[:900])
print("answers:", [r["answer"] and (r["answer"]["name"], r["answer"]["args"]) for r in reqs])
for e in lines("events.jsonl"):
    p = e["payload"] or {}
    print(" ", e["argv"], str(p.get("session_id"))[-8:], p.get("tool_name", ""), p.get("tool_use_id", ""),
          json.dumps(p.get("tool_input"))[:400] if "tool_input" in p else "",
          ("| response: " + json.dumps(p.get("tool_response"))[:200]) if "tool_response" in p else "",
          "| keys:", sorted(p))
