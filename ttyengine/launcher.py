import os, sys, time, threading, traceback, contextlib, inspect, ctypes, re, socket, subprocess, tempfile, shlex
from types import SimpleNamespace
from . import ansi

def highlight_traceback(tb_str: str) -> str:
    if not ansi.color_enabled():
        return tb_str
    RESET, BOLD, RED, GREEN, YELLOW, CYAN, MAGENTA = (
        ansi.RESET, ansi.BOLD, ansi.sgr(91), ansi.sgr(92), ansi.sgr(93), ansi.sgr(96), ansi.sgr(95)
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
            if out: out(ansi.wrap_all(ansi.CLEAR_ALL))
        if out:
            tb_raw = "".join(traceback.format_exc()) + '\n'
            exc = highlight_traceback(tb_raw)
            out(ansi.wrap_all(exc))
            if flush: flush()
    except:
        raise exception

def attempt(func, catch=None, lexer=None, fatal=True, clear=True, reset=True, out=sys.stdout.write, flush=sys.stdout.flush):
    try:
        return func()
    except Exception as e:
        if reset and fatal:
            try: out(ansi.wrap(ansi.FULL_RESET))
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

DEBUG_HOLD = ansi.osc('777;hold')
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
out.write(__OPEN__)
out.flush()
sock = socket.socket()
sock.connect(("127.0.0.1", __PORT__))
decode = codecs.getincrementaldecoder("utf-8")("replace").decode
hold = False
marker = __HOLD__
while True:
    data = sock.recv(65536)
    if not data:
        break
    text = decode(data)
    if marker in text:
        text = text.replace(marker, "")
        hold = True
    out.write(text)
    out.flush()
out.write(__CLOSE__)
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
    return ansi.HOME + (ansi.ERASE_LINE + '\n').join(lines) + ansi.ERASE_LINE + ansi.ERASE_BELOW

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
from . import scene
from .compositor import Compositor
from .terminal import Terminal
from .input_handler import inp
from .ascii_styler import Styler
from .sound import Mixer

#WINDOWS INTIALIZATION
def universal_init():
    if os.name == 'nt':
        hOut = ctypes.windll.kernel32.GetStdHandle(-11)
        dwMode = ctypes.c_uint32()
        ctypes.windll.kernel32.GetConsoleMode(hOut, ctypes.byref(dwMode))
        ctypes.windll.kernel32.SetConsoleMode(hOut, dwMode.value | 0x0004)
try:
    universal_init()
except Exception:
    pass

HANDLE_STATES = ('start', 'update', 'final')

_SPIN_MARGIN = 0.016 if sys.platform == 'win32' else 0.002

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
                'simulation': getattr(self.world.session, 'simulation', None),
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

#SESSION CLASS
class Session():
    APIS = {'inp': True, 'style': True, 'sound': True}
    SETTINGS = {'pausephysics': False, 'pauserendering': False, 'optimize': True, 'mouse': True, 'vsync': True,
                'autoterm': True, 'autodim': True, 'autobg': True, 'outerbg': True, 'clearonstop': True, 'autofps': True,
                'termxoffset': 0, 'termyoffset': 0, 'termwidth': None, 'termheight': None,
                'fullscreen': None, 'hidecursor': None, 'no_color': None}

    def __init__(self, watchfocus=True, trackmotion=True, ffmpeg=None, **kwargs):
        unknown = [k for k in kwargs if k not in self.APIS and k not in self.SETTINGS]
        if unknown:
            raise TypeError(f"Session() got unexpected keyword argument(s): {', '.join(unknown)}")
        self.worlds = []
        self.simulation = None
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
            opening = ((ansi.osc('0;' + title) if title is not None else '')
                       + ansi.mode(1049, False) + ansi.mode(1049, True) + ansi.mode(25, False) + ansi.CLEAR + ansi.HOME)
            script = (DEBUG_RECEIVER
                      .replace('__OPEN__', repr(opening))
                      .replace('__HOLD__', repr(DEBUG_HOLD))
                      .replace('__CLOSE__', repr(ansi.mode(25, True)))
                      .replace('__PORT__', str(server.getsockname()[1]))
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
        self._debug_send(ansi.CLEAR_ALL + highlight_traceback(traceback.format_exc()) + DEBUG_HOLD)

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

    def _footprint(self, region):
        x, y, w, h = region
        if not self.worlds:
            return region
        right = bottom = 0
        for world in self.worlds:
            sc = world.scene
            termx, termy = (w, h) if self.autoterm and world.autoterm else (sc.termx, sc.termy)
            dimx, dimy = (termx, termy) if self.autodim and world.autodim else (sc.dimx, sc.dimy)
            view = Compositor.view(SimpleNamespace(
                termx=termx, termy=termy, dimx=dimx, dimy=dimy,
                dimxoffset=sc.dimxoffset, dimyoffset=sc.dimyoffset,
            ), w, h)
            right = max(right, view[2])
            bottom = max(bottom, view[3])
        return (x, y, right, bottom)

    def _partial(self):
        if self.region != (0, 0, None, None):
            return True
        full = self._resolve_region()
        return self._footprint(full) != full

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

                fs = hc = not self._partial()
                while self.running:
                    if changed_optimized: changed_optimized = False
                    if self.optimize and not is_optimized:
                        fs = self.fullscreen if self.fullscreen is not None else not self._partial()
                        hc = self.hidecursor if self.hidecursor is not None else True
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
                            world.scene.tick(not (world.pausephysics or self.pausephysics))

                            for handle in world.ordered_handles():
                                if handle.pause: continue
                                final = handle.func('final')
                                if final:
                                    final()

                            world.scene.flush()

                        region = self._footprint(self._resolve_region())
                        bounds = (self.term.width, self.term.height)
                        active = [] if self.pauserendering else [w for w in itworlds if not w.pauserendering]
                        self._compositor.no_color = self.no_color
                        frame = self._compositor.compose(
                            self.worlds, active, region, bounds,
                            self.bgcolor if self.outerbg else None,
                            self.autobg,
                        )
                        if frame:
                            if not (hc and fs): frame = ansi.wrap(ansi.SAVE_CURSOR) + frame + ansi.wrap(ansi.RESTORE_CURSOR)
                            if self.vsync: frame = ansi.wrap(ansi.SYNC_BEGIN) + frame + ansi.wrap(ansi.SYNC_END)
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
                        coarse = sleep - _SPIN_MARGIN
                        if coarse > 0: time.sleep(coarse)
                        while time.perf_counter() < tar: pass
                    elif self._pause or len(self.worlds) == 0:
                        with self._resume:
                            self._resume.wait_for(lambda: not self._pause and len(self.worlds) > 0)

                if self.inp:
                    self.inp.stop_all()
                    self.inp.cleanup()
                if self.sound: self.sound.close()
                if self.clearonstop:
                    if self._partial():
                        sys.stdout.write(Compositor.vacate(self._compositor.region, (-1, -1, 0, 0), (self.term.width, self.term.height)) + ansi.wrap(ansi.RESET)
                                         if self._compositor.region else '')
                    else:
                        sys.stdout.write(ansi.wrap_all(ansi.CLEAR_ALL))
                    sys.stdout.flush()
                self.undebug()

    def run(self, **kwargs):
        attempt(lambda: self.run_attempt(**kwargs), self._debug_trace)

class Simulation():
    def __init__(self, *sessions):
        self.sessions = []
        for session in sessions:
            self.add(session)

    @property
    def worlds(self):
        return [w for s in self.sessions for w in s.worlds]

    @property
    def handles(self):
        return [h for w in self.worlds for h in w.handles]

    @property
    def scenes(self):
        return [w.scene for w in self.worlds]

    def __getitem__(self, index):
        return self.sessions[index]

    def __len__(self):
        return len(self.sessions)

    def __iter__(self):
        return iter(self.sessions)

    def add(self, session):
        session.simulation = self
        if session not in self.sessions:
            self.sessions.append(session)
        return session

    def session(self, **kwargs):
        return self.add(Session(**kwargs))

    def _session(self, ref=None):
        if ref is None:
            return self.sessions[-1] if self.sessions else self.session()
        if isinstance(ref, Session):
            return self.add(ref)
        return self.sessions[ref]

    def world(self, session=None, front=True, **kwargs):
        return self._session(session).World(front=front, **kwargs)

    def _world(self, ref=None, session=None):
        if isinstance(ref, World):
            return ref
        target = self._session(session)
        if ref is None:
            return target.worlds[-1] if target.worlds else target.World()
        return target.worlds[ref]

    def launch(self, *handles, world=None, session=None, safe=True, state='start'):
        target = self._world(world, session)
        return [target.launch(handle, safe=safe, state=state) for handle in handles]

    def run(self, session=None, **settings):
        self._session(session).run(**settings)
        return self

    def stop(self):
        for session in self.sessions:
            session.running = False

def start(*launch, **settings):
    simulation = Simulation()
    simulation.session()
    if launch:
        simulation.world()
        simulation.launch(*launch)
    simulation.run(**settings)
    return simulation
