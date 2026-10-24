import os
import re

ESC = chr(27)
BEL = chr(7)
CSI_INTRO = '['
OSC_INTRO = ']'
DCS_INTRO = 'P'
SS3_INTRO = 'O'
CSI = ESC + CSI_INTRO
OSC = ESC + OSC_INTRO
DCS = ESC + DCS_INTRO
SS3 = ESC + SS3_INTRO
ST = ESC + '\\'

PREFIX_ENV = 'TTYENGINE_ANSI_PREFIX'
SUFFIX_ENV = 'TTYENGINE_ANSI_SUFFIX'
NO_COLOR_ENV = 'NO_COLOR'

ESC_RE = re.escape(ESC)
BEL_RE = re.escape(BEL)
CSI_RE = re.escape(CSI)
OSC_RE = re.escape(OSC)
DCS_RE = re.escape(DCS)
ST_RE = re.escape(ST)

_prefix = ''
_suffix = ''
_version = 0


def csi(params, final):
    return CSI + params + final


def sgr(*params):
    return CSI + ';'.join([str(int(p)) for p in params]) + 'm'


def fg(red, green, blue):
    return '%s38;2;%d;%d;%dm' % (CSI, red, green, blue)


def bg(red, green, blue):
    return '%s48;2;%d;%d;%dm' % (CSI, red, green, blue)


def move(row, column):
    return '%s%d;%dH' % (CSI, row, column)


def osc(body):
    return OSC + body + BEL


def mode(number, on):
    return '%s?%d%s' % (CSI, number, 'h' if on else 'l')


def modes(numbers, on):
    return CSI + '?' + ';'.join([str(number) for number in numbers]) + ('h' if on else 'l')


RESET = sgr(0)
RESETS = (RESET, sgr())
BOLD = sgr(1)
ITALIC = sgr(3)
UNDERLINE = sgr(4)
HOME = csi('', 'H')
CLEAR = csi('2', 'J')
CLEAR_SCROLLBACK = csi('3', 'J')
CLEAR_ALL = HOME + CLEAR + CLEAR_SCROLLBACK
ERASE_LINE = csi('', 'K')
ERASE_BELOW = csi('', 'J')
FULL_RESET = ESC + 'c'
SAVE_CURSOR = ESC + '7'
RESTORE_CURSOR = ESC + '8'

_ANY = re.compile(
    ESC_RE + r'(?:' + re.escape(CSI_INTRO) + r'[0-?]*[ -/]*[@-~]|'
    + re.escape(OSC_INTRO) + r'[^' + BEL_RE + ESC_RE + r']*(?:' + BEL_RE + '|' + ST_RE + r')|[ -/]*[0-~])'
)


def _decode(text):
    return text.encode('ascii', 'backslashreplace').decode('unicode_escape')


def set_wrapper(prefix=None, suffix=None):
    global _prefix, _suffix, _version
    if prefix is None:
        prefix = _decode(os.environ.get(PREFIX_ENV, ''))
    if suffix is None:
        suffix = _decode(os.environ.get(SUFFIX_ENV, ''))
    if not isinstance(prefix, str) or not isinstance(suffix, str):
        raise TypeError('wrapper prefix and suffix must be strings')
    _prefix, _suffix = prefix, suffix
    _version += 1


def get_wrapper():
    return _prefix, _suffix


def wrapped():
    return bool(_prefix or _suffix)


def wrap(code):
    return _prefix + code + _suffix


def wrap_all(text):
    if not (_prefix or _suffix):
        return text
    return _ANY.sub(lambda match: _prefix + match.group(0) + _suffix, text)


def _surround(body):
    before = '(?:%s)?' % re.escape(_prefix) if _prefix else ''
    after = '(?:%s)?' % re.escape(_suffix) if _suffix else ''
    return before + '(?:' + body + ')' + after


class Pattern:
    def __init__(self, body, flags=0):
        self.body = body
        self.flags = flags
        self._seen = -1
        self._regex = None

    def regex(self):
        if self._seen != _version:
            self._regex = re.compile(_surround(self.body), self.flags)
            self._seen = _version
        return self._regex

    def search(self, *args):
        return self.regex().search(*args)

    def match(self, *args):
        return self.regex().match(*args)

    def split(self, *args):
        return self.regex().split(*args)

    def sub(self, *args):
        return self.regex().sub(*args)

    def finditer(self, *args):
        return self.regex().finditer(*args)

    def findall(self, *args):
        return self.regex().findall(*args)


SGR = Pattern(CSI_RE + r'([0-9;]*)m')
SEQUENCE = Pattern(
    '(' + CSI_RE + r'[0-9;]*[A-Za-z]|' + OSC_RE + r'[^' + BEL_RE + r']*' + BEL_RE + '?|' + ESC_RE + r'[()]?[A-Za-z0-9])'
)


def color_enabled():
    return not os.environ.get(NO_COLOR_ENV)


def monochrome(no_color=None):
    return (not color_enabled()) if no_color is None else bool(no_color)


def _drop_color(match):
    params = match.group(1).split(';')
    kept = []
    i = 0
    while i < len(params):
        token = params[i]
        code = int(token) if token else 0
        if code in (38, 48, 58):
            kind = params[i + 1] if i + 1 < len(params) else ''
            i += 3 if kind == '5' else 5 if kind == '2' else 1
            continue
        if 30 <= code <= 39 or 40 <= code <= 49 or code == 59 or 90 <= code <= 97 or 100 <= code <= 107:
            i += 1
            continue
        kept.append(token)
        i += 1
    if not kept:
        return ''
    return CSI + ';'.join(kept) + 'm'


def strip_color(text):
    return SGR.sub(_drop_color, text)


set_wrapper()
