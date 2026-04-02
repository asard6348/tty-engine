import keyboard
from blessed import Terminal
term = Terminal()

class inp():
    def __init__(self):
        self.handlers = []
    def hook(self, key, func):
        handler = keyboard.on_press_key(key, lambda e: func(e))
        self.handlers.append(handler)
        return handler
    def unhook(self, handler):
        try:
            keyboard.unhook_key(handler)
            if handler in self.handlers:
                self.handlers.remove(handler)
        except (ValueError, KeyError):
            pass
    def held(self, key):
        return keyboard.is_pressed(key)
    def reset(self):
        for h in self.handlers:
            self.unhook(h)
    
