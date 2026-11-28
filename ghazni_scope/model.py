"""Turns the decoded stream into what the viewer shows.

Times are seconds since the first event seen (float). Segments are
(cpu, task_id, start, end) for running, and (task_id, start, end) for
the time a task was ready but not yet running (its wake-up latency).

An instance of a task (Tracealyzer's "actor instance") runs from the
moment it becomes ready (or first runs) until it blocks again; its
execution time is the CPU time inside, its response time start to end.
Stream v2 also says who calls and signals whom (communication flow),
carries user events, and names endpoints and notifications.
"""
import collections
import threading

from .protocol import TEV, IDLE, NONE, STATES, TSTR_FIRST, TSTR_STATE, HEAP_ADDR

BLOCKING = {3, 4, 5, 6, 7, 8, 9, 10}     # TS_*: the task stopped of its own accord (or died)
EVENTS_KEPT = 200000

KEEP_S = 120.0          # history kept for late browsers and export
EVENTS_SENT = 60000     # raw events in one snapshot (the browser keeps its own history)


# what each trigger measures (English; the page shows its own language from the kind)
TRIGGER_KINDS = {
    "resp": "response time", "exec": "execution time", "lat": "wake-up latency", "isr": "interrupt time",
    "user": "user value", "state": "state entered", "fault": "fault", "throttle": "throttle", "heap": "heap warning",
}
_UNITS = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6}


def parse_trigger(text):
    """'resp pong >5ms', 'exec * >1ms', 'lat shell >2ms', 'isr timer >500us',
    'user 7 >1000', 'user 7 <10', 'state 1 BRAKE', 'fault', 'throttle hog_demo', 'heap'
    -> dict, or raise ValueError with a reason."""
    w = text.split()
    if not w or w[0] not in TRIGGER_KINDS:
        raise ValueError("kind must be one of " + ", ".join(TRIGGER_KINDS))
    k, who = w[0], (w[1] if len(w) > 1 else "*")
    tr = {"kind": k, "who": who, "text": " ".join(w)}
    if k in ("fault", "throttle", "heap"):
        return tr
    if k == "state":
        if len(w) < 3:
            raise ValueError("state <machine number> <state name>")
        tr["value"] = w[2]
        return tr
    if len(w) < 3 or w[2][0] not in "<>":
        raise ValueError(f"{k} <{'channel' if k == 'user' else 'task or interrupt name, or *'}> >value (e.g. >5ms)")
    tr["op"], v = w[2][0], w[2][1:].strip()
    if k == "user":
        tr["value"] = float(v)
    else:
        for u in ("ms", "us", "µs", "s"):
            if v.endswith(u):
                tr["value"] = float(v[:-len(u)]) * _UNITS[u]
                break
        else:
            raise ValueError("put a unit on times: s, ms, us")
    return tr


