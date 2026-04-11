#MODULES
import os, sys, time, subprocess, threading, textwrap, traceback, socket

class main():
    def __init__(self):   #VARIABLES
        self.plrspeed = 1
        self.plrmaxspeed = 10
        self.plrspeedfriction = 0.9
        self.plrjumppower = 10
        self.camrange = 10
        self.void = -100

        #DEBUGGER
        self.debugger = [None]
        self.dinfo = []
        def debug(debugger, dinfo):
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.bind(('127.0.0.1', 0))
            port = server.getsockname()[1]
            server.listen(1)
            reset = "\033[?1049l\033[?1049h\033[?25l\033[2J\033[H"
            script = textwrap.dedent(f"""
                import sys, socket, ctypes
                if sys.platform == "win32":
                    kernel32 = ctypes.windll.kernel32
                    handle = kernel32.GetStdHandle(-11)
                    kernel32.SetConsoleMode(handle, 7)
                sys.stdout.write("{reset}")
                sys.stdout.flush()
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect(('127.0.0.1', {port}))
                f = sock.makefile('r', buffering=1)
                for frame in f:
                    sys.stdout.write(frame)
                    sys.stdout.flush()
            """).strip()
            if sys.platform == "win32":
                try:
                    proc = subprocess.Popen(
                        ['conhost.exe', sys.executable, '-c', script],
                        creationflags=subprocess.CREATE_NEW_CONSOLE,
                        start_new_session=True
                    )
                except FileNotFoundError:
                    proc = subprocess.Popen(
                        [sys.executable, '-c', script],
                        creationflags=subprocess.CREATE_NEW_CONSOLE,
                        start_new_session=True
                    )
            elif sys.platform == "darwin":
                script_file = '/tmp/debugger_recv.py'
                with open(script_file, 'w') as f:
                    f.write(script)
                proc = subprocess.Popen(
                    ["osascript", "-e",
                     f'tell app "Terminal" to do script "python3 {script_file}"']
                )
            else:
                for term in ['x-terminal-emulator', 'gnome-terminal', 'xterm', 'konsole']:
                    try:
                        proc = subprocess.Popen([term, '-e', sys.executable, '-c', script])
                        break
                    except FileNotFoundError:
                        continue
            server.settimeout(5)
            try:
                conn, _ = server.accept()
            except socket.timeout:
                return
            pipe = conn.makefile('w', buffering=1)
            debugger[0] = proc
            from pygments import highlight
            from pygments.lexers.python import PythonConsoleLexer as PythonTracebackLexer
            from pygments.formatters.terminal import TerminalFormatter
            try:
                while True:
                    if proc is not None:
                        lines = "".join(dinfo).split("\n")
                        out = "\033[H"
                        for line in lines:
                            out += line + "\033[K\n"
                        pipe.write(out)
                        pipe.flush()
                    time.sleep(0.01)
            except Exception as e:
                pipe.write("\033[H\033[2J")
                exc = highlight(traceback.format_exc(), PythonTracebackLexer(), TerminalFormatter())
                pipe.write(exc)
                pipe.flush()
            finally:
                try:
                    pipe.write("\033[?25h")
                    pipe.flush()
                except Exception:
                    pass
                input()
                proc.kill()
        threading.Thread(target=debug, daemon=True, args=(self.debugger, self.dinfo)).start()
    
    def start(self, gobj, inp, style):    #START
        gobj.bgcolor = (30,0,0)
        obj = gobj.obj
        self.info = obj().create('Press "q" to quit. Hold "e" to rotate.',0,0, False, False)
        self.plr = obj().create(style(" O \n(|)\n | \n[ ]", color='blue'),0,0,True,True,0,True)
        #self.plr.text = "OOOOOOO\n OOOOOO\n OOOOOO\n OOOOOOOOOOO"
        #self.plr.text += "\n[ ]"*5
        self.enemy = obj().create("OOOOOO\n"*4,25,-(gobj.dimy+1), bounciness=1)
        self.enemy.y += self.enemy.ylen()
        self.enemy.dynamic = True; self.enemy.hitbox = False
        self.ground = obj().create("██████████████████████████████████████████████████████████████████████████████", -15, -(gobj.dimy+1))
        self.floor = obj().create("OOOOOO\n OOOOO",self.enemy.x,self.enemy.y+6)
        self.peak = obj().create("O\n"*20,self.ground.x-55,self.ground.y-6)
        def p(txt,x=0,y=0):
            return obj().create(txt,x,y)
        p1=p("OOOOOOOOO",self.ground.x-20,self.ground.y)
        p2=p("OOOOOOOOO\nOOOOOOOOO",p1.x-20,p1.y+1)
        p3=p("OOOOOOOOO\nOOOOOOOOO",p2.x-30,p2.y-5)
        ip=20
        for i in range(0,6):
            p("OOOOOOOOO", p3.x-ip,p3.y)
            ip+=20

        def onpress(gobj): # key press events
            def w():
                self.plr.yvel += self.plrjumppower if self.plr.touch[1] else 0
            def q():
                inp.reset()
                os._exit(0)
            def f():
                self.enemy.x = self.plr.x - self.plr.xlen()*2
                self.enemy.y = self.plr.y + self.plr.ylen()+1
                self.enemy.rotation = -90
            
            for but in [w,q,f]:
                inp.hook(but.__name__,but)
        onpress(gobj)

    def update(self, gobj, inp, style):   #UPDATE
        def whilepressed(gobj): # key hold events
            def k(but):
                return inp.held(but)
            if(k('e')):
                self.plr.avel += 1
            #if(k('w')):
                #gobj.camy+=0.1
                #self.plr.yvel += self.plrspeed if abs(self.plr.yvel) < self.plrmaxspeed else 0
            #if(k('s')):
                #gobj.camy-=0.1
                #self.plr.yvel += -self.plrspeed if abs(self.plr.xvel) < self.plrmaxspeed else 0
            if(k('d')):
                #gobj.camx+=0.1
                self.plr.xvel += self.plrspeed if abs(self.plr.xvel) < self.plrmaxspeed else 0
            if(k('a')):
                #gobj.camx-=0.1
                self.plr.xvel += -self.plrspeed if abs(self.plr.xvel) < self.plrmaxspeed else 0
        whilepressed(gobj)
        
        if(self.plr.y<self.void):
            self.plr.y=0;self.plr.x=0
        if(self.enemy.y<self.void):
            self.enemy.y=0;self.enemy.x=0
        self.plr.xvel *= self.plrspeedfriction
        #self.plr.yvel *= self.plrspeedfriction
        gobj.camx += (self.plr.x+self.plr.xc(self.plr.htext)-(gobj.dimx/2)-gobj.camx)/self.camrange#; gobj.camx = round(gobj.camx)
        gobj.camy += (self.plr.y-self.plr.yc(self.plr.htext)+(gobj.dimy/2)-gobj.camy)/self.camrange#; gobj.camy = round(gobj.camy)
        self.info.x = gobj.camx
        self.info.y = gobj.camy
        self.dinfo.clear()
        self.dinfo.extend([gobj.recomp.sub('', x) for x in gobj.dinfo])
        
#ENGINE LAUNCHER
from ttyengine import launcher
launcher.launch(main)
