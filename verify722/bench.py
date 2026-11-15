"""Fork-only CPU microbench for #722 step 4: the same work under each interpreter."""
import json
import random
import re
import sys
import sysconfig
import time


def t(name, fn, n=5):
    best = min(_one(fn) for _ in range(n))
    print(f"[bench] {sys.version_info[0]}.{sys.version_info[1]} {name:<22} {best*1000:9.1f} ms", flush=True)


def _one(fn):
    s = time.perf_counter()
    fn()
    return time.perf_counter() - s


def loop():
    x = 0
    for i in range(3_000_000):
        x += i * 2 % 7
    return x


def dicts():
    d = {}
    for i in range(400_000):
        d[f"k{i}"] = i
    return sum(d[f"k{i}"] for i in range(400_000))


def fib(n=27):
    return n if n < 2 else fib(n - 1) + fib(n - 2)


class P:
    __slots__ = ("a", "b")

    def __init__(self, a, b):
        self.a, self.b = a, b

    def m(self):
        return self.a + self.b


def objs():
    return sum(P(i, i).m() for i in range(600_000))


rnd = random.Random(7)
doc = [{"id": i, "v": rnd.random(), "s": "x" * (i % 40), "l": list(range(i % 9))} for i in range(30_000)]


def jsn():
    json.loads(json.dumps(doc))


text = "".join(rnd.choice("abc def/.-_") for _ in range(400_000))
rx = re.compile(r"(?:[a-c]+/)+[d-f]+\.[a-z_-]+")


def regex():
    return len(rx.findall(text))


def canon():
    from tracekit.format.canon import canonical
    for v in doc[:8000]:
        canonical(v)


def fresh_and_build():
    print("[bench] version", sys.version.replace("\n", " "))
    print("[bench] flags", sys.flags)
    print("[bench] CONFIG_ARGS", sysconfig.get_config_var("CONFIG_ARGS"))
    print("[bench] PY_CFLAGS_NODIST", sysconfig.get_config_var("PY_CFLAGS_NODIST"))
    print("[bench] executable", sys.executable)


if __name__ == "__main__":
    fresh_and_build()
    for name, fn in [("loop", loop), ("dicts", dicts), ("fib(27)", fib), ("objects", objs), ("json", jsn),
                     ("regex", regex), ("tracekit canonical", canon)]:
        t(name, fn)
