import os, sys, time, threading, traceback, contextlib, inspect
from pygments import highlight
from pygments.lexers.python import PythonConsoleLexer as TracebackLexer
from pygments.formatters.terminal import TerminalFormatter

def trace(exception, lexer=TracebackLexer, clear=True): # custom traceback for terminal
    try:
        if(clear):
            os.system('cls' if os.name=='nt' else 'clear')
            sys.stdout.write("\033[H\033[2J")
        exc = highlight("".join(traceback.format_exc())+'\n', lexer(), TerminalFormatter())
        sys.stdout.write(exc)
        sys.stdout.flush()
    except:
        raise exception
    
def attempt(func, catch=None, lexer=TracebackLexer, fatal=True, clear=True):
    try:
        return func()
    except Exception as e:
        catchexc = None
        if callable(catch):
            try:
                catch()
            except Exception as ce:
                catchexc = ce
        trace(e, lexer, clear)
        if catchexc: trace(catchexc, lexer, False)
        if fatal:
            try: input()
            except: pass
            try: os._exit(0)
            except: exit()
        
def getargs(func, args): # list of passable arguments to a function
    sig = inspect.signature(func)
    par = sig.parameters
    if any(p.kind == p.VAR_KEYWORD for p in par.values()):
        return args
    resargs = {k: v for k, v in args.items() if k in par}
    return resargs


#MODULES
def attemptimports():
    global obj, Terminal, inp, style
    from . import obj #scene objects module
    from ._vendor.blessed import Terminal #blessed terminal
    from .input_handler import inp #input module
    from .ascii_styler import style #ascii styler callable function
attempt(attemptimports)
    
#WORLD CLASS
class World():
    def __init__(self, session=None, autoreg=True):
        self.session = session
        self.handles = []
        self.scene = obj.Scene() # new object Scene instance
        self.last_tick = time.perf_counter()
        self.pause = False
        self.pausephysics = False
        if autoreg: attempt(self.register)

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
            self.handle = handle(**getargs(handle.__init__, self.handleargs))
            start = getattr(self.handle, 'start', None)
            if start: start(**getargs(start, self.handleargs))
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
            if self not in self.session.worlds: self.session.worlds.append(self)
            with self.session._resume:
                self.session._resume.notify_all()

    def unregister(self):
        if self.session is not None:
            self.session.worlds = [w for w in self.session.worlds if w is not self]

    def tick_ready(self):
        now = time.perf_counter()
        interval = 1.0 / self.scene.framerate
        if now - self.last_tick >= interval:
            self.last_tick += interval
            return True
        return False

#SESSION CLASS
class Session():
    def __init__(self):
        self.worlds = []
        self.World = lambda: World(self) # world factory
        self.term = Terminal() #term instance
        self.input = inp(self.term) #input class instance
        self.style = style #ascii styler function
        self.running = False #set False to stop the Session loop
        self._pause = False
        self.pausephysics = False
        self._resume = threading.Condition()

    @property
    def pause(self):
        return self._pause
    @pause.setter
    def pause(self, value):
        self._pause = value
        if not value:
            with self._resume:
                self._resume.notify_all()

    def run_attempt(self, optimize: bool = True, autodim: bool = True, autobg: bool = True, clearonstop: bool = True):
        if(not self.running):
            self.running = True
            with contextlib.ExitStack() as stack:
                if optimize: # terminal optimalization context
                    stack.enter_context(self.term.fullscreen())
                    stack.enter_context(self.term.cbreak())
                    stack.enter_context(self.term.hidden_cursor())
                    
                while self.running: # the central loop
                    if(not self._pause):
                        #-------------TODO: THE CENTRAL LOOP
                        for world in list(self.worlds): # worlds loop
                            if world.pause or not world.tick_ready():
                                continue
                            if(autodim): # dimx, dimy adaptation to terminal
                                world.scene.dimx = self.term.width
                                world.scene.dimy = self.term.height
                            for handle in list(world.handles): # handles loop
                                if handle.pause: continue
                                update = getattr(handle.handle, 'update', None)
                                if update: # update function
                                    update(**getargs(update, handle.handleargs))
                            for o in world.scene.objs: # objects loop
                                if not world.pausephysics and not self.pausephysics and o.dynamic:
                                    o.physics()
                                o.render() # framebuffer compositor
                            sys.stdout.flush() # framebuffer flush
                    now = time.perf_counter()
                    next_tick = min(
                        (w.last_tick + 1.0 / w.scene.framerate for w in self.worlds if not w.pause),
                        default=now
                    )
                    sleep = next_tick - now
                    if sleep > 0 and not self._pause:
                        time.sleep(sleep) # loop tick
                    else:
                        with self._resume: # contextual wait
                            self._resume.wait_for(lambda: not self._pause and len(self.worlds) > 0)

                if optimize: self.term.reset() # terminal optimalization reset
                if clearonstop: os.system('cls' if os.name=='nt' else 'clear') # console clear wait

    def run(self, optimize: bool = True, autodim: bool = True, autobg: bool = True, clearonstop: bool = True):
        attempt(lambda: self.run_attempt(optimize=optimize, autodim=autodim, autobg=autobg, clearonstop=clearonstop), self.term.reset)

