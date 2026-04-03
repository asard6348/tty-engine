import os, threading, time, traceback
global ex;ex=False

try:
    # OBJECT CLASS
    import game_obj as gobj
    # TERMINAL OPTIMALIZATION AND OBJECT SETTINGS
    from blessed import Terminal
    term = Terminal()
    os.system('cls' if os.name=='nt' else 'clear') # console clear
    def termopt():
        with term.fullscreen(), term.cbreak(), term.hidden_cursor():
            while True: 
                if(term.width-1 != gobj.dimx or term.height-1 != gobj.dimy):
                    print(term.clear)
                gobj.dimx = term.width-1; gobj.dimy = term.height-1
                time.sleep(1/gobj.framerate)
    termoptth=threading.Thread(target=termopt,daemon=True)
    termoptth.start()
    
    # GAME
    from game_main import main
    game = main()
    try:
        game.start(gobj)
    except Exception:
        traceback.print_exc()
        pass
    while True:
        try:
            game.update(gobj)
        except Exception:
            traceback.print_exc()
            pass
        time.sleep(1/gobj.framerate)

except Exception:
    print(term.clear)
    traceback.print_exc()
    input()
finally:
    if(ex==False): time.sleep(9999)
