import sys, re, os, threading, time, inspect, traceback
from collections import defaultdict

try:
    import keyboard
except ImportError:
    keyboard = None

_WINDOWS = sys.platform == 'win32'
if _WINDOWS:
    import msvcrt, ctypes
    _kernel32 = ctypes.windll.kernel32
    _ENABLE_MOUSE_INPUT                 = 0x0010
    _ENABLE_QUICK_EDIT_MODE             = 0x0040
    _ENABLE_EXTENDED_FLAGS              = 0x0080
    _ENABLE_VIRTUAL_TERMINAL_INPUT      = 0x0200
    _ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
    _STD_INPUT_HANDLE  = ctypes.c_ulong(-10)
    _STD_OUTPUT_HANDLE = ctypes.c_ulong(-11)
else:
    import fcntl


def _accepts_arg(cb):
    try:
        sig = inspect.signature(cb)
    except (TypeError, ValueError):
        return True
    for p in sig.parameters.values():
        if p.kind == p.VAR_POSITIONAL:
            return True
    positional = [p for p in sig.parameters.values()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    return len(positional) >= 1


class _FakeKeyEvent:
    __slots__ = ('event_type', 'name')
    def __init__(self, event_type, name):
        self.event_type = event_type
        self.name = name


class _FallbackKeyboard:
    def __init__(self):
        self._cb = None

    def hook(self, callback, suppress=False):
        self._cb = callback
        return callback

    def unhook_all(self):
        self._cb = None

    def feed(self, name):
        if self._cb:
            self._cb(_FakeKeyEvent('down', name))
            self._cb(_FakeKeyEvent('up', name))


_ARROW_SEQS = {
    '\x1b[A': 'up',    '\x1b[B': 'down',  '\x1b[C': 'right', '\x1b[D': 'left',
    '\x1bOA': 'up',    '\x1bOB': 'down',  '\x1bOC': 'right', '\x1bOD': 'left',
}


class inp():
    def __init__(self, term=None, watchfocus=True, trackmotion=False):
        self.lock         = threading.Lock()
        self.wf           = watchfocus
        self.track_motion = trackmotion
        self.focused      = True
        self._term        = None

        # ── keyboard (library handles held/press/release natively) ────────
        self._press_cbs     = defaultdict(list)
        self._release_cbs   = defaultdict(list)
        self._press_queue   = []
        self._release_queue = []
        self._pressed_keys  = set()
        self._kb_is_fallback = False
        self.keyboard = None

        if keyboard is not None:
            try:
                self.keyboard = keyboard
                self._kb_hook = self.keyboard.hook(self._kb_event_raw, suppress=False)
            except Exception:
                self.keyboard = None

        if self.keyboard is None:
            self.keyboard = _FallbackKeyboard()
            self._kb_is_fallback = True
            self._kb_hook = self.keyboard.hook(self._kb_event_raw, suppress=False)
            sys.stderr.write(
                "input_handler: no low-level keyboard access (needs root on "
                "Linux), using basic stdin-based key detection instead -- "
                "onpress/onrelease fire normally, but held() is not reliable "
                "in this mode.\n"
            )

        # ── mouse (raw VT sequence parser) ────────────────────────────────
        self._mouse_x     = 0
        self._mouse_y     = 0
        self._mouse_held  = set() # 0=left, 1=middle, 2=right
        self._mouse_wheel = 0
        self._mouse_cbs   = []
        self._buf         = '' # raw stdin accumulation buffer

        # ── Windows console saved modes ───────────────────────────────────
        self._win_saved_in  = None
        self._win_saved_out = None

        self.term = term # triggers setter

    #TERMINAL SETUP
    @property
    def term(self):
        return self._term

    @term.setter
    def term(self, value):
        self._term = value
        if value:
            if _WINDOWS:
                self._setup_windows_console()
            if self.wf:
                self._enable_focus_reporting()
            self._enable_mouse()

    def _setup_windows_console(self):
        mode = ctypes.c_ulong()
        hin  = _kernel32.GetStdHandle(_STD_INPUT_HANDLE)
        hout = _kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
        _kernel32.GetConsoleMode(hin,  ctypes.byref(mode)); self._win_saved_in  = mode.value
        _kernel32.GetConsoleMode(hout, ctypes.byref(mode)); self._win_saved_out = mode.value
        new_in = (
            (self._win_saved_in | _ENABLE_VIRTUAL_TERMINAL_INPUT
                                | _ENABLE_MOUSE_INPUT
                                | _ENABLE_EXTENDED_FLAGS)
            & ~_ENABLE_QUICK_EDIT_MODE
        )
        _kernel32.SetConsoleMode(hin,  ctypes.c_ulong(new_in))
        _kernel32.SetConsoleMode(hout, ctypes.c_ulong(
            self._win_saved_out | _ENABLE_VIRTUAL_TERMINAL_PROCESSING))

    def _enable_focus_reporting(self):
        sys.stdout.write("\x1b[?1004h"); sys.stdout.flush()

    def _disable_focus_reporting(self):
        sys.stdout.write("\x1b[?1004l"); sys.stdout.flush()

    def _enable_mouse(self):
        codes = "\x1b[?1000h\x1b[?1002h\x1b[?1006h"
        if self.track_motion:
            codes += "\x1b[?1003h"
        sys.stdout.write(codes); sys.stdout.flush()

    def _disable_mouse(self):
        sys.stdout.write("\x1b[?1003l\x1b[?1002l\x1b[?1000l\x1b[?1006l")
        sys.stdout.flush()

    #KEYBOARD
    def _kb_event_raw(self, event):
        with self.lock:
            if event.event_type == 'down':
                self._press_queue.append((event.name, event))
            elif event.event_type == 'up':
                self._release_queue.append((event.name, event))

    #MOUSE
    def _read_raw(self):
        if _WINDOWS:
            chars = []
            while msvcrt.kbhit():
                chars.append(msvcrt.getch().decode('utf-8', errors='replace'))
            return ''.join(chars)
        else:
            fd = sys.stdin.fileno()
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            try:
                chunk = sys.stdin.buffer.read(4096) or b''
            except (BlockingIOError, IOError):
                chunk = b''
            finally:
                fcntl.fcntl(fd, fcntl.F_SETFL, flags)
            return chunk.decode('utf-8', errors='replace')

    def _parse_mouse(self):
        buf = self._buf
        i = 0
        n = len(buf)

        while i < n:

            # ── SGR mouse: \x1b[<digits;digits;digits[Mm] ─────────────────
            if buf[i:i+3] == '\x1b[<':
                m = re.match(r'\x1b\[<(\d+);(\d+);(\d+)([Mm])', buf[i:])
                if m:
                    self._handle_sgr(int(m[1]), int(m[2])-1, int(m[3])-1, m[4])
                    i += len(m.group()); continue
                elif n - i < 32:
                    break           # incomplete sequence — wait for more bytes
                else:
                    i += 1; continue

            # ── X10 legacy mouse: \x1b[M + 3 raw bytes ───────────────────
            if buf[i:i+3] == '\x1b[M':
                if n - i < 6: break
                self._handle_x10(ord(buf[i+3])-32, ord(buf[i+4])-33, ord(buf[i+5])-33)
                i += 6; continue

            # ── arrow keys (fallback keyboard backend only) ────────────────
            if n - i >= 3 and buf[i:i+3] in _ARROW_SEQS:
                if self._kb_is_fallback:
                    self.keyboard.feed(_ARROW_SEQS[buf[i:i+3]])
                i += 3; continue

            # ── focus in / out ─────────────────────────────────────────────
            if buf[i:i+3] == '\x1b[I':
                with self.lock: self.focused = True
                i += 3; continue
            if buf[i:i+3] == '\x1b[O':
                with self.lock: self.focused = False
                i += 3; continue

            # ── any other escape sequence: skip safely ────────────────────
            # If \x1b is near the end of the buffer the sequence is probably
            # incomplete (tail arrives next tick). Stop here and keep the
            # \x1b in the buffer so it can be matched next tick.
            # Only skip past it when there are enough bytes to be sure it
            # isn't the start of something we'd recognise.
            if buf[i] == '\x1b':
                if n - i < 32:
                    break           # might be an incomplete mouse/focus seq
                i += 1; continue   # unknown escape, discard just the \x1b

            # ── everything else (keyboard chars, non-escape bytes) ────────
            if self._kb_is_fallback:
                name = self._char_to_keyname(buf[i])
                if name:
                    self.keyboard.feed(name)
            i += 1

        self._buf = buf[i:]

    @staticmethod
    def _char_to_keyname(ch):
        if ch == ' ':
            return 'space'
        if ch in ('\r', '\n'):
            return 'enter'
        if ch == '\t':
            return 'tab'
        if ch in ('\x7f', '\x08'):
            return 'backspace'
        if ch == '\x1b':
            return 'esc'
        if ch.isprintable():
            return ch.lower()
        return None

    def _handle_sgr(self, btn, x, y, action):
        self._mouse_x, self._mouse_y = x, y
        is_scroll = btn & 64
        is_motion = btn & 32
        button    = btn & 3
        if is_scroll:
            self._mouse_wheel += 1 if button == 0 else -1
            self._fire_mouse('wheel', x, y, self._mouse_wheel)
        elif action == 'M':
            if is_motion:
                self._fire_mouse('move', x, y, button)
            else:
                self._mouse_held.add(button)
                self._fire_mouse('click', x, y, button)
        elif action == 'm':
            self._mouse_held.discard(button)
            self._fire_mouse('release', x, y, button)

    def _handle_x10(self, b, x, y):
        self._mouse_x, self._mouse_y = x, y
        btn = b & 3
        if btn == 3:
            self._mouse_held.clear()
            self._fire_mouse('release', x, y, None)
        else:
            self._mouse_held.add(btn)
            self._fire_mouse('click', x, y, btn)

    def _fire_mouse(self, event, x, y, data):
        for etype, cb in list(self._mouse_cbs):
            if etype in (event, 'any'):
                cb(x, y, data)

    #CENTRAL UPDATE
    def update(self):
        # keyboard
        with self.lock:
            press_q   = self._press_queue[:]
            release_q = self._release_queue[:]
            self._press_queue.clear()
            self._release_queue.clear()
            for key_name, _ in press_q:
                self._pressed_keys.add(key_name)
            for key_name, _ in release_q:
                self._pressed_keys.discard(key_name)
            focused = self.focused

        if focused:
            for key_name, event in press_q:
                for cb, accepts in list(self._press_cbs.get(key_name, [])):
                    try:
                        cb(event) if accepts else cb()
                    except Exception:
                        sys.stderr.write("input_handler: onpress callback for %r raised:\n" % key_name)
                        traceback.print_exc()
            for key_name, event in release_q:
                for cb, accepts in list(self._release_cbs.get(key_name, [])):
                    try:
                        cb(event) if accepts else cb()
                    except Exception:
                        sys.stderr.write("input_handler: onrelease callback for %r raised:\n" % key_name)
                        traceback.print_exc()

        # mouse
        self._mouse_wheel = 0
        self._buf += self._read_raw()
        self._parse_mouse()

    #KEYBOARD API
    def held(self, key=None, caps=False):
        if not self.focused:
            return False
        if isinstance(key, str) and key:
            if caps:
                return key.upper() in self._pressed_keys or key.lower() in self._pressed_keys
            return key in self._pressed_keys
        if isinstance(key, (list, tuple)) and key:
            if caps:
                return any(k.upper() in self._pressed_keys or k.lower() in self._pressed_keys for k in key)
            return any(k in self._pressed_keys for k in key)
        return list(self._pressed_keys)

    def onpress(self, key, callback, caps=False):
        accepts = _accepts_arg(callback)
        if caps:
            self._press_cbs[key.lower()].append((callback, accepts))
            self._press_cbs[key.upper()].append((callback, accepts))
            return (key.lower(), callback, 'press'), (key.upper(), callback, 'press')
        self._press_cbs[key].append((callback, accepts))
        return (key, callback, 'press')

    def onrelease(self, key, callback, caps=False):
        accepts = _accepts_arg(callback)
        if caps:
            self._release_cbs[key.lower()].append((callback, accepts))
            self._release_cbs[key.upper()].append((callback, accepts))
            return (key.lower(), callback, 'release'), (key.upper(), callback, 'release')
        self._release_cbs[key].append((callback, accepts))
        return (key, callback, 'release')

    def stop(self, handle):
        key, cb, kind = handle
        target = self._press_cbs if kind == 'press' else self._release_cbs
        target[key] = [entry for entry in target[key] if entry[0] is not cb]

    def stop_all(self):
        self._press_cbs.clear()
        self._release_cbs.clear()
        self._mouse_cbs.clear()
        self.keyboard.unhook_all()

    #MOUSE API
    @property
    def mouse(self): # actual mouse position
        return (self._mouse_x, self._mouse_y)

    @property
    def wheel(self): # actual mouse wheel delta
        # 1-up, -1-down, 0-none
        return self._mouse_wheel

    def mouseheld(self, button=0): # actual held mouse button
        # 0-left, 1-middle, 2-right
        return button in self._mouse_held

    def onmouse(self, event, callback): # register a mouse event callback
        # event: 'click' | 'release' | 'move' | 'wheel' | 'any'
        # callback: cb(x, y, data)  — data is button index or scroll delta
        handle = (event, callback)
        self._mouse_cbs.append(handle)
        return handle

    def offmouse(self, handle): # unregister a mouse event handle
        self._mouse_cbs = [h for h in self._mouse_cbs if h is not handle]

    #FOCUS API
    def pausefocus(self):
        self._disable_focus_reporting()

    def resumefocus(self):
        self._enable_focus_reporting()

    def cleanup(self):
        self._disable_mouse()
        if self.wf:
            self._disable_focus_reporting()
        self.keyboard.unhook_all()
        if _WINDOWS:
            if self._win_saved_in is not None:
                _kernel32.SetConsoleMode(
                    _kernel32.GetStdHandle(_STD_INPUT_HANDLE),
                    ctypes.c_ulong(self._win_saved_in))
            if self._win_saved_out is not None:
                _kernel32.SetConsoleMode(
                    _kernel32.GetStdHandle(_STD_OUTPUT_HANDLE),
                    ctypes.c_ulong(self._win_saved_out))
