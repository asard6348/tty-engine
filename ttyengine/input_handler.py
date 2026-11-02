import sys, re, os, threading, time, inspect, atexit, codecs, weakref, struct
from collections import defaultdict, deque

try:
    import keyboard
except Exception:
    keyboard = None

from . import ansi
from .terminal import Terminal

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
    _WIN_SCAN = {'H': ansi.csi('', 'A'), 'P': ansi.csi('', 'B'), 'M': ansi.csi('', 'C'), 'K': ansi.csi('', 'D'),
                 'G': ansi.csi('', 'H'), 'O': ansi.csi('', 'F'), 'I': ansi.csi('5', '~'), 'Q': ansi.csi('6', '~'),
                 'R': ansi.csi('2', '~'), 'S': ansi.csi('3', '~')}
    _kernel32.GetModuleHandleW.restype  = wintypes.HMODULE
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetCurrentThreadId.restype  = wintypes.DWORD
    _kernel32.GetCurrentThreadId.argtypes = []
    _user32 = ctypes.WinDLL('user32', use_last_error=True)
    _HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    class _KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [('vkCode', wintypes.DWORD), ('scanCode', wintypes.DWORD),
                    ('flags', wintypes.DWORD), ('time', wintypes.DWORD),
                    ('dwExtraInfo', ctypes.c_size_t)]

    _user32.SetWindowsHookExW.restype    = wintypes.HHOOK
    _user32.SetWindowsHookExW.argtypes   = [ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    _user32.CallNextHookEx.restype       = ctypes.c_ssize_t
    _user32.CallNextHookEx.argtypes      = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    _user32.UnhookWindowsHookEx.restype  = wintypes.BOOL
    _user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    _user32.GetMessageW.restype          = wintypes.BOOL
    _user32.GetMessageW.argtypes         = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.PeekMessageW.restype         = wintypes.BOOL
    _user32.PeekMessageW.argtypes        = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    _user32.PostThreadMessageW.restype   = wintypes.BOOL
    _user32.PostThreadMessageW.argtypes  = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _WH_KEYBOARD_LL = 13
    _WM_QUIT        = 0x0012
else:
    import select

_LINUX = sys.platform.startswith('linux')
if _LINUX:
    import fcntl, glob
    try:
        import grp
    except ImportError:
        grp = None

_DARWIN = sys.platform == 'darwin'
_CG = _CF = None
if _DARWIN:
    import ctypes
    _TAP_CB = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                               ctypes.c_void_p, ctypes.c_void_p)
    try:
        _CG = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
        _CF = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        _CG.CGEventTapCreate.restype  = ctypes.c_void_p
        _CG.CGEventTapCreate.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                         ctypes.c_uint64, _TAP_CB, ctypes.c_void_p]
        _CG.CGEventTapEnable.restype  = None
        _CG.CGEventTapEnable.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        _CG.CGEventGetIntegerValueField.restype  = ctypes.c_int64
        _CG.CGEventGetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        _CF.CFMachPortCreateRunLoopSource.restype  = ctypes.c_void_p
        _CF.CFMachPortCreateRunLoopSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
        _CF.CFRunLoopGetCurrent.restype  = ctypes.c_void_p
        _CF.CFRunLoopGetCurrent.argtypes = []
        _CF.CFRunLoopAddSource.restype  = None
        _CF.CFRunLoopAddSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        _CF.CFRunLoopRunInMode.restype  = ctypes.c_int32
        _CF.CFRunLoopRunInMode.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_ubyte]
        _CF.CFMachPortInvalidate.restype  = None
        _CF.CFMachPortInvalidate.argtypes = [ctypes.c_void_p]
        _CF.CFRelease.restype  = None
        _CF.CFRelease.argtypes = [ctypes.c_void_p]
        _CF_COMMON  = ctypes.c_void_p.in_dll(_CF, 'kCFRunLoopCommonModes').value
        _CF_DEFAULT = ctypes.c_void_p.in_dll(_CF, 'kCFRunLoopDefaultMode').value
    except Exception:
        _CG = _CF = None


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


def _positional_count(cb):
    try:
        sig = inspect.signature(cb)
    except (TypeError, ValueError):
        return None
    count = 0
    for p in sig.parameters.values():
        if p.kind == p.VAR_POSITIONAL:
            return None
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            count += 1
    return count


class _FakeKeyEvent:
    __slots__ = ('event_type', 'name', 'ident', 'silent')
    def __init__(self, event_type, name, ident=None, silent=False):
        self.event_type = event_type
        self.name = name
        self.ident = ident
        self.silent = silent


class _TermKey:
    __slots__ = ('last', 'nev', 'gap', 'next', 'up', 'pend')
    def __init__(self, now, due):
        self.last = now
        self.nev  = 1
        self.gap  = None
        self.next = due
        self.up   = False
        self.pend = None


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