class Model:
    def __init__(self):
        self.lock = threading.Lock()
        self.hz = 0
        self.ncpus = 1
        self.tasks = {}                 # id -> {"name", "prio"}
        self.t0 = None                  # first tick
        self.now = 0.0                  # latest event time (s)
        self.running = {}               # cpu -> (task, start)
        self.ready_since = {}           # task -> time it became ready
        self.segments = collections.deque()     # (cpu, task, s, e)
        self.ready = collections.deque()        # (task, s, e)
        self.marks = collections.deque()        # (t, kind, cpu, task, arg)
        self.console = collections.deque(maxlen=500)   # (line number, text)
        self.console_n = 0
        self.events_total = 0
        self.lost_total = 0
        self.frames = 0
        self.seq_next = None
        self.gaps = 0
        self.stats = {}                 # id -> latest stats dict
        self.load = collections.deque(maxlen=1200)   # (t, {id: percent}) every 100 ms
        self._prev_stats = None
        self.per_task = collections.defaultdict(lambda: {
            "runs": 0, "run_s": 0.0, "max_run_s": 0.0, "max_lat_s": 0.0,
            "lat_sum_s": 0.0, "lat_n": 0, "irqs": 0, "throttles": 0, "faults": 0,
            "timeouts": 0, "boosts": 0})
        self.rate = collections.deque(maxlen=50)     # (t, switches, irqs) per stats tick
        self._sw = self._irq = 0
        self.objects = {"endpoints": [], "notifications": []}
        self.events = collections.deque(maxlen=EVENTS_KEPT)  # (t, kind, cpu, a, b, arg)
        self.inst_open = {}             # task -> [start, exec_s, cpu of last run start]
        self.instances = collections.deque(maxlen=50000)     # (task, start, end, exec, resp)
        self.inst_stats = {}            # task -> [n, exec sum, min, max, resp sum, min, max]
        self.comm = collections.Counter()   # (src, kind, dst) -> count
        self.users = collections.deque(maxlen=20000)         # (t, task, channel, value)
        self.texts = collections.deque(maxlen=20000)         # (t, task, channel, text)
        self.states = collections.deque(maxlen=20000)        # (t, task, machine, state)
        self.heap = collections.deque(maxlen=50000)          # (t, task, op, size, addr, used after)
        self.heap_used = collections.Counter()               # task -> bytes now
        self.heap_peak = collections.Counter()
        self.heap_live = {}                                  # addr -> (t, size, task that allocated it)
        self.heap_warn = collections.deque(maxlen=200)       # (t, kind, task, addr, size)
        self.isr = collections.deque(maxlen=50000)           # (start, cpu, irq id, duration): v3
        self.isr_stats = {}                                  # irq id -> [n, sum, max]
        self._irq_open = {}                                  # cpu -> (start, irq id)
        self.prios = collections.deque(maxlen=20000)         # (t, task, new prio, old prio): v3
        # 0.20: what tasks wait on, who holds which mutex, who serves whom, semaphore counts
        self.blocked = collections.deque(maxlen=100000)      # (task, start, end, state, kind, object)
        self._block_open = {}                                # task -> (start, state, kind, object)
        self.holds = collections.deque(maxlen=50000)         # (ntfn, holder, start, end)
        self._hold_open = {}                                 # ntfn -> (holder, start)
        self.serves = collections.deque(maxlen=50000)        # (endpoint, server, client, start, end)
        self._serve_open = {}                                # server -> (endpoint, client, start)
        self.semcount = collections.deque(maxlen=50000)      # (t, ntfn, count after)
        self.triggers = []                                   # parse_trigger() dicts + id, hits
        self.trig_hits = collections.deque(maxlen=1000)      # (t, trigger id, what happened)
        self._trig_id = 0
        self.uptime = 0.0                                    # target seconds since boot (stats frames)
        self.scope_us = 0                                    # us the driver spent sending the stream (total)
        self.scope_pct = 0.0                                 # ... in the last stats period
        self._scope_prev = None
        self._str = {}                                       # (task, channel) -> [t, bytes]
        self._heap_half = {}                                 # (task, cpu) -> (op, size) waiting for its address
        self.pending_call = {}                               # client -> (t, server or None)
        self.deps = {}                                       # (client, server, kind) -> [n, wait sum, wait max]
        self.connected = False
        self.streaming = False
        self.version = 0                # bumped on every change

    # -------------------------------------------------------------- input
    def text(self, line):
        with self.lock:
            self.console_n += 1
            self.console.append((self.console_n, line))
            self.version += 1

    def frame(self, f):
        with self.lock:
            self.frames += 1
            k = f["kind"]
            if k == "hello" and f.get("repeat") and self.streaming and self.hz == f["hz"]:
                # the same stream, said again (UDP): names only, keep the history
                self.tasks = {t["id"]: {"name": t["name"], "prio": t["prio"]} for t in f["tasks"]}
            elif k == "hello":
                self._reset()
                self.hz = f["hz"]
                self.os = f.get("os", "Ghazni")
                self.ncpus = max(1, f["ncpus"])
                self.tasks = {t["id"]: {"name": t["name"], "prio": t["prio"]} for t in f["tasks"]}
                self.streaming = True
            elif k == "events" and self.hz:
                if self.seq_next is not None and f["first"] != self.seq_next and f["first"] > self.seq_next:
                    self.gaps += 1
                self.lost_total += f["lost"]
                for ev in f["events"]:
                    self._event(*ev)
                self.seq_next = f["first"] + len(f["events"])
                self._trim()
            elif k == "objects":
                self.objects = {"endpoints": f["endpoints"], "notifications": f["notifications"],
                                "irqs": {str(k): v for k, v in f.get("irqs", {}).items()},
                                "ntfn_kinds": f.get("ntfn_kinds", [])}
            elif k == "stats":
                self._stats(f)
            elif k == "stopped":
                self.streaming = False
            self.version += 1

    def _reset(self):
        self.t0 = None
        self.running.clear()
        self.ready_since.clear()
        self.segments.clear()
        self.ready.clear()
        self.marks.clear()
        self.load.clear()
        self.per_task.clear()
        self.events.clear()
        self.inst_open.clear()
        self.instances.clear()
        self.inst_stats.clear()
        self.comm.clear()
        self.users.clear()
        for q in (self.texts, self.states, self.heap):
            q.clear()
        self.heap_used.clear()
        self.heap_peak.clear()
        self.heap_live.clear()
        self.heap_warn.clear()
        self.isr.clear()
        self.isr_stats.clear()
        self._irq_open.clear()
        self.prios.clear()
        for q in (self.blocked, self.holds, self.serves, self.semcount):
            q.clear()
        for d in (self._block_open, self._hold_open, self._serve_open):
            d.clear()
        self.trig_hits.clear()
        for tr in self.triggers:
            tr["hits"] = 0
        self._str.clear()
        self._heap_half.clear()
        self.pending_call.clear()
        self.deps.clear()
        self.scope_us, self.scope_pct, self._scope_prev = 0, 0.0, None
        self._prev_stats = None
        self.seq_next = None
        self.events_total = self.lost_total = self.gaps = 0

    def _t(self, tick):
        if self.t0 is None:
            self.t0 = tick
        return (tick - self.t0) / self.hz

    def _event(self, tick, typ, cpu, a, b, arg):
        t = self._t(tick)
        self.now = max(self.now, t)
        self.events_total += 1
        kind = TEV.get(typ, "?")
        if kind == "ustr":                      # pieces of a string: kept out of the log until whole
            self._ustr(t, cpu, a, b, arg)
            return
        if kind == "heap":
            self._heap_ev(t, cpu, a, b, arg)
            return
        prev = self.events[-1] if self.events else None
        self.events.append((t, kind, cpu, a, b, arg))
        # who receives a signal or an interrupt: the kernel records the wake-up
        # of the waiter (or bound server) right after it, on the same CPU
        if kind == "wake" and prev and prev[2] == cpu:
            if prev[1] == "signal":
                self.comm[(prev[4], "ntw", a)] += 1
                self._dep(prev[3], a, "signal", 0.0)
            elif prev[1] == "irq":
                self.comm[(prev[5], "irqw", a)] += 1
        if kind == "switch":
            self._sw += 1
            prev = self.running.get(cpu)
            if prev is not None:
                task, s = prev
                self.segments.append((cpu, task, s, t))
                if task not in (IDLE, NONE):
                    p = self.per_task[task]
                    p["runs"] += 1
                    p["run_s"] += t - s
                    p["max_run_s"] = max(p["max_run_s"], t - s)
                    inst = self.inst_open.get(task)
                    if inst:
                        inst[1] += t - s
                        if arg & 0xFF in BLOCKING:  # the instance ends here
                            self._close(task, t)
                if arg & 0xFF in BLOCKING and task not in (IDLE, NONE):
                    # 0.20: arg >> 8 = what it blocks on (1 endpoint, 2 notification, 3 server)
                    self._block_open[task] = (t, arg & 0xFF, (arg >> 8) & 0xFF, (arg >> 16) & 0xFF)
            self.running[cpu] = (b, t)
            self._unblock(b, t)
            if b not in (IDLE, NONE) and b not in self.inst_open:
                self.inst_open[b] = [self.ready_since.get(b, t), 0.0]
            if b in self.ready_since:
                s = self.ready_since.pop(b)
                lat = t - s
                self._check("lat", b, lat, t, s)
                self.ready.append((b, s, t))
                p = self.per_task[b]
                p["max_lat_s"] = max(p["max_lat_s"], lat)
                p["lat_sum_s"] += lat
                p["lat_n"] += 1
        elif kind == "wake":
            self._unblock(a, t)
            self.ready_since.setdefault(a, t)
            if a not in self.inst_open:
                self.inst_open[a] = [t, 0.0]
        elif kind in ("call", "send"):
            self.comm[(a, "ep", arg & 0xFF)] += 1
            if b not in (IDLE, NONE):
                self.comm[(arg & 0xFF, "srv", b)] += 1
            if kind == "call":
                self.pending_call[a] = t
                if b not in (IDLE, NONE):       # delivered: the server works for a from now
                    self._serve_open[b] = (arg & 0xFF, a, t)
            elif b not in (IDLE, NONE):
                self._dep(a, b, "send", 0.0)
        elif kind == "recv":
            self.comm[(arg & 0xFF, "srv", a)] += 1
            if b in self.pending_call:          # a queued CALL: served from now
                self._serve_open[a] = (arg & 0xFF, b, t)
        elif kind == "signal":
            if a == NONE and cpu in self._irq_open:     # given from an interrupt handler
                self.comm[(self._irq_open[cpu][1], "isig", b)] += 1
            else:
                self.comm[(a, "ntfn", b)] += 1
            k = self._ntfn_kind(b)
            if k == "mutex":                    # unlock: the holder's time ends
                o = self._hold_open.pop(b, None)
                if o:
                    self.holds.append((b, o[0], o[1], t))
            elif k in ("semaphore", "queue"):  # count / messages waiting after it
                self.semcount.append((t, b, arg))
        elif kind == "take":                    # 0.20: got a mutex or semaphore
            if self._ntfn_kind(b) == "mutex":
                self._hold_open[b] = (a, t)
            elif self._ntfn_kind(b) in ("semaphore", "queue"):
                self.semcount.append((t, b, arg))
        elif kind == "user":
            self.users.append((t, a, b, arg))
            self._check("user", b, arg, t, t, task=a)
        elif kind == "reply":                   # the client waited from its CALL until now
            t0 = self.pending_call.pop(b, None)
            if t0 is not None:
                self._dep(b, a, "call", t - t0)
            o = self._serve_open.pop(a, None)
            if o and o[1] == b:
                self.serves.append((o[0], a, b, o[2], t))
        elif kind == "irqend":                  # v3: the kernel's handler time
            o = self._irq_open.pop(cpu, None)
            if o and o[1] == arg:
                d = t - o[0]
                self.isr.append((o[0], cpu, arg, d))
                self._check("isr", arg, d, t, o[0])
                s = self.isr_stats.setdefault(arg, [0, 0.0, 0.0])
                s[0] += 1
                s[1] += d
                s[2] = max(s[2], d)
        elif kind == "prio":                    # v3: priority inheritance
            self.prios.append((t, a, b, arg))
            if b > arg:
                self.per_task[a]["boosts"] += 1
        else:
            if kind == "irq":
                self._irq += 1
                self.per_task[a]["irqs"] += 1
                self._irq_open[cpu] = (t, arg)
            elif kind == "throttle":
                self.per_task[a]["throttles"] += 1
            elif kind == "fault":
                self.per_task[a]["faults"] += 1
            elif kind == "timeout":
                self.per_task[a]["timeouts"] += 1
            if kind in ("fault", "throttle"):
                self._check(kind, a, 0, t, t)
            self.marks.append((t, kind, cpu, a, arg))

    def _ntfn_kind(self, n):
        k = self.objects.get("ntfn_kinds") or []
        return k[n] if n < len(k) else "event"

    def _unblock(self, task, t):
        o = self._block_open.pop(task, None)
        if o:
            self.blocked.append((task, o[0], t, o[1], o[2], o[3]))

    def _dep(self, src, dst, kind, wait):
        if src in (IDLE, NONE) or dst in (IDLE, NONE):
            return
        d = self.deps.get((src, dst, kind))
        if d is None:
            self.deps[(src, dst, kind)] = [1, wait, wait]
        else:
            d[0] += 1
            d[1] += wait
            d[2] = max(d[2], wait)

    def _ustr(self, t, cpu, task, b, arg):
        key = (task, b & 0x3F | (b & TSTR_STATE))
        if b & TSTR_FIRST or key not in self._str:
            self._str[key] = [t, bytearray()]
        buf = self._str[key][1]
        for k in range(4):
            c = (arg >> (8 * k)) & 0xFF
            if c == 0:
                t0, data = self._str.pop(key)
                text = data.decode(errors="replace")
                ch = b & 0x3F
                if b & TSTR_STATE:
                    self.states.append((t0, task, ch, text))
                    self._check("state", ch, text, t0, t0, task=task)
                    self.events.append((t0, "state", cpu, task, ch, text))
                else:
                    self.texts.append((t0, task, ch, text))
                    self.events.append((t0, "print", cpu, task, ch, text))
                return
            buf.append(c)
        if len(buf) > 4096:                     # a lost end: do not grow for ever
            self._str.pop(key, None)

    def _heap_ev(self, t, cpu, task, b, arg):
        op = b & ~HEAP_ADDR & 0xFF
        if not b & HEAP_ADDR:
            self._heap_half[(task, cpu)] = (op, arg)   # per CPU: both idle tasks are IDLE
            return
        half = self._heap_half.pop((task, cpu), None)
        if not half or half[0] != op:
            return
        size, addr = half[1], arg
        if op == 0:
            old = self.heap_live.get(addr)
            if old:                         # still allocated: a lost free, or an allocator bug
                self.heap_warn.append((t, "double", task, addr, size))
                self._check("heap", task, 0, t, t)
                self.heap_used[old[2]] -= old[1]
                if old[2] != task:
                    self.heap.append((t, old[2], 1, old[1], addr, self.heap_used[old[2]]))
            self.heap_used[task] += size
            self.heap_peak[task] = max(self.heap_peak[task], self.heap_used[task])
            self.heap_live[addr] = (t, size, task)
        else:
            old = self.heap_live.pop(addr, None)
            if old is None:                 # allocated before the trace started, or a double free
                self.heap_warn.append((t, "unknown", task, addr, size))
                self._check("heap", task, 0, t, t)
                self.events.append((t, "heap", cpu, task, op, size))
                return
            if not size:                    # a free without its size (ESP-IDF's hook): the block's
                size = old[1]
            owner = old[2]                  # the block counts against the task that allocated it
            self.heap_used[owner] -= old[1]
            if owner != task:
                self.heap.append((t, owner, op, old[1], addr, self.heap_used[owner]))
                self.events.append((t, "heap", cpu, task, op, size))
                return
        self.heap.append((t, task, op, size, addr, self.heap_used[task]))
        self.events.append((t, "heap", cpu, task, op, size))

    # ------------------------------------------------------------- triggers
    def add_trigger(self, text):
        tr = parse_trigger(text)
        with self.lock:
            same = next((x for x in self.triggers if x["text"] == tr["text"]), None)
            if same:                        # the same condition twice: one trigger
                return same
            self._trig_id += 1
            tr.update(id=self._trig_id, hits=0)
            self.triggers.append(tr)
        return tr

    def del_trigger(self, tid):
        with self.lock:
            self.triggers = [x for x in self.triggers if x["id"] != tid]

    def _name(self, task):
        return "idle" if task == IDLE else self.tasks.get(task, {}).get("name", f"task{task}")

    def _check(self, kind, who, value, t, start, task=None):
        """who: task id (resp/exec/lat/fault/throttle/heap), irq id (isr),
        channel (user), machine (state)."""
        for tr in self.triggers:
            if tr["kind"] != kind:
                continue
            w = tr["who"]
            if kind == "isr":
                name = self.objects.get("irqs", {}).get(str(who), "")
                if w != "*" and w != str(who) and w != name:
                    continue
                label = f"IRQ {who} {name}".strip()
            elif kind in ("user", "state"):
                if w != "*" and w != str(who):
                    continue
                label = f"{self._name(task)} {'ch' if kind == 'user' else 'machine '}{who}"
            else:
                if w != "*" and w != self._name(who):
                    continue
                label = self._name(who)
            if kind == "state":
                if value != tr["value"]:
                    continue
                val = f"→ {value}"
            elif "op" in tr:
                v = value
                if not (v > tr["value"] if tr["op"] == ">" else v < tr["value"]):
                    continue
                val = f"{int(v)}" if kind == "user" else f"{v * 1e3:.3f} ms"
            else:
                val = ""
            what = f"{label} {val}" if kind == "state" else f"{label} {TRIGGER_KINDS[kind]} {val}".rstrip()
            tr["hits"] += 1
            self.trig_hits.append((start, tr["id"], what, kind, label, val))

    def _close(self, task, t):
        start, ex = self.inst_open.pop(task)
        resp = t - start
        self._check("exec", task, ex, t, start)
        self._check("resp", task, resp, t, start)
        self.instances.append((task, start, t, ex, resp))
        s = self.inst_stats.get(task)
        if s is None:
            self.inst_stats[task] = [1, ex, ex, ex, resp, resp, resp]
        else:
            s[0] += 1
            s[1] += ex
            s[2] = min(s[2], ex)
            s[3] = max(s[3], ex)
            s[4] += resp
            s[5] = min(s[5], resp)
            s[6] = max(s[6], resp)

    def _stats(self, f):
        up = f["uptime_us"] / 1e6
        self.uptime = up
        su = f.get("scope_us", 0)
        if self._scope_prev is not None:
            d = (su - self._scope_prev[1]) & 0xFFFFFFFF
            dt = up - self._scope_prev[0]
            if 0 < dt and d < dt * 1e6 * 4:   # a restarted target: ignore the jump
                self.scope_us += d
                self.scope_pct = d / 1e4 / dt
        self._scope_prev = (up, su)
        cur = {t["id"]: t for t in f["tasks"]}
        self.stats = cur
        if self._prev_stats is not None:
            pup, prev = self._prev_stats
            dt = up - pup
            if dt > 0:
                load = {}
                for tid, st in cur.items():
                    if tid in prev:
                        load[tid] = max(0.0, (st["cpu_us"] - prev[tid]["cpu_us"]) / 1e6 / dt * 100)
                self.load.append((self.now, load))
                self.rate.append((self.now, self._sw / dt, self._irq / dt))
        self._sw = self._irq = 0
        self._prev_stats = (up, cur)

    def _trim(self):
        lim = self.now - KEEP_S
        for q, idx in ((self.segments, 3), (self.ready, 2), (self.marks, 0), (self.events, 0),
                       (self.instances, 2), (self.users, 0), (self.texts, 0), (self.states, 0),
                       (self.heap, 0), (self.isr, 0), (self.prios, 0), (self.blocked, 2),
                       (self.holds, 3), (self.serves, 4), (self.semcount, 0)):
            while q and q[0][idx] < lim:
                q.popleft()

    # ------------------------------------------------------------- output
    def console_after(self, n):
        with self.lock:
            return [l for k, l in self.console if k > n], self.console_n

    def snapshot(self, since=None):
        """Everything (since=None) or only what ended after `since` seconds."""
        with self.lock:
            cut = -1e9 if since is None else since
            segs = [s for s in self.segments if s[3] > cut]
            # still running: open segments up to now
            open_segs = [(cpu, task, s, self.now) for cpu, (task, s) in self.running.items()]
            rdy = [r for r in self.ready if r[2] > cut]
            open_rdy = [(task, s, self.now) for task, s in self.ready_since.items()]
            marks = [m for m in self.marks if m[0] > cut]
            loads = [(t, l) for t, l in self.load if t > cut]
            table = []
            for tid, info in sorted(self.tasks.items()):
                p = self.per_task.get(tid)
                st = self.stats.get(tid, {})
                last = self.load[-1][1].get(tid, 0.0) if self.load else 0.0
                table.append({
                    "id": tid, "name": info["name"], "prio": st.get("prio", info["prio"]),
                    "base_prio": info["prio"], "state": st.get("state", "?"),
                    "cpu_pct": round(last, 1), "cpu_ms": round(st.get("cpu_us", 0) / 1000),
                    "cpu_avg_pct": round(st.get("cpu_us", 0) / 1e4 / self.uptime, 1) if self.uptime else 0,
                    "kern_ms": round(st.get("kern_us", 0) / 1000, 3),
                    "kern_pct": round(st.get("kern_us", 0) / st["cpu_us"] * 100, 1) if st.get("cpu_us") else 0,
                    "boosts": p["boosts"] if p else 0,
                    "runs": p["runs"] if p else 0,
                    "max_run_ms": round(p["max_run_s"] * 1000, 3) if p else 0,
                    "max_lat_ms": round(p["max_lat_s"] * 1000, 3) if p else 0,
                    "avg_lat_ms": round(p["lat_sum_s"] / p["lat_n"] * 1000, 3) if p and p["lat_n"] else 0,
                    "irqs": p["irqs"] if p else 0,
                    "throttles": st.get("throttles", 0),
                    "stack": [st.get("stack_used", 0), st.get("stack_size", 0)],
                    "instances": self._inst_row(tid),
                })
            rate = self.rate[-1] if self.rate else (0, 0, 0)
            return {
                "now": self.now, "hz": self.hz, "ncpus": self.ncpus, "os": getattr(self, "os", "Ghazni"),
                "tasks": {str(k): v for k, v in self.tasks.items()},
                "segments": segs, "open": open_segs, "ready": rdy, "open_ready": open_rdy,
                "marks": marks, "load": loads, "table": table,
                "console": [l for _, l in list(self.console)[-200:]],
                "console_n": self.console_n,
                "counters": {"events": self.events_total, "lost": self.lost_total,
                             "gaps": self.gaps, "frames": self.frames,
                             "udp_rejected": getattr(self, "udp_rejected", 0),
                             "switch_per_s": round(rate[1]), "irq_per_s": round(rate[2])},
                "connected": self.connected, "streaming": self.streaming,
                "objects": self.objects,
                "events": list(self.events)[-EVENTS_SENT:] if since is None
                else [e for e in self.events if e[0] > cut][-EVENTS_SENT:],
                "instances": [i for i in self.instances if i[2] > cut][-20000:],
                "comm": [[s, k, d, n] for (s, k, d), n in self.comm.items()],
                "users": [u for u in self.users if u[0] > cut],
                "texts": [x for x in self.texts if x[0] > cut],
                "states": [x for x in self.states if x[0] > cut],
                "heap": [x for x in self.heap if x[0] > cut][-20000:],
                "heap_now": {str(k): [v, self.heap_peak[k]] for k, v in self.heap_used.items()},
                "heap_live": [[v[2], a, v[0], v[1]] for a, v in list(self.heap_live.items())[-500:]],
                "heap_warn": list(self.heap_warn),
                "isr": [x for x in self.isr if x[0] + x[3] > cut][-20000:],
                "isr_stats": [[k, v[0], round(v[1], 9), round(v[2], 9)] for k, v in sorted(self.isr_stats.items())],
                "prios": [x for x in self.prios if x[0] > cut],
                "blocked": [x for x in self.blocked if x[2] > cut][-40000:],
                "open_blocked": [[k, v[0], self.now, v[1], v[2], v[3]] for k, v in self._block_open.items()],
                "holds": [x for x in self.holds if x[3] > cut],
                "open_holds": [[k, v[0], v[1], self.now] for k, v in self._hold_open.items()],
                "serves": [x for x in self.serves if x[4] > cut][-20000:],
                "open_serves": [[v[0], k, v[1], v[2], self.now] for k, v in self._serve_open.items()],
                "semcount": [x for x in self.semcount if x[0] > cut],
                "triggers": [{"id": x["id"], "text": x["text"], "hits": x["hits"]} for x in self.triggers],
                "trig_hits": list(self.trig_hits)[-200:],
                "scope": {"us": self.scope_us, "pct": round(self.scope_pct, 1),
                          "avg_pct": round(self.scope_us / 1e4 / self.uptime, 2) if self.uptime else 0},
                "deps": [[s, d, k, v[0], round(v[1], 6), round(v[2], 6)] for (s, d, k), v in self.deps.items()],
            }

    def _inst_row(self, tid):
        s = self.inst_stats.get(tid)
        if not s:
            return None
        ms = lambda v: round(v * 1000, 4)
        return {"n": s[0], "exec_avg": ms(s[1] / s[0]), "exec_min": ms(s[2]), "exec_max": ms(s[3]),
                "resp_avg": ms(s[4] / s[0]), "resp_min": ms(s[5]), "resp_max": ms(s[6])}

    def perfetto(self):
        """Chrome trace format (open in https://ui.perfetto.dev)."""
        with self.lock:
            name = lambda t: "idle" if t == IDLE else self.tasks.get(t, {}).get("name", f"task{t}")
            out = [{"ph": "M", "name": "process_name", "pid": 1, "args": {"name": getattr(self, "os", "Ghazni")}}]
            for c in range(self.ncpus):
                out.append({"ph": "M", "name": "thread_name", "pid": 1, "tid": c,
                            "args": {"name": f"CPU {c}"}})
            for cpu, task, s, e in self.segments:
                if task in (IDLE, NONE):
                    continue
                out.append({"ph": "X", "pid": 1, "tid": cpu, "name": name(task),
                            "ts": s * 1e6, "dur": (e - s) * 1e6})
            for t, kind, cpu, a, arg in self.marks:
                out.append({"ph": "i", "pid": 1, "tid": cpu, "s": "t", "ts": t * 1e6,
                            "name": f"{kind} {name(a)}" + (f" {arg}" if kind == "irq" else "")})
            return {"traceEvents": out, "displayTimeUnit": "ms"}
