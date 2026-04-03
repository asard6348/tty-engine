import os, sys, subprocess, traceback
global kwargs
kwargs = {}
pas = False
if sys.platform == "win32":
    kwargs = {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
        "close_fds": True}
else:
    kwargs = {
        "start_new_session": True,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL}
    
parent = os.path.dirname(os.path.abspath(__file__))
target = os.path.join(parent, "engine/game_engine.py")
try:
    subprocess.Popen([sys.executable, target], shell=False, **kwargs)
    os._exit(0)
except Exception:
    traceback.print_exc()
    pas = True
    pass
finally:
    if(pas==True):
        while True:
            input()
    else:
        os._exit(0)