_EV_KEY       = 0x01
_KEY_MAX      = 0x2ff
_KEY_ENTER    = 28
_KEY_A        = 30
_KEY_SPACE    = 57
_EVDEV_FMT    = 'llHHi'
_EVDEV_SIZE   = struct.calcsize(_EVDEV_FMT)
_EVDEV_DIR    = '/dev/input'
_EVDEV_RESCAN = 2.0
_EVDEV_NAMES  = {1: 'esc', 2: '1', 3: '2', 4: '3', 5: '4', 6: '5', 7: '6', 8: '7',
                 9: '8', 10: '9', 11: '0', 12: '-', 13: '=', 14: 'backspace', 15: 'tab',
                 16: 'q', 17: 'w', 18: 'e', 19: 'r', 20: 't', 21: 'y', 22: 'u', 23: 'i',
                 24: 'o', 25: 'p', 26: '[', 27: ']', 28: 'enter', 29: 'ctrl',
                 30: 'a', 31: 's', 32: 'd', 33: 'f', 34: 'g', 35: 'h', 36: 'j', 37: 'k',
                 38: 'l', 39: ';', 40: "'", 41: '`', 42: 'shift', 43: '\\',
                 44: 'z', 45: 'x', 46: 'c', 47: 'v', 48: 'b', 49: 'n', 50: 'm',
                 51: ',', 52: '.', 53: '/', 54: 'shift', 55: '*', 56: 'alt', 57: 'space',
                 58: 'caps lock', 69: 'num lock', 70: 'scroll lock',
                 71: '7', 72: '8', 73: '9', 74: '-', 75: '4', 76: '5', 77: '6',
                 78: '+', 79: '1', 80: '2', 81: '3', 82: '0', 83: '.',
                 87: 'f11', 88: 'f12', 96: 'enter', 97: 'ctrl', 98: '/',
                 99: 'print screen', 100: 'alt', 102: 'home', 103: 'up',
                 104: 'page up', 105: 'left', 106: 'right', 107: 'end', 108: 'down',
                 109: 'page down', 110: 'insert', 111: 'delete', 117: '=',
                 119: 'pause', 125: 'windows', 126: 'windows', 127: 'menu'}
_EVDEV_NAMES.update({59 + i: 'f%d' % (i + 1) for i in range(10)})
_EVDEV_NAMES.update({183 + i: 'f%d' % (i + 13) for i in range(12)})

_WIN_NAMES = {0x08: 'backspace', 0x09: 'tab', 0x0D: 'enter', 0x10: 'shift', 0x11: 'ctrl',
              0x12: 'alt', 0x13: 'pause', 0x14: 'caps lock', 0x1B: 'esc', 0x20: 'space',
              0x21: 'page up', 0x22: 'page down', 0x23: 'end', 0x24: 'home', 0x25: 'left',
              0x26: 'up', 0x27: 'right', 0x28: 'down', 0x2C: 'print screen', 0x2D: 'insert',
              0x2E: 'delete', 0x5B: 'windows', 0x5C: 'windows', 0x5D: 'menu',
              0x6A: '*', 0x6B: '+', 0x6D: '-', 0x6E: '.', 0x6F: '/',
              0x90: 'num lock', 0x91: 'scroll lock',
              0xA0: 'shift', 0xA1: 'shift', 0xA2: 'ctrl', 0xA3: 'ctrl', 0xA4: 'alt', 0xA5: 'alt',
              0xBA: ';', 0xBB: '=', 0xBC: ',', 0xBD: '-', 0xBE: '.', 0xBF: '/', 0xC0: '`',
              0xDB: '[', 0xDC: '\\', 0xDD: ']', 0xDE: "'"}
_WIN_NAMES.update({0x30 + i: str(i) for i in range(10)})
_WIN_NAMES.update({0x60 + i: str(i) for i in range(10)})
_WIN_NAMES.update({0x41 + i: chr(97 + i) for i in range(26)})
_WIN_NAMES.update({0x70 + i: 'f%d' % (i + 1) for i in range(24)})
_WIN_ALTGR_CTRL = 0x21D

_MAC_NAMES = {0: 'a', 1: 's', 2: 'd', 3: 'f', 4: 'h', 5: 'g', 6: 'z', 7: 'x', 8: 'c', 9: 'v',
              11: 'b', 12: 'q', 13: 'w', 14: 'e', 15: 'r', 16: 'y', 17: 't', 18: '1', 19: '2',
              20: '3', 21: '4', 22: '6', 23: '5', 24: '=', 25: '9', 26: '7', 27: '-', 28: '8',
              29: '0', 30: ']', 31: 'o', 32: 'u', 33: '[', 34: 'i', 35: 'p', 36: 'enter',
              37: 'l', 38: 'j', 39: "'", 40: 'k', 41: ';', 42: '\\', 43: ',', 44: '/',
              45: 'n', 46: 'm', 47: '.', 48: 'tab', 49: 'space', 50: '`', 51: 'backspace',
              53: 'esc', 54: 'windows', 55: 'windows', 56: 'shift', 57: 'caps lock',
              58: 'alt', 59: 'ctrl', 60: 'shift', 61: 'alt', 62: 'ctrl',
              64: 'f17', 65: '.', 67: '*', 69: '+', 71: 'num lock', 75: '/', 76: 'enter',
              78: '-', 79: 'f18', 80: 'f19', 81: '=', 82: '0', 83: '1', 84: '2', 85: '3',
              86: '4', 87: '5', 88: '6', 89: '7', 90: 'f20', 91: '8', 92: '9',
              96: 'f5', 97: 'f6', 98: 'f7', 99: 'f3', 100: 'f8', 101: 'f9', 103: 'f11',
              105: 'f13', 106: 'f16', 107: 'f14', 109: 'f10', 110: 'menu', 111: 'f12',
              113: 'f15', 114: 'insert', 115: 'home', 116: 'page up', 117: 'delete',
              118: 'f4', 119: 'end', 120: 'f2', 121: 'page down', 122: 'f1',
              123: 'left', 124: 'right', 125: 'down', 126: 'up'}
