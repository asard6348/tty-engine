import os, sys, time, subprocess, threading, textwrap, traceback, socket, ctypes
from pygments import highlight
from pygments.lexers.python import PythonConsoleLexer as PythonTracebackLexer
from pygments.formatters.terminal import TerminalFormatter

def debug(debugger=[], dinfo=[], title=None):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('127.0.0.1', 0))
    port = server.getsockname()[1]
    server.listen(1)
    reset = "\033[?1049l\033[?1049h\033[?25l\033[2J\033[H"
    title_repr = repr(title)
    script = textwrap.dedent(f"""
        import sys, socket, ctypes
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            kernel32.SetConsoleMode(handle, 7)
        if(not {title_repr} is None):
            sys.stdout.write("\033]0;{title}\007")
        sys.stdout.write("{reset}")
        sys.stdout.flush()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(('127.0.0.1', {port}))
        f = sock.makefile('r', buffering=1)
        for frame in f:
            sys.stdout.write(frame)
            sys.stdout.flush()
        input()
        try:
            sock.send(b'\\n')
        except Exception:
            pass
    """).strip()
    if sys.platform == "win32":
        try:
            proc = subprocess.Popen(
                ['conhost.exe', sys.executable, '-c', script],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                start_new_session=True,
            )
        except FileNotFoundError:
            proc = subprocess.Popen(
                [sys.executable, '-c', script],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                start_new_session=True,
            )
    elif sys.platform == "darwin":
        script_file = '/tmp/debugger_recv.py'
        with open(script_file, 'w') as f:
            f.write(script)
        window_title = f"debugger_{port}"
        proc = subprocess.Popen(
            ["osascript", "-e",
             f'tell app "Terminal" to do script "python3 {script_file}"'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        for term in ['x-terminal-emulator', 'gnome-terminal', 'xterm', 'konsole']:
            try:
                proc = subprocess.Popen([term, '-e', sys.executable, '-c', script],
                                        stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL,
                                        close_fds=True)
                break
            except FileNotFoundError:
                continue
    server.settimeout(5)
    try:
        conn, _ = server.accept()
    except socket.timeout:
        return
    pipe = conn.makefile('w', buffering=1)
    debugger.clear()
    debugger.append(proc)
    def renderdinfo(dinfo):
        try:
            while True:
                if proc is not None:
                    lines = "".join(dinfo).split("\n")
                    out = "\033[H"
                    for line in lines:
                        out += line + "\033[K\n"
                    pipe.write(out)
                    pipe.flush()
                time.sleep(0.01)
        except Exception as e:
            try:
                pipe.write("\033[H\033[2J")
                exc = highlight(traceback.format_exc(), PythonTracebackLexer(), TerminalFormatter())
                pipe.write(exc)
                pipe.flush()
                input()
            except Exception:
                pass
            try:
                conn.recv(1)
            except Exception:
                pass
        finally:
            try:
                pipe.write("\033[?25h")
                pipe.flush()
            except Exception:
                pass
            try:
                if sys.platform != "win32":
                    fd = os.open('/dev/tty', os.O_WRONLY | os.O_NOCTTY)
                    os.write(fd, b'\033[I')
                    os.close(fd)
                else:
                    os.write(sys.stdin.fileno(), b'\033[I')
            except OSError:
                pass
            try:
                sys.stdout.write('\033[?1004h')
                sys.stdout.flush()
            except Exception:
                pass
            if sys.platform == "darwin":
                try:
                    subprocess.Popen(
                        ["osascript", "-e",
                         f'tell application "Terminal" to close (every window whose '
                         f'name contains "{port}")'],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
            else:
                try:
                    proc.kill()
                except Exception:
                    pass
    threading.Thread(target=renderdinfo, daemon=True, args=(dinfo,)).start()
    return debugger, dinfo
