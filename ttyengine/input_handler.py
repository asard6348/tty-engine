import time, threading
from ._vendor.pynput import keyboard

class inp():
    def __init__(self, term, gobj=None):
        self.term = term
        self.gobj = gobj
        self.hids = []
        self.pressed_keys = set()
        self.focused = True
        self.lock = threading.Lock()
        print("\033[?1004h", end="", flush=True)
        self.listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        self.listener.start()
        self.focus_monitor = threading.Thread(target=self._watch_focus, daemon=True)
        self.focus_monitor.start()
    def _watch_focus(self):
        while True:
            val = self.term.inkey(timeout=1)
            if not val:
                continue
            seq = str(val)
            if seq == "I":
                with self.lock:
                    self.focused = True
            elif seq == "O":
                with self.lock:
                    self.focused = False
                    self.pressed_keys.clear()
    def _normalize(self, key):
        try:
            return key.char
        except AttributeError:
            return str(key)
    def _on_press(self, key):
        with self.lock:
            if not self.focused:
                return
            key_str = self._normalize(key)
            self.pressed_keys.add(key_str)
            for hid in self.hids:
                if self._normalize(hid.key) == key_str:
                    hid.func()
    def _on_release(self, key):
        with self.lock:
            self.pressed_keys.discard(self._normalize(key))
    def held(self, key):
        with self.lock:
            return self._normalize(key) in self.pressed_keys
    def hook(self, key, func):
        hid = self.handlerid(key, func)
        with self.lock:
            self.hids.append(hid)
        return hid
    def unhook(self, hid):
        with self.lock:
            if hid in self.hids:
                self.hids.remove(hid)
                return True
        return False
    def reset(self):
        self.hids.clear()
    def stop(self):
        print("\033[?1004l", end="", flush=True)
        self.listener.stop()
    class handlerid():
        def __init__(self, key, func):
            self.key = key
            self.func = func
