"""Ghazni Scope: live task profiling in the browser (like Percepio
Tracealyzer's live view), for Ghazni and FreeRTOS.

The target streams kernel events and task statistics (docs/PROTOCOL.md):
Ghazni's tracer task over its console UART or UDP, the FreeRTOS recorder
(targets/freertos) over whatever its port writes to. This tool reads that stream,
keeps the console usable, and serves a live view at http://localhost:8800.

  # FreeRTOS (targets/freertos): a UART, or a program writing the stream to stdout
  ghazni-scope --serial /dev/ttyUSB0 --baud 921600
  ghazni-scope --exec examples/freertos-posix/build/demo
  ghazni-scope --exec "qemu-system-arm -M mps2-an385 -display none -monitor none \
                       -serial stdio -kernel examples/freertos-mps2/build/demo.elf"

  # Ghazni (from the Ghazni tree, 'make scope' does the first)
  ghazni-scope --qemu build/qemu-virt/ghazni.elf     # starts QEMU, serial on a local TCP port
  ghazni-scope --tcp localhost:4444                  # a QEMU started with 'make run-tcp'
  ghazni-scope --serial /dev/ttyUSB0 --baud 1500000  # ROCK 5B (pip install pyserial)
  ghazni-scope --net 192.168.77.2:23                 # remote shell + UDP stream (AMP, docs/NET.md)
  ghazni-scope --qemu build/qemu-virt/ghazni.elf --net

  --record raw.bin   keep the raw stream;  --replay raw.bin   view it later
  --perfetto out.json  write the trace on exit (https://ui.perfetto.dev)
  --check SECONDS    no browser: collect, print a summary, exit (tests)

Without installing: python3 -m ghazni_scope ... from the repository root.
With Ghazni, the tool types 'trace stream on' (with --net: 'trace stream
udp <this host as the target sees it> <port>') into the shell when it sees
the prompt, and 'trace stream off' when it exits. The FreeRTOS recorder
streams from the start.
"""
import argparse, collections, json, os, shlex, signal, socket, subprocess, sys, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .protocol import Splitter, parse
from .model import Model

HERE = os.path.dirname(os.path.abspath(__file__))


class Link:
    """Byte stream to the target: TCP, serial, or a replay file."""

    def __init__(self, a):
        self.a, self.sock, self.ser, self.replay, self.udp, self.proc = a, None, None, None, None, None
        if a.net:                       # remote shell + UDP stream
            host, port = a.net.rsplit(":", 1) if ":" in a.net else (a.net, "23")
            self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp.bind((a.udp_bind, a.udp_port))
            self.udp.settimeout(0.2)
            a.tcp = f"{host}:{port}"
        if a.tcp:
            host, port = a.tcp.rsplit(":", 1)
            for _ in range(100):
                try:
                    self.sock = socket.create_connection((host, int(port)), timeout=2)
                    break
                except OSError:
                    time.sleep(0.1)
            if not self.sock:
                sys.exit(f"cannot connect to {a.tcp}")
            self.sock.settimeout(0.2)
            if self.udp:                # where the target should send the stream
                me = self.sock.getsockname()[0]
                self.reply_to = a.reply_to or ("10.0.2.2" if me.startswith("127.") else me)
        elif a.serial:
            try:
                import serial
            except ImportError:
                sys.exit("--serial needs pyserial: pip install pyserial")
            self.ser = serial.Serial(a.serial, a.baud, timeout=0.2)
        elif a.replay:
            self.replay = open(a.replay, "rb")
        elif a.exec:                    # a program whose output is the stream (FreeRTOS on Linux,
            self.proc = subprocess.Popen(shlex.split(a.exec), stdin=subprocess.PIPE,   # QEMU with
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)  # -serial stdio)
            os.set_blocking(self.proc.stdout.fileno(), False)
        else:
            sys.exit("give --tcp, --serial, --net, --exec or --replay")

    def read(self):
        if self.sock:
            try:
                d = self.sock.recv(65536)
                if d == b"":
                    if self.udp and not getattr(self, "got", False):
                        self.reconnect()        # target network not up yet
                        return b""
                    raise EOFError
                self.got = True
                return d
            except socket.timeout:
                return b""
        if self.ser:
            return self.ser.read(self.ser.in_waiting or 1)
        if self.proc:
            try:
                d = os.read(self.proc.stdout.fileno(), 65536)
            except BlockingIOError:
                time.sleep(0.02)
                return b""
            if not d:
                raise EOFError
            return d
        d = self.replay.read(4096)
        if not d:
            raise EOFError
        return d

    def reconnect(self):
        """--net: the forwarded port answered before the target listened (QEMU
        user networking accepts at once); try again for up to 60 s"""
        self.sock.close()
        host, port = self.a.tcp.rsplit(":", 1)
        end = time.time() + 60
        while time.time() < end:
            time.sleep(0.5)
            try:
                self.sock = socket.create_connection((host, int(port)), timeout=2)
                self.sock.settimeout(0.2)
                return
            except OSError:
                pass
        raise EOFError

    def write(self, data):
        if self.sock:
            self.sock.sendall(data)
        elif self.ser:
            self.ser.write(data)
        elif self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except OSError:
                pass

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()


