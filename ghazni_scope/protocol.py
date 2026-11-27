"""Ghazni Scope stream (Ghazni, FreeRTOS): frame splitting and decoding.

Wire format (include/scope_proto.h, docs/PROTOCOL.md): console text, with binary frames
0x01 COBS(frame) 0x00 in between. Text never contains 0x00/0x01.
"""
import struct

SOF, EOF = 0x01, 0x00
TEV = {1: "switch", 2: "wake", 3: "irq", 4: "timeout", 5: "throttle", 6: "timer", 7: "fault",
       8: "call", 9: "send", 10: "recv", 11: "reply", 12: "signal", 13: "user", 14: "ustr", 15: "heap",
       16: "irqend", 17: "prio", 18: "take"}        # v3: types above 15 are escaped
HAS_B = {1, 5, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18}     # scope_proto.h, 'D' frames
HAS_ARG = {1, 3, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18}
NTFN_KIND = {0: "event", 1: "mutex", 2: "semaphore", 3: "queue", 4: "event group"}
OS_NAME = {0: "Ghazni", 1: "FreeRTOS"}
TSTR_FIRST, TSTR_STATE, HEAP_ADDR = 0x80, 0x40, 0x80
STATES = ["inactive", "running", "ready", "send", "recv", "reply", "wait", "sleep",
          "FAULTED", "exited", "stopped", "throttled"]
IDLE, NONE = 0xFF, 0xFE


def cobs_decode(data):
    out, i = bytearray(), 0
    while i < len(data):
        code = data[i]
        if code == 0:
            raise ValueError("zero byte in COBS data")
        out += data[i + 1:i + code]
        i += code
        if code < 0xFF and i < len(data):
            out.append(0)
    return bytes(out)


class Splitter:
    """Feed raw bytes; get back ('text', str) and ('frame', bytes) items."""

    def __init__(self):
        self.text = bytearray()
        self.frame = None           # bytearray while inside a frame
        self.bad = 0

    def feed(self, data):
        items = []
        for b in data:
            if self.frame is not None:
                if b == EOF:
                    try:
                        items.append(("frame", cobs_decode(bytes(self.frame))))
                    except ValueError:
                        self.bad += 1
                    self.frame = None
                else:
                    self.frame.append(b)
                    if len(self.frame) > 65536:     # lost the end marker
                        self.frame, self.bad = None, self.bad + 1
            elif b == SOF:
                self.frame = bytearray()
            elif b == EOF:
                pass
            else:
                self.text.append(b)
                if b == 0x0A:
                    items.append(("text", self.text.decode(errors="replace").rstrip("\r\n")))
                    self.text.clear()
        return items


