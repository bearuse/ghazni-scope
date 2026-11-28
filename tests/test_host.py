#!/usr/bin/env python3
"""Host side unit tests: the frame decoder (protocol.py) and the model
(model.py) on hand-made frames, no target needed."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0


def check(name, ok, detail=""):
    global fails
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f": {detail}"))
    fails += not ok


print("=== scope decoder: lost and repeated hello ===")
# the package from this checkout, or (SCOPE_INSTALLED=1) the installed one
if not os.environ.get("SCOPE_INSTALLED"):
    sys.path.insert(0, ROOT)
import ghazni_scope                                        # noqa: E402
from ghazni_scope.model import Model                       # noqa: E402
print(f"    ghazni_scope {ghazni_scope.__version__} from {os.path.dirname(ghazni_scope.__file__)}")
TASKS = [{"id": 0, "prio": 1, "name": "a"}, {"id": 1, "prio": 2, "name": "b"}]
HELLO = {"kind": "hello", "version": 1, "ncpus": 1, "hz": 1000000, "tasks": TASKS}
def ev(first):
    return {"kind": "events", "first": first, "lost": 0,
            "events": [(1000 + first, 2, 0, 0, 0, 0), (1001 + first, 2, 0, 1, 0, 0)]}
m = Model()
m.frame(ev(0))                                  # the hello was lost
m.frame(dict(HELLO, repeat=True))               # the repeat starts the stream
m.frame(ev(2))
m.frame(dict(HELLO, repeat=True))               # repeat while streaming: nothing reset
m.frame(ev(4))
check("decoder: a repeated hello recovers a lost one and keeps the history",
      m.streaming and m.events_total == 4 and m.hz == 1000000, (m.streaming, m.events_total))
m.frame(dict(HELLO, repeat=False))              # a new stream starts from scratch
check("decoder: a new stream's hello resets", m.events_total == 0, m.events_total)

# v2 frames: 16 event types ('D'), object names ('O'); instances and the
# communication flow the model derives from them
from ghazni_scope.protocol import parse                    # noqa: E402
import struct                                              # noqa: E402
def zz(v):
    return (v << 1) ^ (v >> 63)
def vi(v):
    out = bytearray()
    while True:
        out.append((v & 0x7F) | (0x80 if v > 0x7F else 0))
        v >>= 7
        if not v:
            return bytes(out)
evs = [(1, 0, 254, 1, 0), (8, 1, 0, 2, 1 | 7 << 8), (11, 1, 2, 0, 0), (1, 0, 1, 3, 4),
       (12, 0, 0, 1, 0x4), (2, 0, 1, 0, 0), (13, 1, 1, 9, 42)]       # type, cpu, a, b, arg
raw = bytearray(b"D" + struct.pack("<QH", 0, len(evs)) + b"\0" + struct.pack("<I", 0) + struct.pack("<Q", 100))
for typ, cpu, a, b, arg in evs:
    raw += vi(zz(10)) + bytes([typ | cpu << 4, a])
    if typ in (1, 5, 8, 9, 10, 11, 12, 13):
        raw += bytes([b])
    if typ in (1, 3, 6, 8, 9, 10, 11, 12, 13):
        raw += vi(arg)
f = parse(bytes(raw))
check("decoder: v2 event frame (16 types, a, b, arg)",
      f and [e[1:] for e in f["events"]] == [(t, c, a, b, g) for t, c, a, b, g in evs], f)
o = parse(b"O\x02\x01\0" + b"serial".ljust(16, b"\0") + b"pong".ljust(16, b"\0") + b"uart".ljust(16, b"\0"))
check("decoder: object names", o == {"kind": "objects", "endpoints": ["serial", "pong"], "notifications": ["uart"], "irqs": {}, "ntfn_kinds": []}, o)
# v3: types above 15 escaped (low nibble 0, then the type), interrupt names in 'O', 32-byte task stats
raw3 = bytearray(b"D" + struct.pack("<QH", 0, 3) + b"\0" + struct.pack("<I", 0) + struct.pack("<Q", 100))
raw3 += vi(zz(0)) + bytes([3 | 1 << 4, 5]) + vi(33)                       # IRQ 33 on CPU 1, during task 5
raw3 += vi(zz(7)) + bytes([0 | 1 << 4, 16, 5]) + vi(33)                   # IRQ_END
raw3 += vi(zz(3)) + bytes([0 | 0 << 4, 17, 4, 12]) + vi(3)                # task 4: priority 3 -> 12
f3 = parse(bytes(raw3))
check("decoder v3: escaped event types (IRQ_END, PRIO)",
      f3 and [e[1:] for e in f3["events"]] == [(3, 1, 5, 0, 33), (16, 1, 5, 0, 33), (17, 0, 4, 12, 3)], f3)
o3 = parse(b"O\x01\x00\x02" + b"pong".ljust(16, b"\0") + struct.pack("<H", 33) + b"uart_rx".ljust(14, b"\0")
           + struct.pack("<H", 30) + b"timer".ljust(14, b"\0"))
check("decoder v3: interrupt names", o3 and o3["irqs"] == {33: "uart_rx", 30: "timer"}, o3)
st3 = parse(b"S" + struct.pack("<Q", 5000) + bytes([1, 32, 0]) + struct.pack("<I", 0)
            + struct.pack("<BBBBIQIIQ", 7, 1, 10, 10, 0, 900, 100, 8192, 250))
check("decoder v3: stats with kernel time", st3 and st3["tasks"][0]["kern_us"] == 250 and st3["tasks"][0]["cpu_us"] == 900, st3)
mv3 = Model()
mv3.frame(HELLO)
mv3.frame(f3)
sv3 = mv3.snapshot()
check("model v3: interrupt handler time from IRQ to IRQ_END, a priority boost",
      len(sv3["isr"]) == 1 and sv3["isr_stats"][0][:2] == [33, 1] and sv3["isr_stats"][0][3] > 0
      and sv3["prios"] and sv3["prios"][0][1:] == (4, 12, 3), (sv3["isr"], sv3["isr_stats"], sv3["prios"]))
m = Model()
m.frame(HELLO)
m.frame(o)
m.frame(f)
snap = m.snapshot()
# text pieces (TEV_USTR), a state, a heap alloc/free pair
m2 = Model()
m2.frame(HELLO)
txt = b"hello, scope! this text is longer than one piece\0"
pieces = [txt[i:i + 4].ljust(4, b"\0") for i in range(0, len(txt), 4)]
ev2 = [(1000 + k, 14, 0, 1, 3 | (0x80 if k == 0 else 0), int.from_bytes(pc, "little")) for k, pc in enumerate(pieces)]
ev2 += [(2000, 14, 0, 1, 2 | 0x40 | 0x80, int.from_bytes(b"RUN\0", "little")),
        (3000, 15, 0, 1, 0, 64), (3001, 15, 0, 1, 0x80, 0x40001000),
        (3002, 15, 0, 1, 0, 32), (3003, 15, 0, 1, 0x80, 0x40002000),
        (4000, 15, 0, 1, 1, 64), (4001, 15, 0, 1, 0x81, 0x40001000)]
m2.frame({"kind": "events", "first": 0, "lost": 0, "events": ev2})
sn = m2.snapshot()
check("model: text pieces joined, a state, heap use and the block still allocated",
      sn["texts"] and sn["texts"][0][3] == "hello, scope! this text is longer than one piece"
      and sn["states"] and sn["states"][0][2:] == (2, "RUN")
      and sn["heap_now"].get("1") == [32, 96] and sn["heap_live"] == [[1, 0x40002000, sn["heap_live"][0][2], 32]],
      (sn["texts"], sn["states"], sn["heap_now"], sn["heap_live"]))
# heap corner cases: a free by another task, an address allocated twice, a free of an unknown block
m3 = Model()
m3.frame(HELLO)
ev3 = [(100, 15, 0, 1, 0, 64), (101, 15, 0, 1, 0x80, 0x5000),      # task 1 allocates
       (200, 15, 0, 2, 1, 64), (201, 15, 0, 2, 0x81, 0x5000),      # task 2 frees it (producer/consumer)
       (300, 15, 0, 1, 0, 32), (301, 15, 0, 1, 0x80, 0x6000),
       (400, 15, 0, 1, 0, 48), (401, 15, 0, 1, 0x80, 0x6000),      # 0x6000 again, never freed
       (500, 15, 0, 1, 1, 16), (501, 15, 0, 1, 0x81, 0x7000)]      # never allocated in the trace
m3.frame({"kind": "events", "first": 0, "lost": 0, "events": ev3})
sn3 = m3.snapshot()
check("model: heap counted against the allocating task, double allocation and unknown free flagged",
      sn3["heap_now"].get("1", [0])[0] == 48 and sn3["heap_now"].get("2", [0])[0] == 0
      and [x[3] for x in sn3["heap_live"]] == [48] and [w[1] for w in sn3["heap_warn"]] == ["double", "unknown"],
      (sn3["heap_now"], sn3["heap_live"], sn3["heap_warn"]))
check("model: call, served, signal -> waiter, user event, one finished instance",
      [0, "ep", 1, 1] in snap["comm"] and [1, "srv", 2, 1] in snap["comm"] and [1, "ntw", 1, 1] in snap["comm"]
      and snap["users"] and snap["users"][0][1:] == (1, 9, 42) and len(snap["instances"]) == 1, snap["comm"])

# 0.20: blocking reasons, mutex holders, semaphore counts, who serves whom
mb = Model()
mb.frame(HELLO)
mb.frame({"kind": "objects", "endpoints": ["pong"], "notifications": ["lock", "sem"], "irqs": {},
          "ntfn_kinds": ["mutex", "semaphore"]})
# switch arg: state 6 (wait) | kind 2 (notification) << 8 | object 0 << 16
evb = [(90, 1, 0, 254, 2, 0),                     # task 2 runs
       (100, 18, 0, 1, 0, 0),                     # task 1 takes mutex 0
       (110, 1, 0, 2, 1, 6 | 2 << 8 | 0 << 16),   # task 2 blocks on it, task 1 runs
       (150, 12, 0, 1, 0, 0),                     # task 1 unlocks
       (151, 18, 0, 2, 0, 0),                     # handed to task 2
       (152, 2, 0, 2, 0, 0),                      # task 2 woken
       (160, 12, 0, 1, 1, 3),                     # task 1 gives the semaphore: count 3
       (170, 8, 0, 2, 1, 0 | 5 << 8),             # task 2 CALLs endpoint 0, delivered to task 1
       (180, 11, 0, 1, 2, 0)]                     # task 1 replies
mb.frame({"kind": "events", "first": 0, "lost": 0, "events": evb})
sb = mb.snapshot()
check("model 0.20: blocked on a mutex (and why), who held it, semaphore count, who served whom",
      [tuple(x[3:]) for x in sb["blocked"]] == [(6, 2, 0)]
      and [tuple(x[:2]) for x in sb["holds"]] == [(0, 1)] and [x[:2] for x in sb["open_holds"]] == [[0, 2]]
      and [tuple(x[1:]) for x in sb["semcount"]] == [(1, 3)] and [tuple(x[:3]) for x in sb["serves"]] == [(0, 1, 2)],
      (sb["blocked"], sb["holds"], sb["open_holds"], sb["semcount"], sb["serves"]))

# triggers: parsing, and hits from the model's own evaluation
from ghazni_scope.model import parse_trigger               # noqa: E402
bad = []
for t in ("resp pong 5ms", "resp pong >5", "nosuch x", "state 1"):
    try:
        parse_trigger(t)
        bad.append(t)
    except ValueError:
        pass
check("triggers: malformed conditions are refused with a reason", not bad, bad)
mt = Model()
mt.frame(HELLO)
for spec in ("isr * >5us", "user 9 >40", "state 2 RUN", "resp * >1ms"):
    mt.add_trigger(spec)
mt.add_trigger("user 9 >40")                               # the same again: one trigger
mt.frame(f3)                                               # IRQ 33 for 7 ticks (7 us at 1 MHz)
mt.frame(f)                                                # user event ch 9 = 42
mt.frame(m2_events := {"kind": "events", "first": 100, "lost": 0, "events": ev2})
ts = {x["text"]: x["hits"] for x in mt.snapshot()["triggers"]}
check("triggers: IRQ handler time, user value, state entered; no hit below the limit; duplicates merged",
      ts == {"isr * >5us": 1, "user 9 >40": 1, "state 2 RUN": 1, "resp * >1ms": 0}, ts)

from ghazni_scope import cli as _gs                         # noqa: E402
check("UDP stream: datagrams only from the target (others on the network dropped)",
      _gs.from_target("192.168.1.50", "192.168.1.50") and not _gs.from_target("192.168.1.50", "192.168.1.66")
      and _gs.from_target("127.0.0.1", "127.0.0.1"))


# ---- the C encoder (include/scope_encode.h) against the decoder: every
# event type, 32-bit arguments, a backward timestamp, COBS blocks
print("=== C encoder -> Python decoder ===")
import subprocess, tempfile                                # noqa: E402
from ghazni_scope.protocol import Splitter                 # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    exe = os.path.join(tmp, "encode_test")
    cc = os.environ.get("CC", "cc")
    subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", os.path.join(ROOT, "include"),
                    os.path.join(ROOT, "tests", "encode_test.c"), "-o", exe], check=True)
    out = subprocess.run([exe], capture_output=True, check=True).stdout
items = Splitter().feed(out)
frames = [parse(x) for k, x in items if k == "frame"]
texts = [x for k, x in items if k == "text"]
want = [tuple(int(v) for v in line.split()) for line in texts[1:]]
got = frames[0]["events"] if frames and frames[0] else []
check("C encoder: one frame, sequence and lost count", len(frames) == 1 and frames[0]["first"] == 42
      and frames[0]["lost"] == 7 and len(got) == 300, frames and frames[0] and (frames[0]["first"], frames[0]["lost"], len(got)))
check("C encoder: all 300 events decode to what was encoded (types 1..18)", [tuple(e) for e in got] == want,
      next(((g, w) for g, w in zip(got, want) if tuple(g) != w), None))
check("C encoder: console text between frames kept", texts[:1] == ["text between frames"], texts[:1])

# ---- FreeRTOS: the OS byte of the hello, queue and event group objects
print("=== FreeRTOS frames ===")
hf = parse(b"H" + bytes([3, 1, 1, 0, 1, 0, 0]) + struct.pack("<Q", 25000000)
           + bytes([0, 2, 0, 0]) + b"producer".ljust(16, b"\0"))
check("hello: OS byte 1 = FreeRTOS, task names", hf and hf["os"] == "FreeRTOS" and hf["tasks"][0]["name"] == "producer"
      and hf["hz"] == 25000000, hf)
of = parse(b"O\x00\x02\x00" + b"samples".ljust(16, b"\0") + b"flags".ljust(16, b"\0") + bytes([3, 4]))
check("objects: queue and event group kinds", of and of["ntfn_kinds"] == ["queue", "event group"]
      and of["notifications"] == ["samples", "flags"], of)
mf = Model()
mf.frame(dict(HELLO, os="FreeRTOS"))
mf.frame(of)
mf.frame({"kind": "events", "first": 0, "lost": 0, "events": [
    (100, 12, 0, 0, 0, 1),                   # task a sends to the queue: 1 message waiting
    (110, 12, 0, 0, 0, 2),
    (120, 18, 0, 1, 0, 1),                   # task b receives: 1 left
    (130, 1, 0, 1, 0, 4 | 2 << 8 | 0 << 16), # b blocks receiving on object 0 (the queue)
    (140, 12, 0, 0, 1, 0x3),                 # a sets bits 0x3 in the event group
]})
sf = mf.snapshot()
check("model: FreeRTOS stream, queue fill level counted (send +, receive -)",
      sf["os"] == "FreeRTOS" and [tuple(x[1:]) for x in sf["semcount"]] == [(0, 1), (0, 2), (0, 1)],
      (sf["os"], sf["semcount"]))
check("model: event group bits are not counted as a fill level",
      all(x[1] != 1 for x in sf["semcount"]), sf["semcount"])

# ---- live deltas: the 1 ms overlap is not sent twice
print("=== live view deltas ===")
gs = _gs
full = {"events": [[0.1, "wake", 0, 1, 0, 0], [0.2, "wake", 0, 2, 0, 0]], "segments": [[0, 1, 0.0, 0.2]]}
prev = gs.delta_tails(full)
d1, prev = gs.dedupe_delta({"events": [[0.2, "wake", 0, 2, 0, 0], [0.2005, "wake", 0, 3, 0, 0]],
                            "segments": [[0, 1, 0.0, 0.2], [0, 2, 0.2, 0.3]]}, prev)
d2, prev = gs.dedupe_delta({"events": [[0.2005, "wake", 0, 3, 0, 0], [0.19, "irq", 1, 0, 0, 5], [0.4, "wake", 0, 1, 0, 0]]}, prev)
d3, prev = gs.dedupe_delta({"events": [[0.4, "wake", 0, 1, 0, 0], [0.4, "wake", 0, 1, 0, 0]]}, prev)
check("live deltas: two identical events, one already sent: the other still sent",
      d3["events"] == [[0.4, "wake", 0, 1, 0, 0]], d3)
check("live deltas: items of the overlap sent once, a late item (another CPU) still sent",
      d1["events"] == [[0.2005, "wake", 0, 3, 0, 0]] and d1["segments"] == [[0, 2, 0.2, 0.3]]
      and d2["events"] == [[0.19, "irq", 1, 0, 0, 5], [0.4, "wake", 0, 1, 0, 0]], (d1, d2))

# ---- RTT through a GDB server: a fake server holding the target's memory;
# the buffer wraps (write offset behind the read offset)
print("=== RTT reader (GDB remote protocol) ===")
import socket, threading                                    # noqa: E402
from ghazni_scope.rtt import Gdb, RttReader                # noqa: E402
mem = bytearray(0x1000)
CB, NAME, DATA, SIZE = 0x100, 0x200, 0x400, 16
mem[CB:CB + 11] = b"SEGGER RTT\0"
struct.pack_into("<ii", mem, CB + 16, 1, 0)
struct.pack_into("<IIIIII", mem, CB + 24, NAME, DATA, SIZE, 3, 12, 0)     # wr 3, rd 12: wrapped
mem[NAME:NAME + 6] = b"Scope\0"
mem[DATA + 12:DATA + 16] = b"ABCD"
mem[DATA:DATA + 3] = b"EFG"
log = []
def fake_gdb(srv):
    c, _ = srv.accept()
    buf = b""
    def reply(body):
        c.sendall(b"$" + body + b"#" + b"%02x" % (sum(body) & 0xFF))
    while True:
        d = c.recv(4096)
        if not d:
            return
        buf += d
        while buf:
            if buf[:1] in (b"+", b"-"):
                buf = buf[1:]
                continue
            if buf[:1] == b"\x03":
                buf = buf[1:]
                log.append("halt")
                reply(b"T05")
                continue
            if b"#" not in buf or len(buf) < buf.index(b"#") + 3:
                break
            end = buf.index(b"#")
            body, buf = buf[1:end], buf[end + 3:]
            c.sendall(b"+")
            if body == b"?":
                reply(b"T05")
            elif body == b"c":
                log.append("go")
            elif body.startswith(b"m"):
                addr, n = (int(x, 16) for x in body[1:].split(b","))
                reply(bytes(mem[addr:addr + n]).hex().encode())
            elif body.startswith(b"M"):
                spec, data = body[1:].split(b":")
                addr, n = (int(x, 16) for x in spec.split(b","))
                mem[addr:addr + n] = bytes.fromhex(data.decode())
                reply(b"OK")
            elif body == b"D":
                reply(b"OK")
                return
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
threading.Thread(target=fake_gdb, args=(srv,), daemon=True).start()
g = Gdb(f"127.0.0.1:{srv.getsockname()[1]}")
r = RttReader(g, CB)
got = r.poll()
rd, = struct.unpack_from("<I", mem, CB + 24 + 16)
again = r.poll()
g.close()
check("RTT: finds the 'Scope' up-buffer, reads across the wrap, moves the read offset on",
      r.name == "Scope" and got == b"ABCDEFG" and rd == 3 and again == b"", (r.name, got, rd, again))
check("RTT: the CPU is stopped only around the reads and runs again after", log[-1] in ("go", "halt") and log.count("go") >= 2, log)

# ---- heap events from two CPUs at once: each operation is two events (size,
# then address); both CPUs' idle tasks (and code before the scheduler) share
# one task id, so the halves interleave and must be paired per CPU
print("=== heap: two CPUs, the same task id ===")
mh = Model()
mh.frame(dict(HELLO, ncpus=2))
IDLE_ = 0xFF
mh.frame({"kind": "events", "first": 0, "lost": 0, "events": [
    (100, 15, 0, IDLE_, 0, 64),        (101, 15, 1, IDLE_, 0, 32),          # CPU 0 and 1: sizes
    (102, 15, 0, IDLE_, 0x80, 0x1000), (103, 15, 1, IDLE_, 0x80, 0x2000),   # then the addresses
    (200, 15, 1, IDLE_, 1, 0),         (201, 15, 1, IDLE_, 0x81, 0x1000),   # CPU 1 frees CPU 0's block
]})
sh = mh.snapshot()
check("heap: halves paired per CPU (no lost allocation, no unknown free)",
      not sh["heap_warn"] and [x[1] for x in sh["heap_live"]] == [0x2000] and [x[3] for x in sh["heap_live"]] == [32],
      (sh["heap_warn"], sh["heap_live"]))

sys.exit(1 if fails else 0)
