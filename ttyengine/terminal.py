import os, sys, re, time, codecs, contextlib

_WINDOWS = sys.platform == 'win32'
if _WINDOWS:
    import msvcrt
else:
    import select, termios, tty

QUERY_TIMEOUT = 5.0

MODE_SYNC = 2026
MODE_MOUSE_CLICK = 1000
MODE_MOUSE_DRAG = 1002
MODE_MOUSE_MOTION = 1003
MODE_MOUSE_SGR = 1006

_CPR = re.compile(r'\x1b\[[0-9]+;[0-9]+R')
_XTVERSION = re.compile(r'\x1bP>\|([^\x1b]*)\x1b\\')
_BGCOLOR = re.compile(r'\x1b\]11;rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)(?:\x07|\x1b\\)')
_FGCOLOR = re.compile(r'\x1b\]10;rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)(?:\x07|\x1b\\)')


def xparse_color(component, bits=16):
    if bits not in (8, 16):
        raise ValueError(f"bits must be 8 or 16, got {bits}")
    size = len(component)
    value = int(component, 16)
    if size == 4:
        wide = value
    elif size == 3:
        wide = (value << 4) | (value >> 8)
    elif size == 2:
        wide = value * 0x0101
    elif size == 1:
        wide = value * 0x1111
    else:
        raise ValueError(f"hex component must be 1-4 characters, got {size}")
    return wide >> 8 if bits == 8 else wide


