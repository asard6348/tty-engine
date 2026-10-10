import sys, re, os, threading, time, inspect, traceback, atexit, codecs, weakref
from collections import defaultdict, deque

try:
    import keyboard
except Exception:
    keyboard = None

try:
    from blessed import Terminal
except Exception:
    Terminal = None

_WINDOWS = sys.platform == 'win32'
if _WINDOWS:
    import msvcrt, ctypes
    from ctypes import wintypes
    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _kernel32.GetStdHandle.restype    = wintypes.HANDLE
    _kernel32.GetStdHandle.argtypes   = [wintypes.DWORD]
    _kernel32.GetConsoleMode.restype  = wintypes.BOOL
    _kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.SetConsoleMode.restype  = wintypes.BOOL
    _kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _ENABLE_MOUSE_INPUT                 = 0x0010
    _ENABLE_QUICK_EDIT_MODE             = 0x0040
    _ENABLE_EXTENDED_FLAGS              = 0x0080
    _ENABLE_VIRTUAL_TERMINAL_INPUT      = 0x0200
    _ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
    _STD_INPUT_HANDLE  = -10 & 0xFFFFFFFF
    _STD_OUTPUT_HANDLE = -11 & 0xFFFFFFFF
    _WIN_SCAN = {'H': '\x1b[A', 'P': '\x1b[B', 'M': '\x1b[C', 'K': '\x1b[D',
                 'G': '\x1b[H', 'O': '\x1b[F', 'I': '\x1b[5~', 'Q': '\x1b[6~',
                 'R': '\x1b[2~', 'S': '\x1b[3~'}
else:
    import select


def _is_tty():
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


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
    __slots__ = ('event_type', 'name', 'ident')
    def __init__(self, event_type, name, ident=None):
        self.event_type = event_type
        self.name = name
        self.ident = ident


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
            self._cb(_FakeKeyEvent('down', name, ('t', name)))
            self._cb(_FakeKeyEvent('up', name, ('t', name)))


_ARROW_LETTERS = {'A': 'up', 'B': 'down', 'C': 'right', 'D': 'left',
                  'H': 'home', 'F': 'end', 'P': 'f1', 'Q': 'f2', 'R': 'f3', 'S': 'f4'}
_SS3_KEYS = dict(_ARROW_LETTERS)
_TILDE_KEYS = {1: 'home', 2: 'insert', 3: 'delete', 4: 'end', 5: 'page up',
               6: 'page down', 7: 'home', 8: 'end', 11: 'f1', 12: 'f2', 13: 'f3',
               14: 'f4', 15: 'f5', 17: 'f6', 18: 'f7', 19: 'f8', 20: 'f9',
               21: 'f10', 23: 'f11', 24: 'f12'}
_KITTY_NAMES = {27: 'esc', 13: 'enter', 9: 'tab', 127: 'backspace', 8: 'backspace',
                57358: 'caps lock', 57359: 'scroll lock', 57360: 'num lock',
                57361: 'print screen', 57362: 'pause', 57363: 'menu',
                57409: '.', 57410: '/', 57411: '*', 57412: '-', 57413: '+',
                57414: 'enter', 57415: '=', 57441: 'shift', 57447: 'shift',
                57442: 'ctrl', 57448: 'ctrl', 57443: 'alt', 57449: 'alt',
                57444: 'windows', 57450: 'windows', 57453: 'alt gr'}

def _kitty_name(code):
    name = _KITTY_NAMES.get(code)
    if name:
        return name
    if 57376 <= code <= 57398:
        return 'f%d' % (code - 57376 + 13)
    if 57399 <= code <= 57408:
        return str(code - 57399)
    if 0 < code < 0x110000 and chr(code).isprintable():
        return 'space' if code == 32 else chr(code).lower()
    return None

_CSI_RE      = re.compile(r'\x1b\[([0-9:;<=>?]*)([ -/]*)([@-~])')
_CSI_PARTIAL_RE = re.compile(r'\x1b\[[0-9:;<=>?]*[ -/]*')
_ESC_TIMEOUT = 0.05


