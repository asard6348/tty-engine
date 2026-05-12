import os, sys, time, threading, traceback, contextlib, inspect, ctypes
from pygments import highlight
from pygments.lexers.python import PythonConsoleLexer as TracebackLexer
from pygments.formatters.terminal import TerminalFormatter

def trace(exception, lexer=TracebackLexer, clear=True, out=sys.stdout.write, flush=sys.stdout.flush): # custom traceback for terminal
    try:
        if(clear):
            os.system('cls' if os.name=='nt' else 'clear')
            if out: out("\033[H\033[2J")
        if out:
            exc = highlight("".join(traceback.format_exc())+'\n', lexer(), TerminalFormatter())
            out(exc)
            if flush: flush()
    except:
        raise exception
    
def attempt(func, catch=None, lexer=TracebackLexer, fatal=True, clear=True, reset=True, out=sys.stdout.write, flush=sys.stdout.flush): # traceback support for terminal relation
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
        
def getargs(func, args): # list of passable arguments to a function
    if not callable(func): return {}
    sig = inspect.signature(func)
    par = sig.parameters
    if any(p.kind == p.VAR_KEYWORD for p in par.values()):
        return args
    resargs = {k: v for k, v in args.items() if k in par}
    return resargs

def latency(samples=1000): # os task latency statistic
    latencies = []
    for _ in range(samples):
        start = time.perf_counter()
        time.sleep(0)
        end = time.perf_counter()
        latencies.append(end - start)
    return latencies


#MODULES
def attemptimports():
    global scene, Terminal, inp, style, fill
    from . import scene #scene objects module
    from ._vendor.blessed import Terminal #blessed terminal
    from .input_handler import inp #input module
    from .ascii_styler import style, fill #ascii styler callable function
attempt(attemptimports)

#WINDOWS INTIALIZATION
def universal_init():
    if os.name == 'nt':
        hOut = ctypes.windll.kernel32.GetStdHandle(-11) # STD_OUTPUT_HANDLE
        dwMode = ctypes.c_uint32()
        ctypes.windll.kernel32.GetConsoleMode(hOut, ctypes.byref(dwMode))
        # 0x0004 is ENABLE_VIRTUAL_TERMINAL_PROCESSING
        ctypes.windll.kernel32.SetConsoleMode(hOut, dwMode.value | 0x0004)
attempt(universal_init)
    
