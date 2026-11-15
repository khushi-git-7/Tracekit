"""Print one scenario's recording: summary.py REC_DIR LABEL"""
import json, os, sys

d, label = sys.argv[1], sys.argv[2]


def lines(name):
    try:
        return [json.loads(l) for l in open(os.path.join(d, name), encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        return []


reqs, evs = lines("requests.jsonl"), lines("events.jsonl")
try:
    ex = open(os.path.join(d, "exit")).read().strip()
except FileNotFoundError:
    ex = "?"
print(f"=== {label}: {ex}, {len(reqs)} requests, {len(evs)} hook events")
tools = []
for r in reqs:
    for t in (r.get("body") or {}).get("tools") or []:
        if t.get("name") not in tools:
            tools.append(t.get("name"))
print("offered tools:", tools)
print("answers:", [(r.get("answer") or {}).get("tool") or (r.get("answer") or {}).get("text")
                   for r in reqs if "body" in r])
for e in evs:
    p = e["payload"] or {}
    print(f"  {e['t']:.3f}+{e['t_end'] - e['t']:.2f} {e['argv'][0]:<18} {p.get('tool_name', ''):<14}"
          f" id={p.get('tool_use_id', '')}",
          json.dumps(p.get("tool_input"))[:200] if "tool_input" in p else "",
          "| resp:", json.dumps(p.get("tool_response"))[:160] if "tool_response" in p else "",
          "| keys:", sorted(p))