_MAC_CAPS       = 57
_MAC_TAP_MASK   = (1 << 10) | (1 << 11) | (1 << 12)
_MAC_TAP_OFF    = (0xFFFFFFFE, 0xFFFFFFFF)

_CSI_RE      = re.compile(ansi.CSI_RE + r'([0-9:;<=>?]*)([ -/]*)([@-~])')
_CSI_PARTIAL_RE = re.compile(ansi.CSI_RE + r'[0-9:;<=>?]*[ -/]*')
_ESC_TIMEOUT = 0.05
_REPEAT_MIN_GAP = 0.008
_NO_REPEAT = frozenset(('shift', 'ctrl', 'alt', 'alt gr', 'windows',
                        'caps lock', 'num lock', 'scroll lock',
                        'left shift', 'right shift', 'left ctrl', 'right ctrl',
                        'left alt', 'right alt', 'left windows', 'right windows'))


class _EvdevKeyboard:
    def __init__(self):
        self._cb      = None
        self._fds     = {}
        self._held    = {}
        self._ignored = set()
        self._stop    = threading.Event()
        self._thread  = None

    @staticmethod
    def accessible():
        if not _LINUX:
            return False
        if os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_TTY'):
            return False
        paths = glob.glob(_EVDEV_DIR + '/event*')
        if not paths:
            return False
        try:
            if os.geteuid() == 0:
                return True
        except AttributeError:
            return False
        if grp is not None:
            try:
                gid = grp.getgrnam('input').gr_gid
                if gid == os.getegid() or gid in os.getgroups():
                    return True
            except (KeyError, OSError):
                pass
        return any(os.access(p, os.R_OK) for p in paths)

    @staticmethod
    def _is_keyboard(fd):
        buf = bytearray(_KEY_MAX // 8 + 1)
        req = (2 << 30) | (len(buf) << 16) | (ord('E') << 8) | (0x20 + _EV_KEY)
        try:
            fcntl.ioctl(fd, req, buf, True)
        except OSError:
            return False
        return all(buf[k >> 3] & (1 << (k & 7)) for k in (_KEY_A, _KEY_ENTER, _KEY_SPACE))

    def _scan(self):
        paths = set(glob.glob(_EVDEV_DIR + '/event*'))
        self._ignored &= paths
        for path in paths:
            if path in self._fds or path in self._ignored:
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                self._ignored.add(path)
                continue
            if self._is_keyboard(fd):
                self._fds[path] = fd
                self._held[fd] = set()
            else:
                os.close(fd)
                self._ignored.add(path)

    def open(self):
        try:
            self._scan()
        except Exception:
            return False
        return bool(self._fds)

    def _emit(self, kind, code):
        cb = self._cb
        name = _EVDEV_NAMES.get(code)
        if cb and name:
            cb(_FakeKeyEvent(kind, name, ('k', code)))

    def _drop(self, fd):
        for path, f in list(self._fds.items()):
            if f == fd:
                del self._fds[path]
        for code in self._held.pop(fd, ()):
            self._emit('up', code)
        try:
            os.close(fd)
        except OSError:
            pass

    def _drain(self, fd):
        try:
            data = os.read(fd, _EVDEV_SIZE * 64)
        except BlockingIOError:
            return
        except OSError:
            self._drop(fd)
            return
        if not data:
            self._drop(fd)
            return
        held = self._held.get(fd, set())
        for off in range(0, len(data) - _EVDEV_SIZE + 1, _EVDEV_SIZE):
            _, _, etype, code, value = struct.unpack_from(_EVDEV_FMT, data, off)
            if etype != _EV_KEY or value == 2:
                continue
            if value:
                held.add(code)
                self._emit('down', code)
            else:
                held.discard(code)
                self._emit('up', code)

    def _run(self, stop):
        next_scan = 0.0
        while not stop.is_set():
            now = time.monotonic()
            if now >= next_scan:
                try:
                    self._scan()
                except Exception:
                    pass
                next_scan = now + _EVDEV_RESCAN
            fds = list(self._fds.values())
            if not fds:
                stop.wait(0.25)
                continue
            try:
                ready, _, _ = select.select(fds, [], [], 0.25)
            except (OSError, ValueError):
                for fd in fds:
                    try:
                        os.fstat(fd)
                    except OSError:
                        self._drop(fd)
                continue
            for fd in ready:
                self._drain(fd)

    def hook(self, callback, suppress=False):
        self._cb = callback
        if not (self._thread and self._thread.is_alive()):
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(self._stop,), daemon=True)
            self._thread.start()
        return callback

    def unhook_all(self):
        self._cb = None
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread and thread is not threading.current_thread():
            thread.join(1.0)
        for fd in list(self._fds.values()):
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds.clear()
        self._held.clear()
        self._ignored.clear()


