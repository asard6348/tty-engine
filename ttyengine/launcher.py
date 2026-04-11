import os, sys, threading, time, traceback, subprocess, ctypes, queue, inspect
from pygments import highlight
from pygments.lexers.python import PythonConsoleLexer as PythonTracebackLexer
from pygments.formatters.terminal import TerminalFormatter
from .input_handler import inp #input module
inp = inp() #input class instance
from .ascii_styler import style #ascii styler callable function
global ex, gobj, term, error
ex=False
error=queue.Queue()

def launch(main):
    global ex, gobj, term, error
    try:
        # TERMINAL AND OBJECT CLASS
        global gobj, term, acbg, error
        from . import obj; gobj = obj
        from blessed import Terminal
        term = Terminal()
        os.system('cls' if os.name=='nt' else 'clear') # console clear wait
        acbg = None
        def updcolor(de=False): # terminal recolor
            global gobj, term, acbg
            if de: acbg = None
            if(acbg != gobj.bgcolor):
                acbg = gobj.bgcolor
                bg=f"\033[48;2;{gobj.bgcolor[0]};{gobj.bgcolor[1]};{gobj.bgcolor[2]}m"
                recolor = ""
                for _ in range(term.height):
                    recolor += bg + (" " * term.width) + "\n"
                sys.stdout.write("\033[H" + recolor + "\033[H")
                sys.stdout.flush()
        def termopt(error, gobj, updcolor): # terminal optimalization
            try:
                with term.fullscreen(), term.cbreak(), term.hidden_cursor():
                    acbg = None
                    while gobj.derror[0] == False:
                        try:
                            err = error.get_nowait()
                            return
                        except queue.Empty:
                            pass
                        if(term.width != gobj.dimx or term.height != gobj.dimy):
                            sys.stdout.write(term.clear)
                            updcolor(True)
                        gobj.dimx = term.width; gobj.dimy = term.height
                        sys.stdout.flush()
                        time.sleep(1/gobj.framerate)
            except Exception as e:
                error.put(e)
        termoptth=threading.Thread(target=termopt,daemon=True,args=(error, gobj, updcolor))
        termoptth.start()
        '''from .ascii_font import font # font configuration module
        font = font() # font instance
        font.fontsize = 12'''
        '''def do():
            while True:
                for x in range(0,5):
                    font.fontsize -= 0.5
                    time.sleep(0.1)
                for x in range(0,5):
                    font.fontsize += 0.5
                    time.sleep(0.1)
        threading.Thread(target=do,daemon=True).start()'''
        
        # MAIN
        game = main()
        gameargs = {
            "gobj": gobj, 
            "inp": inp, 
            "style": style, 
            "term": term
        }
        start = getattr(game, 'start', None)
        update = getattr(game, 'update', None)
        def getargs(func, args):
            sig = inspect.signature(func)
            par = sig.parameters
            if any(p.kind == p.VAR_KEYWORD for p in par.values()):
                return args
            resargs = {k: v for k, v in args.items() if k in par}
            return resargs
        if(callable(start)):
            try:
                updcolor()
                start(**getargs(start, gameargs))
            except Exception as e:
                raise e
        while gobj.derror[0] == False:
            try:
                err = error.get_nowait()
                raise err
            except queue.Empty:
                pass
            try:
                updcolor()
                if(callable(update)):
                    update(**getargs(update, gameargs))
                if(gobj.derror[0] == False):
                    time.sleep(1/gobj.framerate)
            except Exception as e:
                raise e
        try:
            for x in gobj.derror:
                if isinstance(x, Exception):
                    raise x
        except Exception as e:
            raise e

    except Exception as e:
        try:
            gobj.derror[0] = True
            term.reset()
        except Exception:
            pass
        try:
            os.system('cls' if os.name=='nt' else 'clear')
            time.sleep(1/gobj.framerate)
        except:
            pass
        sys.stdout.write("\033[H\033[2J")
        exc = highlight("".join(traceback.format_exc()), PythonTracebackLexer(), TerminalFormatter())
        sys.stdout.write(exc)
        sys.stdout.flush()
        
    finally:
        if(ex==False):
            input()
            os._exit(1)
