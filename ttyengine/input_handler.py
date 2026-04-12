import threading, sys
from ._vendor import keyboard

class inp():
    def __init__(self, term=None, watchfocus=True):
        self.keyboard = keyboard
        self.lock = threading.Lock()
        self.wf = watchfocus
        self.focused = True
        self.term = term
    def _enable_focus_reporting(self):
        sys.stdout.write("\x1b[?1004h")
        sys.stdout.flush()
    def _disable_focus_reporting(self):
        sys.stdout.write("\x1b[?1004l")
        sys.stdout.flush()
    def _watch_focus(self):
        while self._term and self.wf:
            val = self._term.inkey(timeout=1)
            if not val:
                continue
            seq = str(val)
            if seq == "\x1b[I" or seq == "I":
                with self.lock:
                    self.focused = True
            elif seq == "\x1b[O" or seq == "O":
                with self.lock:
                    self.focused = False
    @property
    def term(self):
        return self._term
    @term.setter
    def term(self, value):
        self._term = value
        if value and self.wf:
            self._enable_focus_reporting()
            self.focus_monitor = threading.Thread(
                target=self._watch_focus, daemon=True
            )
            self.focus_monitor.start()
    def onpress(self, key, callback):
        def _guarded(event):
            with self.lock:
                is_focused = self.focused
            if is_focused:
                callback(event)
        self.keyboard.on_press_key(key, _guarded)
    def held(self, key):
        return self.keyboard.is_pressed(key) and self.focused
    def stop(self):
        self._disable_focus_reporting()
        self.keyboard.unhook_all()
