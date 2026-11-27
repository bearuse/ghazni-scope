"""Reading the stream from an RTT buffer in the target's RAM through a GDB
server (docs/RTT.md): OpenOCD (port 3333), SEGGER J-Link GDB Server
(2331), pyOCD (3333), or QEMU's -gdb. Standard library only.

Every few milliseconds the reader stops the CPU, reads the buffer's write
offset and the new bytes, moves the read offset on and lets the CPU run
again. Stopping is what a GDB server needs for memory access in general;
the stop is short (a few memory reads). OpenOCD's and J-Link's own RTT
servers read without stopping the CPU: use those with --tcp when you can.
"""
import socket
import struct
import time

RTT_ID = b"SEGGER RTT\0"


# ---- ELF: the address of a symbol (the RTT control block, _SEGGER_RTT)
def elf_symbol(path, name):
    with open(path, "rb") as f:
        d = f.read()
    if d[:4] != b"\x7fELF":
        raise ValueError(f"{path}: not an ELF file")
    is64, le = d[4] == 2, d[5] == 1
    e = "<" if le else ">"
    if is64:
        shoff, = struct.unpack_from(e + "Q", d, 0x28)
        shentsize, shnum = struct.unpack_from(e + "HH", d, 0x3A)
    else:
        shoff, = struct.unpack_from(e + "I", d, 0x20)
        shentsize, shnum = struct.unpack_from(e + "HH", d, 0x2E)

    def section(i):
        o = shoff + i * shentsize
        if is64:
            _, typ, _, _, off, size, link, _, _, entsize = struct.unpack_from(e + "IIQQQQIIQQ", d, o)
        else:
            _, typ, _, _, off, size, link, _, _, entsize = struct.unpack_from(e + "IIIIIIIIII", d, o)
        return typ, off, size, link, entsize

    want = name.encode()
    for i in range(shnum):
        typ, off, size, link, entsize = section(i)
        if typ != 2:                                    # SHT_SYMTAB
            continue
        _, stroff, _, _, _ = section(link)
        for k in range(size // entsize):
            o = off + k * entsize
            if is64:
                st_name, _, _, _, value, _ = struct.unpack_from(e + "IBBHQQ", d, o)
            else:
                st_name, value, _, _, _, _ = struct.unpack_from(e + "IIIBBH", d, o)
            end = d.index(b"\0", stroff + st_name)
            if d[stroff + st_name:end] == want:
                return value
    raise ValueError(f"{path}: no symbol {name}")


# ---- the GDB remote serial protocol, the few packets this needs
class Gdb:
    def __init__(self, hostport, timeout=5.0):
        host, port = hostport.rsplit(":", 1)
        end = time.time() + timeout
        while True:
            try:
                self.s = socket.create_connection((host, int(port)), timeout=timeout)
                # many tiny request/reply packets: without this each waits for
                # delayed ACKs (~40-200 ms a poll)
                self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                break
            except OSError:
                if time.time() > end:
                    raise
                time.sleep(0.1)
        self.buf = b""
        self.running = False
        self.cmd("?")                                   # the target stops on connect

    def _send(self, body):
        pkt = b"$" + body + b"#" + b"%02x" % (sum(body) & 0xFF)
        while True:
            self.s.sendall(pkt)
            if self._ack():
                return

    def _ack(self):
        while True:
            c = self._byte()
            if c == b"+":
                return True
            if c == b"-":
                return False

    def _byte(self):
        if not self.buf:
            self.buf = self.s.recv(65536)
            if not self.buf:
                raise EOFError("GDB server closed the connection")
        c, self.buf = self.buf[:1], self.buf[1:]
        return c

    def _reply(self):
        while self._byte() != b"$":
            pass
        body = b""
        while True:
            c = self._byte()
            if c == b"#":
                self._byte(), self._byte()
                self.s.sendall(b"+")
                break
            if c == b"}":                               # escaped byte
                c = bytes([self._byte()[0] ^ 0x20])
            body += c
        return body

    def cmd(self, body):
        self._send(body.encode() if isinstance(body, str) else body)
        return self._reply()

    def halt(self):
        if self.running:
            self.s.sendall(b"\x03")
            self._reply()                               # the stop reply
            self.running = False

    def go(self):
        if not self.running:
            self._send(b"c")
            self.running = True

    def read(self, addr, n):
        out = b""
        while len(out) < n:
            k = min(n - len(out), 1024)
            r = self.cmd(f"m{addr + len(out):x},{k:x}")
            if not r or r.startswith(b"E"):
                raise IOError(f"GDB server: cannot read 0x{addr:x}: {r.decode(errors='replace')}")
            out += bytes.fromhex(r.decode())
        return out

    def write32(self, addr, v):
        r = self.cmd(f"M{addr:x},4:" + struct.pack("<I", v).hex())
        if r != b"OK":
            raise IOError(f"GDB server: cannot write 0x{addr:x}: {r.decode(errors='replace')}")

    def close(self):
        try:
            self.halt()
            self.cmd("D")                               # detach: the target runs on
        except (OSError, EOFError):
            pass
        self.s.close()


class RttReader:
    """The up-buffer named `channel` (or with that number) of the RTT control
    block at `addr` (from --elf's _SEGGER_RTT, or --rtt-addr)."""

    def __init__(self, gdb, addr, channel="Scope", wait=10.0):
        self.g, self.addr = gdb, addr
        end = time.time() + wait                        # the target sets the ID at its first write
        while True:
            self.g.halt()
            cb = self.g.read(addr, 24)
            if cb[:len(RTT_ID)] == RTT_ID:
                break
            if time.time() > end:
                raise IOError(f"no RTT control block at 0x{addr:x} (ID {cb[:16]!r})")
            self.g.go()
            time.sleep(0.05)
        n_up, = struct.unpack_from("<i", cb, 16)
        self.buf = None
        for i in range(n_up):
            d = addr + 24 + i * 24
            name_p, start, size, wr, rd, flags = struct.unpack("<IIIIII", self.g.read(d, 24))
            name = self._cstr(name_p)
            if str(i) == str(channel) or name == channel:
                self.buf, self.start, self.size, self.name = d, start, size, name
                break
        if self.buf is None:
            raise IOError(f"RTT: no up-buffer '{channel}' ({n_up} up-buffers)")
        self.g.go()

    def _cstr(self, p):
        if not p:
            return ""
        return self.g.read(p, 32).split(b"\0")[0].decode(errors="replace")

    def poll(self):
        """New bytes since the last call (stops the CPU for the reads)."""
        self.g.halt()
        try:
            wr, rd = struct.unpack("<II", self.g.read(self.buf + 12, 8))
            if wr == rd or wr >= self.size or rd >= self.size:
                return b""
            if wr > rd:
                data = self.g.read(self.start + rd, wr - rd)
            else:
                data = self.g.read(self.start + rd, self.size - rd) + (self.g.read(self.start, wr) if wr else b"")
            self.g.write32(self.buf + 16, wr)           # RdOff: the space is free again
            return data
        finally:
            self.g.go()
