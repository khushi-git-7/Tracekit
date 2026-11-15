"""Fork-only profile of test_policy2.Speed (#722 step 3). Not for upstream."""
import collections, functools, heapq, json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
import regex
import test_policy2 as tp
from factories import process_pool
from tracekit.policy2 import compile as pc

T0 = time.time()

def task(item, scale):
    t_start = time.time()
    rid, key, pattern = item
    sp = tp.Speed()
    budget = sp.RULE_BUDGET_S.get(rid, sp.BUDGET_S) * scale
    t = time.perf_counter(); rx = regex.compile(pc.translate(pattern), regex.ASCII | regex.V0); t_comp = time.perf_counter() - t
    t = time.perf_counter(); fl = sp.fillers(rid, pattern); t_fill = time.perf_counter() - t
    times = []; over = []
    for s in fl:
        took = sp.search(rx, s, budget)
        times.append(took)
        if took > budget: over.append(s)
    return dict(rid=rid, key=key, n=len(fl), distinct=len(set(fl)), t_comp=t_comp, t_fill=t_fill,
                t_search=sum(times), t_max=max(times) if times else 0, over=len(over), pid=os.getpid(),
                start=t_start, end=time.time(), rescan=rid in sp.RESCAN, plen=len(pattern),
                top=sorted(times, reverse=True)[:5], budget=budget)

def lpt(durs, k):
    h = [0.0] * k
    for d in sorted(durs, reverse=True):
        heapq.heapreplace(h, h[0] + d)
    return max(h)

def inorder(durs, k):
    h = [0.0] * k
    for d in durs:
        heapq.heapreplace(h, h[0] + d)
    return max(h)

def main():
    out = {}
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    out["cpus"] = cpus
    t = time.perf_counter(); pats = tp.pack_patterns(); out["t_pack_patterns"] = time.perf_counter() - t
    t = time.perf_counter(); scale = tp.machine_scale(); out["t_machine_scale"] = time.perf_counter() - t
    out["scale"] = scale; out["patterns"] = len(pats)
    texts = collections.Counter(p for _, _, p in pats)
    out["distinct_pattern_texts"] = len(texts)
    out["dup_pattern_extra_items"] = sum(c - 1 for c in texts.values())
    t_pool = time.time()
    with process_pool() as pool:
        t_first = time.time()
        res = list(pool.map(functools.partial(task, scale=scale), pats))
        t_mapped = time.time()
    t_closed = time.time()
    out["t_pool_create"] = t_first - t_pool
    out["t_map_wall"] = t_mapped - t_first
    out["t_pool_shutdown"] = t_closed - t_mapped
    out["first_task_start_after_pool"] = min(r["start"] for r in res) - t_first
    busy = sum(r["end"] - r["start"] for r in res)
    out["sum_task_s"] = busy
    out["sum_search_s"] = sum(r["t_search"] for r in res)
    out["sum_fill_s"] = sum(r["t_fill"] for r in res)
    out["sum_comp_s"] = sum(r["t_comp"] for r in res)
    out["fillers_total"] = sum(r["n"] for r in res)
    out["fillers_distinct_within_pattern"] = sum(r["distinct"] for r in res)
    out["over_total"] = sum(r["over"] for r in res)
    out["utilisation"] = busy / (cpus * out["t_map_wall"])
    durs = [r["end"] - r["start"] for r in res]
    out["ideal_makespan"] = busy / cpus
    out["inorder_sim"] = inorder(durs, cpus)
    out["lpt_sim"] = lpt(durs, cpus)
    last_end = max(r["end"] for r in res)
    per_pid = collections.defaultdict(float)
    for r in res: per_pid[r["pid"]] += r["end"] - r["start"]
    out["per_worker_busy"] = sorted(per_pid.values())
    out["worker_idle_tail"] = sorted(last_end - max(r["end"] for r in res if r["pid"] == p) for p in per_pid)
    # dup searches: same (pattern text, filler) across items -> estimate via text dup
    byt = collections.defaultdict(float)
    for (rid, key, p), r in zip(pats, res): byt[p] += r["end"] - r["start"]
    seen = set(); dup_s = 0.0
    for (rid, key, p), r in zip(pats, res):
        if p in seen: dup_s += r["end"] - r["start"]
        seen.add(p)
    out["dup_pattern_task_s"] = dup_s
    # parent re-check like the test
    t = time.perf_counter(); rechecks = 0
    sp = tp.Speed()
    with process_pool() as pool:
        over = list(pool.map(functools.partial(tp._over_budget, scale=scale), pats))
    out["t_test_like_map"] = time.perf_counter() - t
    t = time.perf_counter()
    for (rid, key, pattern), fl in zip(pats, over):
        budget = sp.RULE_BUDGET_S.get(rid, sp.BUDGET_S) * scale
        rx = regex.compile(pc.translate(pattern), regex.ASCII | regex.V0)
        for s in fl:
            rechecks += 1
            min(sp.search(rx, s, budget) for _ in range(3))
    out["t_recheck"] = time.perf_counter() - t; out["rechecks"] = rechecks
    res.sort(key=lambda r: -(r["end"] - r["start"]))
    out["top_tasks"] = [dict(rid=r["rid"], key=r["key"], s=round(r["end"] - r["start"], 2), n=r["n"],
                             distinct=r["distinct"], search=round(r["t_search"], 2), fill=round(r["t_fill"], 3),
                             tmax=round(r["t_max"], 3), over=r["over"], rescan=r["rescan"],
                             top=[round(x, 3) for x in r["top"]]) for r in res[:25]]
    total = busy; acc = 0; k = 0
    for r in res:
        acc += r["end"] - r["start"]; k += 1
        if acc >= total / 2: break
    out["tasks_for_half_time"] = k
    # per-filler-time histogram across all tasks is not kept; instead share of search vs fill
    print("PROF722 " + json.dumps(out, indent=1))

if __name__ == "__main__":
    main()