class Terminal:
    def __init__(self, stream=None):
        self.stream = stream if stream is not None else sys.__stdout__
        self._pending = ''
        self._decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self._cbreak = False
        self._modes = {}
        self._modes_ok = False
        self._modes_dead = False
        self._apple_found = None
        try:
            self._fd = sys.__stdin__.fileno() if sys.__stdin__.isatty() else None
        except Exception:
            self._fd = None

    @property
    def is_a_tty(self):
        try:
            return bool(self.stream.isatty())
        except Exception:
            return False

    def _size(self):
        for stream in (self.stream, sys.__stdout__):
            try:
                size = os.get_terminal_size(stream.fileno())
                return size.lines, size.columns
            except (OSError, ValueError, AttributeError, TypeError):
                pass
        return int(os.getenv('LINES', '25')), int(os.getenv('COLUMNS', '80'))

    @property
    def height(self):
        return self._size()[0]

    @property
    def width(self):
        return self._size()[1]

    def _write(self, text):
        try:
            self.stream.write(text)
            self.stream.flush()
        except Exception:
            pass

    def take(self):
        text, self._pending = self._pending, ''
        return text

    def ungetch(self, text):
        self._pending = text + self._pending

    def kbhit(self, timeout=None):
        if self._fd is None:
            return False
        if _WINDOWS:
            end = None if timeout is None else time.monotonic() + timeout
            while not msvcrt.kbhit():
                if end is not None and time.monotonic() >= end:
                    return False
                time.sleep(0.005)
            return True
        try:
            return bool(select.select([self._fd], [], [], timeout)[0])
        except (OSError, ValueError):
            return False

    def _read_available(self):
        if self._fd is None:
            return ''
        if _WINDOWS:
            chars = []
            while msvcrt.kbhit():
                chars.append(msvcrt.getwch())
            return ''.join(chars)
        chunks = []
        while True:
            try:
                ready, _, _ = select.select([self._fd], [], [], 0)
                if not ready:
                    break
                data = os.read(self._fd, 4096)
            except (OSError, ValueError):
                break
            if not data:
                break
            chunks.append(data)
            if len(data) < 4096:
                break
        return self._decoder.decode(b''.join(chunks)) if chunks else ''

    def _read_until(self, pattern, timeout):
        start = time.monotonic()
        buf = self.take()
        while True:
            buf += self._read_available()
            match = pattern.search(buf)
            if match is not None or len(buf) > 65536:
                break
            left = timeout - (time.monotonic() - start)
            if left <= 0 or not self.kbhit(left):
                break
        return match, buf

    def _query(self, query, pattern, timeout):
        if not self.is_a_tty or self._fd is None:
            return None
        with self._rare():
            self._write(query + '\x1b[6n')
            boundary, data = self._read_until(_CPR, timeout)
            if boundary is not None:
                data = data[:boundary.start()] + data[boundary.end():]
            found = pattern.search(data)
            if found is not None:
                data = data[:found.start()] + data[found.end():]
        self.ungetch(data)
        return found

    @contextlib.contextmanager
    def _rare(self):
        if self._cbreak:
            yield
        else:
            with self.cbreak():
                yield

    @contextlib.contextmanager
    def cbreak(self):
        if _WINDOWS or self._fd is None:
            yield
            return
        saved = termios.tcgetattr(self._fd)
        was = self._cbreak
        tty.setcbreak(self._fd, termios.TCSANOW)
        self._cbreak = True
        try:
            yield
        finally:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, saved)
            self._cbreak = was

    @contextlib.contextmanager
    def _sequence(self, enter, leave):
        styled = self.is_a_tty
        if styled:
            self._write(enter)
        try:
            yield
        finally:
            if styled:
                self._write(leave)

    def fullscreen(self):
        return self._sequence('\x1b[?1049h\x1b[22;0;0t', '\x1b[?1049l\x1b[23;0;0t')

    def hidden_cursor(self):
        return self._sequence('\x1b[?25l', '\x1b[?12l\x1b[?25h')

    def no_line_wrap(self):
        return self._sequence('\x1b[?7l', '\x1b[?7h')

    def _apple(self, timeout):
        if os.environ.get('TERM_PROGRAM') == 'Apple_Terminal':
            return True
        if self._apple_found is None:
            match = self._query('\x1b[>q', _XTVERSION, timeout)
            self._apple_found = bool(match) and match.group(1).startswith('Apple_Terminal')
        return self._apple_found

    def get_dec_mode(self, mode, timeout=QUERY_TIMEOUT):
        if mode in self._modes:
            return self._modes[mode]
        if self._modes_dead or self._apple(timeout):
            return -1
        pattern = re.compile(r'\x1b\[\?%d;([0-4])\$y' % mode)
        match = self._query('\x1b[?%d$p' % mode, pattern, timeout)
        if match is None:
            if self.is_a_tty and self._fd is not None and not self._modes_ok:
                self._modes_dead = True
            return -1
        self._modes_ok = True
        self._modes[mode] = int(match.group(1))
        return self._modes[mode]

    @contextlib.contextmanager
    def dec_modes_enabled(self, *modes, timeout=QUERY_TIMEOUT):
        turned = [mode for mode in modes if self.get_dec_mode(mode, timeout) == 2]
        if turned and self.is_a_tty:
            self._write('\x1b[?%sh' % ';'.join(str(mode) for mode in turned))
            for mode in turned:
                self._modes[mode] = 1
        try:
            yield
        finally:
            if turned and self.is_a_tty:
                self._write('\x1b[?%sl' % ';'.join(str(mode) for mode in turned))
                for mode in turned:
                    self._modes[mode] = 2

    def synchronized_output(self, timeout=QUERY_TIMEOUT):
        return self.dec_modes_enabled(MODE_SYNC, timeout=timeout)

    def mouse_enabled(self, *, clicks=True, report_drag=False, report_motion=False, timeout=QUERY_TIMEOUT):
        modes = [MODE_MOUSE_SGR]
        if report_motion:
            modes.append(MODE_MOUSE_MOTION)
        elif report_drag:
            modes.append(MODE_MOUSE_DRAG)
        elif clicks:
            modes.append(MODE_MOUSE_CLICK)
        return self.dec_modes_enabled(*modes, timeout=timeout)

    def _color(self, query, pattern, timeout, bits):
        if bits not in (8, 16):
            raise ValueError(f"bits must be 8 or 16, got {bits}")
        match = self._query(query, pattern, timeout)
        if match is None:
            return (-1, -1, -1)
        return tuple(xparse_color(value, bits) for value in match.groups())

    def get_bgcolor(self, timeout=QUERY_TIMEOUT, bits=16):
        return self._color('\x1b]11;?\x07', _BGCOLOR, timeout, bits)

    def get_fgcolor(self, timeout=QUERY_TIMEOUT, bits=16):
        return self._color('\x1b]10;?\x07', _FGCOLOR, timeout, bits)