class _WinKeyboard:
    def __init__(self):
        self._cb     = None
        self._held   = set()
        self._thread = None
        self._tid    = 0
        self._proc   = None
        self._hook   = None
        self._ok     = False

    @staticmethod
    def accessible():
        return _WINDOWS

    def _emit(self, kind, ident, name):
        cb = self._cb
        if cb and name:
            cb(_FakeKeyEvent(kind, name, ('k', ident)))

    def _on_key(self, ncode, wparam, lparam):
        if ncode == 0:
            try:
                info = _KBDLLHOOKSTRUCT.from_address(lparam)
                vk = info.vkCode
                if not (vk == 0xA2 and info.scanCode == _WIN_ALTGR_CTRL):
                    ident = vk | ((info.flags & 1) << 8)
                    name = _WIN_NAMES.get(vk)
                    if wparam in (0x100, 0x104):
                        if ident not in self._held:
                            self._held.add(ident)
                            self._emit('down', ident, name)
                    elif wparam in (0x101, 0x105):
                        self._held.discard(ident)
                        self._emit('up', ident, name)
            except Exception:
                pass
        return _user32.CallNextHookEx(None, ncode, wparam, lparam)

    def _run(self, ready):
        msg = wintypes.MSG()
        try:
            self._tid = _kernel32.GetCurrentThreadId()
            _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
            self._proc = _HOOKPROC(self._on_key)
            self._hook = _user32.SetWindowsHookExW(
                _WH_KEYBOARD_LL, self._proc, _kernel32.GetModuleHandleW(None), 0)
            self._ok = bool(self._hook)
        except Exception:
            self._ok = False
        ready.set()
        if not self._ok:
            return
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        _user32.UnhookWindowsHookEx(self._hook)
        self._hook = None

    def open(self):
        if self._thread and self._thread.is_alive():
            return self._ok
        ready = threading.Event()
        self._ok = False
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait(2.0)
        if not self._ok:
            self.unhook_all()
        return self._ok

    def hook(self, callback, suppress=False):
        self._cb = callback
        if not (self._thread and self._thread.is_alive()):
            self.open()
        return callback

    def unhook_all(self):
        self._cb = None
        thread, self._thread = self._thread, None
        if thread and thread is not threading.current_thread():
            if self._ok:
                _user32.PostThreadMessageW(self._tid, _WM_QUIT, 0, 0)
            thread.join(1.0)
        self._ok = False
        self._held.clear()


class _MacKeyboard:
    def __init__(self):
        self._cb     = None
        self._held   = set()
        self._stop   = threading.Event()
        self._thread = None
        self._tap    = None
        self._ref    = None
        self._ok     = False

    @staticmethod
    def _secure_input():
        try:
            carbon = ctypes.CDLL('/System/Library/Frameworks/Carbon.framework/Carbon')
            carbon.IsSecureEventInputEnabled.restype  = ctypes.c_ubyte
            carbon.IsSecureEventInputEnabled.argtypes = []
            return bool(carbon.IsSecureEventInputEnabled())
        except Exception:
            return False

    @staticmethod
    def accessible():
        if not _DARWIN or _CG is None:
            return False
        if os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_TTY'):
            return False
        check = getattr(_CG, 'CGPreflightListenEventAccess', None)
        if check is not None:
            check.restype  = ctypes.c_bool
            check.argtypes = []
            try:
                if not check():
                    return False
            except Exception:
                return False
        return not _MacKeyboard._secure_input()

    def _emit(self, kind, code):
        cb = self._cb
        name = _MAC_NAMES.get(code)
        if cb and name:
            cb(_FakeKeyEvent(kind, name, ('k', code)))

    def _on_tap(self, proxy, etype, event, refcon):
        try:
            if etype in _MAC_TAP_OFF:
                _CG.CGEventTapEnable(self._tap, True)
            elif etype in (10, 11, 12):
                code = _CG.CGEventGetIntegerValueField(event, 9)
                if etype == 12:
                    if code == _MAC_CAPS:
                        self._emit('down', code)
                        self._emit('up', code)
                    elif code in self._held:
                        self._held.discard(code)
                        self._emit('up', code)
                    else:
                        self._held.add(code)
                        self._emit('down', code)
                elif etype == 10:
                    if code not in self._held:
                        self._held.add(code)
                        self._emit('down', code)
                else:
                    self._held.discard(code)
                    self._emit('up', code)
        except Exception:
            pass
        return event

    def _run(self, ready):
        src = None
        try:
            self._ref = _TAP_CB(self._on_tap)
            self._tap = _CG.CGEventTapCreate(1, 0, 1, _MAC_TAP_MASK, self._ref, None)
            if self._tap:
                src = _CF.CFMachPortCreateRunLoopSource(None, self._tap, 0)
                if src:
                    _CF.CFRunLoopAddSource(_CF.CFRunLoopGetCurrent(), src, _CF_COMMON)
                    _CG.CGEventTapEnable(self._tap, True)
                    self._ok = True
        except Exception:
            self._ok = False
        ready.set()
        stop = self._stop
        while self._ok and not stop.is_set():
            _CF.CFRunLoopRunInMode(_CF_DEFAULT, 0.1, 0)
        try:
            if self._tap:
                _CF.CFMachPortInvalidate(self._tap)
            if src:
                _CF.CFRelease(src)
            if self._tap:
                _CF.CFRelease(self._tap)
        except Exception:
            pass
        self._tap = None

    def open(self):
        if self._thread and self._thread.is_alive():
            return self._ok
        ready = threading.Event()
        self._ok = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait(2.0)
        if not self._ok:
            self.unhook_all()
        return self._ok

    def hook(self, callback, suppress=False):
        self._cb = callback
        if not (self._thread and self._thread.is_alive()):
            self.open()
        return callback

    def unhook_all(self):
        self._cb = None
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread and thread is not threading.current_thread():
            thread.join(1.0)
        self._ok = False
        self._held.clear()


