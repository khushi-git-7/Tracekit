"""Print the Claude Code binary's text around each marker: src.py BINARY WIDTH MARKER...

Only printable runs are kept, so the bundled JavaScript reads as text."""
import re, sys

data = open(sys.argv[1], "rb").read()
width = int(sys.argv[2])
for marker in sys.argv[3:]:
    m = marker.encode()
    hits = [h.start() for h in re.finditer(re.escape(m), data)][:3]
    print(f"##### {marker}: {len(hits)} shown")
    seen = -10**9
    for at in hits:
        if at - seen < width:
            continue
        seen = at
        chunk = data[max(0, at - width):at + width]
        print(re.sub(rb"[^\x20-\x7e\n]+", b" ", chunk).decode())
        print("-----")
