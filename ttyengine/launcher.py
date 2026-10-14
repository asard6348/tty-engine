import os, sys, time, threading, traceback, contextlib, inspect, ctypes, re, socket, subprocess, tempfile, shlex
from itertools import groupby
from operator import itemgetter

def highlight_traceback(tb_str: str) -> str:
    RESET, BOLD, RED, GREEN, YELLOW, CYAN, MAGENTA = (
        "\033[0m", "\033[1m", "\033[91m", "\033[92m", "\033[93m", "\033[96m", "\033[95m"
    )
    lines = []
    for line in tb_str.splitlines(True):
        if line.startswith("Traceback"):
            lines.append(f"{BOLD}{RED}{line}{RESET}")
        elif line.strip().startswith("File "):
            m = re.match(r'^(\s*File )("[^"]+")(, line )(\d+)(, in )(.*)$', line)
            if m:
                lines.append(
                    f"{m.group(1)}{GREEN}{m.group(2)}{RESET}"
                    f"{m.group(3)}{YELLOW}{m.group(4)}{RESET}"
                    f"{m.group(5)}{CYAN}{m.group(6)}{RESET}\n"
                )
            else:
                lines.append(line)
        elif ":" in line and not line.startswith(" "):
            parts = line.split(":", 1)
            lines.append(f"{BOLD}{RED}{parts[0]}:{RESET}{BOLD}{parts[1]}{RESET}")
        else:
            line_hl = re.sub(r'("[^"]*"|\'[^\']*\')', rf'{GREEN}\1{RESET}', line)
            kw = r'\b(def|class|return|if|elif|else|while|for|in|import|from|as|try|except|finally|raise|with|pass|break|continue|and|or|not|is|None|True|False)\b'
            line_hl = re.sub(kw, rf'{MAGENTA}\1{RESET}', line_hl)
            lines.append(line_hl)
    return "".join(lines)

def trace(exception, lexer=None, clear=True, out=sys.stdout.write, flush=sys.stdout.flush):
    try:
        if clear:
            if out: out("\033[H\033[2J\033[3J")
        if out:
            tb_raw = "".join(traceback.format_exc()) + '\n'
            exc = highlight_traceback(tb_raw)
            out(exc)
            if flush: flush()
    except:
        raise exception

def attempt(func, catch=None, lexer=None, fatal=True, clear=True, reset=True, out=sys.stdout.write, flush=sys.stdout.flush):
    try:
        return func()
    except Exception as e:
        if reset and fatal:
            try: out('\033c')
            except: pass
        catchexc = None
        if callable(catch):
            try:
                catch()
            except Exception as ce:
                catchexc = ce
        trace(e, lexer, clear, out, flush)
        if catchexc: trace(catchexc, lexer, False, out, flush)
        if fatal:
            try: input()
            except: pass
            try: os._exit(0)
            except: exit()

DEBUG_HOLD = '\033]777;hold\007'
DEBUG_RECEIVER = r"""
import sys, socket, codecs
if sys.platform == "win32":
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    if __BACK__:
        hwnd = kernel32.GetConsoleWindow()
        if hwnd: ctypes.windll.user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 19)
out = sys.stdout
title = __TITLE__
if title is not None:
    out.write("\033]0;" + title + "\007")
out.write("\033[?1049l\033[?1049h\033[?25l\033[2J\033[H")
out.flush()
sock = socket.socket()
sock.connect(("127.0.0.1", __PORT__))
decode = codecs.getincrementaldecoder("utf-8")("replace").decode
hold = False
while True:
    data = sock.recv(65536)
    if not data:
        break
    text = decode(data)
    if "\033]777;hold\007" in text:
        text = text.replace("\033]777;hold\007", "")
        hold = True
    out.write(text)
    out.flush()
out.write("\033[?25h")
out.flush()
if hold:
    try: input()
    except Exception: pass
"""

