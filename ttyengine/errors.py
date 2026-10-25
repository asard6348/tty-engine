import contextlib, os, re, sys, threading, traceback

from . import ansi

HOLD_ENV = 'TTYENGINE_HOLD'
HOLD_PROMPT = 'Press Enter to close...'
EXIT_CODE = 1

_pending = []
_pending_lock = threading.Lock()
_wake = None

def highlight_traceback(tb_str: str) -> str:
    if not ansi.color_enabled():
        return tb_str
    RESET, BOLD, RED, GREEN, YELLOW, CYAN, MAGENTA = (
        ansi.RESET, ansi.BOLD, ansi.sgr(91), ansi.sgr(92), ansi.sgr(93), ansi.sgr(96), ansi.sgr(95)
    )
    lines = []
    for line in tb_str.splitlines(True):
        if line.startswith("Traceback"):
            lines.append(f"{BOLD}{RED}{line}{RESET}")
        elif line.strip().startswith("File "):
            m = re.match(r'^(\s*File )("[^"]+")(, line )(\d+)(, in )(.*)$', line)
            if m:
                lines.append(
                    f"{m.group(1)}{GREEN}{m.group(2)}{RESET}"
                    f"{m.group(3)}{YELLOW}{m.group(4)}{RESET}"
                    f"{m.group(5)}{CYAN}{m.group(6)}{RESET}\n"
                )
            else:
                lines.append(line)
        elif ":" in line and not line.startswith(" "):
            parts = line.split(":", 1)
            lines.append(f"{BOLD}{RED}{parts[0]}:{RESET}{BOLD}{parts[1]}{RESET}")
        else:
            line_hl = re.sub(r'("[^"]*"|\'[^\']*\')', rf'{GREEN}\1{RESET}', line)
            kw = r'\b(def|class|return|if|elif|else|while|for|in|import|from|as|try|except|finally|raise|with|pass|break|continue|and|or|not|is|None|True|False)\b'
            line_hl = re.sub(kw, rf'{MAGENTA}\1{RESET}', line_hl)
            lines.append(line_hl)
    return "".join(lines)


def _stream(stream=None):
    if stream is not None:
        return stream
    for candidate in (sys.stderr, sys.stdout, sys.__stderr__, sys.__stdout__):
        if candidate is not None:
            return candidate
    return None


def _is_tty(stream):
    try:
        return bool(stream and stream.isatty())
    except Exception:
        return False


def owns_console():
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        pids = (ctypes.c_uint * 4)()
        count = ctypes.windll.kernel32.GetConsoleProcessList(pids, 4)
        return 0 < count <= 2
    except Exception:
        return False


def should_hold(hold=None):
    if hold is None:
        hold = os.environ.get(HOLD_ENV, 'auto')
    if isinstance(hold, str):
        mode = hold.strip().lower()
        if mode in ('1', 'true', 'yes', 'on', 'always'):
            return True
        if mode in ('0', 'false', 'no', 'off', 'never'):
            return False
        return owns_console()
    return bool(hold)


def hold_console(prompt=HOLD_PROMPT, stream=None):
    stream = _stream(stream)
    try:
        if stream is not None and prompt:
            stream.write(prompt)
            stream.flush()
        input()
    except (Exception, KeyboardInterrupt):
        pass


def format_error(exc=None, color=None, skip=0):
    if exc is None:
        exc = sys.exc_info()[1]
    if exc is None:
        return ''
    tb = exc.__traceback__
    for _ in range(skip):
        if tb is not None and tb.tb_next is not None:
            tb = tb.tb_next
    text = ''.join(traceback.format_exception(type(exc), exc, tb))
    if color is None:
        color = ansi.color_enabled()
    return highlight_traceback(text) if color else text


def report(exc=None, clear=True, stream=None, out=None, flush=None, skip=0):
    stream = _stream(stream)
    if out is None:
        if stream is None:
            return False
        out, flush = stream.write, stream.flush
    tty = _is_tty(stream)
    try:
        if clear and tty:
            out(ansi.wrap_all(ansi.CLEAR_ALL))
        text = format_error(exc, color=tty and ansi.color_enabled(), skip=skip) + '\n'
        out(ansi.wrap_all(text) if tty else text)
        if flush:
            flush()
        return True
    except Exception:
        return False


def trace(exception, lexer=None, clear=True, out=None, flush=None):
    if not report(exception, clear=clear, out=out, flush=flush):
        raise exception


def attempt(func, catch=None, lexer=None, fatal=True, clear=True, reset=True, out=None, flush=None,
            hold=None, code=EXIT_CODE, stream=None):
    try:
        return func()
    except Exception as e:
        target = _stream(stream)
        tty = _is_tty(target)
        if out is None and target is not None:
            out, flush = target.write, target.flush
        if reset and fatal and tty and out:
            try:
                out(ansi.wrap(ansi.FULL_RESET))
            except Exception:
                pass
        catch_exc = None
        if callable(catch):
            try:
                catch()
            except Exception as ce:
                catch_exc = ce
        if not report(e, clear=clear, stream=target, out=out, flush=flush, skip=1):
            raise
        if catch_exc is not None:
            report(catch_exc, clear=False, stream=target, out=out, flush=flush)
        if not fatal:
            return None
        if should_hold(hold):
            hold_console(stream=target)
        sys.exit(code)


def install(hold=None, code=EXIT_CODE, stream=None):
    previous = sys.excepthook

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return previous(exc_type, exc, tb)
        target = _stream(stream)
        text = ''.join(traceback.format_exception(exc_type, exc, tb))
        tty = _is_tty(target)
        try:
            if target is not None:
                target.write(highlight_traceback(text) if tty and ansi.color_enabled() else text)
                target.flush()
        except Exception:
            return previous(exc_type, exc, tb)
        if should_hold(hold):
            hold_console(stream=target)

    sys.excepthook = hook
    return previous


def defer(exc):
    with _pending_lock:
        if not _pending:
            _pending.append(exc)
    wake = _wake
    if wake is not None:
        try:
            wake()
        except Exception:
            pass


def pending():
    return bool(_pending)


def raise_pending():
    with _pending_lock:
        exc = _pending[0] if _pending else None
        del _pending[:]
    if exc is not None:
        raise exc


@contextlib.contextmanager
def capture(wake=None):
    global _wake
    previous = threading.excepthook, sys.unraisablehook, _wake

    def on_thread(args):
        if args.exc_type is SystemExit:
            return
        exc = args.exc_value
        if exc is None:
            exc = args.exc_type()
        defer(exc)

    def on_unraisable(args):
        if args.exc_value is not None:
            defer(args.exc_value)

    with _pending_lock:
        del _pending[:]
    _wake = wake
    threading.excepthook = on_thread
    sys.unraisablehook = on_unraisable
    try:
        yield
    finally:
        threading.excepthook, sys.unraisablehook, _wake = previous