def parse(frame):
    """Decoded frame -> dict, or None for unknown frames."""
    if not frame:
        return None
    kind = chr(frame[0])
    if kind == "H" and len(frame) >= 16:
        ver, ncpus, ntasks = frame[1], frame[2], frame[3]
        hz = struct.unpack_from("<Q", frame, 8)[0]
        tasks = []
        for i in range(ntasks):
            off = 16 + i * 20
            if off + 20 > len(frame):
                break
            tid, prio = frame[off], frame[off + 1]
            name = frame[off + 4:off + 20].split(b"\0")[0].decode(errors="replace")
            tasks.append({"id": tid, "prio": prio, "name": name})
        return {"kind": "hello", "version": ver, "ncpus": ncpus, "hz": hz, "tasks": tasks,
                "repeat": bool(frame[4]), "os": OS_NAME.get(frame[5], f"os {frame[5]}")}
    if kind == "E" and len(frame) >= 16:
        first = struct.unpack_from("<Q", frame, 1)[0]
        n = struct.unpack_from("<H", frame, 9)[0]
        lost = struct.unpack_from("<I", frame, 12)[0]
        evs = []
        for i in range(n):
            off = 16 + i * 16
            if off + 16 > len(frame):
                break
            tick, typ, cpu, a, b, arg = struct.unpack_from("<QBBBBI", frame, off)
            evs.append((tick, typ, cpu, a, b, arg))
        return {"kind": "events", "first": first, "lost": lost, "events": evs}
    if kind in "CD" and len(frame) >= 24:
        first = struct.unpack_from("<Q", frame, 1)[0]
        n = struct.unpack_from("<H", frame, 9)[0]
        lost = struct.unpack_from("<I", frame, 12)[0]
        tick = struct.unpack_from("<Q", frame, 16)[0]
        evs, i = [], 24

        def varint():
            nonlocal i
            v = shift = 0
            while True:
                b = frame[i]
                i += 1
                v |= (b & 0x7F) << shift
                shift += 7
                if b < 0x80:
                    return v
        try:
            for _ in range(n):
                z = varint()
                tick += (z >> 1) ^ -(z & 1)
                tc = frame[i]
                i += 1
                if kind == "D" and tc & 15 == 0:    # v3: an escaped type above 15
                    tc |= frame[i] << 8
                    i += 1
                a = frame[i]
                i += 1
                if kind == "C":                 # v1: 7 event types
                    typ, cpu, b, arg = tc & 7, tc >> 3, 0, 0
                    if typ in (1, 5):
                        b = frame[i]
                        i += 1
                    elif typ in (3, 6):
                        arg = varint()
                else:
                    typ, cpu, b, arg = (tc >> 8 if tc & 15 == 0 else tc & 15), (tc >> 4) & 15, 0, 0
                    if typ in HAS_B:
                        b = frame[i]
                        i += 1
                    if typ in HAS_ARG:
                        arg = varint()
                evs.append((tick, typ, cpu, a, b, arg))
        except IndexError:
            return None
        return {"kind": "events", "first": first, "lost": lost, "events": evs}
    if kind == "O" and len(frame) >= 4:
        neps, nntfns = frame[1], frame[2]
        names = [frame[4 + k * 16:4 + k * 16 + 16].split(b"\0")[0].decode(errors="replace")
                 for k in range(neps + nntfns) if 4 + k * 16 + 16 <= len(frame)]
        irqs = {}
        for k in range(frame[3]):                       # v3: interrupt number and name
            off = 4 + (neps + nntfns + k) * 16
            if off + 16 <= len(frame):
                irqs[struct.unpack_from("<H", frame, off)[0]] = frame[off + 2:off + 16].split(b"\0")[0].decode(errors="replace")
        off = 4 + (neps + nntfns + frame[3]) * 16              # 0.20: notification kinds
        kinds = [NTFN_KIND.get(b, "event") for b in frame[off:off + nntfns]] if len(frame) >= off + nntfns else []
        return {"kind": "objects", "endpoints": names[:neps], "notifications": names[neps:], "irqs": irqs,
                "ntfn_kinds": kinds}
    if kind == "S" and len(frame) >= 16:
        up = struct.unpack_from("<Q", frame, 1)[0]
        n = frame[9]
        size = frame[10] or 24                  # v3: 32 bytes, with kernel time
        tasks = []
        for i in range(n):
            off = 16 + i * size
            if off + size > len(frame):
                break
            tid, st, prio, base, thr, cpu_us, su, ss = struct.unpack_from("<BBBBIQII", frame, off)
            kern_us = struct.unpack_from("<Q", frame, off + 24)[0] if size >= 32 else 0
            tasks.append({"id": tid, "state": STATES[st] if st < len(STATES) else "?",
                          "prio": prio, "base_prio": base, "throttles": thr,
                          "cpu_us": cpu_us, "stack_used": su, "stack_size": ss, "kern_us": kern_us})
        scope_us = struct.unpack_from("<I", frame, 12)[0]
        return {"kind": "stats", "uptime_us": up, "tasks": tasks, "scope_us": scope_us}
    if kind == "X":
        return {"kind": "stopped"}
    return None