def _kernel_keyboard():
    if _LINUX:
        return _EvdevKeyboard()
    if _WINDOWS:
        return _WinKeyboard()
    if _DARWIN:
        return _MacKeyboard()
    return None


class inp():
    def __init__(self, term=None, watchfocus=True, trackmotion=False,
                 legacy_hold=0.1, quiet=True, repeatdelay=0.5, repeatrate=30,
                 backend=None):
        force = None if backend in (None, 'auto') else str(backend).lower()
        if force == 'raw':
            force = 'terminal'
        if force == 'evdev':
            force = 'kernel'
        if force not in (None, 'keyboard', 'kitty', 'kernel', 'terminal'):
            raise ValueError(
                "backend must be None, 'auto', 'keyboard', 'kitty', 'kernel' (or 'evdev') or 'terminal'")
        self._forced      = force
        self.lock         = threading.RLock()
        self.wf           = watchfocus
        self.track_motion = trackmotion
        self.focused      = True
        self._term        = None
        self.legacy_hold  = legacy_hold
        self.repeatdelay  = repeatdelay
        self.repeatrate   = repeatrate
        self.quiet        = quiet

        # ── keyboard (library handles held/press/release natively) ────────
        self._press_cbs     = defaultdict(list)
        self._release_cbs   = defaultdict(list)
        self._events        = deque()
        self._down          = {}
        self._pressed_keys  = set()
        self._release_at    = {}
        self._last_press    = {}   # name -> monotonic time of last terminal press (legacy tier)
        self._delayed_rel   = {}   # (name, id(entry)) -> (name, entry, due) for onrelease(delay=...)
        self._term_keys     = {}
        self._krep          = {}
        self._os_delay      = None
        self._os_gap        = None
        self._key_cbs       = []
        self._kitty_state   = None
        self._kitty_t       = 0.0
        self._kb_is_fallback = False
        self._kb_hook = None
        self.keyboard = None

        # Tier 1: the `keyboard` library (needs root on Linux/macOS and a local
        # keyboard, so it is skipped when either is missing).
        if force in (None, 'keyboard') and keyboard is not None \
                and (force or self._keyboard_usable()):
            try:
                self._kb_hook = keyboard.hook(self._native_event, suppress=False)
                self.keyboard = keyboard
            except Exception:
                self.keyboard = None
        if force == 'keyboard' and self.keyboard is None:
            raise RuntimeError("input_handler: backend 'keyboard' is unavailable")

        if force == 'kernel' and not self._open_kernel(True):
            raise RuntimeError("input_handler: backend 'kernel' is unavailable")

        # Tier 2-4: terminal input. Kitty keyboard protocol (true press/release)
        # if the terminal answers the probe, else the kernel tier (evdev / Windows
        # hook / macOS event tap), else raw stdin (press-only, held() is emulated
        # and only stays True while key repeats keep arriving).
        if self.keyboard is None:
            self.keyboard = _FallbackKeyboard()
            self._kb_is_fallback = True
            self._kb_hook = self.keyboard.hook(self._kb_event_raw, suppress=False)
            if force == 'terminal':
                self._kitty_state = 'off'
            if not self.quiet and force is None:
                sys.stderr.write(
                    "input_handler: `keyboard` unavailable, trying kitty keyboard "
                    "protocol, then kernel input, then raw stdin "
                    "(press-only, held() needs key repeat).\n"
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

        if term is None and _is_tty():
            term = Terminal()
        self.term = term # triggers setter
        if force == 'kitty' and self._kitty_state is None:
            self.cleanup()
            raise RuntimeError("input_handler: backend 'kitty' needs an interactive terminal")
        if force is None and self._kb_is_fallback and self._kitty_state is None:
            self._fall_to_kernel()

    def _open_kernel(self, force=False):
        kb = _kernel_keyboard()
        if kb is None or not (force or kb.accessible()) or not kb.open():
            return False
        try:
            self._kb_hook = kb.hook(self._native_event, suppress=False)
        except Exception:
            kb.unhook_all()
            return False
        self.keyboard = kb
        return True

    def _fall_to_kernel(self):
        if not self._kb_is_fallback or self._forced is not None:
            return
        old = self.keyboard
        if not self._open_kernel():
            return
        self._release_all()
        old.unhook_all()
        self._kb_is_fallback = False

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

    @property
    def backend(self):
        if not self._kb_is_fallback:
            if isinstance(self.keyboard, _EvdevKeyboard):
                return 'evdev'
            if isinstance(self.keyboard, (_WinKeyboard, _MacKeyboard)):
                return 'kernel'
            return 'keyboard'
        if self._kitty_state == 'on':
            return 'kitty'
        return 'terminal'

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
            sys.stdout.write(ansi.wrap_all(s)); sys.stdout.flush()
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
        self._write(ansi.mode(1004, True))

    def _disable_focus_reporting(self):
        self._write(ansi.mode(1004, False))

    def _enable_mouse(self):
        codes = ansi.mode(1000, True) + ansi.mode(1002, True) + ansi.mode(1006, True)
        if self.track_motion:
            codes += ansi.mode(1003, True)
        self._write(codes)

    def _disable_mouse(self):
        self._write(ansi.mode(1003, False) + ansi.mode(1002, False) + ansi.mode(1000, False) + ansi.mode(1006, False))

    def _start_kitty_probe(self):
        if self._kitty_state is not None:
            return
        try:
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                return
        except Exception:
            return
        self._kitty_state, self._kitty_t = 'probing', time.monotonic()
        self._write(ansi.csi('?', 'u') + ansi.csi('', 'c'))

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

    def _native_event(self, event):
        ident = getattr(event, 'ident', None)
        if ident is None:
            ident = getattr(event, 'scan_code', None)
        if ident is None:
            ident = event.name
        if event.event_type == 'down':
            self._key_down(ident, event)
        elif event.event_type == 'up':
            self._key_up(ident, event)

    def _key_down(self, ident, event):
        with self.lock:
            if ident in self._krep:
                return
            due = None if event.name in _NO_REPEAT else time.monotonic() + self.repeatdelay
            self._krep[ident] = [event.name, due, event]
            self._events.append((ident, event))

    def _key_up(self, ident, event):
        with self.lock:
            self._krep.pop(ident, None)
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
            self._last_press.clear()
            self._delayed_rel.clear()
            self._term_keys.clear()
            self._krep.clear()

    def _legacy_mode(self):
        # True only for the last tier: terminal input without kitty's real
        # press/release events (raw stdin), where held() is emulated.
        return self._kb_is_fallback and self._kitty_state != 'on'

    def _repeat_interval(self):
        rate = self.repeatrate
        return 1.0 / rate if rate and rate > 0 else None

    def _hold_for(self, st):
        gap = st.gap or self._os_gap
        return max(self.legacy_hold, 2.5 * gap) if gap else self.legacy_hold

    def _pend_wait(self):
        if self._os_gap:
            return max(self.legacy_hold, 2.5 * self._os_gap)
        return max(self.legacy_hold, 0.15)

    def _first_window(self):
        d = self._os_delay
        if d:
            return 0.6 * d, 1.5 * d
        return 0.2, 1.2

    def _learn_gap(self, st, gap):
        if gap >= _REPEAT_MIN_GAP:
            st.gap = gap if st.gap is None else 0.5 * (st.gap + gap)
            self._os_gap = gap if self._os_gap is None else 0.5 * (self._os_gap + gap)

    def _term_span(self, st):
        if st.nev >= 2:
            return self._hold_for(st)
        return self._first_window()[1]

    def _term_emit(self, kind, name, silent=False):
        self._kb_event_raw(_FakeKeyEvent(kind, name, ('t', name), silent))

    def _term_new(self, name, now):
        old = self._term_keys.get(name)
        if old is not None and not old.up:
            self._release_at.pop(name, None)
            self._term_emit('up', name)
        self._term_keys[name] = _TermKey(now, now + self.repeatdelay)
        self._term_emit('down', name)
        self._release_at[name] = now + self.legacy_hold

    def _term_commit(self, name, st):
        p = st.pend
        if not st.up:
            self._release_at.pop(name, None)
            self._term_emit('up', name)
        st.last = p
        st.nev  = 1
        st.gap  = None
        st.next = p + self.repeatdelay
        st.up   = False
        st.pend = None
        self._term_emit('down', name)
        self._release_at[name] = time.monotonic() + self.legacy_hold

    def _term_settle(self, name, st, now):
        if st.pend is not None:
            if now - st.pend <= self._pend_wait():
                return st
            self._term_commit(name, st)
        if now - st.last > self._term_span(st):
            if not st.up:
                self._release_at.pop(name, None)
                self._term_emit('up', name)
            del self._term_keys[name]
            return None
        return st

    def _term_press(self, name):
        now = time.monotonic()
        self._last_press[name] = now
        for entry in self._release_cbs.get(name, ()):
            if entry[3] is not None:       # per-callback release delay: (re)arm
                self._delayed_rel[(name, id(entry))] = (name, entry, now + entry[3])
        st = self._term_keys.get(name)
        if st is not None:
            st = self._term_settle(name, st, now)
        if st is None:
            self._term_new(name, now)
            return
        if st.pend is not None:
            if st.pend - st.last >= 0.2:
                self._os_delay = st.pend - st.last
            self._learn_gap(st, now - st.pend)
            st.pend = None
            st.nev = 3
        elif st.nev >= 2:
            self._learn_gap(st, now - st.last)
            st.nev += 1
        else:
            gap = now - st.last
            lo, hi = self._first_window()
            if gap < _REPEAT_MIN_GAP or self._pend_wait() < gap < lo:
                self._term_new(name, now)
                return
            st.pend = now
            return
        st.last = now
        if st.up:
            st.up = False
            self._term_emit('down', name, True)
        self._release_at[name] = now + self._hold_for(st)

    def _tick_repeats(self, now):
        interval = self._repeat_interval()
        with self.lock:
            for ident, rep in list(self._krep.items()):
                due = rep[1]
                if due is None or interval is None or now < due:
                    continue
                self._events.append((ident, rep[2]))
                due += interval
                rep[1] = due if due > now else now + interval
        for name, st in list(self._term_keys.items()):
            st = self._term_settle(name, st, now)
            if st is None or interval is None or st.pend is not None or st.nev < 2:
                continue
            if now >= st.next and now - st.last <= self._hold_for(st):
                self._term_emit('down', name)
                st.next += interval
                if st.next <= now:
                    st.next = now + interval

    def _flush_releases(self, now):
        if self._release_at:
            for name, t in list(self._release_at.items()):
                if now >= t:
                    del self._release_at[name]
                    st = self._term_keys.get(name)
                    if st is not None:
                        st.up = True
                    self._kb_event_raw(_FakeKeyEvent('up', name, ('t', name)))

    def _stdin_press(self, name):
        if self._kb_is_fallback and self._kitty_state != 'on':
            self._term_press(name)

    def _term_event(self, name, ident, ev):
        if not self._kb_is_fallback:
            return
        if self._kitty_state == 'on':
            if ev == 3:
                self._key_up(ident, _FakeKeyEvent('up', name, ident))
            else:
                self._key_down(ident, _FakeKeyEvent('down', name, ident))
        elif ev != 3:
            self._term_press(name)

    #MOUSE
    def _read_raw(self):
        take = getattr(self._term, 'take', None)
        return (take() if callable(take) else '') + self._read_stdin()

    def _read_stdin(self):
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
            if c != ansi.ESC:
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
            if nxt == ansi.CSI_INTRO:
                if buf.startswith(ansi.CSI + 'M', i):
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
            if nxt == ansi.SS3_INTRO:
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
                self._write(ansi.csi('>11', 'u'))
            elif final == 'c' and self._kitty_state == 'probing':
                self._kitty_state = 'off'
                self._fall_to_kernel()
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
        if ch == ansi.ESC:
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
        for handle in list(self._mouse_cbs):
            etype, cb, once, nargs = handle
            if etype in (event, 'any'):
                if once:
                    # skip if already removed (e.g. by stopmouse from another callback)
                    if not any(h is handle for h in self._mouse_cbs):
                        continue
                    self._mouse_cbs = [h for h in self._mouse_cbs if h is not handle]
                args = (x, y, data, event)
                if nargs is not None:
                    args = args[:nargs]
                cb(*args)

    #CENTRAL UPDATE
    def update(self):
        now = time.monotonic()
        self._mouse_wheel = 0
        self._buf += self._read_raw()
        self._parse_input(now)
        if self._kitty_state == 'probing' and now - self._kitty_t > 1.5:
            self._kitty_state = 'off'
            if self._forced == 'kitty':
                raise RuntimeError(
                    "input_handler: backend 'kitty' is unsupported by this terminal")
            self._fall_to_kernel()
        self._tick_repeats(now)
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
            legacy = self._legacy_mode()
            for ident, event in events:
                if getattr(event, 'silent', False):
                    continue
                down = event.event_type == 'down'
                self._fire_key(event.name, 'press' if down else 'release')
                table = self._press_cbs if down else self._release_cbs
                for entry in list(table.get(event.name, ())):
                    if not down and legacy and entry[3] is not None:
                        continue    # has its own delay: fired by _fire_delayed_releases
                    self._dispatch(table, entry, event, down)
            self._fire_delayed_releases(now)
        else:
            self._delayed_rel.clear()

    def _dispatch(self, table, entry, event, down):
        cb, accepts, token, _delay = entry
        if token is not None and not self._consume(table, token):
            return    # one-shot already fired / removed
        cb(event) if accepts else cb()

    def _fire_key(self, name, event):
        for handle in list(self._key_cbs):
            key, etype, cb, once, nargs, caps = handle
            if etype not in (event, 'any'):
                continue
            if key is not None and key != 'any':
                if caps:
                    if str(key).lower() != str(name).lower():
                        continue
                elif key != name:
                    continue
            if once:
                if not any(h is handle for h in self._key_cbs):
                    continue
                self._key_cbs = [h for h in self._key_cbs if h is not handle]
            args = (name, event)
            if nargs is not None:
                args = args[:nargs]
            cb(*args)

    def _fire_delayed_releases(self, now):
        if not self._delayed_rel:
            return
        legacy = self._legacy_mode()
        for k, (name, entry, due) in list(self._delayed_rel.items()):
            if now < due:
                continue
            del self._delayed_rel[k]
            if not legacy:
                continue    # kitty took over: real release events are used instead
            if not any(e is entry for e in self._release_cbs.get(name, ())):
                continue    # unregistered meanwhile
            self._dispatch(self._release_cbs, entry,
                           _FakeKeyEvent('up', name, ('t', name)), False)

    #KEYBOARD API
    def held(self, key=None, caps=False, delay=None):
        # delay: seconds a key stays "held" after its last press. Only used in
        # the last tier (terminal fallback without kitty), where there are no
        # release events and held() is emulated from key-repeat. It replaces
        # legacy_hold for this call, so a developer can bridge the OS
        # repeat-start gap (often 250-600 ms) for actions like a persistent jump.
        # Ignored by the `keyboard`, kitty and kernel tiers, which report real releases.
        if not self.focused:
            return False
        pressed = self._pressed_keys
        if delay is not None and self._legacy_mode():
            now = time.monotonic()
            pressed = {n for n, t in list(self._last_press.items())
                       if now - t <= delay}
        if isinstance(key, str) and key:
            if caps:
                return key.upper() in pressed or key.lower() in pressed
            return key in pressed
        if isinstance(key, (list, tuple)) and key:
            if caps:
                return any(k.upper() in pressed or k.lower() in pressed for k in key)
            return any(k in pressed for k in key)
        return list(pressed)

    @staticmethod
    def _consume(table, token):
        # Remove every entry carrying `token` (a once-group shared by the
        # lower/upper registrations when caps=True). Returns True if any
        # entry was still registered.
        removed = False
        for k, lst in list(table.items()):
            kept = [e for e in lst if e[2] is not token]
            if len(kept) != len(lst):
                removed = True
                table[k] = kept
        return removed

    def onpress(self, key, callback, caps=False, once=False):
        accepts = _accepts_arg(callback)
        token = object() if once else None
        if caps:
            self._press_cbs[key.lower()].append((callback, accepts, token, None))
            self._press_cbs[key.upper()].append((callback, accepts, token, None))
            return (key.lower(), callback, 'press'), (key.upper(), callback, 'press')
        self._press_cbs[key].append((callback, accepts, token, None))
        return (key, callback, 'press')

    def onrelease(self, key, callback, caps=False, once=False, delay=None):
        # delay: seconds after the key's last press before the callback fires.
        # Only used in the last tier (terminal fallback without kitty), where the
        # release is emulated; it replaces legacy_hold for this callback and
        # matches held(key, delay=...). Ignored by the keyboard, kitty and kernel tiers.
        accepts = _accepts_arg(callback)
        token = object() if once else None
        if caps:
            self._release_cbs[key.lower()].append((callback, accepts, token, delay))
            self._release_cbs[key.upper()].append((callback, accepts, token, delay))
            return (key.lower(), callback, 'release'), (key.upper(), callback, 'release')
        self._release_cbs[key].append((callback, accepts, token, delay))
        return (key, callback, 'release')

    def onkey(self, key, callback, event='any', once=False, caps=False):
        # key: key name, or None / 'any' for every key
        # event: 'press' | 'release' | 'any'
        # callback: cb(key, event) — receives as many of these as its signature accepts
        # once: if True, the callback is removed after it fires the first time
        handle = (key, event, callback, once, _positional_count(callback), caps)
        self._key_cbs.append(handle)
        return handle

    def stopkey(self, handle):
        before = len(self._key_cbs)
        self._key_cbs = [h for h in self._key_cbs if h is not handle]
        return len(self._key_cbs) != before

    def offkey(self, handle):
        return self.stopkey(handle)

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
        self._key_cbs.clear()
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

    def onmouse(self, event, callback, once=False): # register a mouse event callback
        # event: 'click' | 'release' | 'move' | 'wheel' | 'any'
        # callback: cb(x, y, data, event) — receives as many of these as its signature accepts
        # data is button index or scroll delta; event is the event name that fired
        # once: if True, the callback is removed after it fires the first time
        handle = (event, callback, once, _positional_count(callback))
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
                self._write(ansi.csi('<', 'u'))
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