#WORLD CLASS
class World():
    def __init__(self, session=None, autoreg=True, front=True, **kwargs):
        self.session = session
        self.handles = []
        self.scene = scene.Scene() # new object Scene instance
        self.layer = 0
        self.last_tick = time.perf_counter()
        self.pause = False
        self.pausephysics = False
        self.pauserendering = False
        self.autoterm = True
        self.autodim = True
        self.autobg = True
        self.autofps = True if session is None else session.autofps
        for setting, val in kwargs.items():
            if val is not None: setattr(self, setting, val)
        if not session is None: self.scene.bgcolor = self.session.bgcolor
        if autoreg: attempt(self.register)
        if front: self.front()
        else: self.back()
        if self.autofps: self.scene.maxframerate = 1/max(latency())

    class Handle(): # scene behaviour handle
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
            start = getattr(self.handle, 'start', None)
            self.startargs = getargs(start, self.handleargs)
            if start: start(**self.startargs)
            self.updateargs = getargs(getattr(self.handle, 'update', None), self.handleargs)
            self.finalargs = getargs(getattr(self.handle, 'final', None), self.handleargs)
            self.world.handles.append(self)
        def cancel(self):
            self.world.handles = [h for h in self.world.handles if h is not self]
            
    def launch(self, handle, safe=True):
        return (attempt(lambda: self.Handle(handle, self))
                if safe else self.Handle(handle, self))

    def cancel(self, handle):
        self.handles = [h for h in self.handles if h is not handle]

    def register(self):
        if self.session is not None:
            if self not in self.session.worlds:
                self.session.worlds.append(self)
                self.session.worlds = sorted(list(self.session.worlds), key=lambda w: getattr(w, 'layer', 0))
                with self.session._resume:
                    self.session._resume.notify_all()

    def unregister(self):
        if self.session is not None:
            self.session.worlds = [w for w in self.session.worlds if w is not self]

    def front(self):
        if self.session is not None:
            ll = None
            l = 0
            for w in self.session.worlds:
                if ll is None:
                    ll = w.layer
                    l = w.layer
                    continue
                if w.layer > ll: l = w.layer
            self.layer = l + 1

    def back(self):
        if self.session is not None:
            ll = None
            l = 0
            for w in self.session.worlds:
                if ll is None:
                    ll = w.layer
                    l = w.layer
                    continue
                if w.layer < ll: l = w.layer
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
    def __init__(self, watchfocus=True, trackmotion=True):
        self.worlds = []
        self.World = lambda front=True, **kwargs: World(session=self, autoreg=True, front=front, **kwargs)
        self.term = Terminal()
        self.inp = inp(term=self.term, watchfocus=watchfocus, trackmotion=trackmotion)
        self.fill = fill
        self.running = False
        self._pause = False
        self.pausephysics = False
        self.pauserendering = False
        self._termxoffset = 0
        self._termyoffset = 0
        bg = self.term.get_bgcolor(bits=8)
        self.bgcolor = bg if bg != (-1, -1, -1) else (0, 0, 0)
        fg = self.term.get_fgcolor(bits=8)
        self.fgcolor = fg if fg != (-1, -1, -1) else (204, 204, 204)
        self._resume = threading.Condition()
        # DEFAULT SETTINGS
        self.optimize = True
        self.mouse = True
        self.vsync = True
        self.autoterm = True
        self.autodim = True
        self.autobg = True
        self.outerbg = True
        self.clearonstop = True
        self.autofps = True

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
        args = list(args)
        if 'bg' not in kwargs:
            bg = args.pop(7) if len(args) > 7 else self.bgcolor
        else:
            bg = kwargs.pop('bg')
        if 'fg' not in kwargs:
            fg = args.pop(8) if len(args) > 8 else self.fgcolor
        else:
            fg = kwargs.pop('fg')
        return style(*args, bg=bg, fg=fg, **kwargs)

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

                    tickdelta = 0
                    if(not self._pause):
                        bef = time.perf_counter()
                        self.inp.update()
                        fillbuffer = ""
                        removebuffer = ""
                        drawbuffer = ""

                        dim_changed = any([w.scene.checkres() for w in self.worlds]) or changed_optimized
                        if self.outerbg and dim_changed:
                            fillbuffer += self.fill(
                                self.bgcolor,
                                self.term.width,
                                self.term.height,
                            )

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

                        for idx, world in enumerate(self.worlds):
                            if world.pause: continue
                            
                            termx = self.term.width
                            termy = self.term.height
                            if self.autoterm and world.autoterm:
                                world.scene.termx = termx
                                world.scene.termy = termy
                            if self.autodim and world.autodim:
                                world.scene.dimx = world.scene.termx
                                world.scene.dimy = world.scene.termy

                            if self.autobg and world.autobg and dim_changed:
                                fillbuffer += self.fill(
                                    world.scene.bgcolor,
                                    world.scene.dimx,
                                    world.scene.dimy,
                                    world.scene.dimxoffset,
                                    -world.scene.dimyoffset,
                                    world.scene.termx,
                                    world.scene.termy,
                                )

                            should_tick = world.scene.framerate in ready_fps and world.tick_ready()
                            if not should_tick: continue

                            for handle in list(world.handles):
                                if handle.pause: continue
                                update = getattr(handle.handle, 'update', None)
                                if update:
                                    update(**handle.updateargs)

                            for o in world.scene.objs:
                                if hasattr(o, 'physics'):
                                    if not world.pausephysics and not self.pausephysics and o.physics.dynamic:
                                        o.physics.physics()

                            for handle in list(world.handles):
                                if handle.pause: continue
                                final = getattr(handle.handle, 'final', None)
                                if final:
                                    final(**handle.finalargs)
                            
                            for o in world.scene.objs:
                                if hasattr(o, 'rendering'):
                                    if not world.pauserendering and not self.pauserendering:
                                        o.rendering._markdirty()
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
                                        rem, draw = o.rendering.render(False, True, exclude_rects)
                                        removebuffer += rem
                                        if o.rendering.show: drawbuffer += draw
                            world.scene.flush()

                        framebuffer = '\033[?2026h' if self.vsync else ''
                        framebuffer += removebuffer + fillbuffer + drawbuffer
                        framebuffer += '\033[?2026l' if self.vsync else ''
                        sys.stdout.write(framebuffer)
                        sys.stdout.flush()
                        tickdelta = -(time.perf_counter() - bef)

                    now = time.perf_counter()
                    next_tick = min(
                        (min(w.last_tick for w in group) + 1.0 / fps
                         for fps, group in framerate_groups.items()),
                        default=now
                    )
                    sleep = next_tick - now - tickdelta
                    if sleep > max(latency()) and not self._pause:
                        tar = time.perf_counter() + sleep
                        while time.perf_counter() < tar: pass
                    elif self._pause or len(self.worlds) == 0:
                        with self._resume:
                            self._resume.wait_for(lambda: not self._pause and len(self.worlds) > 0)

                self.inp.stop_all()
                self.inp.cleanup()
                if self.optimize: self.term.reset()
                if self.clearonstop: os.system('cls' if os.name == 'nt' else 'clear')

    def run(self, **kwargs):
        attempt(lambda: self.run_attempt(**kwargs), lambda: contextlib.ExitStack().close())