class inp():
    def __init__(self, term=None, watchfocus=True, trackmotion=False,
                 legacy_hold=0.1, quiet=False):
        self.lock         = threading.RLock()
        self.wf           = watchfocus
        self.track_motion = trackmotion
        self.focused      = True
        self._term        = None
        self.legacy_hold  = legacy_hold
        self.quiet        = quiet

        # ── keyboard (library handles held/press/release natively) ────────
        self._press_cbs     = defaultdict(list)
        self._release_cbs   = defaultdict(list)
        self._events        = deque()
        self._down          = {}
        self._pressed_keys  = set()
        self._release_at    = {}
        self._kitty_state   = None
        self._kitty_t       = 0.0
        self._kb_is_fallback = False
        self._kb_hook = None
        self.keyboard = None

        # Tier 1: the `keyboard` library (needs root on Linux/macOS and a local
        # keyboard, so it is skipped when either is missing).
        if keyboard is not None and self._keyboard_usable():
            try:
                self._kb_hook = keyboard.hook(self._kb_event_raw, suppress=False)
                self.keyboard = keyboard
            except Exception:
                self.keyboard = None

        # Tier 2/3: terminal input. Kitty keyboard protocol (true press/release)
        # if the terminal answers the probe, else term.inkey (press-only, held()
        # is emulated and only stays True while key repeats keep arriving).
        if self.keyboard is None:
            self.keyboard = _FallbackKeyboard()
            self._kb_is_fallback = True
            self._kb_hook = self.keyboard.hook(self._kb_event_raw, suppress=False)
            if not self.quiet:
                sys.stderr.write(
                    "input_handler: low-level keyboard unavailable, using terminal "
                    "input: kitty keyboard protocol if supported, otherwise "
                    "term.inkey (press-only, held() needs key repeat).\n"
                )

        # ── mouse (raw VT sequence parser) ────────────────────────────────
        self._mouse_x     = 0
        self._mouse_y     = 0
        self._mouse_held  = set() # 0=left, 1=middle, 2=right
        self._mouse_wheel = 0
        self._mouse_cbs   = []
        self._buf         = '' # raw stdin accumulation buffer
        self._buf_t       = 0.0
        self._dec         = codecs.getincrementaldecoder('utf-8')('replace')

        # ── Windows console saved modes ───────────────────────────────────
        self._win_saved_in  = None
        self._win_saved_out = None
        self._win_vt_in     = False
        self._cleaned       = False

        ref = weakref.ref(self)
        atexit.register(lambda: ref() and ref().cleanup())

        if term is None and Terminal is not None and _is_tty():
            term = Terminal()
        self.term = term # triggers setter

    @staticmethod
    def _keyboard_usable():
        if _WINDOWS:
            return True
        try:
            if os.geteuid() != 0:          # keyboard lib needs root on Linux/macOS
                return False
        except AttributeError:
            return False
        # a global hook sees the *machine's* keyboard, not an SSH client's
        if os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_TTY'):
            return False
        return True

    def _uses_inkey(self):
        return callable(getattr(self._term, 'inkey', None))

    @property
    def backend(self):
        if not self._kb_is_fallback:
            return 'keyboard'
        if self._kitty_state == 'on':
            return 'kitty'
        return 'inkey' if self._uses_inkey() else 'terminal'

    #TERMINAL SETUP
    @property
    def term(self):
        return self._term

    @term.setter
    def term(self, value):
        self._term = value
        if value:
            self._cleaned = False
            if _WINDOWS:
                self._setup_windows_console()
            if self.wf:
                self._enable_focus_reporting()
            self._enable_mouse()
            if self._kb_is_fallback:
                self._start_kitty_probe()

    @staticmethod
    def _write(s):
        try:
            sys.stdout.write(s); sys.stdout.flush()
        except Exception:
            pass

    def _setup_windows_console(self):
        mode = wintypes.DWORD()
        hin  = _kernel32.GetStdHandle(_STD_INPUT_HANDLE)
        hout = _kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
        if self._win_saved_in is None and _kernel32.GetConsoleMode(hin, ctypes.byref(mode)):
            self._win_saved_in = mode.value
            new_in = (
                (mode.value | _ENABLE_VIRTUAL_TERMINAL_INPUT
                            | _ENABLE_MOUSE_INPUT
                            | _ENABLE_EXTENDED_FLAGS)
                & ~_ENABLE_QUICK_EDIT_MODE
            )
            self._win_vt_in = bool(_kernel32.SetConsoleMode(hin, new_in))
        if self._win_saved_out is None and _kernel32.GetConsoleMode(hout, ctypes.byref(mode)):
            self._win_saved_out = mode.value
            _kernel32.SetConsoleMode(hout, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING)

    def _enable_focus_reporting(self):
        self._write("\x1b[?1004h")

    def _disable_focus_reporting(self):
        self._write("\x1b[?1004l")

    def _enable_mouse(self):
        codes = "\x1b[?1000h\x1b[?1002h\x1b[?1006h"
        if self.track_motion:
            codes += "\x1b[?1003h"
        self._write(codes)

    def _disable_mouse(self):
        self._write("\x1b[?1003l\x1b[?1002l\x1b[?1000l\x1b[?1006l")

    def _start_kitty_probe(self):
        if self._kitty_state is not None:
            return
        try:
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                return
        except Exception:
            return
        self._kitty_state, self._kitty_t = 'probing', time.monotonic()
        self._write("\x1b[?u\x1b[c")

    #KEYBOARD
    def _kb_event_raw(self, event):
        ident = getattr(event, 'ident', None)
        if ident is None:
            ident = getattr(event, 'scan_code', None)
        if ident is None:
            ident = event.name
        if event.event_type not in ('down', 'up'):
            return
        with self.lock:
            self._events.append((ident, event))

    def _release_all(self):
        with self.lock:
            pending = dict(self._down)
            for ident, event in self._events:
                if event.event_type == 'down':
                    pending[ident] = event.name
                else:
                    pending.pop(ident, None)
            for ident, name in pending.items():
                self._events.append((ident, _FakeKeyEvent('up', name, ident)))
            self._release_at.clear()

    def _term_press(self, name):
        self._kb_event_raw(_FakeKeyEvent('down', name, ('t', name)))
        self._release_at[name] = time.monotonic() + self.legacy_hold

    def _flush_releases(self, now):
        if self._release_at:
            for name, t in list(self._release_at.items()):
                if now >= t:
                    del self._release_at[name]
                    self._kb_event_raw(_FakeKeyEvent('up', name, ('t', name)))

    def _stdin_press(self, name):
        if self._kb_is_fallback and self._kitty_state != 'on':
            self._term_press(name)

    def _term_event(self, name, ident, ev):
        if not self._kb_is_fallback:
            return
        if self._kitty_state == 'on':
            self._kb_event_raw(_FakeKeyEvent('up' if ev == 3 else 'down', name, ident))
        elif ev != 3:
            self._term_press(name)

    #MOUSE
    def _read_inkey(self):
        # Drain term.inkey and glue the keystrokes back into the raw stream, so
        # mouse / focus / kitty replies still go through the same parser.
        ink = self._term.inkey
        out = []
        for _ in range(512):
            try:
                ks = ink(timeout=0, esc_delay=0)
            except TypeError:           # older blessed: no esc_delay argument
                try:
                    ks = ink(timeout=0)
                except Exception:
                    break
            except Exception:
                break
            if not ks:
                break
            out.append(str(ks))
        return ''.join(out)

    def _read_raw(self):
        if self._kb_is_fallback and self._uses_inkey():
            return self._read_inkey()
        if _WINDOWS:
            chars = []
            while msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ('\x00', '\xe0') and not self._win_vt_in:
                    chars.append(_WIN_SCAN.get(msvcrt.getwch(), ''))
                else:
                    chars.append(ch)
            return ''.join(chars)
        try:
            fd = sys.stdin.fileno()
        except Exception:
            return ''
        chunks = []
        while True:
            try:
                r, _, _ = select.select([fd], [], [], 0)
                if not r:
                    break
                data = os.read(fd, 4096)
            except (OSError, ValueError):
                break
            if not data:
                break
            chunks.append(data)
            if len(data) < 4096:
                break
        return self._dec.decode(b''.join(chunks)) if chunks else ''

    def _parse_input(self, now):
        buf = self._buf
        n = len(buf)
        if not n:
            return
        stale = bool(self._buf_t) and (now - self._buf_t) >= _ESC_TIMEOUT
        i = 0
        while i < n:
            c = buf[i]
            if c != '\x1b':
                name = self._char_to_keyname(c)
                if name:
                    self._stdin_press(name)
                i += 1; continue
            if i + 1 >= n:
                if stale:
                    self._stdin_press('esc')
                    i += 1; continue
                break
            nxt = buf[i + 1]
            if nxt == '[':
                if buf.startswith('\x1b[M', i):
                    if n - i < 6:
                        if stale: i += 3; continue
                        break
                    self._handle_x10(ord(buf[i+3])-32, ord(buf[i+4])-33, ord(buf[i+5])-33)
                    i += 6; continue
                m = _CSI_RE.match(buf, i)
                if m:
                    self._on_csi(m.group(1), m.group(3))
                    i = m.end(); continue
                if n - i < 64 and not stale:
                    break
                i = _CSI_PARTIAL_RE.match(buf, i).end(); continue
            if nxt == 'O':
                if n - i < 3:
                    if stale:
                        self._stdin_press('esc')
                        i += 1; continue
                    break
                name = _SS3_KEYS.get(buf[i + 2])
                if name:
                    self._stdin_press(name)
                i += 3; continue
            self._stdin_press('esc')
            i += 1
        left = buf[i:]
        if not left:
            self._buf_t = 0.0
        elif i > 0 or not self._buf_t:
            self._buf_t = now
        self._buf = left

    def _on_csi(self, params, final):
        if params[:1] == '<' and final in 'Mm':
            p = params[1:].split(';')
            if len(p) == 3 and all(x.isdigit() for x in p):
                self._handle_sgr(int(p[0]), int(p[1]) - 1, int(p[2]) - 1, final)
            return
        if not params and final in 'IO':
            self._set_focus(final == 'I')
            return
        if params[:1] == '?':
            if final == 'u' and self._kitty_state == 'probing':
                self._kitty_state = 'on'
                self._write("\x1b[>11u")
            elif final == 'c' and self._kitty_state == 'probing':
                self._kitty_state = 'off'
            return
        if final == 'Z':
            self._term_event('tab', ('t', 'tab'), 1)
            return
        if final not in 'u~' and final not in _ARROW_LETTERS:
            return
        f = params.split(';')
        try:
            code = int(f[0].split(':')[0]) if f[0] else 1
            ev = 1
            if len(f) > 1 and ':' in f[1]:
                e = f[1].split(':')[1]
                ev = int(e) if e else 1
        except ValueError:
            return
        if final == 'u':
            name, ident = _kitty_name(code), ('t', code)
        elif final == '~':
            name = _TILDE_KEYS.get(code); ident = ('t', name)
        else:
            name = _ARROW_LETTERS[final]; ident = ('t', name)
        if name:
            self._term_event(name, ident, ev)

    def _set_focus(self, value):
        with self.lock:
            self.focused = value
        if not value and self._kb_is_fallback:
            self._release_all()

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
            if button > 1:
                return
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
                try:
                    cb(x, y, data)
                except Exception:
                    sys.stderr.write("input_handler: onmouse callback for %r raised:\n" % event)
                    traceback.print_exc()

    #CENTRAL UPDATE
    def update(self):
        now = time.monotonic()
        self._mouse_wheel = 0
        self._buf += self._read_raw()
        self._parse_input(now)
        if self._kitty_state == 'probing' and now - self._kitty_t > 1.5:
            self._kitty_state = 'off'
        self._flush_releases(now)

        with self.lock:
            events = list(self._events)
            self._events.clear()
            focused = self.focused

        if events:
            for ident, event in events:
                if event.event_type == 'down':
                    self._down[ident] = event.name
                else:
                    self._down.pop(ident, None)
            self._pressed_keys = set(self._down.values())

        if focused:
            for ident, event in events:
                down = event.event_type == 'down'
                table = self._press_cbs if down else self._release_cbs
                for cb, accepts in list(table.get(event.name, ())):
                    try:
                        cb(event) if accepts else cb()
                    except Exception:
                        sys.stderr.write("input_handler: %s callback for %r raised:\n"
                                         % ('onpress' if down else 'onrelease', event.name))
                        traceback.print_exc()

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

    @staticmethod
    def _clear_key(table, key, caps):
        keys = {key.lower(), key.upper()} if caps else {key}
        removed = 0
        for k in keys:
            removed += len(table.pop(k, ()))
        return removed

    def offpress(self, key, caps=False):
        return self._clear_key(self._press_cbs, key, caps)

    def offrelease(self, key, caps=False):
        return self._clear_key(self._release_cbs, key, caps)

    def stop(self, handle):
        if handle and isinstance(handle[0], tuple):
            for h in handle:
                self.stop(h)
            return
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

    def stopmouse(self, handle):
        if isinstance(handle, (list, tuple)) and handle and isinstance(handle[0], tuple):
            return any([self.stopmouse(h) for h in handle])
        before = len(self._mouse_cbs)
        self._mouse_cbs = [h for h in self._mouse_cbs if h is not handle]
        return len(self._mouse_cbs) != before

    def offmouse(self, handle):
        return self.stopmouse(handle)

    #FOCUS API
    def pausefocus(self):
        self._disable_focus_reporting()

    def resumefocus(self):
        self._enable_focus_reporting()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cleanup()

    def cleanup(self):
        if self._cleaned:
            return
        self._cleaned = True
        if self._term:
            self._disable_mouse()
            if self.wf:
                self._disable_focus_reporting()
            if self._kitty_state == 'on':
                self._write("\x1b[<u")
            self._kitty_state = None
        try:
            self.keyboard.unhook_all()
        except Exception:
            pass
        if _WINDOWS:
            if self._win_saved_in is not None:
                _kernel32.SetConsoleMode(
                    _kernel32.GetStdHandle(_STD_INPUT_HANDLE),
                    self._win_saved_in)
                self._win_saved_in = None
            if self._win_saved_out is not None:
                _kernel32.SetConsoleMode(
                    _kernel32.GetStdHandle(_STD_OUTPUT_HANDLE),
                    self._win_saved_out)
                self._win_saved_out = None
