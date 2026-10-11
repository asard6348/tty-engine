import sys, os, re, glob, math, time, struct, random, shutil, queue, atexit, weakref, inspect, tempfile, ctypes, ctypes.util, threading, subprocess
from array import array

__all__ = ['Mixer', 'Sound', 'Voice', 'note_freq', 'decoders', 'find_ffmpeg', 'set_ffmpeg']

_RATE = 44100
_TAU = 2.0 * math.pi
_NOTE_RE = re.compile(r'^([A-Ga-g])([#b]?)(-?\d+)?$')
_SEMITONES = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
_RESTS = ('', 'R', 'REST', '-', '_')
_FLIP = bytes(b ^ 0x80 for b in range(256))


def _locate(spec):
    if spec is None:
        return None
    if callable(spec):
        return _locate(spec())
    if isinstance(spec, (tuple, list)):
        return float(spec[0]), float(spec[1])
    t = getattr(spec, 'transform', None)
    if t is not None:
        x = t.x + t.vx
        y = t.y + t.vy
        try:
            x += t.xlen() / 2.0
            y -= t.ylen() / 2.0
        except Exception:
            pass
        return float(x), float(y)
    if hasattr(spec, 'camx') and hasattr(spec, 'dimx'):
        return spec.camx + spec.dimx / 2.0, spec.camy - spec.dimy / 2.0
    if hasattr(spec, 'x') and hasattr(spec, 'y'):
        return float(spec.x), float(spec.y)
    raise TypeError(f'cannot derive a position from {spec!r}')


def _call(cb, arg):
    try:
        params = inspect.signature(cb).parameters.values()
        wants = any(p.kind in (p.VAR_POSITIONAL, p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) for p in params)
    except (TypeError, ValueError):
        wants = True
    if wants:
        cb(arg)
    else:
        cb()


def note_freq(note):
    if isinstance(note, (int, float)):
        return float(note)
    text = str(note).strip()
    if text.upper() in _RESTS:
        return 0.0
    m = _NOTE_RE.match(text)
    if not m:
        raise ValueError(f'invalid note: {note!r}')
    letter, accidental, octave = m.groups()
    semi = _SEMITONES[letter.upper()] + (1 if accidental == '#' else -1 if accidental == 'b' else 0)
    octave = 4 if octave is None else int(octave)
    return 440.0 * 2.0 ** ((12 * (octave + 1) + semi - 69) / 12.0)


def _sine(p): return math.sin(_TAU * p)
def _square(p): return 1.0 if p < 0.5 else -1.0
def _saw(p): return 2.0 * p - 1.0
def _triangle(p): return 1.0 - 4.0 * abs(p - 0.5)
def _noise(p): return random.random() * 2.0 - 1.0

_WAVES = {'sine': _sine, 'square': _square, 'saw': _saw, 'triangle': _triangle, 'noise': _noise}


def _synth(rate, freq, duration, wave, volume, end_freq, attack, release):
    fn = _WAVES.get(wave)
    if fn is None:
        raise ValueError(f'unknown waveform: {wave!r} (choose from {", ".join(_WAVES)})')
    n = max(1, int(duration * rate))
    out = array('h', bytes(2 * n))
    f0 = note_freq(freq)
    f1 = f0 if end_freq is None else note_freq(end_freq)
    if f0 <= 0.0 and f1 <= 0.0:
        return out
    amp = 32767.0 * min(1.0, max(0.0, volume))
    a = max(1, int(attack * rate))
    r = max(1, int(release * rate))
    df = (f1 - f0) / n
    f = f0
    phase = 0.0
    for i in range(n):
        env = i / a if i < a else 1.0
        left = n - i
        if left < r:
            env = min(env, left / r)
        out[i] = int(fn(phase) * amp * env)
        phase += f / rate
        if phase >= 1.0:
            phase -= 1.0
        f += df
    return out