def spawn_console(script):
    if sys.platform == "win32":
        for cmd in (['conhost.exe', sys.executable, '-c', script], [sys.executable, '-c', script]):
            try:
                return subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
            except FileNotFoundError:
                continue
        return None
    if sys.platform == "darwin":
        fd, path = tempfile.mkstemp(prefix='ttyengine_debug_', suffix='.py')
        with os.fdopen(fd, 'w') as f:
            f.write(script)
        command = f'{shlex.quote(sys.executable)} {shlex.quote(path)}; rm -f {shlex.quote(path)}; exit'
        command = command.replace('\\', '\\\\').replace('"', '\\"')
        return subprocess.Popen(['osascript', '-e', f'tell application "Terminal" to do script "{command}"'],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for term in ['x-terminal-emulator', 'gnome-terminal', 'xterm', 'konsole']:
        try:
            return subprocess.Popen([term, '-e', sys.executable, '-c', script],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, close_fds=True)
        except FileNotFoundError:
            continue
    return None

def format_dinfo(value):
    if value is None:
        lines = []
    elif isinstance(value, str):
        lines = value.split('\n')
    elif isinstance(value, dict):
        lines = [line for k, v in value.items() for line in f'{k}: {v}'.split('\n')]
    elif isinstance(value, (list, tuple, set, frozenset)):
        lines = [line for v in value for line in str(v).split('\n')]
    else:
        lines = str(value).split('\n')
    return '\033[H' + '\033[K\n'.join(lines) + '\033[K\033[J'

def getargs(func, args):
    if not callable(func): return {}
    sig = inspect.signature(func)
    par = sig.parameters
    if any(p.kind == p.VAR_KEYWORD for p in par.values()):
        return args
    resargs = {k: v for k, v in args.items() if k in par}
    return resargs

def latency(samples=1000):
    latencies = []
    for _ in range(samples):
        start = time.perf_counter()
        time.sleep(0)
        end = time.perf_counter()
        latencies.append(end - start)
    return latencies


#MODULES
def attemptimports():
    global scene, Terminal, inp, Styler, Mixer
    from . import scene
    from blessed import Terminal
    from .input_handler import inp
    from .ascii_styler import Styler
    from .sound import Mixer
attempt(attemptimports)

#WINDOWS INTIALIZATION
def universal_init():
    if os.name == 'nt':
        hOut = ctypes.windll.kernel32.GetStdHandle(-11)
        dwMode = ctypes.c_uint32()
        ctypes.windll.kernel32.GetConsoleMode(hOut, ctypes.byref(dwMode))
        ctypes.windll.kernel32.SetConsoleMode(hOut, dwMode.value | 0x0004)
attempt(universal_init)

HANDLE_STATES = ('start', 'update', 'final')

def handle_state(state):
    if isinstance(state, str):
        name = state.strip().lower()
        if name in HANDLE_STATES:
            return name
    elif isinstance(state, int) and not isinstance(state, bool) and 0 <= state < len(HANDLE_STATES):
        return HANDLE_STATES[state]
    raise ValueError(f"invalid handle state {state!r}: use 'start'/0, 'update'/1 or 'final'/2")

def is_handle(obj):
    return obj is not None and any(callable(getattr(obj, n, None)) for n in HANDLE_STATES)

def handle_class(handle, state='start'):
    if inspect.isclass(handle):
        return handle
    if not callable(handle):
        raise TypeError(f"launch() expects a class or a function, got {type(handle).__name__}")
    name = handle_state(state)
    base = getattr(handle, '__name__', None) or type(handle).__name__
    return type(base, (), {
        name: staticmethod(handle),
        '_factory': name == 'start',
        '__doc__': getattr(handle, '__doc__', None),
        '__module__': getattr(handle, '__module__', __name__),
    })

#WORLD CLASS
class World():
    def __init__(self, session=None, autoreg=True, front=True, **kwargs):
        self.session = session
        self.handles = []
        self.scene = scene.Scene()
        self._layer = 0
        self.last_tick = time.perf_counter()
        self.pause = False
        self.pausephysics = False
        self.pauserendering = False
        self.autoterm = True
        self.autodim = True
        self.autobg = True
        self.autofps = True
        for setting, val in kwargs.items():
            if val is not None: setattr(self, setting, val)
        if autoreg: attempt(lambda: self.register(front))

    @property
    def layer(self):
        return self._layer
    @layer.setter
    def layer(self, value):
        self._layer = value
        self.sort()

    def sort(self, layer=None):
        if self.session is not None:
            self.session.worlds = sorted(list(self.session.worlds), key=lambda w: getattr(w, '_layer', 0) if w is not self or layer is None else layer)

    class Handle():
        def __init__(self, handle, world):
            self.world = world
            self.pause = False
            self.handleargs = {
                'scene': self.world.scene,
                'handle': self,
                'world': self.world,
                'session': self.world.session,
                'sound': getattr(self.world.session, 'sound', None),
            }
            self.handle = handle(**getargs(handle, self.handleargs))
            if not hasattr(self.handle, 'priority'):
                self.priority = 0
            start = getattr(self.handle, 'start', None)
            self.startargs = getargs(start, self.handleargs)
            self.world.handles.append(self)
            result = start(**self.startargs) if start else None
            if getattr(self.handle, '_factory', False) and is_handle(result):
                self.handle = result
                start = getattr(result, 'start', None)
                self.startargs = getargs(start, self.handleargs)
                if start: start(**self.startargs)
        @property
        def priority(self):
            return getattr(self.handle, 'priority', 0)
        @priority.setter
        def priority(self, value):
            self.handle.priority = value
        def func(self, key: str):
            fu = getattr(self.handle, key, None)
            method_cache_attr = f"_{key}_method"
            args_cache_attr = f"{key}args"
            if fu != getattr(self, method_cache_attr, None):
                setattr(self, method_cache_attr, fu)
                if fu is not None:
                    ar = getargs(fu, self.handleargs)
                    setattr(self, args_cache_attr, ar)
                else:
                    if hasattr(self, args_cache_attr):
                        delattr(self, args_cache_attr)
            if fu:
                return lambda: fu(**getattr(self, args_cache_attr))
            return None
        def cancel(self):
            self.world.handles = [h for h in self.world.handles if h is not self]

    def ordered_handles(self):
        return sorted(self.handles, key=lambda h: -h.priority)

    def launch(self, handle=None, safe=True, state='start'):
        if handle is None:
            return lambda h: self.launch(h, safe=safe, state=state)
        cls = handle_class(handle, state)
        return (attempt(lambda: self.Handle(cls, self))
                if safe else self.Handle(cls, self))

    def cancel(self, handle):
        self.handles = [h for h in self.handles if h is not handle]

    def register(self, front=True):
        if self.session is not None:
            if self not in self.session.worlds:
                self.session.worlds.append(self)
                self.sync_colors()
                if front: self.front()
                else: self.back()
                self.sort()
                self.session.latency = max(latency())
                with self.session._resume:
                    self.session._resume.notify_all()

    def sync_colors(self):
        if self.session is not None:
            self.scene.bgcolor = self.session.bgcolor
            self.scene.fgcolor = self.session.fgcolor

    def unregister(self):
        if self.session is not None:
            self.session.worlds = [w for w in self.session.worlds if w is not self]

    def front(self):
        if self.session is not None:
            ll = None
            l = 0
            for w in self.session.worlds:
                if ll is None:
                    ll = w._layer
                    l = w._layer
                    continue
                if w._layer > ll: l = w._layer
            self.layer = l + 1

    def back(self):
        if self.session is not None:
            ll = None
            l = 0
            for w in self.session.worlds:
                if ll is None:
                    ll = w._layer
                    l = w._layer
                    continue
                if w._layer < ll: l = w._layer
            self.layer = l - 1

    def tick_ready(self):
        now = time.perf_counter()
        interval = 1.0 / self.scene.framerate
        if now - self.last_tick >= interval:
            self.last_tick = max(self.last_tick + interval, now - interval)
            return True
        return False

#COMPOSITOR CLASS
class Compositor:
    runs = re.compile(b'\x01(?:\x00{0,3}\x01)*')

    def __init__(self):
        self.front = None
        self.width = 0
        self.height = 0
        self.known = {}
        self.region = None

    def invalidate(self):
        self.front = None

    @staticmethod
    def vacate(old, new, bounds):
        ox, oy, ow, oh = old
        nx, ny, nw, nh = new
        tw, th = bounds
        out = ['\033[0m']
        for y in range(max(0, oy), min(oy + oh, th)):
            a, b = max(0, ox), min(ox + ow, tw)
            if ny <= y < ny + nh:
                segs = ((a, min(b, nx)), (max(a, nx + nw), b))
            else:
                segs = ((a, b),)
            for s, e in segs:
                if s < e:
                    out.append(f'\033[{y + 1};{s + 1}H' + ' ' * (e - s))
        return ''.join(out) if len(out) > 1 else ''

    def stale(self, width, height):
        return self.front is None or self.width != width or self.height != height

    @staticmethod
    def bgstyle(color):
        return f'\033[48;2;{int(color[0])};{int(color[1])};{int(color[2])}m'

    @staticmethod
    def parse(scene, text, spaces):
        bg = Compositor.bgstyle(scene.bgcolor)
        rows = []
        for row in text.split('\n'):
            cells = []
            active = ''
            for part in scene.recomp.split(row):
                if not part:
                    continue
                if scene.recomp.match(part):
                    if part in ('\033[0m', '\033[m'):
                        active = ''
                    elif part.startswith('\033[') and part.endswith('m'):
                        active += part
                    continue
                style = bg + active
                for char in part:
                    cells.append((char, style) if spaces or char != ' ' else None)
            runs = []
            start = None
            for i, cell in enumerate(cells):
                if cell is None:
                    if start is not None:
                        runs.append((start, cells[start:i]))
                        start = None
                elif start is None:
                    start = i
            if start is not None:
                runs.append((start, cells[start:]))
            rows.append((len(cells), runs))
        return rows

    def sync(self, worlds, active):
        rects = []
        seen = set()
        known = self.known
        for w in worlds:
            sc = w.scene
            live = w in active
            if live:
                ir = sc.iround
                camx = ir(sc.camx)
                camy = ir(sc.camy)
                xoff = sc.dimxoffset
                yoff = sc.dimyoffset
                bgcolor = sc.bgcolor
            for o in sc.objs:
                r = getattr(o, 'rendering', None)
                if r is None:
                    continue
                seen.add(r)
                if not live or not r.t.rtext:
                    continue
                state = known.get(r)
                if state is None:
                    state = known[r] = [(0, 0, '', 0, 0), None, [], 0]
                current = r.state(camx, camy, xoff, yoff)
                previous = state[0]
                if previous == current:
                    continue
                if previous[2]:
                    x, y, _, xo, yo = previous
                    rects.append((x + xo, y - yo, x + xo + state[3], y - yo + len(state[2])))
                if current[2]:
                    key = (current[2], r.renderspaces, bgcolor)
                    if state[1] != key:
                        state[1] = key
                        state[2] = self.parse(sc, current[2], r.renderspaces)
                        state[3] = max(row[0] for row in state[2])
                    x, y, _, xo, yo = current
                    rects.append((x + xo, y - yo, x + xo + state[3], y - yo + len(state[2])))
                state[0] = current
        for r in [r for r in known if r not in seen]:
            state = known.pop(r)
            if state[0][2]:
                x, y, _, xo, yo = state[0]
                rects.append((x + xo, y - yo, x + xo + state[3], y - yo + len(state[2])))
        return rects

    def layers(self, worlds, width, height, autobg):
        layers = []
        for w in worlds:
            sc = w.scene
            view = (
                max(0, sc.dimxoffset),
                max(0, -sc.dimyoffset),
                min(width, sc.termx, sc.dimxoffset + sc.dimx),
                min(height, sc.termy, -sc.dimyoffset + sc.dimy),
            )
            bg = self.bgstyle(sc.bgcolor) if autobg and w.autobg else None
            sprites = []
            for r in sorted([o.rendering for o in sc.objs if hasattr(o, 'rendering')], key=lambda r: r.z):
                state = self.known.get(r)
                if state is None or not state[0][2]:
                    continue
                key = (state[0][2], r.renderspaces, sc.bgcolor)
                if state[1] != key:
                    state[1] = key
                    state[2] = self.parse(sc, state[0][2], r.renderspaces)
                    state[3] = max(row[0] for row in state[2])
                x, y, _, xo, yo = state[0]
                sprites.append((x + xo, y - yo, state[2]))
            layers.append((view, bg, sprites))
        return layers

    def compose(self, worlds, active, region, bounds, outer, autobg):
        regx, regy, width, height = region
        rects = self.sync(worlds, active)
        prefix = ''
        moved = self.region is not None and self.region != region
        if moved:
            prefix = self.vacate(self.region, region, bounds)
        self.region = region
        if moved or self.stale(width, height):
            self.front = [[None] * width for _ in range(height)]
            self.width = width
            self.height = height
            rects = [(0, 0, width, height)]
        spans = {}
        for x0, y0, x1, y1 in rects:
            x0 = max(0, x0)
            y0 = max(0, y0)
            x1 = min(width, x1)
            y1 = min(height, y1)
            if x0 >= x1 or y0 >= y1:
                continue
            for y in range(y0, y1):
                span = spans.get(y)
                if span is None:
                    spans[y] = [x0, x1]
                else:
                    if x0 < span[0]: span[0] = x0
                    if x1 > span[1]: span[1] = x1
        if not spans:
            return prefix
        top = min(spans)
        bottom = max(spans) + 1
        right = max(s[1] for s in spans.values())
        base = (' ', self.bgstyle(outer) if outer is not None else '')
        back = {y: [base] * width for y in spans}
        for view, bg, sprites in self.layers(worlds, width, height, autobg):
            vx0, vy0, vx1, vy1 = view
            if bg is not None:
                cell = (' ', bg)
                for y in range(max(vy0, top), min(vy1, bottom)):
                    span = spans.get(y)
                    if span is None:
                        continue
                    a = max(vx0, span[0])
                    b = min(vx1, span[1])
                    if a < b:
                        back[y][a:b] = [cell] * (b - a)
            for x, y, grid in sprites:
                if y >= bottom or y + len(grid) <= top or x >= right:
                    continue
                for i, (rowwidth, runs) in enumerate(grid):
                    ry = y + i
                    if ry < vy0 or ry >= vy1:
                        continue
                    span = spans.get(ry)
                    if span is None:
                        continue
                    a = max(vx0, span[0], x)
                    b = min(vx1, span[1], x + rowwidth)
                    if a >= b:
                        continue
                    line = back[ry]
                    for offset, cells in runs:
                        s = max(a, x + offset)
                        e = min(b, x + offset + len(cells))
                        if s < e:
                            line[s:e] = cells[s - x - offset:e - x - offset]
        out = []
        style = None
        for y in sorted(spans):
            lo, hi = spans[y]
            new = back[y][lo:hi]
            old = self.front[y][lo:hi]
            if new == old:
                continue
            mask = bytes([a != b for a, b in zip(new, old)])
            for run in self.runs.finditer(mask):
                start, end = run.span()
                out.append(f'\033[{regy + y + 1};{regx + lo + start + 1}H')
                for cellstyle, group in groupby(new[start:end], key=itemgetter(1)):
                    if cellstyle != style:
                        style = cellstyle
                        out.append('\033[0m' + style)
                    out.append(''.join([cell[0] for cell in group]))
                self.front[y][lo + start:lo + end] = new[start:end]
        if not out:
            return prefix
        out.append('\033[0m')
        return prefix + ''.join(out)

#SESSION CLASS
class Session():
    APIS = {'inp': True, 'style': True, 'sound': True}
    SETTINGS = {'pausephysics': False, 'pauserendering': False, 'optimize': True, 'mouse': True, 'vsync': True,
                'autoterm': True, 'autodim': True, 'autobg': True, 'outerbg': True, 'clearonstop': True, 'autofps': True,
                'termxoffset': 0, 'termyoffset': 0, 'termwidth': None, 'termheight': None,
                'fullscreen': None, 'hidecursor': None}

    def __init__(self, watchfocus=True, trackmotion=True, ffmpeg=None, **kwargs):
        unknown = [k for k in kwargs if k not in self.APIS and k not in self.SETTINGS]
        if unknown:
            raise TypeError(f"Session() got unexpected keyword argument(s): {', '.join(unknown)}")
        self.worlds = []
        self.World = lambda front=True, **kwargs: World(session=self, autoreg=True, front=front, **kwargs)
        self.term = Terminal()
        self.apis = {name: kwargs.get(name, default) for name, default in self.APIS.items()}
        self.inp = inp(term=self.term, watchfocus=watchfocus, trackmotion=trackmotion) if self.apis['inp'] else None
        self.sound = Mixer(listener=self._listener, ffmpeg=ffmpeg) if self.apis['sound'] else None
        self._compositor = Compositor()
        self.running = False
        self._pause = False
        self._dinfo = None
        self._debug = None
        self._latency = max(latency())
        self._idle_scene = scene.Scene() if self.apis['style'] else None
        bg = self.term.get_bgcolor(bits=8)
        self._bgcolor = bg if bg != (-1, -1, -1) else (0, 0, 0)
        fg = self.term.get_fgcolor(bits=8)
        self._fgcolor = fg if fg != (-1, -1, -1) else (204, 204, 204)
        self._sync_colors()
        self._resume = threading.Condition()
        for name, default in self.SETTINGS.items():
            setattr(self, name, kwargs.get(name, default))

    @property
    def bgcolor(self):
        return self._bgcolor
    @bgcolor.setter
    def bgcolor(self, value):
        self._bgcolor = value
        self._sync_colors()

    @property
    def fgcolor(self):
        return self._fgcolor
    @fgcolor.setter
    def fgcolor(self, value):
        self._fgcolor = value
        self._sync_colors()

    def _sync_colors(self):
        for w in self.worlds:
            w.sync_colors()
        if self._idle_scene is not None:
            self._idle_scene.bgcolor = self._bgcolor
            self._idle_scene.fgcolor = self._fgcolor

    @property
    def dinfo(self):
        return self._dinfo
    @dinfo.setter
    def dinfo(self, value):
        self._dinfo = value
        self._debug_push()

    def debug(self, title=None, back=False):
        if self._debug is not None:
            return True
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(('127.0.0.1', 0))
            server.listen(1)
            script = (DEBUG_RECEIVER
                      .replace('__PORT__', str(server.getsockname()[1]))
                      .replace('__TITLE__', repr(title))
                      .replace('__BACK__', repr(bool(back))))
            proc = spawn_console(script)
            if proc is None:
                return False
            server.settimeout(5)
            try:
                conn, _ = server.accept()
            except socket.timeout:
                try: proc.kill()
                except Exception: pass
                return False
        finally:
            server.close()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.settimeout(1.0)
        try: sys.stdout.reconfigure(encoding='utf-8')
        except Exception: pass
        self._debug = {'proc': proc, 'conn': conn, 'last': None, 'hold': False}
        if self.inp and self.inp.wf:
            self.inp.focused = False
        self._debug_push()
        return True

    def undebug(self):
        d, self._debug = self._debug, None
        if d is None:
            return
        try: d['conn'].close()
        except OSError: pass
        if sys.platform != 'darwin' and not d['hold']:
            try: d['proc'].kill()
            except Exception: pass
        if self.inp and self.inp.wf:
            self.inp.focused = True

    def _debug_send(self, frame):
        try:
            self._debug['conn'].sendall(frame.encode('utf-8'))
            return True
        except (OSError, ValueError):
            self.undebug()
            return False

    def _debug_push(self):
        d = self._debug
        if d is None:
            return
        frame = format_dinfo(self._dinfo)
        if frame != d['last'] and self._debug_send(frame):
            d['last'] = frame

    def _debug_trace(self):
        d = self._debug
        if d is None:
            return
        d['hold'] = True
        self._debug_send('\033[H\033[2J\033[3J' + highlight_traceback(traceback.format_exc()) + DEBUG_HOLD)

    def _listener(self):
        if not self.worlds:
            return None
        sc = self.worlds[-1].scene
        return (sc.camx + sc.dimx / 2.0, sc.camy - sc.dimy / 2.0)

    @property
    def styler(self):
        if not self.apis['style']:
            return None
        return (self.worlds[-1].scene if self.worlds else self._idle_scene).styler

    @property
    def pause(self):
        return self._pause
    @pause.setter
    def pause(self, value):
        self._pause = value
        if not value:
            with self._resume:
                self._resume.notify_all()

    @property
    def latency(self):
        return self._latency
    @latency.setter
    def latency(self, value):
        self._latency = value
        if self.autofps:
            for w in self.worlds:
                if w.autofps: w.scene.maxframerate = 1/value

    @property
    def region(self):
        return (self.termxoffset, self.termyoffset, self.termwidth, self.termheight)
    @region.setter
    def region(self, value):
        x, y, w, h = (0, 0, None, None) if value is None else value
        self.termxoffset, self.termyoffset, self.termwidth, self.termheight = x, y, w, h

    @property
    def resolved_region(self):
        return self._resolve_region()

    def _resolve_region(self):
        tw, th = self.term.width, self.term.height
        x, y = self.termxoffset or 0, self.termyoffset or 0
        if x < 0: x += tw
        if y < 0: y += th
        x = min(max(x, 0), tw)
        y = min(max(y, 0), th)
        w = tw - x if self.termwidth is None else max(0, min(self.termwidth, tw - x))
        h = th - y if self.termheight is None else max(0, min(self.termheight, th - y))
        return (x, y, w, h)

    def _partial(self):
        return self.region != (0, 0, None, None)

    def style(self, *args, **kwargs):
        if not self.apis['style']:
            raise RuntimeError("the style API is disabled for this Session (Session(style=False))")
        return self.styler.style(*args, **kwargs)

    def run_attempt(self, **kwargs):
        if(not self.running):
            self.running = True
            for setting, val in kwargs.items():
                if val is not None: setattr(self, setting, val)
            with contextlib.ExitStack() as main_stack:
                opt_stack = main_stack.enter_context(contextlib.ExitStack())
                is_optimized = False
                changed_optimized = False
                optt_stack = main_stack.enter_context(contextlib.ExitStack())
                is_mouse = False

                hc = not self._partial()
                while self.running:
                    if changed_optimized: changed_optimized = False
                    if self.optimize and not is_optimized:
                        fs = self.fullscreen if self.fullscreen is not None else not self._partial()
                        hc = self.hidecursor if self.hidecursor is not None else fs
                        if fs: opt_stack.enter_context(self.term.fullscreen())
                        opt_stack.enter_context(self.term.cbreak())
                        if hc: opt_stack.enter_context(self.term.hidden_cursor())
                        opt_stack.enter_context(self.term.no_line_wrap())
                        opt_stack.enter_context(self.term.synchronized_output())
                        is_optimized = True
                        changed_optimized = True
                        if is_mouse:
                            optt_stack.close()
                            optt_stack = main_stack.enter_context(contextlib.ExitStack())
                            optt_stack.enter_context(
                                self.term.mouse_enabled(report_drag=True, report_motion=True)
                            )
                    elif not self.optimize and is_optimized:
                        opt_stack.close()
                        opt_stack = main_stack.enter_context(contextlib.ExitStack())
                        is_optimized = False
                    if self.mouse and not is_mouse:
                        optt_stack.enter_context(self.term.mouse_enabled(report_drag=True, report_motion=True))
                        is_mouse = True
                    elif not self.mouse and is_mouse:
                        optt_stack.close()
                        optt_stack = main_stack.enter_context(contextlib.ExitStack())
                        is_mouse = False

                    if(not self._pause):
                        bef = time.perf_counter()
                        if self.inp: self.inp.update()
                        framerate_groups = {}
                        for w in self.worlds:
                            if w.pause: continue
                            fps = w.scene.framerate
                            if fps not in framerate_groups:
                                framerate_groups[fps] = []
                            framerate_groups[fps].append(w)
                        ready_fps = set()
                        for fps, group in framerate_groups.items():
                            now = time.perf_counter()
                            if any(now - w.last_tick >= 1.0 / fps for w in group):
                                ready_fps.add(fps)

                        itworlds = [w for w in self.worlds if not w.pause and w.scene.framerate in ready_fps and w.tick_ready()]

                        region = self._resolve_region()
                        for idx, world in enumerate(itworlds):
                            termx, termy = region[2], region[3]
                            if self.autoterm and world.autoterm:
                                world.scene.termx = termx
                                world.scene.termy = termy
                            if self.autodim and world.autodim:
                                world.scene.dimx = world.scene.termx
                                world.scene.dimy = world.scene.termy

                            for handle in world.ordered_handles():
                                if handle.pause: continue
                                update = handle.func('update')
                                if update:
                                    update()

                        dim_changed = any([w.scene.checkres() for w in self.worlds if not w.pause]) or changed_optimized
                        if dim_changed:
                            self._compositor.invalidate()

                        for idx, world in enumerate(itworlds):
                            for o in list(world.scene.objs):
                                if hasattr(o, 'physics'):
                                    if not world.pausephysics and not self.pausephysics and o.physics.dynamic:
                                        o.physics.physics()
                            world.scene.tick()
                            for o in list(world.scene.objs):
                                tf = getattr(o, 'transform', None)
                                if tf is not None:
                                    tf.tick()
                                jnt = getattr(o, 'joint', None)
                                if jnt is not None and not world.pausephysics and not self.pausephysics:
                                    jnt.step()
                                lgt = getattr(o, 'light', None)
                                if lgt is not None:
                                    lgt.step()

                            for handle in world.ordered_handles():
                                if handle.pause: continue
                                final = handle.func('final')
                                if final:
                                    final()

                            world.scene.flush()

                        region = self._resolve_region()
                        bounds = (self.term.width, self.term.height)
                        active = [] if self.pauserendering else [w for w in itworlds if not w.pauserendering]
                        frame = self._compositor.compose(
                            self.worlds, active, region, bounds,
                            self.bgcolor if self.outerbg else None,
                            self.autobg,
                        )
                        if frame:
                            if not hc: frame = '\0337' + frame + '\0338'
                            if self.vsync: frame = '\033[?2026h' + frame + '\033[?2026l'
                            sys.stdout.write(frame)
                            sys.stdout.flush()

                    now = time.perf_counter()
                    next_tick = min(
                        (min(w.last_tick for w in group) + 1.0 / fps
                         for fps, group in framerate_groups.items()),
                        default=now
                    )
                    sleep = next_tick - now
                    if sleep > self._latency and not self._pause:
                        tar = time.perf_counter() + sleep
                        while time.perf_counter() < tar: pass
                    elif self._pause or len(self.worlds) == 0:
                        with self._resume:
                            self._resume.wait_for(lambda: not self._pause and len(self.worlds) > 0)

                if self.inp:
                    self.inp.stop_all()
                    self.inp.cleanup()
                if self.sound: self.sound.close()
                if self.optimize: self.term.reset()
                if self.clearonstop:
                    if self._partial():
                        sys.stdout.write(Compositor.vacate(self._compositor.region, (-1, -1, 0, 0), (self.term.width, self.term.height)) + '\033[0m'
                                         if self._compositor.region else '')
                    else:
                        sys.stdout.write("\033[H\033[2J\033[3J")
                    sys.stdout.flush()
                self.undebug()

    def run(self, **kwargs):
        attempt(lambda: self.run_attempt(**kwargs), self._debug_trace)