class Capture:
    """The raw stream as received (console text and frames, UDP datagrams
    too), for 'save recording' in the browser and --record. The same format
    --replay reads. Stops growing at CAPTURE_MAX (and says so)."""
    MAX = 256 << 20

    def __init__(self, path=None):
        self.buf, self.full, self.lock = bytearray(), False, threading.Lock()
        self.file = open(path, "wb") if path else None

    def add(self, d):
        with self.lock:
            if self.file:
                self.file.write(d)
            if len(self.buf) + len(d) <= self.MAX:
                self.buf += d
            else:
                self.full = True

    def bytes(self):
        with self.lock:
            return bytes(self.buf)

    def close(self):
        with self.lock:
            if self.file:
                self.file.close()
                self.file = None


def load_recording(data, triggers=()):
    """A saved stream -> a Model with everything in it (the browser's 'open')."""
    m, split = Model(), Splitter()
    for t in triggers:
        m.add_trigger(t)
    for kind, v in split.feed(data):
        if kind == "text":
            m.text(v)
        else:
            f = parse(v)
            if f:
                m.frame(f)
    m.connected = m.streaming = False
    return m


def from_target(peer, src):
    """a stream datagram is taken only from the target's address (the remote
    shell's peer); QEMU user networking: both are loopback addresses"""
    return not peer or src == peer or (peer.startswith("127.") and src.startswith("127."))


def udp_reader(link, model, args, state):
    """frames arriving as UDP datagrams (--net): whole frames per datagram"""
    split = Splitter()
    while not state["stop"]:
        try:
            d, src = link.udp.recvfrom(2048)
        except socket.timeout:
            continue
        except OSError:
            break
        try:                            # only the target we talk to (not anyone on the network)
            peer = link.sock.getpeername()[0]
        except OSError:
            peer = None
        if not from_target(peer, src[0]):
            model.udp_rejected = getattr(model, "udp_rejected", 0) + 1
            continue
        model.udp_bytes = getattr(model, "udp_bytes", 0) + len(d)
        if state.get("capture"):
            state["capture"].add(d)
        for kind, v in split.feed(d):
            if kind == "frame":
                f = parse(v)
                if f:
                    model.frame(f)


def stream_on(link):
    return (f"trace stream udp {link.reply_to} {link.a.udp_port}\r" if link.udp
            else "trace stream on\r").encode()


