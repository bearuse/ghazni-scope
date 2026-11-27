#!/usr/bin/env python3
"""FreeRTOS end to end: build the demo (examples/common/demo.c) for a
target, run it, read its stream with host/ghazni_scope.py --check and
check what the Scope saw.

    tests/run_freertos.py posix     FreeRTOS on Linux (POSIX port)
    tests/run_freertos.py mps2      FreeRTOS on Cortex-M3 in QEMU (mps2-an385)
    tests/run_freertos.py           both (mps2 skipped without clang/QEMU)
"""
import json, os, shutil, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOPE = os.path.join(ROOT, "host", "ghazni_scope.py")
QEMU = os.environ.get("QEMU_ARM", "qemu-system-arm")
fails = 0


def check(name, ok, detail=""):
    global fails
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f": {str(detail)[:400]}"))
    fails += not ok


def scope(cmd, secs):
    """Run the target program under the host tool; returns its summary."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "s.json")
        env = dict(os.environ, SCOPE_JSON=out)
        r = subprocess.run([sys.executable, SCOPE, "--exec", cmd, "--check", str(secs), "--quiet"],
                           env=env, capture_output=True, text=True, timeout=secs + 90)
        print("   ", r.stdout.splitlines()[0] if r.stdout else r.stderr[-300:])
        if r.returncode != 0 or not os.path.exists(out):
            return None
        return json.load(open(out))


def verify(s, target):
    if not s:
        check(f"{target}: the stream started", False, "no summary")
        return
    names = {v["name"]: int(k) for k, v in s["tasks"].items()}
    c = s["counters"]
    check(f"{target}: stream from FreeRTOS, events and no loss",
          s["os"] == "FreeRTOS" and c["events"] > 2000 and c["lost"] == 0 and c["gaps"] == 0, (s["os"], c))
    check(f"{target}: all demo tasks named (idle task hidden as the CPU's idle)",
          {"producer", "consumer", "low", "mid", "high", "controller", "worker", "isr_handler", "tracer"} <= set(names)
          and not any(n.startswith("IDLE") for n in names), sorted(names))
    o = s["objects"]
    kinds = dict(zip(o["notifications"], o["ntfn_kinds"]))
    check(f"{target}: objects with names and kinds",
          kinds == {"samples": "queue", "bus_lock": "mutex", "done": "semaphore", "isr_sem": "semaphore",
                    "flags": "event group"}, kinds)
    obj = {n: i for i, n in enumerate(o["notifications"])}
    blk = s["blocked"] + [x[:6] for x in s["open_blocked"]]
    def blocked_on(task, name, state):
        return any(b[0] == names[task] and b[4] == 2 and b[5] == obj[name] and b[3] == state for b in blk)
    check(f"{target}: blocking reasons: consumer on the queue, high on the mutex, worker on the event group, "
          "isr_handler on its semaphore",
          blocked_on("consumer", "samples", 4) and blocked_on("high", "bus_lock", 4)
          and blocked_on("worker", "flags", 6) and blocked_on("isr_handler", "isr_sem", 4),
          [b for b in blk if b[4]][:12])
    check(f"{target}: delays seen as sleep", any(b[3] == 7 and b[0] == names["producer"] for b in blk), blk[:5])
    holds = [h for h in s["holds"] if h[0] == obj["bus_lock"]]
    check(f"{target}: mutex holders: low for ~30 ms, high briefly",
          any(h[1] == names["low"] and 0.02 < h[3] - h[2] < 0.06 for h in holds)
          and any(h[1] == names["high"] for h in holds), holds[:6])
    pr = [tuple(p[1:]) for p in s["prios"]]
    check(f"{target}: priority inheritance every cycle: low 1 -> 5 and back to 1",
          pr.count((names["low"], 5, 1)) >= 4 and pr.count((names["low"], 1, 5)) >= 4, pr[:6])
    q = [x[2] for x in s["semcount"] if x[1] == obj["samples"]]
    check(f"{target}: queue fill level rises and falls", q and max(q) >= 2 and min(q) == 0, q[:20])
    check(f"{target}: semaphore counts", any(x[1] == obj["done"] for x in s["semcount"])
          and any(x[1] == obj["isr_sem"] for x in s["semcount"]), s["semcount"][:6])
    isr = {x[0]: x for x in s["isr_stats"]}
    check(f"{target}: interrupt 'tick20' every 20 ms with its handler time",
          o["irqs"].get("1") == "tick20" and 1 in isr and isr[1][1] >= 40 * s["now"] / 3 / 1.5,
          (o["irqs"], s["isr_stats"], s["now"]))
    comm = {(x[0], x[1], x[2]): x[3] for x in s["comm"]}
    check(f"{target}: communication flow: producer -> queue -> consumer, interrupt tick20 -> isr_sem -> isr_handler",
          comm.get((names["producer"], "ntfn", obj["samples"]), 0) > 100
          and comm.get((obj["samples"], "ntw", names["consumer"]), 0) > 10
          and comm.get((1, "isig", obj["isr_sem"]), 0) > 20
          and comm.get((obj["isr_sem"], "ntw", names["isr_handler"]), 0) > 20, s["comm"])
    texts = [t[3] for t in s["texts"]]
    check(f"{target}: printf text, state machine, user values",
          any(t.startswith("sample ") and t.endswith(" processed") for t in texts)
          and any("waited" in t for t in texts)
          and {x[3] for x in s["states"]} >= {"IDLE", "MEASURE", "SEND"} and len(s["users"]) > 10,
          (texts[:3], s["states"][:3]))
    hp = s["heap_now"].get(str(names["consumer"]))
    check(f"{target}: heap: consumer's allocations seen, no warnings",
          hp and hp[1] > 0 and not s["heap_warn"], (hp, s["heap_warn"][:3]))
    tab = {r["name"]: r for r in s["table"]}
    check(f"{target}: statistics: CPU time and stack use per task",
          tab["low"]["cpu_ms"] > 0 and tab["consumer"]["stack"][0] > 0
          and tab["consumer"]["stack"][1] >= tab["consumer"]["stack"][0], {k: (v["cpu_ms"], v["stack"]) for k, v in tab.items()})
    check(f"{target}: wake-ups and run segments", len(s["segments"]) > 1000 and s["counters"]["switch_per_s"] > 100,
          (len(s["segments"]), c))


def live_stream(cmd, secs):
    """The browser's view of the stream: the full snapshot plus the live deltas
    -> (events, run segments) as the page would hold them, and a full snapshot after."""
    import socket, urllib.request
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    tool = subprocess.Popen([sys.executable, SCOPE, "--exec", cmd, "--port", str(port), "--quiet"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    events, segs = [], []
    try:
        end = time.time() + secs + 10
        while time.time() < end:
            try:
                r = urllib.request.urlopen(f"http://127.0.0.1:{port}/stream", timeout=5)
                break
            except OSError:
                time.sleep(0.3)
        t_end = time.time() + secs
        data = b""
        for line in r:
            if line.startswith(b"data: "):
                d = json.loads(line[6:])
                events += [tuple(e) for e in d.get("events", [])]
                segs += [tuple(x) for x in d.get("segments", [])]
            if time.time() > t_end:
                break
        r.close()
        snap = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/snapshot", timeout=10))
    finally:
        tool.kill()
        tool.wait()
    return events, segs, snap


def make(d, *args):
    r = subprocess.run(["make", "-s", "-C", os.path.join(ROOT, "examples", d), *args], capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-2000:])
    return r.returncode == 0


targets = sys.argv[1:] or ["posix", "mps2"]
if "posix" in targets:
    print("=== FreeRTOS on Linux (POSIX port) ===")
    if make("freertos-posix"):
        exe = os.path.join(ROOT, "examples", "freertos-posix", "build", "demo")
        verify(scope(f"env SCOPE_RUN_S=8 {exe}", 3), "posix")
        ev, sg, snap = live_stream(exe, 4)
        import collections
        t1 = max(e[0] for e in ev) - 0.05            # what both have for sure
        live = collections.Counter(e for e in ev if e[0] <= t1)
        model = collections.Counter(tuple(e) for e in snap["events"] if e[0] <= t1)
        segs = collections.Counter(x for x in sg if x[3] <= t1)
        smodel = collections.Counter(tuple(x) for x in snap["segments"] if x[3] <= t1)
        check("posix: live view (snapshot + deltas) holds exactly what the tool has: no item twice, none missing",
              len(ev) > 2000 and live == model and segs == smodel,
              (len(ev), sum((live - model).values()), sum((model - live).values()),
               sum((segs - smodel).values()), sum((smodel - segs).values())))
    else:
        check("posix: build", False)
if "mps2" in targets:
    print("=== FreeRTOS on Cortex-M3 (QEMU mps2-an385) ===")
    if not shutil.which(QEMU) or not shutil.which("clang") or not shutil.which("ld.lld"):
        print("  [SKIP] needs qemu-system-arm, clang and ld.lld")
        if sys.argv[1:]:
            fails += 1
    elif make("freertos-mps2"):
        elf = os.path.join(ROOT, "examples", "freertos-mps2", "build", "demo.elf")
        verify(scope(f"{QEMU} -M mps2-an385 -display none -monitor none -serial stdio -kernel {elf}", 4), "mps2")
    else:
        check("mps2: build", False)
print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
