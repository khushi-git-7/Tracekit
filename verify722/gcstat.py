"""Fork-only pytest plugin for #722 step 4: gc time and count per test file, and any tracer or monitor left on."""
import collections
import gc
import sys
import time

_t0 = [0.0]
gen_n = collections.Counter()
gen_s = collections.Counter()
file_gc = collections.Counter()
file_wall = collections.Counter()
_cur = ["-"]


def _cb(phase, info):
    if phase == "start":
        _t0[0] = time.perf_counter()
    else:
        d = time.perf_counter() - _t0[0]
        g = info.get("generation")
        gen_n[g] += 1
        gen_s[g] += d
        file_gc[_cur[0]] += d


def _hooks(tag):
    out = {"settrace": repr(sys.gettrace()), "setprofile": repr(sys.getprofile())}
    mon = getattr(sys, "monitoring", None)
    if mon is not None:
        out["monitoring"] = {i: mon.get_tool(i) for i in range(6) if mon.get_tool(i)}
    out["gc_threshold"] = gc.get_threshold()
    out["gc_freeze"] = gc.get_freeze_count()
    out["gc_enabled"] = gc.isenabled()
    print(f"\n[gcstat {tag}] {out}", flush=True)


def pytest_sessionstart(session):
    import os
    th = os.environ.get("GC_THRESHOLD")
    if th:
        gc.set_threshold(*map(int, th.split(",")))
    gc.callbacks.append(_cb)
    _hooks("start")


import pytest  # noqa: E402


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    _cur[0] = item.nodeid.split("::")[0]
    t = time.perf_counter()
    yield
    file_wall[_cur[0]] += time.perf_counter() - t


def pytest_sessionfinish(session, exitstatus):
    _hooks("end")
    print(f"[gcstat] {sys.version.split()[0]} collections per gen {dict(gen_n)} seconds per gen "
          f"{ {k: round(v, 2) for k, v in gen_s.items()} } total {sum(gen_s.values()):.2f}s; objects tracked {len(gc.get_objects())}")
    for f, w in sorted(file_wall.items()):
        print(f"[gcstat] file {f}: call {w:.1f}s, gc {file_gc[f]:.2f}s")
