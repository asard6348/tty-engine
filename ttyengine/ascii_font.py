# TODO: DYNAMIC TERMINAL ZOOMING
import json, os

class font():
    def __init__(self):
        self._fontsize = None

    @property
    def fontsize(self):
        return self._fontsize
    @fontsize.setter
    def fontsize(self, value):
        if not isinstance(value, (int,float)): return

        if(os.name == "nt"):
            path = os.path.expandvars(r'%LOCALAPPDATA%\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.json')
            if not os.path.exists(path):
                path = os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\Windows Terminal\settings.json')
            with open(path, 'r+', encoding='utf-8') as f:
                settings = json.load(f)
                settings['profiles']['defaults']['fontSize'] = value
                f.seek(0)
                json.dump(settings, f, indent=4)
                f.truncate()
            self._fontsize = value
