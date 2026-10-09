import os, sys, time, threading, traceback, contextlib, inspect, ctypes, re

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
    global scene, Terminal, inp, Styler
    from . import scene
    from blessed import Terminal
    from .input_handler import inp
    from .ascii_styler import Styler
attempt(attemptimports)

#WINDOWS INTIALIZATION
def universal_init():
    if os.name == 'nt':
        hOut = ctypes.windll.kernel32.GetStdHandle(-11)
        dwMode = ctypes.c_uint32()
        ctypes.windll.kernel32.GetConsoleMode(hOut, ctypes.byref(dwMode))
        ctypes.windll.kernel32.SetConsoleMode(hOut, dwMode.value | 0x0004)
attempt(universal_init)

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
            }
            self.handle = handle(**getargs(handle, self.handleargs))
            if not hasattr(self.handle, 'priority'):
                self.priority = 0
            start = getattr(self.handle, 'start', None)
            self.startargs = getargs(start, self.handleargs)
            self.world.handles.append(self)
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

    def launch(self, handle, safe=True):
        return (attempt(lambda: self.Handle(handle, self))
                if safe else self.Handle(handle, self))

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
    APIS = {'inp': True, 'style': True}
    SETTINGS = {'pausephysics': False, 'pauserendering': False, 'optimize': True, 'mouse': True, 'vsync': True,
                'autoterm': True, 'autodim': True, 'autobg': True, 'outerbg': True, 'clearonstop': True, 'autofps': True}

    def __init__(self, watchfocus=True, trackmotion=True, **kwargs):
        unknown = [k for k in kwargs if k not in self.APIS and k not in self.SETTINGS]
        if unknown:
            raise TypeError(f"Session() got unexpected keyword argument(s): {', '.join(unknown)}")
        self.worlds = []
        self.World = lambda front=True, **kwargs: World(session=self, autoreg=True, front=front, **kwargs)
        self.term = Terminal()
        self.apis = {name: kwargs.get(name, default) for name, default in self.APIS.items()}
        self.inp = inp(term=self.term, watchfocus=watchfocus, trackmotion=trackmotion) if self.apis['inp'] else None
        self.fill = Styler.fill
        self.running = False
        self._pause = False
        self._latency = max(latency())
        self._termxoffset = 0
        self._termyoffset = 0
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
    def termxoffset(self):
        return self._termxoffset
    @termxoffset.setter
    def termxoffset(self, value):
        delta = value - self._termxoffset
        for w in self.worlds:
            w.scene.dimxoffset += delta
        self._termxoffset = value

    @property
    def termyoffset(self):
        return self._termyoffset
    @termyoffset.setter
    def termyoffset(self, value):
        delta = value - self._termyoffset
        for w in self.worlds:
            w.scene.dimyoffset += delta
        self._termyoffset = value

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

                while self.running:
                    if changed_optimized: changed_optimized = False
                    if self.optimize and not is_optimized:
                        opt_stack.enter_context(self.term.fullscreen())
                        opt_stack.enter_context(self.term.cbreak())
                        opt_stack.enter_context(self.term.hidden_cursor())
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
                        fillbuffer = ""
                        removebuffer = ""
                        drawbuffer = ""

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

                        for idx, world in enumerate(itworlds):
                            termx = self.term.width
                            termy = self.term.height
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
                            if self.outerbg:
                                fillbuffer += self.fill(
                                    self.bgcolor,
                                    self.term.width,
                                    self.term.height,
                                )
                            if self.autobg:
                                for world in self.worlds:
                                    if world.pause: continue
                                    if world.autobg:
                                        fillbuffer += self.fill(
                                            world.scene.bgcolor,
                                            world.scene.dimx,
                                            world.scene.dimy,
                                            world.scene.dimxoffset,
                                            -world.scene.dimyoffset,
                                            world.scene.termx,
                                            world.scene.termy,
                                        )

                        for idx, world in enumerate(itworlds):
                            for o in list(world.scene.objs):
                                if hasattr(o, 'physics'):
                                    if not world.pausephysics and not self.pausephysics and o.physics.dynamic:
                                        o.physics.physics()

                            for handle in world.ordered_handles():
                                if handle.pause: continue
                                final = handle.func('final')
                                if final:
                                    final()

                            world.scene.flush()

                            world_layer = getattr(world, 'layer', 0)
                            exclude_rects = [
                                (
                                    w.scene.dimxoffset + 1,
                                    -w.scene.dimyoffset + 1,
                                    w.scene.dimxoffset + w.scene.dimx,
                                    -w.scene.dimyoffset + w.scene.dimy,
                                )
                                for w in self.worlds
                                if not w.pause and getattr(w, 'layer', 0) > world_layer
                            ]
                            objs = sorted(world.scene.objs, key=lambda ko: ko.rendering.z if hasattr(ko, 'rendering') else 0)
                            for o in list(objs):
                                if hasattr(o, 'rendering'):
                                    if not world.pauserendering and not self.pauserendering:
                                        o.rendering._markdirty()
                                        rem, draw = o.rendering.render(False, True, exclude_rects)
                                        removebuffer += rem
                                        if o.rendering.show: drawbuffer += draw
                            removebuffer += ''.join(world.scene.discards)
                            world.scene.discards.clear()

                        framebuffer = '\033[?2026h' if self.vsync else ''
                        framebuffer += removebuffer + fillbuffer + drawbuffer
                        framebuffer += '\033[?2026l' if self.vsync else ''
                        sys.stdout.write(framebuffer)
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
                if self.optimize: self.term.reset()
                if self.clearonstop:
                    sys.stdout.write("\033[H\033[2J\033[3J")
                    sys.stdout.flush()

    def run(self, **kwargs):
        attempt(lambda: self.run_attempt(**kwargs), lambda: contextlib.ExitStack().close())