def reader(link, model, args, state):
    split = Splitter()
    if link.udp:
        threading.Thread(target=udp_reader, args=(link, model, args, state), daemon=True).start()
    rec = state.get("capture")
    model.connected = True
    try:
        while not state["stop"]:
            try:
                d = link.read()
            except EOFError:
                break
            if not d:
                continue
            if rec:
                rec.add(d)
            for kind, v in split.feed(d):
                if kind == "text":
                    model.text(v)
                    if not args.quiet:
                        print(v, flush=True)
                    if "ghazni>" in v or "[shell] ready" in v:
                        state["prompt"] = True
                else:
                    f = parse(v)
                    if f:
                        model.frame(f)
            # the prompt itself has no newline: look at the partial text
            if b"ghazni> " in bytes(split.text[-16:]):
                state["prompt"] = True
            if state["prompt"] and not state["started"] and not args.replay:
                time.sleep(0.2)
                link.write(stream_on(link))
                state["started"] = True
    finally:
        model.connected = False
        state["eof"] = True


# Live deltas overlap the previous one by 1 ms (an item can arrive a little
# out of order, e.g. from another CPU), so the browser would get the items of
# that 1 ms twice. Each delta drops what the previous message already carried.
DELTA_LISTS = ("segments", "ready", "marks", "events", "instances", "users", "texts", "states", "heap",
               "isr", "prios", "blocked", "holds", "serves", "semcount", "load")
DELTA_TAIL = 5000           # the overlap is at the end of each list


def delta_tails(d):
    return {k: collections.Counter(json.dumps(x) for x in d.get(k, [])[-DELTA_TAIL:]) for k in DELTA_LISTS}


def dedupe_delta(d, prev):
    """-> (d without the items prev already sent, the tails to check the next delta against).
    Counted: two identical items (two equal allocations in the same microsecond) are
    both kept unless both were sent already."""
    tails = delta_tails(d)
    for k in DELTA_LISTS:
        if k in d and prev.get(k):
            seen, keep = collections.Counter(prev[k]), []
            for x in d[k]:
                j = json.dumps(x)
                if seen[j] > 0:
                    seen[j] -= 1
                else:
                    keep.append(x)
            d[k] = keep
    return d, tails