def _shorts(raw):
    out = array('h')
    out.frombytes(bytes(raw[:len(raw) // 2 * 2]))
    if sys.byteorder == 'big':
        out.byteswap()
    return out


def _parse_wav(data):
    if len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError('unsupported audio file (only WAV is supported without external libraries)')
    pos = 12
    size_all = len(data)
    fmt = None
    pcm = None
    while pos + 8 <= size_all:
        cid = data[pos:pos + 4]
        size = struct.unpack_from('<I', data, pos + 4)[0]
        body = pos + 8
        if cid == b'fmt ' and body + 16 <= size_all:
            tag, ch, rate, _, _, bits = struct.unpack_from('<HHIIHH', data, body)
            if tag == 0xFFFE and size >= 26 and body + 26 <= size_all:
                tag = struct.unpack_from('<H', data, body + 24)[0]
            fmt = (tag, ch, rate, bits)
        elif cid == b'data':
            pcm = data[body:min(body + size, size_all)]
        pos = body + size + (size & 1)
    if fmt is None or pcm is None:
        raise ValueError('incomplete WAV file')
    return fmt, pcm


def _decode(fmt, pcm):
    tag, ch, rate, bits = fmt
    if ch < 1 or rate < 1:
        raise ValueError('invalid WAV header')
    if tag == 1 and bits == 8:
        raw = bytearray(2 * len(pcm))
        raw[1::2] = pcm.translate(_FLIP)
        samples = _shorts(raw)
    elif tag == 1 and bits == 16:
        samples = _shorts(pcm)
    elif tag == 1 and bits == 24:
        n = len(pcm) // 3
        raw = bytearray(2 * n)
        raw[0::2] = pcm[1:3 * n:3]
        raw[1::2] = pcm[2:3 * n:3]
        samples = _shorts(raw)
    elif tag == 1 and bits == 32:
        n = len(pcm) // 4
        raw = bytearray(2 * n)
        raw[0::2] = pcm[2:4 * n:4]
        raw[1::2] = pcm[3:4 * n:4]
        samples = _shorts(raw)
    elif tag == 3 and bits in (32, 64):
        floats = array('f' if bits == 32 else 'd')
        width = bits // 8
        floats.frombytes(bytes(pcm[:len(pcm) // width * width]))
        if sys.byteorder == 'big':
            floats.byteswap()
        samples = array('h', [int(max(-1.0, min(1.0, x)) * 32767.0) for x in floats])
    else:
        raise ValueError(f'unsupported WAV encoding (format={tag}, bits={bits})')
    return _from_samples(samples, ch, rate)


def _from_samples(samples, ch, rate):
    frames = len(samples) // ch
    samples = samples[:frames * ch]
    if ch == 1:
        return Sound(samples, None, rate)
    return Sound(samples[0::ch], samples[1::ch], rate)


def _with_file(data, path, run):
    tmp = None
    try:
        if path is None:
            fd, tmp = tempfile.mkstemp(prefix='ttyengine_', suffix='.audio')
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
            path = tmp
        return run(path)
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


_FFMPEG_CONFIG = []
_FFMPEG_FOUND = []


def _exe_names():
    return ('ffmpeg.exe', 'ffmpeg') if sys.platform == 'win32' else ('ffmpeg',)


def _in_dir(directory):
    for sub in ('', 'bin'):
        for name in _exe_names():
            candidate = os.path.join(directory, sub, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                yield candidate


def _from_setting(value):
    value = os.path.expanduser(os.path.expandvars(str(value)))
    if os.path.isdir(value):
        yield from _in_dir(value)
    else:
        yield shutil.which(value) or value


def _known_dirs():
    home = os.path.expanduser('~')
    if sys.platform == 'win32':
        local = os.environ.get('LOCALAPPDATA', os.path.join(home, 'AppData', 'Local'))
        program = os.environ.get('ProgramFiles', 'C:\\Program Files')
        found = [os.path.join(local, 'Microsoft', 'WinGet', 'Links'), os.path.join(program, 'ffmpeg'), 'C:\\ffmpeg',
                 os.path.join(home, 'scoop', 'shims'), 'C:\\ProgramData\\chocolatey\\bin']
        found += glob.glob(os.path.join(local, 'Microsoft', 'WinGet', 'Packages', 'Gyan.FFmpeg*', 'ffmpeg-*', 'bin'))
        return found
    return ['/opt/homebrew/bin', '/usr/local/bin', '/opt/local/bin', '/usr/bin', '/snap/bin', os.path.join(home, '.local', 'bin')]


def _ffmpeg_candidates():
    for value in _FFMPEG_CONFIG:
        yield from _from_setting(value)
    for var in ('TTYENGINE_FFMPEG', 'FFMPEG_BINARY', 'FFMPEG_PATH'):
        if os.environ.get(var):
            yield from _from_setting(os.environ[var])
    main = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else None
    for directory in (os.path.dirname(os.path.abspath(__file__)), os.getcwd(), main,
                      os.path.join(os.path.expanduser('~'), '.ttyengine')):
        if directory:
            yield from _in_dir(directory)
    found = shutil.which('ffmpeg')
    if found:
        yield found
    try:
        import imageio_ffmpeg
        yield imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    for directory in _known_dirs():
        yield from _in_dir(directory)


def _works(exe):
    try:
        proc = subprocess.run([exe, '-version'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
    except Exception:
        return False
    return proc.returncode == 0 and b'ffmpeg' in proc.stdout[:200].lower()


def find_ffmpeg():
    if _FFMPEG_FOUND:
        if os.path.exists(_FFMPEG_FOUND[0]):
            return _FFMPEG_FOUND[0]
        _FFMPEG_FOUND.clear()
    seen = set()
    for candidate in _ffmpeg_candidates():
        candidate = os.path.abspath(candidate)
        if candidate in seen:
            continue
        seen.add(candidate)
        if _works(candidate):
            _FFMPEG_FOUND[:] = [candidate]
            return candidate
    return None


def set_ffmpeg(path=None):
    _FFMPEG_CONFIG[:] = [os.fspath(path)] if path else []
    _FFMPEG_FOUND.clear()
    return find_ffmpeg()


def _ffmpeg_hint():
    if sys.platform == 'win32':
        how = 'winget install ffmpeg'
    elif sys.platform == 'darwin':
        how = 'brew install ffmpeg'
    else:
        how = 'sudo apt install ffmpeg, or your distro equivalent'
    return (f'ffmpeg was not found; only WAV can be loaded without it. Install it ({how}; or pip install imageio-ffmpeg), '
            'put the ffmpeg binary next to sound.py, or point to it with set_ffmpeg(path) / the TTYENGINE_FFMPEG environment variable')


def _via_ffmpeg(data, path, rate):
    exe = find_ffmpeg()
    if not exe:
        raise OSError(_ffmpeg_hint())
    rate = int(rate or _RATE)

    def run(src):
        proc = subprocess.run([exe, '-v', 'error', '-nostdin', '-i', src, '-vn', '-f', 's16le', '-acodec', 'pcm_s16le',
                               '-ac', '2', '-ar', str(rate), 'pipe:1'],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if proc.returncode or not proc.stdout:
            raise ValueError((proc.stderr.decode('utf-8', 'replace').strip().splitlines() or ['decode failed'])[-1])
        return _from_samples(_shorts(proc.stdout), 2, rate)

    return _with_file(data, path, run)


def decoders():
    return {'wav': True, 'ffmpeg': find_ffmpeg()}


def _resample(chan, src, dst):
    if src == dst or len(chan) == 0:
        return chan
    n = len(chan)
    m = max(1, int(n * dst / src))
    step = src / dst
    last = n - 1
    out = array('h', bytes(2 * m))
    for k in range(m):
        p = k * step
        i = int(p)
        if i >= last:
            out[k] = chan[last]
        else:
            out[k] = int(chan[i] + (chan[i + 1] - chan[i]) * (p - i))
    return out


def _clip(values):
    try:
        return array('h', values)
    except OverflowError:
        return array('h', [32767 if s > 32767 else -32768 if s < -32768 else s for s in values])


def _pack(left, right):
    out = array('h', bytes(4 * len(left)))
    out[0::2] = _clip(left)
    out[1::2] = _clip(right)
    if sys.byteorder == 'big':
        out.byteswap()
    return out.tobytes()


class Sound:
    def __init__(self, left, right=None, rate=_RATE):
        self.left = left
        self.right = left if right is None else right
        self.rate = rate
        self._cache = {}

    @property
    def frames(self):
        return len(self.left)

    @property
    def duration(self):
        return len(self.left) / float(self.rate)

    def at_rate(self, rate):
        if rate == self.rate:
            return self
        snd = self._cache.get(rate)
        if snd is None:
            left = _resample(self.left, self.rate, rate)
            right = left if self.right is self.left else _resample(self.right, self.rate, rate)
            snd = self._cache[rate] = Sound(left, right, rate)
        return snd

    @classmethod
    def load(cls, src, rate=None):
        path = None
        if isinstance(src, (bytes, bytearray, memoryview)):
            data = bytes(src)
        elif hasattr(src, 'read'):
            data = src.read()
        else:
            path = os.fspath(src)
            with open(path, 'rb') as f:
                data = f.read()
        errors = []
        if data[:4] == b'RIFF' and data[8:12] == b'WAVE':
            try:
                snd = _decode(*_parse_wav(data))
            except ValueError as e:
                errors.append(f'wav: {e}')
            else:
                if rate and snd.rate != rate and find_ffmpeg():
                    try:
                        return _via_ffmpeg(data, path, rate)
                    except Exception:
                        pass
                return snd
        try:
            return _via_ffmpeg(data, path, rate)
        except Exception as e:
            errors.append(f'ffmpeg: {e}')
        raise ValueError('cannot decode audio (' + '; '.join(errors) + ')')

    @classmethod
    def tone(cls, freq=440.0, duration=0.2, wave='sine', volume=0.5, end_freq=None, attack=0.005, release=0.02, rate=_RATE):
        return cls(_synth(rate, freq, duration, wave, volume, end_freq, attack, release), None, rate)

    @classmethod
    def melody(cls, notes, wave='square', volume=0.4, beat=1.0, attack=0.005, release=0.03, rate=_RATE):
        if isinstance(notes, str):
            notes = [t for t in re.split(r'[\s,]+', notes.strip()) if t]
        out = array('h')
        for item in notes:
            if isinstance(item, str):
                name, _, dur = item.partition(':')
                beats = float(dur) if dur else 1.0
            else:
                name, beats = item
            out.extend(_synth(rate, name, beats * beat, wave, volume, None, attack, release))
        return cls(out, None, rate)


class Voice:
    def __init__(self, mixer, sound, volume=1.0, pan=0.0, loop=False, on_end=None, speed=1.0, at=None):
        self._mixer = mixer
        self._sound = sound
        self._pos = 0
        self._speed = max(0.05, min(32.0, float(speed)))
        self._at = None
        self._hook = None
        self._lastpos = None
        self.pan_width = None
        self.hear_range = None
        self._volume = max(0.0, float(volume))
        self._pan = max(-1.0, min(1.0, float(pan)))
        self._target = self._volume
        self._rate = 0.0
        self._stop_after = False
        if loop is True:
            self._left = None
        elif loop:
            self._left = max(1, int(loop))
        else:
            self._left = 1
        self.paused = False
        self.done = False
        self.on_end = on_end
        if at is not None:
            self.at = at

    @property
    def speed(self):
        return self._speed
    @speed.setter
    def speed(self, value):
        self._speed = max(0.05, min(32.0, float(value)))

    @property
    def pitch(self):
        return 12.0 * math.log2(self._speed)
    @pitch.setter
    def pitch(self, semitones):
        self.speed = 2.0 ** (float(semitones) / 12.0)

    @property
    def at(self):
        return self._at
    @at.setter
    def at(self, value):
        self._detach()
        self._at = value
        hook = getattr(value, 'ondiscard', None)
        if callable(hook) and hasattr(value, 'offdiscard'):
            def gone():
                self._at = self._lastpos
                self._hook = None
            hook(gone)
            self._hook = (value, gone)

    def _detach(self):
        hook, self._hook = self._hook, None
        if hook is not None:
            try:
                hook[0].offdiscard(hook[1])
            except Exception:
                pass

    @property
    def volume(self):
        return self._volume
    @volume.setter
    def volume(self, value):
        self._volume = max(0.0, float(value))
        self._rate = 0.0

    @property
    def pan(self):
        return self._pan
    @pan.setter
    def pan(self, value):
        self._pan = max(-1.0, min(1.0, float(value)))

    @property
    def playing(self):
        return not self.done

    @property
    def position(self):
        return self._pos / float(self._sound.rate)

    @property
    def duration(self):
        return self._sound.duration

    def fade(self, target, seconds, stop=False):
        target = max(0.0, float(target))
        self._stop_after = stop
        if seconds <= 0 or target == self._volume:
            self._volume = target
            self._rate = 0.0
            if stop:
                self.done = True
            return self
        self._target = target
        self._rate = abs(target - self._volume) / seconds
        return self

    def stop(self, fade=0.0):
        return self.fade(0.0, fade, True)

    def pause(self):
        self.paused = True
        return self

    def resume(self):
        self.paused = False
        self._mixer._ensure()
        return self


class _Null:
    name = 'null'

    def __init__(self, rate, block):
        self.rate = rate
        self.next = time.perf_counter()

    def write(self, data):
        now = time.perf_counter()
        self.next = max(self.next, now - 0.05) + len(data) / (4.0 * self.rate)
        delay = self.next - now
        if delay > 0:
            time.sleep(delay)

    def close(self):
        pass


class _WAVEFORMATEX(ctypes.Structure):
    _pack_ = 1
    _fields_ = [('wFormatTag', ctypes.c_ushort), ('nChannels', ctypes.c_ushort),
                ('nSamplesPerSec', ctypes.c_uint32), ('nAvgBytesPerSec', ctypes.c_uint32),
                ('nBlockAlign', ctypes.c_ushort), ('wBitsPerSample', ctypes.c_ushort),
                ('cbSize', ctypes.c_ushort)]


class _WAVEHDR(ctypes.Structure):
    _pack_ = 1
    _fields_ = [('lpData', ctypes.c_void_p), ('dwBufferLength', ctypes.c_uint32),
                ('dwBytesRecorded', ctypes.c_uint32), ('dwUser', ctypes.c_size_t),
                ('dwFlags', ctypes.c_uint32), ('dwLoops', ctypes.c_uint32),
                ('lpNext', ctypes.c_void_p), ('reserved', ctypes.c_size_t)]


class _WinMM:
    name = 'winmm'
    COUNT = 4

    def __init__(self, rate, block):
        self.h = None
        self.hdrs = []
        self.bufs = []
        lib = self.lib = ctypes.WinDLL('winmm')
        hdr_ptr = ctypes.POINTER(_WAVEHDR)
        for fn in ('waveOutPrepareHeader', 'waveOutWrite', 'waveOutUnprepareHeader'):
            f = getattr(lib, fn)
            f.argtypes = [ctypes.c_void_p, hdr_ptr, ctypes.c_uint]
            f.restype = ctypes.c_uint
        lib.waveOutOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint, ctypes.POINTER(_WAVEFORMATEX),
                                    ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint32]
        lib.waveOutOpen.restype = ctypes.c_uint
        for fn in ('waveOutReset', 'waveOutClose'):
            f = getattr(lib, fn)
            f.argtypes = [ctypes.c_void_p]
            f.restype = ctypes.c_uint
        fmt = _WAVEFORMATEX(1, 2, rate, rate * 4, 4, 16, 0)
        handle = ctypes.c_void_p()
        if lib.waveOutOpen(ctypes.byref(handle), 0xFFFFFFFF, ctypes.byref(fmt), 0, 0, 0):
            raise OSError('waveOutOpen failed')
        self.h = handle
        size = block * 4
        for _ in range(self.COUNT):
            buf = ctypes.create_string_buffer(size)
            hdr = _WAVEHDR(ctypes.addressof(buf), size, 0, 0, 0, 0, None, 0)
            if lib.waveOutPrepareHeader(self.h, ctypes.byref(hdr), ctypes.sizeof(hdr)):
                self.close()
                raise OSError('waveOutPrepareHeader failed')
            self.bufs.append(buf)
            self.hdrs.append(hdr)
        self.busy = [False] * self.COUNT
        self.i = 0

    def write(self, data):
        i = self.i
        hdr = self.hdrs[i]
        deadline = time.perf_counter() + 2.0
        while self.busy[i] and not (hdr.dwFlags & 1):
            if time.perf_counter() > deadline:
                raise OSError('waveOut stalled')
            time.sleep(0.001)
        n = min(len(data), len(self.bufs[i]))
        ctypes.memmove(self.bufs[i], data, n)
        hdr.dwBufferLength = n
        if self.lib.waveOutWrite(self.h, ctypes.byref(hdr), ctypes.sizeof(hdr)):
            raise OSError('waveOutWrite failed')
        self.busy[i] = True
        self.i = (i + 1) % self.COUNT

    def close(self):
        if self.h is None:
            return
        try:
            self.lib.waveOutReset(self.h)
            for hdr in self.hdrs:
                self.lib.waveOutUnprepareHeader(self.h, ctypes.byref(hdr), ctypes.sizeof(hdr))
        finally:
            self.lib.waveOutClose(self.h)
            self.h = None


class _ASBD(ctypes.Structure):
    _fields_ = [('mSampleRate', ctypes.c_double), ('mFormatID', ctypes.c_uint32),
                ('mFormatFlags', ctypes.c_uint32), ('mBytesPerPacket', ctypes.c_uint32),
                ('mFramesPerPacket', ctypes.c_uint32), ('mBytesPerFrame', ctypes.c_uint32),
                ('mChannelsPerFrame', ctypes.c_uint32), ('mBitsPerChannel', ctypes.c_uint32),
                ('mReserved', ctypes.c_uint32)]


class _AQBuffer(ctypes.Structure):
    _fields_ = [('mAudioDataBytesCapacity', ctypes.c_uint32), ('mAudioData', ctypes.c_void_p),
                ('mAudioDataByteSize', ctypes.c_uint32), ('mUserData', ctypes.c_void_p),
                ('mPacketDescriptionCapacity', ctypes.c_uint32), ('mPacketDescriptions', ctypes.c_void_p),
                ('mPacketDescriptionCount', ctypes.c_uint32)]


_AQ_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_AQBuffer))


class _CoreAudio:
    name = 'coreaudio'
    COUNT = 4

    def __init__(self, rate, block):
        self.q = None
        path = ctypes.util.find_library('AudioToolbox') or '/System/Library/Frameworks/AudioToolbox.framework/AudioToolbox'
        lib = self.lib = ctypes.CDLL(path)
        buf_ptr = ctypes.POINTER(_AQBuffer)
        lib.AudioQueueNewOutput.argtypes = [ctypes.POINTER(_ASBD), _AQ_CALLBACK, ctypes.c_void_p, ctypes.c_void_p,
                                            ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        lib.AudioQueueAllocateBuffer.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(buf_ptr)]
        lib.AudioQueueEnqueueBuffer.argtypes = [ctypes.c_void_p, buf_ptr, ctypes.c_uint32, ctypes.c_void_p]
        lib.AudioQueueStart.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.AudioQueueStop.argtypes = [ctypes.c_void_p, ctypes.c_ubyte]
        lib.AudioQueueDispose.argtypes = [ctypes.c_void_p, ctypes.c_ubyte]
        for fn in ('AudioQueueNewOutput', 'AudioQueueAllocateBuffer', 'AudioQueueEnqueueBuffer',
                   'AudioQueueStart', 'AudioQueueStop', 'AudioQueueDispose'):
            getattr(lib, fn).restype = ctypes.c_int32
        self.free = queue.Queue()
        self.cb = _AQ_CALLBACK(self._returned)
        fmt = _ASBD(float(rate), 0x6C70636D, 0x0C, 4, 1, 4, 2, 16, 0)
        handle = ctypes.c_void_p()
        if lib.AudioQueueNewOutput(ctypes.byref(fmt), self.cb, None, None, None, 0, ctypes.byref(handle)):
            raise OSError('AudioQueueNewOutput failed')
        self.q = handle
        self.size = block * 4
        self.bufs = []
        for _ in range(self.COUNT):
            buf = buf_ptr()
            if lib.AudioQueueAllocateBuffer(self.q, self.size, ctypes.byref(buf)):
                self.close()
                raise OSError('AudioQueueAllocateBuffer failed')
            self.bufs.append(buf)
            self.free.put(buf)
        self.queued = 0
        self.started = False

    def _returned(self, user, aq, buf):
        self.free.put(buf)

    def write(self, data):
        try:
            buf = self.free.get(timeout=1.0)
        except queue.Empty:
            raise OSError('AudioQueue stalled')
        n = min(len(data), self.size)
        ctypes.memmove(buf.contents.mAudioData, data, n)
        buf.contents.mAudioDataByteSize = n
        if self.lib.AudioQueueEnqueueBuffer(self.q, buf, 0, None):
            raise OSError('AudioQueueEnqueueBuffer failed')
        self.queued += 1
        if not self.started and self.queued >= self.COUNT:
            if self.lib.AudioQueueStart(self.q, None):
                raise OSError('AudioQueueStart failed')
            self.started = True

    def close(self):
        if self.q is None:
            return
        q, self.q = self.q, None
        try:
            self.lib.AudioQueueStop(q, 1)
        finally:
            self.lib.AudioQueueDispose(q, 1)


class _PASpec(ctypes.Structure):
    _fields_ = [('format', ctypes.c_int), ('rate', ctypes.c_uint32), ('channels', ctypes.c_uint8)]


class _PAAttr(ctypes.Structure):
    _fields_ = [('maxlength', ctypes.c_uint32), ('tlength', ctypes.c_uint32), ('prebuf', ctypes.c_uint32),
                ('minreq', ctypes.c_uint32), ('fragsize', ctypes.c_uint32)]


class _Pulse:
    name = 'pulse'

    def __init__(self, rate, block):
        lib = self.lib = ctypes.CDLL(ctypes.util.find_library('pulse-simple') or 'libpulse-simple.so.0')
        lib.pa_simple_new.restype = ctypes.c_void_p
        lib.pa_simple_new.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
                                      ctypes.c_char_p, ctypes.POINTER(_PASpec), ctypes.c_void_p,
                                      ctypes.POINTER(_PAAttr), ctypes.POINTER(ctypes.c_int)]
        lib.pa_simple_write.restype = ctypes.c_int
        lib.pa_simple_write.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_int)]
        lib.pa_simple_free.restype = None
        lib.pa_simple_free.argtypes = [ctypes.c_void_p]
        spec = _PASpec(3, rate, 2)
        unset = 0xFFFFFFFF
        attr = _PAAttr(unset, block * 4 * 4, unset, unset, unset)
        err = ctypes.c_int(0)
        self.s = lib.pa_simple_new(None, b'ttyengine', 1, None, b'sound', ctypes.byref(spec), None,
                                   ctypes.byref(attr), ctypes.byref(err))
        if not self.s:
            raise OSError(f'pulseaudio unavailable ({err.value})')

    def write(self, data):
        err = ctypes.c_int(0)
        if self.lib.pa_simple_write(self.s, data, len(data), ctypes.byref(err)) < 0:
            raise OSError(f'pulseaudio write failed ({err.value})')

    def close(self):
        s, self.s = self.s, None
        if s:
            self.lib.pa_simple_free(s)


_ALSA_ERROR = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p)
_alsa_quiet = _ALSA_ERROR(lambda *args: None)


class _Alsa:
    name = 'alsa'

    def __init__(self, rate, block):
        lib = self.lib = ctypes.CDLL(ctypes.util.find_library('asound') or 'libasound.so.2')
        try:
            lib.snd_lib_error_set_handler.argtypes = [_ALSA_ERROR]
            lib.snd_lib_error_set_handler(_alsa_quiet)
        except AttributeError:
            pass
        lib.snd_pcm_open.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        lib.snd_pcm_set_params.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                                           ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
        lib.snd_pcm_writei.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        lib.snd_pcm_writei.restype = ctypes.c_long
        lib.snd_pcm_recover.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        lib.snd_pcm_drop.argtypes = [ctypes.c_void_p]
        lib.snd_pcm_close.argtypes = [ctypes.c_void_p]
        device = os.environ.get('TTYENGINE_ALSA_DEVICE', 'default').encode()
        self.pcm = ctypes.c_void_p()
        if lib.snd_pcm_open(ctypes.byref(self.pcm), device, 0, 0) < 0:
            raise OSError('no ALSA playback device')
        latency = int(block * 4 / float(rate) * 1000000)
        if lib.snd_pcm_set_params(self.pcm, 2, 3, 2, rate, 1, latency) < 0:
            lib.snd_pcm_close(self.pcm)
            raise OSError('ALSA rejected the stream parameters')

    def write(self, data):
        frames = len(data) // 4
        buf = ctypes.create_string_buffer(data, len(data))
        base = ctypes.addressof(buf)
        done = 0
        tries = 0
        while done < frames:
            n = self.lib.snd_pcm_writei(self.pcm, base + done * 4, frames - done)
            if n < 0:
                tries += 1
                if tries > 4 or self.lib.snd_pcm_recover(self.pcm, int(n), 1) < 0:
                    raise OSError('ALSA write failed')
                continue
            done += n

    def close(self):
        try:
            self.lib.snd_pcm_drop(self.pcm)
        finally:
            self.lib.snd_pcm_close(self.pcm)


def _pipe_commands(rate):
    r = str(rate)
    return [
        ['paplay', '--raw', '--format=s16le', '--rate=' + r, '--channels=2', '--latency-msec=60'],
        ['aplay', '-q', '-t', 'raw', '-f', 'S16_LE', '-r', r, '-c', '2', '-B', '60000'],
        ['play', '-q', '-t', 'raw', '-r', r, '-e', 'signed', '-b', '16', '-c', '2', '-'],
        ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', '-f', 's16le', '-ar', r, '-ac', '2', '-i', 'pipe:0'],
    ]


class _Pipe:
    name = 'pipe'

    def __init__(self, rate, block):
        self.p = None
        for cmd in _pipe_commands(rate):
            if not shutil.which(cmd[0]):
                continue
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                continue
            time.sleep(0.15)
            if proc.poll() is None:
                self.p = proc
                return
        raise OSError('no command line audio player found')

    def write(self, data):
        self.p.stdin.write(data)
        self.p.stdin.flush()

    def close(self):
        p, self.p = self.p, None
        if p is None:
            return
        try:
            p.stdin.close()
        except Exception:
            pass
        try:
            p.terminate()
            p.wait(timeout=1.0)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


_BACKENDS = {'winmm': _WinMM, 'coreaudio': _CoreAudio, 'pulse': _Pulse, 'alsa': _Alsa, 'pipe': _Pipe, 'null': _Null}


def _chain():
    if sys.platform == 'win32':
        return [_WinMM]
    if sys.platform == 'darwin':
        return [_CoreAudio]
    return [_Pulse, _Alsa, _Pipe]


def _open(spec, rate, block):
    if callable(spec):
        return spec(rate, block)
    if spec in (None, 'auto'):
        candidates = _chain()
    elif spec in _BACKENDS:
        candidates = [_BACKENDS[spec]]
    else:
        raise ValueError(f'unknown sound backend: {spec!r}')
    for cls in candidates:
        try:
            return cls(rate, block)
        except Exception:
            continue
    return _Null(rate, block)


def _name(backend):
    return getattr(backend, 'name', type(backend).__name__)


def _atexit(ref):
    mixer = ref()
    if mixer is not None:
        mixer.close()


class Mixer:
    def __init__(self, rate=_RATE, block=512, backend=None, volume=1.0, idle=1.0, max_voices=32,
                 listener=None, pan_width=40.0, hear_range=120.0, rolloff=1.0, aspect=2.0, ffmpeg=None):
        if not 8000 <= rate <= 192000:
            raise ValueError('rate must be between 8000 and 192000')
        if block < 64:
            raise ValueError('block must be at least 64 frames')
        if not (backend is None or callable(backend) or backend == 'auto' or backend in _BACKENDS):
            raise ValueError(f'unknown sound backend: {backend!r}')
        self.rate = int(rate)
        self.block = int(block)
        self.idle = float(idle)
        self.max_voices = int(max_voices)
        if ffmpeg:
            set_ffmpeg(ffmpeg)
        self.listener = listener
        self.pan_width = pan_width
        self.hear_range = hear_range
        self.rolloff = rolloff
        self.aspect = aspect
        self._spec = backend
        self._volume = max(0.0, float(volume))
        self._voices = []
        self._cache = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._backend_name = None
        self._paused = False
        self._silence = bytes(self.block * 4)
        atexit.register(_atexit, weakref.ref(self))

    @property
    def volume(self):
        return self._volume
    @volume.setter
    def volume(self, value):
        self._volume = max(0.0, float(value))

    @property
    def backend(self):
        return self._backend_name

    @property
    def voices(self):
        with self._lock:
            return [v for v in self._voices if not v.done]

    @property
    def paused(self):
        return self._paused

    @property
    def decoders(self):
        return decoders()

    def probe(self):
        if callable(self._spec):
            return getattr(self._spec, 'name', 'custom')
        backend = _open(self._spec, self.rate, self.block)
        name = _name(backend)
        try:
            backend.close()
        except Exception:
            pass
        return name

    def load(self, src):
        key = None
        if isinstance(src, (str, os.PathLike)):
            key = os.path.abspath(os.fspath(src))
            cached = self._cache.get(key)
            if cached is not None:
                return cached
        snd = Sound.load(src, self.rate).at_rate(self.rate)
        if key is not None:
            self._cache[key] = snd
        return snd

    def tone(self, freq=440.0, duration=0.2, wave='sine', volume=0.5, end_freq=None, attack=0.005, release=0.02):
        return Sound.tone(freq, duration, wave, volume, end_freq, attack, release, self.rate)

    def melody(self, notes, wave='square', volume=0.4, beat=1.0, attack=0.005, release=0.03):
        return Sound.melody(notes, wave, volume, beat, attack, release, self.rate)

    def play(self, sound, volume=1.0, pan=0.0, loop=False, fade=0.0, on_end=None, speed=1.0, pitch=0.0, at=None):
        snd = sound if isinstance(sound, Sound) else self.load(sound)
        voice = Voice(self, snd.at_rate(self.rate), volume, pan, loop, on_end, speed * 2.0 ** (pitch / 12.0), at)
        if fade > 0:
            voice._volume = 0.0
            voice._target = volume
            voice._rate = max(0.0, float(volume)) / fade
        with self._lock:
            self._voices.append(voice)
            excess = len(self._voices) - self.max_voices
            if excess > 0:
                for old in [v for v in self._voices if not v.done and v is not voice][:excess]:
                    old.done = True
        self._ensure()
        return voice

    def beep(self, freq=880.0, duration=0.12, wave='square', volume=0.3, **kwargs):
        play = {k: kwargs.pop(k) for k in ('pan', 'fade', 'on_end', 'speed', 'pitch', 'at', 'loop') if k in kwargs}
        return self.play(self.tone(freq, duration, wave, volume, **kwargs), **play)

    def stop_all(self, fade=0.0):
        with self._lock:
            voices = list(self._voices)
        for v in voices:
            v.stop(fade)

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False
        self._ensure()

    def close(self):
        with self._lock:
            thread = self._thread
            self._thread = None
            voices = self._voices
            self._voices = []
        for v in voices:
            v.done = True
        self._stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(2.0)
        self._stop.clear()

    def _ensure(self):
        with self._lock:
            thread = self._thread
            if thread is not None and thread.is_alive():
                return
            thread = threading.Thread(target=self._run, name='ttyengine-sound', daemon=True)
            self._thread = thread
            thread.start()

    def _run(self):
        backend = _open(self._spec, self.rate, self.block)
        self._backend_name = _name(backend)
        span = self.block / float(self.rate)
        idle = 0.0
        try:
            while not self._stop.is_set():
                with self._lock:
                    active = not self._paused and any(not v.paused for v in self._voices)
                    if not active and idle >= self.idle:
                        if self._thread is threading.current_thread():
                            self._thread = None
                        break
                if active:
                    idle = 0.0
                    try:
                        data = self._render()
                    except Exception:
                        data = self._silence
                else:
                    idle += span
                    data = self._silence
                try:
                    backend.write(data)
                except Exception:
                    try:
                        backend.close()
                    except Exception:
                        pass
                    backend = _Null(self.rate, self.block)
                    self._backend_name = 'null'
        finally:
            try:
                backend.close()
            except Exception:
                pass

    def _spatial(self, voice):
        try:
            src = _locate(voice._at)
        except Exception:
            src = voice._lastpos
        if src is None:
            return 0.0, 1.0
        voice._lastpos = src
        try:
            lis = _locate(self.listener)
        except Exception:
            lis = None
        if lis is None:
            lis = (0.0, 0.0)
        dx = src[0] - lis[0]
        dy = (src[1] - lis[1]) * self.aspect
        width = voice.pan_width if voice.pan_width is not None else self.pan_width
        reach = voice.hear_range if voice.hear_range is not None else self.hear_range
        pan = max(-1.0, min(1.0, dx / width)) if width else 0.0
        gain = 1.0
        if reach:
            gain = max(0.0, 1.0 - math.hypot(dx, dy) / reach) ** self.rolloff
        return pan, gain

    def _render(self):
        frames = self.block
        with self._lock:
            voices = list(self._voices)
        left = [0] * frames
        right = [0] * frames
        dt = frames / float(self.rate)
        master = self._volume
        ended = []
        for v in voices:
            if v.done:
                ended.append(v)
                continue
            if v.paused:
                continue
            if v._rate:
                step = v._rate * dt
                gap = v._target - v._volume
                if abs(gap) <= step:
                    v._volume = v._target
                    v._rate = 0.0
                    if v._stop_after:
                        v.done = True
                        ended.append(v)
                        continue
                else:
                    v._volume += step if gap > 0 else -step
            spatial_pan = 0.0
            spatial_gain = 1.0
            if v._at is not None:
                spatial_pan, spatial_gain = self._spatial(v)
            gain = v._volume * master * spatial_gain * 256.0
            pan = max(-1.0, min(1.0, v._pan + spatial_pan))
            gl = int(gain * (1.0 if pan <= 0 else 1.0 - pan))
            gr = int(gain * (1.0 if pan >= 0 else 1.0 + pan))
            speed = v._speed
            snd = v._sound
            total = snd.frames
            n = 0
            while n < frames:
                if v._pos >= total:
                    if total and (v._left is None or v._left > 1):
                        if v._left is not None:
                            v._left -= 1
                        v._pos = v._pos % total
                    else:
                        v.done = True
                        ended.append(v)
                        break
                if speed == 1.0:
                    start = int(v._pos)
                    take = min(total - start, frames - n)
                    end = start + take
                    if gl:
                        left[n:n + take] = [m + ((s * gl) >> 8) for m, s in zip(left[n:n + take], snd.left[start:end])]
                    if gr:
                        right[n:n + take] = [m + ((s * gr) >> 8) for m, s in zip(right[n:n + take], snd.right[start:end])]
                    v._pos = end
                    n += take
                else:
                    pos = v._pos
                    cnt = int((total - pos) / speed)
                    if pos + cnt * speed < total:
                        cnt += 1
                    take = max(1, min(cnt, frames - n))
                    if gl or gr:
                        ps = [pos + k * speed for k in range(take)]
                        ii = [int(q) for q in ps]
                        fr = [q - i for q, i in zip(ps, ii)]
                        last = total - 1
                        jj = [i + 1 if i < last else last for i in ii]
                        if gl:
                            src = snd.left
                            left[n:n + take] = [m + (int(src[i] + (src[j] - src[i]) * f) * gl >> 8)
                                                for m, i, j, f in zip(left[n:n + take], ii, jj, fr)]
                        if gr:
                            src = snd.right
                            right[n:n + take] = [m + (int(src[i] + (src[j] - src[i]) * f) * gr >> 8)
                                                 for m, i, j, f in zip(right[n:n + take], ii, jj, fr)]
                    v._pos = pos + take * speed
                    n += take
        if ended:
            gone = set(map(id, ended))
            with self._lock:
                self._voices = [v for v in self._voices if id(v) not in gone]
            for v in ended:
                v._detach()
                if v.on_end:
                    try:
                        _call(v.on_end, v)
                    except Exception:
                        pass
        return _pack(left, right)