class Handler(BaseHTTPRequestHandler):
    model = link = live = capture = None
    gen = 0                             # changes when the view switches between live and a file
    source = "live"

    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "web", "index.html"), "rb") as f:
                self._send(200, "text/html; charset=utf-8", f.read())
        elif self.path == "/snapshot":
            self._send(200, "application/json", json.dumps(self.model.snapshot()).encode())
        elif self.path == "/perfetto.json":
            body = json.dumps(self.model.perfetto()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Disposition", "attachment; filename=ghazni-trace.json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/recording":
            body = Handler.capture.bytes() if Handler.capture else b""
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", "attachment; filename=ghazni-scope.gzscope")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/source":
            full = bool(Handler.capture and Handler.capture.full)
            self._send(200, "application/json", json.dumps({"source": Handler.source, "capture_full": full}).encode())
        elif self.path == "/stream":
            # server-sent events: a full snapshot, then deltas every 200 ms
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                snap = self.model.snapshot()
                snap["source"] = Handler.source
                self.wfile.write(b"event: full\ndata: " + json.dumps(snap).encode() + b"\n\n")
                last, console_n, ver, gen = snap["now"], snap["console_n"], self.model.version, Handler.gen
                prev = delta_tails(snap)
                while True:
                    time.sleep(0.2)
                    if Handler.gen != gen:      # switched to a file or back: start over
                        snap = self.model.snapshot()
                        snap["source"] = Handler.source
                        self.wfile.write(b"event: full\ndata: " + json.dumps(snap).encode() + b"\n\n")
                        self.wfile.flush()
                        last, console_n, ver, gen = snap["now"], snap["console_n"], self.model.version, Handler.gen
                        prev = delta_tails(snap)
                        continue
                    if self.model.version == ver:
                        self.wfile.write(b": idle\n\n")
                        self.wfile.flush()
                        continue
                    ver = self.model.version
                    d = self.model.snapshot(since=last - 0.001)
                    d, prev = dedupe_delta(d, prev)
                    d["console"], console_n = self.model.console_after(console_n)
                    last = d["now"]
                    self.wfile.write(b"event: delta\ndata: " + json.dumps(d).encode() + b"\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        if self.path == "/cmd":
            n = int(self.headers.get("Content-Length", 0))
            cmd = self.rfile.read(n).decode(errors="replace").strip()
            if self.link and cmd:
                self.link.write(cmd.encode() + b"\r")
            self._send(200, "text/plain", b"ok")
        elif self.path == "/load":                  # view a saved recording instead of the target
            n = int(self.headers.get("Content-Length", 0))
            name = urllib.parse.unquote(self.headers.get("X-File-Name", "recording"))
            # the live view's trigger conditions are checked over the file as well
            m = load_recording(self.rfile.read(n), [t["text"] for t in Handler.live.triggers])
            if not m.tasks:
                self._send(400, "application/json", json.dumps({"ok": False, "error": "not a Scope recording (no hello frame)"}).encode())
                return
            Handler.model, Handler.source, Handler.gen = m, "file:" + name, Handler.gen + 1
            self._send(200, "application/json", json.dumps({"ok": True, "events": m.events_total, "seconds": round(m.now, 3)}).encode())
        elif self.path == "/live":
            Handler.model, Handler.source, Handler.gen = Handler.live, "live", Handler.gen + 1
            self._send(200, "application/json", b'{"ok": true}')
        elif self.path in ("/trigger", "/trigger/del"):
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n).decode(errors="replace").strip()
            try:
                if self.path == "/trigger":
                    tr = self.model.add_trigger(body)
                    self._send(200, "application/json", json.dumps({"ok": True, "id": tr["id"]}).encode())
                else:
                    self.model.del_trigger(int(body))
                    self._send(200, "application/json", b'{"ok": true}')
            except ValueError as e:
                self._send(400, "application/json", json.dumps({"ok": False, "error": str(e)}).encode())
        else:
            self._send(404, "text/plain", b"not found")


def summary(model):
    s = model.snapshot()
    c = s["counters"]
    print(f"scope: {c['events']} events, {c['lost']} lost, {c['frames']} frames, "
          f"{len(s['segments'])} run segments, {s['ncpus']} CPU(s), {len(s['tasks'])} tasks")
    for row in s["table"]:
        if row["runs"]:
            print(f"  {row['name']:<11} runs {row['runs']:6}  cpu {row['cpu_pct']:5.1f} %  "
                  f"max slice {row['max_run_ms']:8.3f} ms  max wake latency {row['max_lat_ms']:8.3f} ms  "
                  f"throttles {row['throttles']}")
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="\n".join(__doc__.split("\n")[2:]))
    ap.add_argument("--version", action="version", version=f"ghazni-scope {__version__}")
    ap.add_argument("--qemu", metavar="ELF", help="start QEMU with this kernel and connect to it")
    ap.add_argument("--smp", type=int, default=2, help="CPUs for --qemu")
    ap.add_argument("--tcp")
    ap.add_argument("--net", nargs="?", const="", metavar="HOST[:PORT]",
                    help="remote shell (TCP, default port 23) for commands, stream as UDP; "
                         "with --qemu: give the guest a NIC")
    ap.add_argument("--udp-bind", default="0.0.0.0",
                    help="address to receive the UDP stream on (default: all); datagrams from other "
                         "hosts than the target are dropped either way")
    ap.add_argument("--udp-port", type=int, default=9900, help="UDP port to receive the stream on")
    ap.add_argument("--reply-to", help="this host's address as the target sees it "
                                       "(default: from the TCP connection; 10.0.2.2 for QEMU)")
    ap.add_argument("--serial")
    ap.add_argument("--baud", type=int, default=1500000)
    ap.add_argument("--replay")
    ap.add_argument("--exec", metavar="CMD", help="run CMD and read the stream from its output "
                    "(FreeRTOS on Linux, or QEMU with -serial stdio)")
    ap.add_argument("--record")
    ap.add_argument("--perfetto")
    ap.add_argument("--port", type=int, default=8800, help="web view port")
    ap.add_argument("--check", type=float, help="collect this many seconds, print a summary, exit")
    ap.add_argument("--send", action="append", default=[],
                    help="shell command to type once streaming (with --check), may repeat")
    ap.add_argument("--quiet", action="store_true", help="do not echo the console")
    ap.add_argument("--trigger", action="append", default=[],
                    help="condition to watch, may repeat: 'resp pong >5ms', 'isr timer >500us', "
                         "'user 7 >1000', 'state 1 BRAKE', 'fault' (hits: web view, --check summary)")
    a = ap.parse_args()

    # a plain kill (SIGTERM) must also stop a QEMU we started
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    qemu = None
    if a.qemu:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        if a.net is not None:           # NIC on user networking, the remote shell forwarded
            nic = ["-netdev", f"user,id=n0,hostfwd=tcp:127.0.0.1:{port}-:23",
                   "-device", "virtio-net-device,netdev=n0"]
            serial = ["-serial", "null"]
            a.net = f"127.0.0.1:{port}"
        else:
            nic = ["-nic", "none"]
            serial = ["-serial", f"tcp:127.0.0.1:{port},server=on,wait=on"]
            a.tcp = f"127.0.0.1:{port}"
        qemu = subprocess.Popen([os.environ.get("QEMU", "qemu-system-aarch64"), "-machine", "virt,gic-version=3",
                                 "-cpu", "cortex-a76", "-m", "256M", "-smp", str(a.smp), "-display", "none",
                                 "-monitor", "none"] + nic + serial + ["-kernel", a.qemu],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    model = Model()
    try:
        return run(a, model, qemu)
    except KeyboardInterrupt:
        return 0
    finally:
        if qemu:
            qemu.kill()
            qemu.wait()


def run(a, model, qemu):
    for t in a.trigger:
        try:
            model.add_trigger(t)
        except ValueError as e:
            print(f"ghazni scope: bad --trigger '{t}': {e}", file=sys.stderr)
            return 2
    link = Link(a)
    state = {"stop": False, "prompt": False, "started": False, "eof": False,
             "capture": None if a.replay else Capture(a.record)}
    th = threading.Thread(target=reader, args=(link, model, a, state), daemon=True)
    th.start()

    if a.check is not None:
        end = time.time() + 60
        while not model.streaming and time.time() < end and not state["eof"]:
            time.sleep(0.1)
        for cmd in a.send:
            time.sleep(0.5)
            link.write(cmd.encode() + b"\r")
        if not a.replay:
            time.sleep(a.check)
        else:
            th.join()
        ok = model.streaming or bool(a.replay)
        s = summary(model)
        for tr in s.get("triggers", []):
            print(f"  trigger '{tr['text']}': {tr['hits']} hits")
        if a.perfetto:
            json.dump(model.perfetto(), open(a.perfetto, "w"))
        with open(os.environ.get("SCOPE_JSON", os.devnull), "w") as f:
            json.dump(s, f)
        if not a.replay:
            link.write(b"trace stream off\r")
            time.sleep(0.3)
        state["stop"] = True
        link.close()
        if state["capture"]:
            state["capture"].close()
        return 0 if ok else 1

    Handler.model, Handler.link, Handler.live, Handler.capture = model, link, model, state["capture"]
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"ghazni scope: open http://localhost:{a.port}", file=sys.stderr, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if not a.replay:
            try:
                link.write(b"trace stream off\r")
            except OSError:
                pass
        if a.perfetto:
            json.dump(model.perfetto(), open(a.perfetto, "w"))
            print(f"wrote {a.perfetto}", file=sys.stderr)
        state["stop"] = True
        link.close()
        if state["capture"]:
            state["capture"].close()
    return 0

