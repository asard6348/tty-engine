#_owned - list of owned variables which will be inspected upon obj().create()
#_required - list of required components to be included upon obj().create()
#_default - bool of the component auto-inclusion upon obj().create()
#def on_discard() - function that will be called upon obj().discard()

#MODULES
import math, re, statistics, inspect, collections.abc, functools

#GLOBAL
_NEIGHBOURS4 = ((-1, 0), (1, 0), (0, -1), (0, 1))
_NEIGHBOURS8 = _NEIGHBOURS4 + ((-1, -1), (1, -1), (-1, 1), (1, 1))
_NEIGHBOURS_HALF = ((1, 0), (0, 1), (1, 1), (-1, 1))

_EASINGS = {
    'linear': lambda p: p,
    'in': lambda p: p * p,
    'out': lambda p: 1 - (1 - p) * (1 - p),
    'smooth': lambda p: p * p * (3 - 2 * p),
}

def _easing(mode):
    if callable(mode):
        return mode
    try:
        return _EASINGS[mode]
    except (KeyError, TypeError):
        raise ValueError('ease must be a callable or one of: ' + ', '.join(_EASINGS))

@functools.lru_cache(maxsize=16)
def _offsets(radius, aspect):
    span = int(radius / aspect) + 1
    found = []
    for dx in range(-span, span + 1):
        for dy in range(-radius, radius + 1):
            if dx or dy:
                cost = math.hypot(dx * aspect, dy)
                if cost <= radius:
                    found.append((cost - (0.01 if dy > 0 else 0), dx, dy))
    found.sort()
    return tuple((dx, dy) for _, dx, dy in found)
_SHAPES = ('circle', 'square', 'diamond')

@functools.lru_cache(maxsize=64)
def _footprint(radius, aspect, shape):
    if shape not in _SHAPES:
        raise ValueError('shape must be one of: ' + ', '.join(_SHAPES))
    reach = max(1, radius) - 0.5
    span_x = int(reach / aspect) + 1
    span_y = int(reach) + 1
    found = []
    for dy in range(-span_y, span_y + 1):
        for dx in range(-span_x, span_x + 1):
            ux, uy = abs(dx) * aspect, abs(dy)
            if shape == 'circle':
                inside = math.hypot(ux, uy) < reach
            elif shape == 'square':
                inside = ux < reach and uy < reach
            else:
                inside = ux + uy < reach
            if inside:
                found.append((dx, dy))
    return tuple(found)

_SHADOWS = ('physics', 'visual', 'hitbox')

def _check_shadow(value):
    if value is not None and value not in _SHADOWS:
        raise ValueError('shadow must be None or one of: ' + ', '.join(_SHADOWS))
    return value

def _contact_point_cells(pixels, nx, ny, center):
    n = len(pixels)
    mx = sum(p[0] for p in pixels) / n
    my = sum(p[1] for p in pixels) / n
    if nx is None:
        return (mx, my)
    cx, cy = center
    if ny:
        xs = [p[0] for p in pixels]
        return (max(min(xs) - 0.5, min(max(xs) + 0.5, cx)), my)
    ys = [p[1] for p in pixels]
    return (mx, max(min(ys) - 0.5, min(max(ys) + 0.5, cy)))

def _gradient_cells(pixels, center, sign, aspect):
    cx, cy = center
    sx = sy = 0.0
    for x in range(math.ceil(cx - 2.5), math.floor(cx + 2.5) + 1):
        for y in range(math.ceil(cy - 2.5), math.floor(cy + 2.5) + 1):
            if (x, y) in pixels:
                sx += (x - cx) * aspect
                sy += y - cy
    length = math.hypot(sx, sy)
    if length < 1e-9:
        return None
    return sign * sx / length, sign * sy / length

def _contact_normal_cells(mine, theirs, point, nx, ny, inside, slope, aspect):
    if not slope:
        return nx, ny
    shift = 0.5 if inside else -0.5
    cx, cy = point
    if abs(nx) > abs(ny):
        cx += shift * (1 if nx > 0 else -1)
    else:
        cy += shift * (1 if ny > 0 else -1)
    center = (round(cx * 2) / 2, round(cy * 2) / 2)
    go = _gradient_cells(theirs, center, -1, aspect)
    gs = _gradient_cells(mine, center, 1, aspect)
    best = None
    for g in (go, gs):
        if g is None:
            continue
        d = g[0] * nx + g[1] * ny
        if best is None or d > best[0]:
            best = (d, g)
    if best is None or best[0] < 0.25:
        return nx, ny
    return best[1]

def _mtv_cells(mine, other_pixels, aspect):
    best = None
    for dx, dy, cost in ((1, 0, aspect), (-1, 0, aspect), (0, 1, 1.0), (0, -1, 1.0)):
        for k in range(1, 64):
            if not ({(p[0] + dx * k, p[1] + dy * k) for p in mine} & other_pixels):
                score = k * cost - (0.01 if dy == 1 else 0)
                if best is None or score < best[0]:
                    best = (score, dx, dy, k)
                break
    return best

_SGR = re.compile(r'\x1b\[([0-9;]*)m')
_FGCODE = re.compile(r'\033\[38;2;(\d{1,3});(\d{1,3});(\d{1,3})m')
_BGCODE = re.compile(r'\033\[48;2;(\d{1,3});(\d{1,3});(\d{1,3})m')

def _argslen(cb):
    params = inspect.signature(cb).parameters
    l = len(params) - (1 if hasattr(cb, '__self__') else 0)
    return l

def _closure_refs(fn, obj):
    if not fn.__closure__:
        return False
    for cell in fn.__closure__:
        try:
            if cell.cell_contents is obj:
                return True
        except ValueError:
            pass
    return False

def _styleprop(name):
    def fget(self):
        return getattr(self, '_' + name)
    def fset(self, value):
        self._setstyle(name, value)
    return property(fget, fset)

class _metainit(type):
    def __new__(mcs, name, bases, attrs, **kwargs):
        init_val = kwargs.pop('init', None)
        cls = super().__new__(mcs, name, bases, attrs, **kwargs)
        if init_val:
            cls._target_init = init_val
        return cls
    def __call__(cls, *args, **kwargs):
        inst = super().__call__(*args, **kwargs)
        initfunc = getattr(cls, '_target_init', '_init')
        instinit = getattr(inst, initfunc, None)
        if instinit:
            instinit()
        return inst

class _change_callback(metaclass=_metainit, init='_chinit'):
    def _chinit(self):
        self._onchangecb = {}
        self._changing = False
        def cln():
            discarded = self.obj
            for other in self.obj.scene.objs:
                com = getattr(other, self.__class__.__name__, None)
                if other is discarded or not com or not hasattr(com, '_onchangecb'):
                    continue
                com._onchangecb = {
                    cb:par for cb,par in com._onchangecb.items()
                    if not _closure_refs(cb, discarded)
                }
        if not hasattr(self, 'on_discard'):
            self.on_discard = cln
        else:
            old_func = self.on_discard
            def cln_():
                try:
                    old_func(self) 
                except TypeError:
                    old_func()
                cln()
            self.on_discard = cln_

    def onchange(self, cb, once=False):
        if once:
            match_attr = once if isinstance(once, str) else None
            l = _argslen(cb)
            fired = [False]
            orig = cb
            def wrapped(attr=None, old=None, internal=False):
                if fired[0]: return
                if match_attr is not None and attr != match_attr: return
                fired[0] = True
                if wrapped in self._onchangecb:
                    del self._onchangecb[wrapped]
                if l > 2: orig(attr, old, internal)
                elif l > 1: orig(attr, old)
                elif l > 0: orig(attr)
                else: orig()
            cb = wrapped
            self._onchangecb[cb] = 3
        else:
            self._onchangecb[cb] = _argslen(cb)
        return cb

    def offchange(self, cb):
        self._onchangecb = {f:par for f,par in self._onchangecb.items() if f is not cb}

    def _change(self, attr, old):
        internal = self._changing
        self._changing = True
        try:
            for cb, l in list(self._onchangecb.items()):
                if l > 2:
                    cb(attr, old, internal)
                elif l > 1:
                    cb(attr, old)
                elif l > 0:
                    cb(attr)
                else:
                    cb()
        finally:
            self._changing = internal


#COMPONENTS
class transform(_change_callback):
    _owned = [
        'x', 'y',
        'vx', 'vy',
        'text', 'rtext', 'htext',
        'vtext', 'vrtext', 'vhtext',
        'rotation',
        'rotaspect',
        'fg', 'bg', 'alpha', 'bgalpha',
        'flip',
        'shadow',
    ]
    _default = True
    _settings = ('x', 'y', 'text', 'rtext', 'htext', 'rotation', 'aspect', 'fg', 'bg', 'alpha', 'bgalpha',
                 'flip', 'shadow')
    _aliases = {'aspect': 'rotaspect'}

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.scene = obj.scene
        raw = kwargs.get('text', '')
        ctext = obj.scene.recomp.sub('', raw) if raw else ''
        self._x = kwargs.get('x', 0)
        self._y = kwargs.get('y', 0)
        self._vx = kwargs.get('vx', 0)
        self._vy = kwargs.get('vy', 0)
        self._fg = kwargs.get('fg', None)
        self._bg = kwargs.get('bg', None)
        self._alpha = kwargs.get('alpha', None)
        self._bgalpha = kwargs.get('bgalpha', None)
        self._style_cache = {}
        self._styled_for = None
        self._fade = None
        self._plain_layout = None
        self.vtext = raw
        self._vbase = raw
        self._vrtext = raw
        self.vhtext = raw
        self._text = ctext
        self._rtext = ctext
        self._htext = ctext
        self._rotation = kwargs.get('rotation', 0)
        self._rot_cache_angle = None
        self._rotaspect = kwargs.get('rotaspect', None)
        self._flip = kwargs.get('flip', None)
        self._shadow = _check_shadow(kwargs.get('shadow', None))
        self._cells_cache = None
        self._anim = None
        self._onsplit = {}
        self._xlen_cache = None
        self._ylen_cache = None
        self._parse_pixels_key = None
        self._parse_pixels_val = None
        self._centroid_cache = {}
        self._bg_cache = {}
        self._rotmap = None
        self._rotcells_v = {}
        self._rotsrc_v = {}
        self._rotmaps_ok = True
        self._rotangle = 0
        self._rotsize = (0, 0)
        self._rotorigin = (0, 0)
        self._ptext = ctext
        self._pvx = 0
        self._pvy = 0
        self._pkey = None
        self._onchangecb = {}
        self._changing = False
        self._vrtext = self._restyle(raw)
        self.rotate(self._rotation, init=True)
        if 'htext' in kwargs:
            self.htext = kwargs['htext']
        elif 'rtext' in kwargs:
            self.rtext = kwargs['rtext']

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def _invalidate(self):
        self._xlen_cache = None
        self._ylen_cache = None
        self._parse_pixels_key = None
        self._parse_pixels_val = None
        self._centroid_cache = {}
        self._rot_cache_angle = None

    @property
    def x(self):
        return self._x
    @x.setter
    def x(self, value):
        old = self._x
        self._x = value
        self._change('x', old)

    @property
    def y(self):
        return self._y
    @y.setter
    def y(self, value):
        old = self._y
        self._y = value
        self._change('y', old)

    @property
    def vx(self):
        return self._vx
    @vx.setter
    def vx(self, value):
        old = self._vx
        self._vx = value
        self._change('vx', old)

    @property
    def vy(self):
        return self._vy
    @vy.setter
    def vy(self, value):
        old = self._vy
        self._vy = value
        self._change('vy', old)

    @property
    def text(self):
        return self._text
    @text.setter
    def text(self, value):
        old = self._text
        self._anim = None
        ctext = self.scene.recomp.sub('', value)
        self.vrtext = value
        self.vhtext = value
        self._htext = ctext
        self._rtext = ctext
        self._invalidate()
        self.rotate(self._rotation)
        self._change('text', old)

    @property
    def rtext(self):
        return self._rtext
    @rtext.setter
    def rtext(self, value):
        old = self._rtext
        ctext = self.scene.recomp.sub('', value)
        self.vrtext = value
        self._rtext = ctext
        self._invalidate()
        self.rotate(self._rotation)
        self._change('rtext', old)

    @property
    def htext(self):
        return self._htext
    @htext.setter
    def htext(self, value):
        old = self._htext
        self._anim = None
        ctext = self.scene.recomp.sub('', value)
        self.vrtext = value
        self.vhtext = value
        self._htext = ctext
        self._rtext = ctext
        self._invalidate()
        self.rotate(self._rotation)
        self._change('htext', old)

    @property
    def ptext(self):
        return self._ptext

    @property
    def pvx(self):
        return self._pvx

    @property
    def pvy(self):
        return self._pvy

    @property
    def rotation(self):
        return self._rotation
    @rotation.setter
    def rotation(self, value):
        old = self._rotation
        oldt = self._text
        self._rotation = value
        self.rotate(value)
        self._change('rotation', old)
        self._change('text', oldt)

    @property
    def rotaspect(self):
        return self.scene.aspect if self._rotaspect is None else self._rotaspect
    @rotaspect.setter
    def rotaspect(self, value):
        old = self._rotaspect
        oldt = self._text
        self._rotaspect = value
        self._invalidate()
        self.rotate(self._rotation)
        self._change('rotaspect', old)
        self._change('text', oldt)

    @property
    def flip(self):
        return self._flip
    @flip.setter
    def flip(self, value):
        old = self._flip
        oldt = self._text
        self._flip = value
        self._invalidate()
        self.rotate(self._rotation)
        self._change('flip', old)
        self._change('text', oldt)

    @property
    def aspect(self):
        return self.rotaspect
    @aspect.setter
    def aspect(self, value):
        self.rotaspect = value

    @property
    def shadow(self):
        return self._shadow
    @shadow.setter
    def shadow(self, value):
        old = self._shadow
        self._shadow = _check_shadow(value)
        self._change('shadow', old)

    @property
    def vrtext(self):
        return self._vrtext
    @vrtext.setter
    def vrtext(self, value):
        self._vbase = value
        self._vrtext = self._restyle(value)

    fg = _styleprop('fg')
    bg = _styleprop('bg')
    alpha = _styleprop('alpha')
    bgalpha = _styleprop('bgalpha')

    def _setstyle(self, key, value):
        self._fade = None
        self._applystyle(**{key: value})

    def _applystyle(self, **changes):
        olds = {key: getattr(self, '_' + key) for key in changes}
        for key, value in changes.items():
            setattr(self, '_' + key, value)
        self._style_cache = {}
        self._vrtext = self._restyle(self._vbase)
        self._vrotate()
        for key, old in olds.items():
            self._change(key, old)

    def _stylecheck(self):
        if self._styled_for is not None and self._styled_for != (self.scene.bgcolor, self.scene.fgcolor):
            self._style_cache = {}
            self._vrtext = self._restyle(self._vbase)
            self._vrotate()

    def _styled(self, style):
        cached = self._style_cache.get(style)
        if cached is None:
            sample = self.scene.styler.style(style + 'x', color=self._fg, alpha=self._alpha,
                                             bgcolor=self._bg, bgalpha=self._bgalpha, onbg=True, clean=True)
            cached = sample[:sample.index('x')]
            self._style_cache[style] = cached
        return cached

    def _restyle(self, base):
        if self._fg is None and self._bg is None and self._alpha is None and self._bgalpha is None:
            self._styled_for = None
            return base
        self._styled_for = (self.scene.bgcolor, self.scene.fgcolor)
        pixels = self.parse_pixels(base)
        last = {}
        widths = {}
        for (ci, ri), (char, _) in pixels.items():
            widths[ri] = max(widths.get(ri, 0), ci + 1)
            if char != ' ':
                last[ri] = max(last.get(ri, -1), ci)
        restyled = {}
        for (ci, ri), (char, style) in pixels.items():
            restyled[(ci, ri)] = (char, self._styled(style) if ci <= last.get(ri, -1) else style)
        return '\n'.join(self.build_rows(restyled, 0, widths.get(ri, 0) - 1, ri, ri)
                         for ri in range(len(base.splitlines())))

    def _has_background(self, style):
        cached = self._bg_cache.get(style)
        if cached is not None:
            return cached
        found = False
        for match in _SGR.finditer(style):
            params = [int(v) if v else 0 for v in match.group(1).split(';')]
            i = 0
            while i < len(params):
                v = params[i]
                if v == 48 or 40 <= v <= 47 or 100 <= v <= 107:
                    found = True
                    break
                if v == 38:
                    i += 2 if i + 1 < len(params) and params[i + 1] == 5 else 4
                i += 1
            if found:
                break
        self._bg_cache[style] = found
        return found

    def _pixel_centroid(self, txt):
        cached = self._centroid_cache.get(id(txt))
        if cached is not None and cached[0] == txt:
            return cached[1]
        clean = self.scene.recomp.sub('', txt)
        xs, ys = [], []
        for ri, row in enumerate(clean.splitlines()):
            for ci, char in enumerate(row):
                if char not in (' ', '\n'):
                    xs.append(ci)
                    ys.append(ri)
        result = (sum(xs) / len(xs), sum(ys) / len(ys)) if xs else (0.0, 0.0)
        self._centroid_cache[id(txt)] = (txt, result)
        return result

    def parse_pixels(self, text):
        if self._parse_pixels_key is not None and self._parse_pixels_key == text:
            return self._parse_pixels_val
        pixels = {}
        current_style = ''
        for ri, line in enumerate(text.splitlines()):
            ci = 0
            for part in self.scene.recomp.split(line):
                if not part:
                    continue
                if self.scene.recomp.match(part):
                    if part == '\033[0m':
                        current_style = ''
                    else:
                        current_style += part
                else:
                    for char in part:
                        pixels[(ci, ri)] = (char, current_style)
                        ci += 1
        self._parse_pixels_key = text
        self._parse_pixels_val = pixels
        return pixels

    def build_rows(self, pixels, min_x, max_x, min_y, max_y):
        out_rows = []
        for ri in range(min_y, max_y + 1):
            row = ''
            prev_style = ''
            for ci in range(min_x, max_x + 1):
                if (ci, ri) in pixels:
                    char, style = pixels[(ci, ri)]
                    if style != prev_style:
                        row += ('\033[0m' if prev_style else '') + style
                        prev_style = style
                    row += char
                else:
                    if prev_style:
                        row += '\033[0m'
                        prev_style = ''
                    row += ' '
            if prev_style:
                row += '\033[0m'
            out_rows.append(row)
        return '\n'.join(out_rows)

    def merge(self, *layers, dx=0, dy=0, center=True):
        items = []
        for layer in layers:
            if isinstance(layer, str):
                items.append((layer, 0, 0))
            else:
                text, ox, oy = (tuple(layer) + (0, 0))[:3]
                items.append((text, ox, oy))
        if len(items) == 1:
            items.insert(0, (self._vrtext, 0, 0))
        floor = math.floor

        def middle(pixels):
            cells = [p for p, (char, _) in pixels.items() if char != ' '] or list(pixels)
            if not cells:
                return None
            xs = [p[0] for p in cells]
            ys = [p[1] for p in cells]
            return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

        merged = dict(self.parse_pixels(items[0][0]))
        anchor = middle(merged)
        for text, ox, oy in items[1:]:
            pixels = self.parse_pixels(text)
            mid = middle(pixels)
            sx = ox + dx
            sy = -(oy + dy)
            if center and anchor is not None and mid is not None:
                sx += floor(anchor[0] - mid[0] + 0.5)
                sy += floor(anchor[1] - mid[1] + 0.5)
            for (ci, ri), (char, style) in pixels.items():
                if char != ' ' or (style and self._has_background(style)):
                    merged[(ci + sx, ri + sy)] = (char, style)
        if not merged:
            return ''
        xs = [p[0] for p in merged]
        ys = [p[1] for p in merged]
        return self.build_rows(merged, min(xs), max(xs), min(ys), max(ys))

    def cells(self, mode=None):
        mode = self._shadow if mode is None else _check_shadow(mode)
        p = getattr(self.obj, 'physics', None)
        if mode in (None, 'physics'):
            if p is not None:
                return p.getpixels()
            text, ox, oy, full = self._ptext, self._pvx, self._pvy, False
        elif mode == 'hitbox':
            text, ox, oy, full = self._htext, 0, 0, True
        else:
            text, ox, oy, full = self._text, self.vx, self.vy, False
        rx = round(self._x + ox)
        ry = round(self._y + oy)
        key = (full, rx, ry, text)
        cached = self._cells_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        found = set()
        for i, row in enumerate(text.splitlines()):
            for j, char in enumerate(row):
                if full or char != ' ':
                    found.add((rx + j, ry - i))
        self._cells_cache = (key, found)
        return found

    def collides(self, objs, mode=None):
        mine = self.cells(mode)
        if not isinstance(objs, (list, tuple, set)):
            objs = [objs]
        found = {}
        if not mine:
            return found
        for other in objs:
            other = getattr(other, 'obj', other)
            ot = getattr(other, 'transform', None)
            if other is self.obj or ot is None:
                continue
            inter = mine & ot.cells(mode)
            if inter:
                found[other] = inter
        return found

    def normal(self, other, local=None):
        me = self.obj if local is None else getattr(local, 'obj', local)
        other = getattr(other, 'obj', other)
        mine = me.transform.cells()
        theirs = other.transform.cells()
        aspect = self.scene.aspect
        slope = all(getattr(getattr(o, 'physics', None), 'slope', True) for o in (me, other))
        inside = bool(mine & theirs)
        if inside:
            best = _mtv_cells(mine, theirs, aspect)
            if best is None:
                return None
            nx, ny = best[1], best[2]
            contact = mine & theirs
        else:
            found = None
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                touching = [q for q in mine if (q[0] + dx, q[1] + dy) in theirs]
                if touching and (found is None or len(touching) > len(found[2])):
                    found = (-dx, -dy, touching)
            if found is None:
                return None
            nx, ny, contact = found
        n = len(mine)
        center = (sum(q[0] for q in mine) / n, sum(q[1] for q in mine) / n)
        point = _contact_point_cells(contact, nx, ny, center)
        gx, gy = _contact_normal_cells(mine, theirs, point, nx, ny, inside, slope, aspect)
        return math.degrees(math.atan2(gx, gy)) % 360

    def tolocal(self, pixels):
        rx = round(self._x + self.vx)
        ry = round(self._y + self.vy)
        local_pixels = set()
        for gx, gy in pixels:
            local_pixels.add((gx - rx, ry - gy))
        return local_pixels

    def toworld(self, pixels):
        rx = round(self._x + self.vx)
        ry = round(self._y + self.vy)
        local_pixels = set()
        for gx, gy in pixels:
            local_pixels.add((gx + rx, ry + gy))
        return local_pixels

    def _rotator(self, angle_degrees):
        angle = math.radians(angle_degrees)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        if self._flip is None:
            ma, mb, mc, md = cos_a, -sin_a, sin_a, cos_a
            ja, jb, jc, jd = cos_a, sin_a, -sin_a, cos_a
        else:
            mirror = math.radians(2 * self._flip)
            fa, fb, fc, fd = -math.cos(mirror), -math.sin(mirror), -math.sin(mirror), math.cos(mirror)
            ma, mb = cos_a * fa - sin_a * fc, cos_a * fb - sin_a * fd
            mc, md = sin_a * fa + cos_a * fc, sin_a * fb + cos_a * fd
            ja, jb = fa * cos_a - fb * sin_a, fa * sin_a + fb * cos_a
            jc, jd = fc * cos_a - fd * sin_a, fc * sin_a + fd * cos_a
        ASPECT = self.rotaspect
        floor = math.floor
        ident = self._flip is None and angle_degrees % 360 == 0

        def layout(source):
            glyphs = [p for p, px in source.items() if px[0] != ' ']
            if not glyphs:
                return None
            count = len(glyphs)
            cx = sum(p[0] for p in glyphs) / count
            cy = sum(p[1] for p in glyphs) / count
            if ident:
                xs = [p[0] for p in source]
                ys = [p[1] for p in glyphs]
                return glyphs, cx, cy, {p: p for p in glyphs}, {}, min(xs), max(xs), min(ys), max(ys)

            spots = []
            for ci, ri in glyphs:
                u = (ci - cx) * ASPECT
                v = ri - cy
                fx = cx + (u * ma + v * mb) / ASPECT
                fy = cy + (u * mc + v * md)
                gx = floor(fx + 0.5 + 1e-7)
                gy = floor(fy + 0.5 + 1e-7)
                spots.append((((fx - gx) * ASPECT) ** 2 + (fy - gy) ** 2, ri, ci, fx, fy, gx, gy))
            spots.sort()

            placed = {}
            loose = []
            for spot in spots:
                cell = (spot[5], spot[6])
                if cell in placed:
                    loose.append(spot)
                else:
                    placed[cell] = (spot[2], spot[1])
            for _, ri, ci, fx, fy, gx, gy in loose:
                reach_x = 2
                reach_y = 1
                best = None
                while best is None:
                    for ny in range(gy - reach_y, gy + reach_y + 1):
                        for nx in range(gx - reach_x, gx + reach_x + 1):
                            if (nx, ny) in placed:
                                continue
                            rx = (nx - cx) * ASPECT
                            ry = ny - cy
                            hit = (floor((rx * ja + ry * jb) / ASPECT + cx + 0.5 + 1e-7),
                                   floor(rx * jc + ry * jd + cy + 0.5 + 1e-7)) in source
                            cost = ((nx - fx) * ASPECT) ** 2 + (ny - fy) ** 2 - 0.02 * (nx - fx) * ASPECT + (0 if hit else 1)
                            key = (round(cost, 6), ny, -nx)
                            if best is None or key < best:
                                best = key
                    reach_x *= 2
                    reach_y *= 2
                placed[(-best[2], best[1])] = (ci, ri)

            where = {src: cell for cell, src in placed.items()}
            extra = {}
            for (ci, ri), a in where.items():
                for dx, dy in _NEIGHBOURS_HALF:
                    b = where.get((ci + dx, ri + dy))
                    if b is None:
                        continue
                    ex = b[0] - a[0]
                    ey = b[1] - a[1]
                    if -1 <= ex <= 1 and -1 <= ey <= 1:
                        continue
                    steps = max(abs(ex), abs(ey))
                    for k in range(1, steps):
                        f = k / steps
                        cell = (floor(a[0] + ex * f + 0.5 + 1e-7), floor(a[1] + ey * f + 0.5 + 1e-7))
                        if cell not in placed and cell not in extra:
                            extra[cell] = (ci, ri) if f < 0.5 else (ci + dx, ri + dy)

            around = {}
            for group in (placed, extra):
                for x, y in group:
                    for dx, dy in _NEIGHBOURS4:
                        c = (x + dx, y + dy)
                        around[c] = around.get(c, 0) + 1
            for (nx, ny), n in around.items():
                if n < 4 or (nx, ny) in placed or (nx, ny) in extra:
                    continue
                rx = (nx - cx) * ASPECT
                ry = ny - cy
                ci = floor((rx * ja + ry * jb) / ASPECT + cx + 0.5 + 1e-7)
                ri = floor(rx * jc + ry * jd + cy + 0.5 + 1e-7)
                px = source.get((ci, ri))
                if px is not None and px[0] != ' ':
                    extra[(nx, ny)] = (ci, ri)

            min_x = min(c[0] for c in placed)
            max_x = max(c[0] for c in placed)
            min_y = min(c[1] for c in placed)
            max_y = max(c[1] for c in placed)
            for cell in extra:
                if cell[0] < min_x:
                    min_x = cell[0]
                if cell[0] > max_x:
                    max_x = cell[0]
                if cell[1] < min_y:
                    min_y = cell[1]
                if cell[1] > max_y:
                    max_y = cell[1]
            for (ci, ri), px in source.items():
                if px[0] != ' ':
                    continue
                gx = floor(cx + (((ci - cx) * ASPECT) * ma + (ri - cy) * mb) / ASPECT + 0.5 + 1e-7)
                if gx < min_x:
                    min_x = gx
                if gx > max_x:
                    max_x = gx
            return glyphs, cx, cy, placed, extra, min_x, max_x, min_y, max_y

        def render(source, lay, record=False, size=(0, 0), maps=False):
            glyphs, cx, cy, placed, extra, min_x, max_x, min_y, max_y = lay
            new_pixels = {}
            cells = {}
            sources = {}
            for group in (placed, extra):
                for cell, src in group.items():
                    new_pixels[cell] = source[src]
                    if maps:
                        cells[cell] = [src]
                        sources.setdefault(src, []).append(cell)
            if any(px[0] == ' ' and px[1] and self._has_background(px[1]) for px in source.values()):
                for ny in range(min_y, max_y + 1):
                    ry = ny - cy
                    for nx in range(min_x, max_x + 1):
                        if (nx, ny) in new_pixels:
                            continue
                        rx = (nx - cx) * ASPECT
                        ci = floor((rx * ja + ry * jb) / ASPECT + cx + 0.5 + 1e-7)
                        ri = floor(rx * jc + ry * jd + cy + 0.5 + 1e-7)
                        px = source.get((ci, ri))
                        if px is not None and px[0] == ' ' and px[1] and self._has_background(px[1]):
                            new_pixels[(nx, ny)] = px
            if record:
                self._rotmap = (cx, cy, min_x, min_y, ASPECT, ja, jb, jc, jd)
                self._rotsize = size
                self._rotorigin = (min_x, min_y)
                if maps:
                    self._rotcells_v = cells
                    self._rotsrc_v = sources
            return self.build_rows(new_pixels, min_x, max_x, min_y, max_y)

        layout.ident = ident
        return layout, render

    def _vrender(self, layout, render, plain_layout):
        styled_source = self.parse_pixels(self._vrtext)
        if plain_layout is None:
            styled_layout = layout(styled_source) if self._vrtext.splitlines() else None
        elif [p for p, px in styled_source.items() if px[0] != ' '] == plain_layout[0]:
            styled_layout = plain_layout
        else:
            styled_layout = layout(styled_source)
        self.vtext = render(styled_source, styled_layout) if styled_layout is not None else ''

    def _keeps_layout(self):
        return (self._fade is not None or self._fg is not None or self._bg is not None
                or self._alpha is not None or self._bgalpha is not None)

    def _vrotate(self):
        layout, render = self._rotator(self._rotation)
        plain = self._plain_layout
        if plain is None and not layout.ident and self._rtext.splitlines():
            plain = layout(self.parse_pixels(self._rtext))
            if self._keeps_layout():
                self._plain_layout = plain
        self._vrender(layout, render, plain)
        self._parse_pixels_key = None
        self._parse_pixels_val = None

    def rotate(self, angle_degrees, init=False):
        if not init:
            rounded = round(angle_degrees * 20) / 20
            if self._rot_cache_angle == rounded:
                return
            self._rot_cache_angle = rounded

        layout, render = self._rotator(angle_degrees)
        plain = self._rtext
        crows = plain.splitlines()
        plain_source = self.parse_pixels(plain)
        plain_layout = layout(plain_source) if crows else None
        self._plain_layout = plain_layout if not layout.ident and self._keeps_layout() else None
        self._rotangle = angle_degrees
        self._vrender(layout, render, plain_layout)
        if plain_layout is not None:
            self._text = render(plain_source, plain_layout, True, (max(len(r) for r in crows), len(crows)))
            self._rotcells_v = {}
            self._rotsrc_v = {}
            self._rotmaps_ok = False
        else:
            self._text = ''
            self._rotmap = None
            self._rotcells_v = {}
            self._rotsrc_v = {}
            self._rotmaps_ok = True
            self._rotsize = (0, 0)
            self._rotorigin = (0, 0)
        self._xlen_cache = None
        self._ylen_cache = None
        self._protate(angle_degrees, layout, render)
        self._parse_pixels_key = None
        self._parse_pixels_val = None

        self.vx = self._rotorigin[0]
        self.vy = -self._rotorigin[1]

    def _protate(self, angle_degrees, layout, render):
        if self._htext == self._rtext:
            self._ptext = self._text
            self._pvx = self._rotorigin[0]
            self._pvy = -self._rotorigin[1]
            self._pkey = None
            return
        key = (angle_degrees, self._htext, self._flip, self.rotaspect)
        if self._pkey == key:
            return
        self._pkey = key
        source = self.parse_pixels(self._htext)
        lay = layout(source) if self._htext.splitlines() else None
        if lay is None:
            self._ptext = ''
            self._pvx = 0
            self._pvy = 0
        else:
            self._ptext = render(source, lay)
            self._pvx = lay[5]
            self._pvy = -lay[7]

    def _rotmaps(self):
        if self._rotmaps_ok:
            return
        self._rotmaps_ok = True
        plain = self._rtext
        if not plain.splitlines():
            return
        layout, render = self._rotator(self._rotangle)
        source = self.parse_pixels(plain)
        lay = layout(source)
        if lay is not None:
            render(source, lay, True, self._rotsize, True)

    @property
    def _rotcells(self):
        self._rotmaps()
        return self._rotcells_v

    @property
    def _rotsrc(self):
        self._rotmaps()
        return self._rotsrc_v

    def _origin(self):
        return round(self._x + self.vx), round(self._y + self.vy)

    def _cell_world(self, cell):
        m = self._rotmap
        ox, oy = self._origin()
        return ox + (cell[0] - m[2]), oy - (cell[1] - m[3])

    def rtext_to_world(self, ci, ri):
        if self._rotmap is None:
            return None
        cells = self._rotsrc.get((ci, ri))
        if not cells:
            return None
        return self._cell_world(min(cells))

    def worldcells(self):
        if self._rotmap is None:
            return set()
        return {self._cell_world(c) for c in self._rotcells}

    def world_to_rtext_all(self, wx, wy):
        m = self._rotmap
        if m is None:
            return []
        ox, oy = self._origin()
        return self._rotcells.get((wx - ox + m[2], oy - wy + m[3]), [])

    def world_to_rtext(self, wx, wy):
        found = self.world_to_rtext_all(wx, wy)
        return found[0] if found else None

    def world_to_rtextf(self, wx, wy):
        m = self._rotmap
        if m is None:
            return None
        cx, cy, min_x, min_y, ASPECT, ja, jb, jc, jd = m
        ox, oy = self._origin()
        rx_n = (wx - ox + min_x - cx) * ASPECT
        ry_n = oy - wy + min_y - cy
        rel_x = (rx_n * ja + ry_n * jb) / ASPECT
        rel_y = rx_n * jc + ry_n * jd
        return rel_x + cx, rel_y + cy

    def cutline(self, p0, p1):
        a = self.world_to_rtextf(*p0)
        b = self.world_to_rtextf(*p1)
        if a is None or b is None:
            return set()
        width, height = self._rotsize
        if (max(a[0], b[0]) < -1 or min(a[0], b[0]) > width
                or max(a[1], b[1]) < -1 or min(a[1], b[1]) > height):
            return set()
        steps = max(1, int(math.ceil(max(abs(b[0] - a[0]), abs(b[1] - a[1])) * 2)))
        pixels = self.parse_pixels(self.vrtext)
        walls = set()
        for i in range(steps + 1):
            u = i / steps
            c = (round(a[0] + (b[0] - a[0]) * u), round(a[1] + (b[1] - a[1]) * u))
            if c in pixels and pixels[c][0] != ' ':
                walls.add(c)
        return walls

    def _clear(self, cells):
        styled = self.parse_pixels(self._vbase)
        hit = [c for c in cells if c in styled and styled[c][0] != ' ']
        if not hit:
            return False
        styled = dict(styled)
        for c in hit:
            styled[c] = (' ', '')
        ref = next((p for p, (char, _) in styled.items() if char != ' ' and self._rotsrc.get(p)), None)
        before = self.rtext_to_world(*ref) if ref is not None else None
        xs = [p[0] for p in styled]
        ys = [p[1] for p in styled]
        phys = getattr(self.obj, 'physics', None)
        old_mass = phys.mass if phys is not None else None
        rows = self.build_rows(styled, min(xs), max(xs), min(ys), max(ys))
        self._htext = self.scene.recomp.sub('', rows)
        self.vhtext = rows
        self.rtext = rows
        if old_mass and phys.mass != old_mass:
            k = phys.mass / old_mass
            phys.xvel *= k
            phys.yvel *= k
            phys.avel *= k
        after = self.rtext_to_world(ref[0] - min(xs), ref[1] - min(ys)) if ref is not None else None
        if before is not None and after is not None:
            if before[0] != after[0]:
                self.x = self._x + before[0] - after[0]
            if before[1] != after[1]:
                self.y = self._y + before[1] - after[1]
        return True

    def cut(self, wx, wy, r=1, shape='circle'):
        return self.cutpoints([(wx, wy)], r, shape)

    def cutpoints(self, points, r=1, shape='circle'):
        offsets = _footprint(r, self.scene.aspect, shape)
        cells = []
        for wx, wy in points:
            for dx, dy in offsets:
                cells.extend(self.world_to_rtext_all(wx + dx, wy + dy))
        return self._clear(cells)

    def _notify_whole(self, callback):
        if callable(callback):
            l = _argslen(callback)
            if l > 1: callback([self.obj], self.obj)
            elif l > 0: callback([self.obj])
            else: callback()

    def _fragments(self, coords, diagonal=True, walls=()):
        walls = set(walls)
        neighbours = _NEIGHBOURS8 if diagonal else _NEIGHBOURS4
        remaining = set(coords)
        components = []
        while remaining:
            group = set()
            stack = [next(iter(remaining))]
            while stack:
                pos = stack.pop()
                if pos not in remaining:
                    continue
                remaining.remove(pos)
                group.add(pos)
                cx, cy = pos
                for dx, dy in neighbours:
                    nxt = (cx + dx, cy + dy)
                    if nxt not in remaining:
                        continue
                    if dx and dy and (cx + dx, cy) in walls and (cx, cy + dy) in walls:
                        continue
                    stack.append(nxt)
            components.append(group)
        return components

    def _spawn_from_components(self, components, pixels, callback=None):
        rotation = self._rotation
        ox, oy = self._x, self._y
        parent = getattr(self.obj, 'physics', None)
        motion = None
        if parent is not None:
            A = self.scene.aspect
            pcx, pcy, _ = parent.body()
            motion = (parent.xvel / parent.mass * A, parent.yvel / parent.mass, parent._omega(),
                      parent.avel / parent.mass, pcx, pcy)

        fading = dict(self._fade) if self._fade is not None else None
        spawns = []
        anchors = []
        for group in components:
            xs = [p[0] for p in group]
            ys = [p[1] for p in group]
            min_x, max_x = min(xs), max(xs) + 1
            min_y, max_y = min(ys), max(ys) + 1
            target = {self._cell_world(c) for p in group for c in self._rotsrc.get(p, ())}

            kw = self.obj.kwargs()
            for key in ('mass', 'rtext', 'htext', 'vtext', 'vrtext', 'vhtext', 'vx', 'vy', 'xvel', 'yvel', 'avel', 'joints'):
                kw.pop(key, None)
            if parent is not None:
                kw.update(dynamic=parent.dynamic, bounciness=parent.bounciness, friction=parent.friction)
            if self._rotaspect is not None:
                kw['rotaspect'] = self._rotaspect
            for key in ('fg', 'bg', 'alpha', 'bgalpha'):
                value = getattr(self, key)
                if value is not None:
                    kw[key] = value
            spawns.append({
                **kw,
                'text': self.build_rows({p: pixels[p] for p in group}, min_x, max_x - 1, min_y, max_y - 1),
                'x': ox + min_x,
                'y': oy - min_y,
                'rotation': rotation,
                'flip': self._flip,
            })
            anchors.append(target)

        obj_ref = self.obj
        def do_split(spawns=spawns, anchors=anchors, obj_ref=obj_ref, cb=callback, motion=motion, fading=fading):
            parts = []
            for kw, target in zip(spawns, anchors):
                part = obj_ref.scene.obj().create(**kw)
                ft = part.transform
                if fading is not None:
                    ft._fade = dict(fading)
                placed = ft.worldcells()
                if target and placed:
                    dx = round(sum(w[0] for w in target) / len(target) - sum(w[0] for w in placed) / len(placed))
                    dy = round(sum(w[1] for w in target) / len(target) - sum(w[1] for w in placed) / len(placed))
                    best = min(
                        ((sx, sy) for sx in range(dx - 1, dx + 2) for sy in range(dy - 1, dy + 2)),
                        key=lambda s: len({(wx + s[0], wy + s[1]) for wx, wy in placed} ^ target)
                    )
                    ft.x = ft.x + best[0]
                    ft.y = ft.y + best[1]
                fp = getattr(part, 'physics', None)
                if fp is not None and motion is not None:
                    vx, vy, omega, spin, pcx, pcy = motion
                    fcx, fcy, _ = fp.body()
                    A = obj_ref.scene.aspect
                    rx, ry = (fcx - pcx) * A, fcy - pcy
                    fp.xvel = (vx - omega * ry) / A * fp.mass
                    fp.yvel = (vy + omega * rx) * fp.mass
                    fp.avel = spin * fp.mass
                parts.append(part)
            if getattr(obj_ref, 'joint', None) is not None:
                joint.transfer(obj_ref, parts)
            if callable(cb):
                l = _argslen(cb)
                if l > 1: cb(parts, obj_ref)
                elif l > 0: cb(parts)
                else: cb()
            for calb, cl in list(self._onsplit.items()):
                if cl > 1: calb(parts, obj_ref)
                elif cl > 0: calb(parts)
                else: calb()
            obj_ref.discard()
        do_split()
        return do_split

    def split(self, callback=None, diagonal=True):
        if getattr(self.obj, 'transform', None) is not self:
            return
        pixels = self.parse_pixels(self._vbase)
        coords = {pos for pos, (char, _) in pixels.items() if char != ' '}
        if not coords:
            self._notify_whole(callback)
            self.obj.discard()
            return

        components = self._fragments(coords, diagonal)
        if len(components) < 2:
            self._notify_whole(callback)
            return

        self._split_cb = self._spawn_from_components(components, pixels, callback)
        return self._split_cb

    def split_at(self, wall_pixels, callback=None, diagonal=True):
        if getattr(self.obj, 'transform', None) is not self:
            return
        pixels = self.parse_pixels(self._vbase)
        coords = {pos for pos, (char, _) in pixels.items() if char != ' '}

        valid_walls = set(wall_pixels) & coords
        if not valid_walls:
            self._notify_whole(callback)
            return

        components = self._fragments(coords - valid_walls, diagonal, valid_walls)
        if len(components) < 2:
            self._notify_whole(callback)
            return

        neighbours = _NEIGHBOURS8 if diagonal else _NEIGHBOURS4
        remaining = set(valid_walls)
        grew = True
        while remaining and grew:
            grew = False
            for wp in sorted(remaining):
                cx, cy = wp
                for comp in components:
                    if any((cx + dx, cy + dy) in comp for dx, dy in neighbours):
                        comp.add(wp)
                        remaining.discard(wp)
                        grew = True
                        break
        if remaining:
            components.extend(self._fragments(remaining, diagonal))

        self._split_cb = self._spawn_from_components(components, pixels, callback)
        return self._split_cb

    def onsplit(self, cb, once=False):
        if once:
            l = _argslen(cb)
            fired = [False]
            orig = cb
            def wrapped(parts=None, obj_ref=None):
                if fired[0]: return
                fired[0] = True
                if wrapped in self._onsplit:
                    del self._onsplit[wrapped]
                if l > 1: orig(parts, obj_ref)
                elif l > 0: orig(parts)
                else: orig()
            cb = wrapped
            self._onsplit[cb] = 2
        else:
            self._onsplit[cb] = _argslen(cb)
        return cb

    def offsplit(self, cb):
        self._onsplit = {f:par for f,par in self._onsplit.items() if f is not cb}

    def xlen(self, text=None):
        if text is None:
            if self._xlen_cache is not None:
                return self._xlen_cache
            text = self._text
            lens = []
            for row in text.splitlines():
                for i, char in enumerate(row):
                    if char != ' ':
                        lens.append(i)
            result = abs(max(lens) - (min(lens) - 1)) if lens else 0
            self._xlen_cache = result
            return result
        lens = []
        for row in text.splitlines():
            for i, char in enumerate(row):
                if char != ' ':
                    lens.append(i)
        return abs(max(lens) - (min(lens) - 1)) if lens else 0

    def ylen(self, text=None):
        if text is None:
            if self._ylen_cache is not None:
                return self._ylen_cache
            text = self._text
            count = 0
            for row in text.splitlines():
                if any(c != ' ' and c != '\n' for c in row):
                    count += 1
            self._ylen_cache = count
            return count
        count = 0
        for row in text.splitlines():
            if any(c != ' ' and c != '\n' for c in row):
                count += 1
        return count

    def xc(self, text=None):
        return self.xlen(text) / 2

    def yc(self, text=None):
        return self.ylen(text) / 2

    def extent(self):
        rows = self._text.splitlines()
        cols = [i for row in rows for i, char in enumerate(row) if char != ' ']
        if not cols:
            return self._x + self.vx, self._y + self.vy, 0, 0
        lo, hi = min(cols), max(cols) + 1
        return (self._x + self.vx + (lo + hi) / 2, self._y + self.vy - len(rows) / 2,
                (hi - lo) / 2, len(rows) / 2)

    def forward(self, move=1, offset=0, angle=None):
        angle = math.radians((self._rotation if angle is None else angle) + offset)
        x = math.sin(angle) * move
        y = math.cos(angle) * self.scene.aspect * move
        return (x, y)

    def pivot(self, local=False):
        m = self._rotmap
        if m is None:
            return (0.0, 0.0) if local else (self._x + self.vx, self._y + self.vy)
        if local:
            return m[0], -m[1]
        ox, oy = self._origin()
        return ox + m[0] - m[2], oy - (m[1] - m[3])

    def point(self, tx, ty, offset=0, origin=None):
        ox, oy = self.pivot() if origin is None else origin
        dx = tx - ox
        dy = ty - oy
        ASPECT = self.scene.aspect
        angle = math.degrees(math.atan2(-dy, dx * ASPECT))+90
        return angle + offset

    def aim(self, obj, offset=0):
        return self.point(*obj.transform.pivot(), offset=offset)

    def alerp(self, angle):
        return (angle - self._rotation + 540) % 360 - 180

    def bounce(self, normal, angle=None):
        if isinstance(normal, (tuple, list)):
            normal = math.degrees(math.atan2(normal[0], normal[1]))
        heading = self._rotation if angle is None else angle
        return (2 * normal - heading + 180) % 360

    @property
    def animating(self):
        return self._anim is not None

    def _frame(self, frame):
        self.rtext = self.vhtext if frame is None else frame

    def animate(self, frames, delay=1, loop=True, callback=None, restore=False):
        frames = list(frames)
        if not frames:
            return self.unanimate()
        delays = list(delay) if isinstance(delay, (list, tuple)) else [delay] * len(frames)
        if len(delays) != len(frames):
            raise ValueError('delay must be a number or have one entry per frame')
        if any(d <= 0 for d in delays):
            raise ValueError('delay must be positive')
        passes = None if loop is True else max(1, int(loop))
        self._anim = {'frames': frames, 'delays': delays, 'index': 0, 'passes': passes,
                      'cb': callback, 'restore': restore, 'wait': delays[0]}
        self._frame(frames[0])
        return self

    def unanimate(self, restore=True):
        was = self._anim is not None
        self._anim = None
        if was and restore:
            self.rtext = self.vhtext
        return self

    def _tick(self):
        if self._fade is not None:
            self._tickfade()
        self._tickanim()

    @property
    def fading(self):
        return self._fade is not None

    def fade(self, alpha=0, time=1, delay=0, bgalpha=None, start=None, callback=None, discard=False, ease='linear'):
        if time < 0 or delay < 0:
            raise ValueError('time and delay must not be negative')
        curve = _easing(ease)
        a0 = 1.0 if self._alpha is None else self._alpha
        b0 = 1.0 if self._bgalpha is None else self._bgalpha
        if start is not None:
            a0, b0 = start if isinstance(start, (tuple, list)) else (start, start)
            self._fade = None
            self._applystyle(alpha=a0, bgalpha=b0)
        self._fade = {'a0': a0, 'b0': b0, 'a1': alpha, 'b1': alpha if bgalpha is None else bgalpha,
                      'time': time, 'delay': delay, 'elapsed': 0.0, 'cb': callback,
                      'discard': discard, 'ease': curve}
        if time <= 0 and delay <= 0:
            self._finishfade()
        return self

    def unfade(self, finish=False):
        f = self._fade
        self._fade = None
        if f is not None and finish:
            self._fadeto(f, 1.0)
        return self

    def _fadeto(self, f, progress):
        if progress >= 1:
            a, b = f['a1'], f['b1']
        else:
            p = f['ease'](progress)
            a = f['a0'] + (f['a1'] - f['a0']) * p
            b = f['b0'] + (f['b1'] - f['b0']) * p
        a = max(0.0, min(1.0, a))
        b = max(0.0, min(1.0, b))
        self._applystyle(alpha=None if a >= 1 else a, bgalpha=None if b >= 1 else b)

    def _finishfade(self):
        f = self._fade
        self._fade = None
        self._fadeto(f, 1.0)
        cb = f['cb']
        if callable(cb):
            if _argslen(cb):
                cb(self.obj)
            else:
                cb()
        if f['discard'] and getattr(self.obj, 'transform', None) is self:
            self.obj.discard()

    def _tickfade(self):
        f = self._fade
        dt = 1 / self.scene.framerate
        if f['delay'] > 0:
            f['delay'] -= dt
            if f['delay'] > 0:
                return
            dt = -f['delay']
            f['delay'] = 0
        f['elapsed'] += dt
        if f['elapsed'] >= f['time']:
            self._finishfade()
        else:
            self._fadeto(f, f['elapsed'] / f['time'])

    def _tickanim(self):
        a = self._anim
        if a is None:
            return
        a['wait'] -= 1
        while a['wait'] <= 0 and self._anim is a:
            a['index'] += 1
            if a['index'] >= len(a['frames']):
                if a['passes'] is not None:
                    a['passes'] -= 1
                    if a['passes'] <= 0:
                        self._anim = None
                        if a['restore']:
                            self.rtext = self.vhtext
                        cb = a['cb']
                        if callable(cb):
                            if _argslen(cb):
                                cb(self.obj)
                            else:
                                cb()
                        return
                a['index'] = 0
            self._frame(a['frames'][a['index']])
            a['wait'] += a['delays'][a['index']]

    def lerp(self, alpha=1, **kwargs):
        for key, target in kwargs.items():
            current = getattr(self, key)
            if alpha == 1:
                value = target
            elif key == 'rotation':
                value = current + self.alerp(target) * alpha
            else:
                value = current + (target - current) * alpha
            setattr(self, key, value)
        return self


class rendering():
    _owned = ['show', 'renderspaces', 'z']
    _required = [transform]
    _default = True
    _settings = ('show', 'spaces', 'z')
    _aliases = {'spaces': 'renderspaces'}

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.t = obj.transform
        self.scene = obj.scene
        self._litkey = None
        self._lit = ''
        self.show = kwargs.get('show', True)
        self.renderspaces = kwargs.get('renderspaces', False)
        self.z = kwargs.get('z', 0)

    @property
    def z(self):
        return self._z

    @z.setter
    def z(self, value):
        self._z = value
        if self._z > self.scene._lastz: self.scene._lastz = self._z
        if self._z < self.scene._firstz: self.scene._firstz = self._z

    @property
    def spaces(self):
        return self.renderspaces
    @spaces.setter
    def spaces(self, value):
        self.renderspaces = value

    def _shown(self):
        self.t._stylecheck()
        text = self.t.vtext
        sc = self.scene
        if not text or (not sc.lights and sc.ambient >= 1):
            return text
        lights = tuple((id(l), l._version) for l in sc.lights if l.on and l._affects(self.obj))
        key = (text, self.t._origin(), sc.ambient, sc.bgcolor, sc.fgcolor, lights)
        if self._litkey != key:
            self._litkey = key
            self._lit = light.shade(sc, self.obj, text)
        return self._lit

    def state(self, camx, camy, xoff, yoff):
        if not self.show:
            return (0, 0, '', 0, 0)
        t = self.t
        return (
            int((t.x + t.vx - camx + 0.5) // 1),
            -int((t.y + t.vy - camy + 0.5) // 1),
            self._shown(),
            xoff,
            yoff,
        )

    def front(self):
        self.z = self.scene._lastz +1

    def back(self):
        self.z = self.scene._firstz -1


class physics(_change_callback):
    _owned = [
        'xvel', 'yvel', 'avel',
        'dynamic',
        'bounciness',
        'friction',
        'mass', 'automass',
        'solid',
        'hitbox',
        'touch',
        'phantom',
        'gravity',
        'drag',
        'adrag',
        'precision',
        'rprecision',
        'slope',
    ]
    _required = [transform]
    _settings = ('xvel', 'yvel', 'avel', 'dynamic', 'bounciness', 'friction', 'mass', 'automass', 'solid',
                 'hitbox', 'phantom', 'gravity', 'drag', 'adrag', 'precision', 'rprecision', 'slope')
    _running = 0
    def on_discard(self):
        self.scene.solids = [s for s in self.scene.solids if s is not self.obj]
        discarded = self.obj
        for other in self.scene.objs:
            if other is discarded or not hasattr(other, 'physics'):
                continue
            p = other.physics
            p._touch_callbacks = [
                cb for cb in p._touch_callbacks
                if not _closure_refs(cb, discarded)
            ]
            other._ghosts[:] = [
                g for g in other._ghosts
                if g is not discarded and not (getattr(g, '__closure__', None) and _closure_refs(g, discarded))
            ]

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.t = obj.transform
        self.scene = obj.scene
        self._axises = ('x', 'y')
        self._xvel = kwargs.get('xvel', 0)
        self._yvel = kwargs.get('yvel', 0)
        self._avel = kwargs.get('avel', 0)
        self.dynamic = kwargs.get('dynamic', True)
        self.bounciness = kwargs.get('bounciness', 0)
        self.friction = kwargs.get('friction', 0)
        gravity = kwargs.get('gravity', None)
        self._gravity = None if gravity is None else tuple(gravity)
        if self._gravity is not None and len(self._gravity) != 2:
            raise ValueError('gravity must be a (x, y) pair or None')
        self._drag = kwargs.get('drag', None)
        self._adrag = kwargs.get('adrag', None)
        self._precision = kwargs.get('precision', None)
        self._rprecision = kwargs.get('rprecision', 3)
        if (self._precision is not None and self._precision <= 0) or self._rprecision <= 0:
            raise ValueError('precision and rprecision must be positive')
        self.mass = kwargs.get('mass', None)
        self.automass = kwargs.get('automass', self.mass is None)
        def masscal(prop='text'):
            if self.automass and prop.endswith('text'):
                self.mass = sum(1 for c in self.t._htext if c not in (' ', '\n'))
        if self.mass is None:
            masscal()
        self.t.onchange(masscal)
        self.solid = kwargs.get('solid', True)
        self.hitbox = kwargs.get('hitbox', False)
        self.phantom = kwargs.get('phantom', False)
        self.slope = kwargs.get('slope', True)
        self.touch = (False, False)
        self.sides = (False, False, False, False)
        self._touch_callbacks = []
        self._pixel_cache = None
        self._bounds_cache = None
        self._body_cache = None
        self._ext_cache = None
        self._good = None
        self._depenskip = 0
        def dirty(attr):
            self._dirty(attr)
        self.t.onchange(dirty)

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    @property
    def solid(self):
        return self._solid
    @solid.setter
    def solid(self, value):
        self._solid = value
        if value:
            if not any(o is self.obj for o in self.scene.solids):
                self.scene.solids.append(self.obj)
        else:
            self.scene.solids = [o for o in self.scene.solids if o is not self.obj]

    @property
    def hitbox(self):
        return self._hitbox
    @hitbox.setter
    def hitbox(self, value):
        old = getattr(self, '_hitbox', None)
        self._hitbox = value
        self._dirty()
        if old is not None and old != value:
            self._change('hitbox', old)

    @property
    def xvel(self):
        return self._xvel
    @xvel.setter
    def xvel(self, value):
        old = self._xvel
        self._xvel = value
        self._change('xvel', old)

    @property
    def yvel(self):
        return self._yvel
    @yvel.setter
    def yvel(self, value):
        old = self._yvel
        self._yvel = value
        self._change('yvel', old)

    @property
    def avel(self):
        return self._avel
    @avel.setter
    def avel(self, value):
        old = self._avel
        self._avel = value
        self._change('avel', old)

    @property
    def mass(self):
        return self._mass
    @mass.setter
    def mass(self, value):
        self._mass = max(1, value) if isinstance(value, (int, float)) else value

    @property
    def gravity(self):
        return self.scene.gravity if self._gravity is None else self._gravity
    @gravity.setter
    def gravity(self, value):
        old = self._gravity
        if value is not None:
            value = tuple(value)
            if len(value) != 2:
                raise ValueError('gravity must be a (x, y) pair or None')
        self._gravity = value
        self._change('gravity', old)

    @property
    def drag(self):
        return self.scene.drag if self._drag is None else self._drag
    @drag.setter
    def drag(self, value):
        old = self._drag
        self._drag = value
        self._change('drag', old)

    @property
    def adrag(self):
        return self.drag if self._adrag is None else self._adrag
    @adrag.setter
    def adrag(self, value):
        old = self._adrag
        self._adrag = value
        self._change('adrag', old)

    @property
    def precision(self):
        return self.scene.precision if self._precision is None else self._precision
    @precision.setter
    def precision(self, value):
        if value is not None and value <= 0:
            raise ValueError('precision must be positive or None')
        old = self._precision
        self._precision = value
        self._change('precision', old)

    @property
    def rprecision(self):
        return self._rprecision
    @rprecision.setter
    def rprecision(self, value):
        if value <= 0:
            raise ValueError('rprecision must be positive')
        old = self._rprecision
        self._rprecision = value
        self._change('rprecision', old)

    def _dirty(self, attr=None):
        self._pixel_cache = None
        self._bounds_cache = None
        self._body_cache = None
        if attr != 'x' and attr != 'y':
            self._ext_cache = None

    def _extent(self):
        ext = self._ext_cache
        if ext is None:
            hitbox = self.hitbox
            text = self.t._htext if hitbox else self.t._ptext
            lo = hi = top = bottom = None
            for i, row in enumerate(text.splitlines()):
                if hitbox:
                    if not row:
                        continue
                    a, b = 0, len(row) - 1
                else:
                    if not row.strip(' '):
                        continue
                    a = len(row) - len(row.lstrip(' '))
                    b = len(row.rstrip(' ')) - 1
                if lo is None or a < lo:
                    lo = a
                if hi is None or b > hi:
                    hi = b
                if top is None:
                    top = i
                bottom = i
            ext = (lo, hi, top, bottom) if lo is not None else ()
            self._ext_cache = ext
        return ext

    def _extent_bounds(self, x=None, y=None):
        ext = self._extent()
        if not ext:
            return None
        t = self.t
        x = t.x if x is None else x
        y = t.y if y is None else y
        if self.hitbox:
            ox = oy = 0
        else:
            ox, oy = t._pvx, t._pvy
        rx = round(x + ox)
        ry = round(y + oy)
        return (rx + ext[0], rx + ext[1], ry - ext[3], ry - ext[2])

    def ontouch(self, callback, when=None, once=False):
        l = _argslen(callback)
        fired = [False]
        def wrapped(obj2, intersection):
            if once and fired[0]: return
            if when is None or when(obj2):
                if once: fired[0] = True
                if l > 1: callback(obj2, intersection)
                elif l > 0: callback(obj2)
                else: callback()
                if once and wrapped in self._touch_callbacks:
                    self._touch_callbacks.remove(wrapped)
        self._touch_callbacks.append(wrapped)
        return callback

    def offtouch(self, callback):
        self._touch_callbacks = [
            cb for cb in self._touch_callbacks if cb.__closure__ and
            cb.__closure__[0].cell_contents is not callback
        ]

    def ghost(self, other):
        if not any(g is other for g in self.obj._ghosts):
            self.obj._ghosts.append(other)

    def getpixels(self, x=None, y=None, text=None):
        default_call = x is None and y is None and text is None
        if default_call and self._pixel_cache is not None:
            return self._pixel_cache

        x = self.t.x if x is None else x
        y = self.t.y if y is None else y
        if self.hitbox:
            text = self.t._htext
            ox = oy = 0
        elif text is None:
            text = self.t._ptext
            ox, oy = self.t._pvx, self.t._pvy
        else:
            ox, oy = self.t.vx, self.t.vy
        rx = round(x + ox)
        ry = round(y + oy)
        pixels = set()
        for i, row in enumerate(text.splitlines()):
            for j, char in enumerate(row):
                if (char != ' ' and char != '\n' and not self.hitbox) or self.hitbox:
                    pixels.add((rx + j, ry - i))

        if default_call:
            self._pixel_cache = pixels
            self._bounds_cache = None
        return pixels

    def bounds(self, pixels=None):
        if pixels is None:
            if self._bounds_cache is not None:
                return self._bounds_cache
            if self._pixel_cache is None:
                result = self._extent_bounds()
                self._bounds_cache = result
                return result
            pixels = self._pixel_cache
        if not pixels:
            result = None
        else:
            xs = [p[0] for p in pixels]
            ys = [p[1] for p in pixels]
            result = (min(xs), max(xs), min(ys), max(ys))
        if pixels is self._pixel_cache:
            self._bounds_cache = result
        return result

    def collides(self, objs, x=None, y=None, text=None, full=False):
        if text is None:
            b1 = self._extent_bounds(x, y)
            if b1 is None:
                return {}
            pixels1 = None
        else:
            pixels1 = self.getpixels(x, y, text)
            if not pixels1:
                return {}
            b1 = self.bounds(pixels1)

        if not isinstance(objs, list):
            objs = [objs]

        result = {}
        for obj2 in objs:
            if obj2 is self.obj:
                continue
            p2 = obj2.physics
            b2 = p2.bounds()
            if b2 is None or b2[1] < b1[0] or b2[0] > b1[1] or b2[3] < b1[2] or b2[2] > b1[3]:
                continue
            if pixels1 is None:
                pixels1 = self.getpixels(x, y)
            intersection = pixels1 & p2.getpixels()
            if intersection:
                result[obj2] = intersection
                if not self.phantom and not full:
                    break
        return result

    def overlaps(self, pixels=None):
        b1 = self.bounds() if pixels is None else self.bounds(pixels)
        found = {}
        if b1 is None:
            return found
        for obj2 in self.scene.solids:
            if obj2 is self.obj:
                continue
            p2 = getattr(obj2, 'physics', None)
            if p2 is None or p2.phantom or not p2.solid:
                continue
            b2 = p2.bounds()
            if b2 is None or b2[1] < b1[0] or b2[0] > b1[1] or b2[3] < b1[2] or b2[2] > b1[3]:
                continue
            if pixels is None:
                pixels = self.getpixels()
            inter = pixels & p2.getpixels()
            if inter and not self._ghosted(obj2, inter):
                found[obj2] = inter
        return found

    def body(self):
        if self._body_cache is None:
            pixels = self.getpixels()
            n = len(pixels)
            if n == 0:
                self._body_cache = (0.0, 0.0, 1.0)
            else:
                A = self.scene.aspect
                cx = sum(p[0] for p in pixels) / n
                cy = sum(p[1] for p in pixels) / n
                spread = sum(((p[0] - cx) * A) ** 2 + (p[1] - cy) ** 2 for p in pixels) / n
                self._body_cache = (cx, cy, spread + (A * A + 1) / 12)
        return self._body_cache

    def _invinertia(self):
        if self.hitbox or not self.slope or not self.dynamic or not self.solid or len(self.getpixels()) < 2:
            return 0.0
        return 1.0 / (self.mass * self.body()[2])

    def _velocity(self):
        A = self.scene.aspect
        return self.xvel / self.mass * A, self.yvel / self.mass

    def _omega(self):
        return -math.radians(self.avel / self.mass)

    def _impulse(self, jx, jy, rx=0.0, ry=0.0):
        A = self.scene.aspect
        self.xvel += jx / A
        self.yvel += jy
        if rx or ry:
            self._spin(rx * jy - ry * jx)

    def _spin(self, torque):
        inv = self._invinertia()
        if inv and torque:
            self.avel -= math.degrees(torque * inv) * self.mass

    def _arm(self, point):
        A = self.scene.aspect
        cx, cy, _ = self.body()
        return (point[0] - cx) * A, point[1] - cy

    def _shifted(self, dx, dy):
        return {(p[0] + dx, p[1] + dy) for p in self.getpixels()}

    def _ghosted(self, other, intersection=None):
        for owner, partner in ((self.obj, other), (other, self.obj)):
            for ghost in list(getattr(owner, '_ghosts', ())):
                if ghost is partner:
                    return True
                if callable(ghost):
                    count = _argslen(ghost)
                    if count > 1:
                        result = ghost(partner, intersection)
                    elif count > 0:
                        result = ghost(partner)
                    else:
                        result = ghost()
                    if result:
                        return True
        return False

    def _blocked(self, dx, dy, exclude=()):
        b = self.bounds()
        hits = []
        if b is None:
            return hits
        shifted = None
        for obj2 in self.scene.solids:
            if obj2 is self.obj or obj2 in exclude:
                continue
            p2 = getattr(obj2, 'physics', None)
            if p2 is None or p2.phantom or not p2.solid:
                continue
            b2 = p2.bounds()
            if b2 is None or b2[1] < b[0] + dx or b2[0] > b[1] + dx or b2[3] < b[2] + dy or b2[2] > b[3] + dy:
                continue
            if shifted is None:
                shifted = self._shifted(dx, dy)
            inter = shifted & p2.getpixels()
            if inter and not self._ghosted(obj2, inter):
                hits.append(obj2)
        return hits

    def cluster(self, start, dx, dy):
        members = [start]
        seen = {id(start.obj), id(self.obj)}
        queue = [start]
        while queue:
            body = queue.pop()
            if not body.dynamic:
                return None
            for obj2 in body._blocked(dx, dy, exclude=[m.obj for m in members] + [self.obj]):
                p2 = obj2.physics
                if id(obj2) in seen:
                    continue
                if not p2.dynamic:
                    return None
                seen.add(id(obj2))
                members.append(p2)
                queue.append(p2)
        return members

    def _solve(self, other, group, point, nx, ny, restitution=None):
        A = self.scene.aspect
        ra = self._arm(point)
        va = self._velocity()
        wa = self._omega()
        vax = va[0] - wa * ra[1]
        vay = va[1] + wa * ra[0]

        if group is None:
            rb = (0.0, 0.0)
            vbx = vby = 0.0
            invmb = 0.0
            invib = 0.0
            e_other = other.bounciness
            mu_other = other.friction
            single = None
        else:
            single = group[0] if len(group) == 1 else None
            total = sum(m.mass for m in group)
            invmb = 1.0 / total
            if single is not None:
                rb = single._arm(point)
                vb = single._velocity()
                wb = single._omega()
                vbx = vb[0] - wb * rb[1]
                vby = vb[1] + wb * rb[0]
                invib = single._invinertia()
            else:
                rb = (0.0, 0.0)
                vbx = sum(m.xvel / m.mass * A * m.mass for m in group) / total
                vby = sum(m.yvel for m in group) / total
                invib = 0.0
            e_other = max(m.bounciness for m in group)
            mu_other = max(m.friction for m in group)

        vn = (vax - vbx) * nx + (vay - vby) * ny
        if vn >= 0:
            return False

        e = max(self.bounciness, e_other) if restitution is None else restitution
        if -vn < 0.25:
            e = 0.0

        inva = 1.0 / self.mass
        ia = self._invinertia()
        can = (ra[0] * ny - ra[1] * nx) ** 2 * ia
        cbn = (rb[0] * ny - rb[1] * nx) ** 2 * invib
        denom = inva + invmb + can + cbn
        gravity = self.gravity
        boost = e * max(0.0, -(gravity[0] * A * nx + gravity[1] * ny))
        j = (-(1 + e) * vn + boost) / denom

        self._impulse(j * nx, j * ny, *ra)
        self._apply_other(group, single, -j * nx, -j * ny, rb)

        mu = max(self.friction, mu_other)
        if mu:
            tx, ty = -ny, nx
            va = self._velocity()
            wa = self._omega()
            vax = va[0] - wa * ra[1]
            vay = va[1] + wa * ra[0]
            if group is None:
                vbx = vby = 0.0
            elif single is not None:
                vb = single._velocity()
                wb = single._omega()
                vbx = vb[0] - wb * rb[1]
                vby = vb[1] + wb * rb[0]
            else:
                vbx = sum(m.xvel * A / 1.0 for m in group) / total
                vby = sum(m.yvel for m in group) / total
            vt = (vax - vbx) * tx + (vay - vby) * ty
            cat = (ra[0] * ty - ra[1] * tx) ** 2 * ia
            cbt = (rb[0] * ty - rb[1] * tx) ** 2 * invib
            jt = -vt / (inva + invmb + cat + cbt)
            limit = mu * j
            jt = max(-limit, min(limit, jt))
            self._impulse(jt * tx, jt * ty, *ra)
            self._apply_other(group, single, -jt * tx, -jt * ty, rb)
        return True

    def _apply_other(self, group, single, jx, jy, rb):
        if group is None:
            return
        if single is not None:
            single._impulse(jx, jy, *rb)
            return
        total = sum(m.mass for m in group)
        for m in group:
            share = m.mass / total
            m._impulse(jx * share, jy * share)

    def _contact_point(self, pixels, nx=None, ny=None):
        return _contact_point_cells(pixels, nx, ny, self.body()[:2])

    def _contact_normal(self, other, point, nx, ny, inside):
        return _contact_normal_cells(self.getpixels(), other.getpixels(), point, nx, ny, inside,
                                     self.slope and other.slope, self.scene.aspect)

    def normal(self, other, local=None):
        return self.t.normal(other, local)

    def _mtv(self, other_pixels):
        return _mtv_cells(self.getpixels(), other_pixels, self.scene.aspect)

    def _remember(self):
        self._good = (self.t.x, self.t.y, self.t.rotation)

    def _settle(self, dx, dy):
        if dx and self.xvel * dx < 0:
            self.xvel = 0
        if dy and self.yvel * dy < 0:
            self.yvel = 0

    def _tunnels(self, found, dx, dy):
        cx, cy, _ = self.body()
        for obj2 in found:
            p2 = obj2.physics
            if p2.dynamic:
                continue
            b = p2.bounds()
            if b is None:
                continue
            mx, my = (b[0] + b[1]) / 2, (b[2] + b[3]) / 2
            if dx and (cx - mx) * (cx + dx - mx) < 0:
                return True
            if dy and (cy - my) * (cy + dy - my) < 0:
                return True
        return False

    def _unstick(self):
        t = self.t
        found = self.overlaps()
        good = self._good
        if good is not None:
            x, y, r = t.x, t.y, t.rotation
            if r != good[2]:
                t.rotation = good[2]
                if not self.overlaps():
                    self.avel = 0
                    self._remember()
                    return
            t.x, t.y = good[0], good[1]
            if not self.overlaps():
                self.xvel = self.yvel = self.avel = 0
                self._remember()
                return
            t.x, t.y = x, y
            if t.rotation != r:
                t.rotation = r
        for dx, dy in _offsets(6, self.scene.aspect):
            if not self._tunnels(found, dx, dy) and not self.overlaps(self._shifted(dx, dy)):
                t.x += dx
                t.y += dy
                self._settle(dx, dy)
                self._remember()
                return
        for dx, dy in ((0, 1), (1, 0), (-1, 0), (0, -1)):
            for k in range(7, 129):
                if not self._tunnels(found, dx * k, dy * k) and not self.overlaps(self._shifted(dx * k, dy * k)):
                    t.x += dx * k
                    t.y += dy * k
                    self._settle(dx, dy)
                    self._remember()
                    return
        self._depenskip = 4

    def _depenetrate(self):
        if self.phantom:
            return
        if self._depenskip > 0:
            self._depenskip -= 1
            return
        jt = getattr(self.obj, 'joint', None)
        pinned, owned = jt._hierarchy() if jt is not None else ((), ())
        budget = _RELIEF if pinned else None
        def hits():
            found = self.overlaps()
            if owned:
                return {o: v for o, v in found.items() if not any(o is d for d in owned)}
            return found
        seen = set()
        for _ in range(12):
            found = hits()
            if not found:
                self._remember()
                return
            key = (round(self.t.x, 4), round(self.t.y, 4), frozenset((id(o), round(o.transform.x, 4), round(o.transform.y, 4)) for o in found))
            if key in seen:
                break
            seen.add(key)
            obj2 = max(found, key=lambda o: len(found[o]))
            p2 = obj2.physics
            best = self._mtv(p2.getpixels())
            if best is None:
                break
            _, dx, dy, k = best
            if budget is not None:
                k = min(k, budget)
                budget -= k
            movable = p2.dynamic and not any(obj2 is a for a in pinned)
            if movable:
                mine_share = int(min(k, max(1, math.ceil(k * p2.mass / (self.mass + p2.mass)))))
                theirs_share = k - mine_share
            else:
                mine_share, theirs_share = k, 0
            if movable:
                if theirs_share and any(o is not self.obj for o in p2.overlaps(p2._shifted(-dx * theirs_share, -dy * theirs_share))):
                    mine_share, theirs_share = k, 0
                if mine_share and any(o is not obj2 for o in self.overlaps(self._shifted(dx * mine_share, dy * mine_share))):
                    if any(o is not self.obj for o in p2.overlaps(p2._shifted(-dx * k, -dy * k))):
                        break
                    mine_share, theirs_share = 0, k
            self.t.x += dx * mine_share
            self.t.y += dy * mine_share
            if theirs_share:
                p2.t.x -= dx * theirs_share
                p2.t.y -= dy * theirs_share
            for body, sign in ((self, 1), (p2, -1)):
                if body is p2 and not theirs_share:
                    continue
                if dx and body.xvel * dx * sign < 0:
                    body.xvel = 0
                if dy and body.yvel * dy * sign < 0:
                    body.yvel = 0
            if budget is not None and budget <= 0:
                if not hits():
                    self._remember()
                return
        if hits():
            self._unstick()
        else:
            self._remember()

    @property
    def grounded(self):
        return self.sides[2]

    @property
    def ceiling(self):
        return self.sides[3]

    def _probe(self):
        touch = [False, False]
        sides = [False, False, False, False]
        if self.solid and not self.phantom:
            mine = None
            for ia in (0, 1):
                for s in (1, -1):
                    dx, dy = (s, 0) if ia == 0 else (0, s)
                    for obj2 in self._blocked(dx, dy):
                        p2 = obj2.physics
                        theirs = p2.getpixels()
                        if mine is None:
                            mine = self.getpixels()
                        if not mine.isdisjoint(theirs):
                            continue
                        contact = [p for p in mine if (p[0] + dx, p[1] + dy) in theirs]
                        if not contact:
                            continue
                        touch[ia] = True
                        sides[ia * 2 + (0 if s == -1 else 1)] = True
                        group = self.cluster(p2, dx, dy) if p2.dynamic else None
                        point = self._contact_point(contact, -dx, -dy)
                        cn = self._contact_normal(p2, point, -dx, -dy, False)
                        self._solve(p2, group, point, cn[0], cn[1])
        self.touch = tuple(touch)
        self.sides = tuple(sides)
        if abs(self._xvel) < 1e-9: self._xvel = 0
        if abs(self._yvel) < 1e-9: self._yvel = 0
        if abs(self._avel) < 1e-9: self._avel = 0

    def physics(self, axises=None):
        physics._running += 1
        try:
            self._physics(axises)
        finally:
            physics._running -= 1

    def _physics(self, axises=None):
        axises = self._axises if axises is None else axises
        actualmass = self.mass
        gravity = self.gravity
        drag = self.drag
        precision = self.precision
        self._dirty('x')

        for ia, a in enumerate(axises):
            self[a + 'vel'] *= drag
            self[a + 'vel'] += gravity[ia] * actualmass
            c = 1 if self[a + 'vel'] > 0 else -1 if self[a + 'vel'] < 0 else 0
            ch = abs(self[a + 'vel']) / actualmass
            d = (c, 0) if ia == 0 else (0, c)

            while ch > 0:
                step = min(precision, ch)
                t = {a: self.t[a] + c * step}
                collisions = self.collides(self.scene.solids, full=True, **t)

                physical = []
                for obj2, intersection in list(collisions.items()):
                    obj2p = getattr(obj2, 'physics', None)
                    if obj2p is None:
                        continue
                    for cb in list(self._touch_callbacks):
                        cb(obj2, intersection)
                    if getattr(self.obj, 'physics', None) is not self:
                        return
                    for cb in list(obj2p._touch_callbacks):
                        cb(self.obj, intersection)
                    if getattr(self.obj, 'physics', None) is not self:
                        return
                    if getattr(obj2, 'physics', None) is not obj2p:
                        continue
                    if self.solid and not self.phantom and not obj2p.phantom and not self._ghosted(obj2, intersection):
                        physical.append((obj2, obj2p, intersection))

                if physical:
                    for obj2, obj2p, intersection in physical:
                        if getattr(obj2, 'physics', None) is not obj2p:
                            continue
                        group = self.cluster(obj2p, d[0], d[1]) if obj2p.dynamic else None
                        point = self._contact_point(intersection, -d[0], -d[1])
                        cn = self._contact_normal(obj2p, point, -d[0], -d[1], True)
                        self._solve(obj2p, group, point, cn[0], cn[1])
                    break

                self.t[a] += c * step
                ch -= step

        self._depenetrate()

        self.avel *= self.adrag
        degrees = self.avel / actualmass
        if degrees:
            pieces = max(1, int(math.ceil(abs(degrees) / self._rprecision)))
            da = degrees / pieces
            check = self.solid and not self.phantom and not self.hitbox
            for _ in range(pieces):
                self.t.rotation += da
                hit = self.overlaps() if check else None
                if not hit:
                    continue
                contacts = []
                for obj2, intersection in hit.items():
                    mtv = self._mtv(obj2.physics.getpixels())
                    if mtv is None:
                        continue
                    contacts.append((obj2.physics, self._contact_point(intersection, mtv[1], mtv[2]), mtv[1], mtv[2]))
                self.t.rotation -= da
                applied = False
                for obj2p, point, nx, ny in contacts:
                    group = [obj2p] if obj2p.dynamic else None
                    if self._solve(obj2p, group, point, nx, ny):
                        applied = True
                if applied:
                    break
                if contacts:
                    self.avel = 0
                    break
                self.t.rotation += da

        self._depenetrate()
        self._probe()

class pen():
    _owned = ['penchar', 'penx', 'peny', 'pradius', 'pshape']
    _required = [transform]
    _settings = ('char', 'x', 'y', 'radius', 'shape')
    _aliases = {'char': 'penchar', 'x': 'penx', 'y': 'peny', 'radius': 'pradius', 'shape': 'pshape'}

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.scene = obj.scene
        self._x = kwargs.get('penx', 0)
        self._y = kwargs.get('peny', 0)
        self._px = self._x
        self._py = self._y
        self.char = kwargs.get('penchar', '█')
        self.pradius = kwargs.get('pradius', 1)
        self.pshape = kwargs.get('pshape', 'circle')
        self.active = False
        self.current_obj = None
        self._pixels = {}
        self._path = []
        self._hits = {}
        self._ox = 0
        self._oy = 0
        self._pcut = None
        self._cut_walls = {}

    @property
    def x(self):
        return self._x
    @x.setter
    def x(self, value):
        self._x = value

    @property
    def y(self):
        return self._y
    @y.setter
    def y(self, value):
        self._y = value

    @property
    def penchar(self):
        return self.char
    @penchar.setter
    def penchar(self, value):
        self.char = value

    @property
    def penx(self):
        return self._x
    @penx.setter
    def penx(self, value):
        self._x = value

    @property
    def peny(self):
        return self._y
    @peny.setter
    def peny(self, value):
        self._y = value

    @property
    def radius(self):
        return self._pradius
    @radius.setter
    def radius(self, value):
        self.pradius = value

    @property
    def shape(self):
        return self._pshape
    @shape.setter
    def shape(self, value):
        self.pshape = value

    @property
    def pradius(self):
        return self._pradius
    @pradius.setter
    def pradius(self, value):
        # same meaning as `r` in cut/cutcommit (1 = a single cell). Values below 1 are treated as 1.
        self._pradius = max(1, value)

    @property
    def pshape(self):
        return self._pshape
    @pshape.setter
    def pshape(self, value):
        if value not in _SHAPES:
            raise ValueError('shape must be one of: ' + ', '.join(_SHAPES))
        self._pshape = value

    def footprint(self, r=None, shape=None):
        return _footprint(self._pradius if r is None else r, self.scene.aspect, self._pshape if shape is None else shape)

    @property
    def char(self):
        return self._char
    @char.setter
    def char(self, value):
        self._char = value
        self._pchar = value

    def down(self, x=None, y=None, char=None, **kwargs):
        if self.active:
            return self.current_obj
        self.active = True
        self._pixels = {}
        if x is not None: self._x = x
        if y is not None: self._y = y
        self._ox = round(self._x)
        self._oy = round(self._y)
        self._px = self._ox
        self._py = self._oy
        self._pchar = char or self.char
        self._pixels = {}
        self._brush(0, 0)
        self._path = [(0, 0)]
        self._hits = {(0, 0): 1}
        for key, value in (('text', self._pchar), ('x', self._ox), ('y', self._oy)):
            kwargs.setdefault(key, value)
        self.current_obj = self.scene.obj().create(**kwargs)
        if self._pradius > 1:
            self._rebuild()
        return self.current_obj

    def trail(self):
        return [(self._ox + x, self._oy + y) for (x, y) in self._pixels]

    def commit(self, **kwargs):
        if self.current_obj is None or self.current_obj not in self.scene.objs:
            return None
        return self.current_obj.create(**kwargs)

    def up(self, **kwargs):
        finished = self.commit(**kwargs)
        self.active = False
        self.current_obj = None
        self._pixels = {}
        return finished

    def drop(self):
        if self.current_obj is not None and self.current_obj in self.scene.objs:
            self.current_obj.discard()
        self.active = False
        self.current_obj = None
        self._pixels = {}

    def move(self, x, y, rebuild=True):
        self._x = x
        self._y = y
        if self.active:
            self._plot(rebuild)

    def _plot(self, rebuild=True):
        nx = round(self._x)
        ny = round(self._y)
        for (ix, iy) in self._line(self._px, self._py, nx, ny):
            self._stamp(ix - self._ox, iy - self._oy)
        self._px = nx
        self._py = ny
        if rebuild:
            self._rebuild()

    def _stamp(self, x, y):
        path = self._path
        if path and path[-1] == (x, y):
            return
        path.append((x, y))
        self._brush(x, y)
        self._hits[(x, y)] = self._hits.get((x, y), 0) + 1
        if len(path) < 3 or self._pradius > 1:
            return
        ax, ay = path[-3]
        bx, by = path[-2]
        if abs(x - ax) == 1 and abs(y - ay) == 1 and (bx, by) in ((ax, y), (x, ay)) and self._hits[(bx, by)] == 1:
            del self._pixels[(bx, by)]
            del self._hits[(bx, by)]
            del path[-2]

    def _brush(self, x, y):
        for dx, dy in self.footprint():
            self._pixels[(x + dx, y + dy)] = self._pchar

    def _line(self, x0, y0, x1, y1):
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        points = []
        while True:
            points.append((x0, y0))
            if x0 == x1 and y0 == y1:
                return points
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def _rebuild(self):
        if not self._pixels or self.current_obj is None or self.current_obj not in self.scene.objs:
            return

        xs = [p[0] for p in self._pixels]
        ys = [p[1] for p in self._pixels]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        rows = []
        for row_y in range(max_y, min_y - 1, -1):
            row = ''
            for col_x in range(min_x, max_x + 1):
                row += self._pixels.get((col_x, row_y), ' ')
            rows.append(row)

        t = self.current_obj.transform
        t.x = self._ox + min_x
        t.y = self._oy + max_y
        t.text = '\n'.join(rows)

    def cut(self, wx, wy, r=0, when=True, shape=None):
        shape = self._pshape if shape is None else shape
        end = (round(wx), round(wy))
        start = self._pcut if self._pcut is not None else end
        self._pcut = end
        cut = False
        for o in list(self.scene.objs):
            if o is self.obj or not hasattr(o, 'transform') or not (when(o) if callable(when) else when):
                continue
            t = o.transform
            if r == 0:
                walls = t.cutline(start, end)
                if walls:
                    entry = self._cut_walls.setdefault(id(o), (o, set()))
                    if entry[1] is not None:
                        entry[1].update(walls)
                    cut = True
            else:
                for ix, iy in self._line(*start, *end):
                    if t.cut(ix, iy, r=r, shape=shape):
                        self._cut_walls.setdefault(id(o), (o, None))
                        cut = True
        return cut

    def cutcommit(self, r=0, callback=None, diagonal=True, keep=False, **kwargs):
        cut_objs = []
        for o, wall_pixels in list(self._cut_walls.values()):
            if o not in self.scene.objs:
                continue
            o.create(**kwargs)
            if r == 0 and wall_pixels:
                o.transform.split_at(wall_pixels, callback=callback, diagonal=diagonal)
            else:
                o.transform.split(callback=callback, diagonal=diagonal)
            cut_objs.append(o)
        self._cut_walls = {}
        if not keep:
            self._pcut = None
        return cut_objs

    def cancel(self):
        self._pcut = None
        self._cut_walls = {}

_CONDITIONS = {
    'physical': lambda o, p: p is not None,
    'solid': lambda o, p: p is not None and bool(p.solid) and not p.phantom,
    'phantom': lambda o, p: p is not None and bool(p.phantom),
    'dynamic': lambda o, p: p is not None and bool(p.dynamic),
    'static': lambda o, p: p is not None and not p.dynamic,
}

def _condition(name):
    negate = name.startswith('!')
    check = _CONDITIONS.get(name[1:] if negate else name)
    if check is None:
        raise ValueError('unknown affect condition: ' + name)
    return lambda o: check(o, getattr(o, 'physics', None)) != negate

def _matches(rule, o):
    if rule is None:
        return True
    if isinstance(rule, str):
        return _condition(rule)(o)
    if hasattr(rule, 'transform'):
        return rule is o
    if callable(rule):
        return bool(rule(o))
    return any(_matches(r, o) for r in rule)

def _compile(rule):
    if rule is None:
        return None
    ids = set()
    checks = []
    def walk(r):
        if isinstance(r, str):
            checks.append(_condition(r))
        elif hasattr(r, 'transform'):
            ids.add(id(r))
        elif callable(r):
            checks.append(lambda o, r=r: bool(r(o)))
        else:
            for item in r:
                walk(item)
    walk(rule)
    return lambda o: id(o) in ids or any(c(o) for c in checks)

class force():
    _owned = ['affect', 'cap', 'force', 'position', 'radius', 'torque', 'shield']
    _required = [transform]
    _settings = ('affect', 'cap', 'strength', 'position', 'radius', 'torque', 'shield')
    _aliases = {'strength': 'force'}

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.t = obj.transform
        self.scene = obj.scene
        self.affect = kwargs.get('affect', None)
        self.cap = kwargs.get('cap', None)
        self.force = kwargs.get('force', 0)
        self.position = kwargs.get('position', None)
        self.radius = kwargs.get('radius', None)
        self.torque = kwargs.get('torque', True)
        self.shield = kwargs.get('shield', True)

    @property
    def strength(self):
        return self.force
    @strength.setter
    def strength(self, value):
        self.force = value

    @staticmethod
    def _resolve(value, o):
        if callable(value):
            return value(o) if _argslen(value) else value()
        return value

    @staticmethod
    def _center(o):
        return o.transform.extent()[:2]

    def targets(self):
        accept = _compile(self.affect)
        me = self.obj
        return [
            o for o in self.scene.objs
            if o is not me and hasattr(o, 'transform') and hasattr(o, 'physics') and o.physics.dynamic
            and (accept is None or accept(o))
        ]

    @staticmethod
    def _shadowed(cells, box, point, direction, reach, aspect):
        x, y = point
        step_x = direction[0] * 0.25 / aspect
        step_y = direction[1] * 0.25
        min_x, max_x, min_y, max_y = box
        for i in range(1, int(reach / 0.25) + 1):
            cell = (math.floor(x + step_x * i), math.ceil(y + step_y * i))
            if cell[0] < min_x or cell[0] > max_x or cell[1] < min_y or cell[1] > max_y:
                return False
            if cell in cells:
                return True
        return False

    def apply(self, x=None, y=None):
        affected = []
        A = self.scene.aspect
        for o in self.targets():
            p = o.physics
            cells = p.getpixels()
            if not cells:
                continue
            if self.position is None:
                px, py = self._center(self.obj)
            else:
                px, py = self._resolve(self.position, o)
            if x is not None: px = x
            if y is not None: py = y

            value = self._resolve(self.force, o)
            vector = isinstance(value, (tuple, list))
            if vector:
                fx, fy = value
                magnitude = math.hypot(fx * A, fy)
                if not magnitude:
                    continue
                travel = (fx * A / magnitude, fy / magnitude)
            elif not value:
                continue
            aimed = self.position is not None or x is not None or y is not None or self.radius is not None
            uniform = vector and not aimed

            faces = []
            for X, Y in cells:
                for nx, ny in _NEIGHBOURS4:
                    if (X + nx, Y + ny) in cells:
                        continue
                    ex = X + 0.5 + 0.5 * nx
                    ey = Y - 0.5 + 0.5 * ny
                    dx = (ex - px) * A
                    dy = ey - py
                    dist = math.hypot(dx, dy)
                    if self.radius is not None and dist > self.radius:
                        continue
                    if uniform or (vector and dist < 1e-9):
                        ux, uy = travel
                    elif dist < 1e-9:
                        continue
                    else:
                        ux, uy = dx / dist, dy / dist
                    cosine = -(nx * ux + ny * uy)
                    if cosine <= 1e-9:
                        continue
                    faces.append((ex, ey, dist, ux, uy, cosine * (1.0 if nx else A)))
            if vector and aimed and self.radius is None and faces:
                nearest = min(f[2] for f in faces)
                faces = [f for f in faces if f[2] <= nearest + 1e-9]

            xs = [c[0] for c in cells]
            ys = [c[1] for c in cells]
            box = (min(xs), max(xs), min(ys), max(ys))
            cx, cy, _ = p.body()
            weight_sum = jx_sum = jy_sum = torque_sum = 0.0
            for ex, ey, dist, ux, uy, weight in faces:
                if vector:
                    jx, jy = fx * A, fy
                else:
                    strength = value / (4 * math.pi * max(dist, 0.5))
                    if self.cap is not None:
                        strength = max(-self.cap, min(self.cap, strength))
                    jx, jy = strength * ux, strength * uy
                reach = 1e9 if uniform else dist - 0.5
                if self.shield and self._shadowed(cells, box, (ex, ey), (-ux, -uy), reach, A):
                    continue
                weight_sum += weight
                jx_sum += weight * jx
                jy_sum += weight * jy
                torque_sum += weight * ((ex - cx - 0.5) * A * jy - (ey - cy + 0.5) * jx)
            if weight_sum <= 0:
                continue

            p._impulse(jx_sum / weight_sum, jy_sum / weight_sum)
            if self.torque:
                p._spin(torque_sum / weight_sum)
            affected.append(o)
        return affected

def _wrap(angle):
    return (angle + 180) % 360 - 180

def _sequence(value):
    return value if isinstance(value, (list, tuple)) else tuple(value)

def _band(value, keep=0.0):
    if value == 'keep':
        low = high = keep
    elif isinstance(value, (int, float)):
        low = high = value
    else:
        values = [keep if v == 'keep' else v for v in value]
        low, high = min(values), max(values)
    if low < 0:
        raise ValueError('radius must not be negative')
    return low, high

def _arc(value):
    if value is None:
        return None
    values = list(value)
    low, high = min(values), max(values)
    if high - low >= 360:
        return None
    return (low + high) / 2, (high - low) / 2

def _check_radius(value):
    if value is None:
        return 0
    if not isinstance(value, (int, float)) and value != 'keep':
        value = _sequence(value)
    _band(value)
    return value

def _check_range(value):
    if value is None:
        return None
    value = _sequence(value)
    _arc(value)
    return value

_KINDS = ('ball', 'hinge', 'fixed', 'slider')

def _check_kind(value):
    if value not in _KINDS:
        raise ValueError('kind must be one of: ' + ', '.join(_KINDS))
    return value

def _check_rest(value):
    if value is None or value == 'keep' or isinstance(value, (int, float)):
        return value
    raise ValueError("rest must be None, 'keep' or an angle")

def _check_slide(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return (0.0, value) if value >= 0 else (value, 0.0)
    values = list(value)
    return (min(values), max(values))

def _check_elasticity(value):
    if value <= 0:
        raise ValueError('elasticity must be positive')
    return value

def _check_durability(value):
    if value < 0:
        raise ValueError('durability must not be negative')
    return value

_PARAMS = {
    'xoffset': (0, None),
    'yoffset': (0, None),
    'radius': (0, _check_radius),
    'range': (None, _check_range),
    'elasticity': (1, _check_elasticity),
    'durability': (0, _check_durability),
    'physical': (True, bool),
    'vel': (0, None),
    'collide': (False, bool),
    'kind': ('ball', _check_kind),
    'rest': (None, _check_rest),
    'axis': (0, None),
    'slide': (None, _check_slide),
    'pinx': (0, None),
    'piny': (0, None),
}
_GEOMETRY = frozenset(('xoffset', 'yoffset', 'pinx', 'piny', 'radius', 'range', 'physical', 'kind', 'rest', 'axis', 'slide'))
_POSE = frozenset(('xoffset', 'yoffset', 'pinx', 'piny', 'kind', 'axis'))
_SWEEPS = 4
_RELIEF = 1
_SPINPIECES = 4
_KEEP = object()

class _param():
    def __init__(self, name, check):
        self.name = name
        self.check = check

    def __get__(self, inst, owner=None):
        if inst is None:
            return self
        return inst._value(self.name)

    def __set__(self, inst, value):
        if self.check is not None:
            value = self.check(value)
        inst._store(self.name, value)

    def __delete__(self, inst):
        inst._clear(self.name)

def _withparams(cls):
    for name, (_, check) in _PARAMS.items():
        setattr(cls, name, _param(name, check))
    return cls

def _ghost_hold(owner, partner):
    refs = owner.__dict__.setdefault('_ghostrefs', {})
    entry = refs.get(id(partner))
    if entry is None:
        added = not any(g is partner for g in owner._ghosts)
        if added:
            owner._ghosts.append(partner)
        refs[id(partner)] = [1, added]
    else:
        entry[0] += 1

def _ghost_drop(owner, partner):
    refs = owner.__dict__.get('_ghostrefs')
    entry = refs.get(id(partner)) if refs else None
    if entry is None:
        return
    entry[0] -= 1
    if entry[0] > 0:
        return
    del refs[id(partner)]
    if entry[1]:
        owner._ghosts[:] = [g for g in owner._ghosts if g is not partner]

class _jointlist(collections.abc.MutableSequence):
    def __init__(self, owner):
        self._owner = owner

    def _items(self):
        owner = self._owner
        return [edge.other(owner).obj for edge in owner._edges.values()]

    def __len__(self):
        return len(self._owner._edges)

    def __iter__(self):
        return iter(self._items())

    def __contains__(self, item):
        return id(item) in self._owner._edges

    def __getitem__(self, index):
        return self._items()[index]

    def __setitem__(self, index, value):
        items = self._items()
        items[index] = value
        self._owner._assign(items)

    def __delitem__(self, index):
        items = self._items()
        del items[index]
        self._owner._assign(items)

    def __eq__(self, other):
        if isinstance(other, (list, tuple, _jointlist)):
            return self._items() == list(other)
        return NotImplemented

    __hash__ = None

    def __repr__(self):
        return repr(self._items())

    def __iadd__(self, items):
        self.extend(items)
        return self

    def insert(self, index, item):
        items = self._items()
        items.insert(index, item)
        self._owner._assign(items)

    def append(self, item):
        self._owner._assign(self._items() + [item])

    def extend(self, items):
        self._owner._assign(self._items() + list(items))

    def remove(self, item):
        self._owner.remove(item)

    def pop(self, index=-1):
        item = self._items()[index]
        self._owner.remove(item)
        return item

    def clear(self):
        self._owner._assign(())

class _edge():
    def __init__(self, origin, follower):
        self.origin = origin
        self.follower = follower
        self.alive = True
        self.held = False
        self.engaged = False
        self.pose = None
        self._collide = None

    def other(self, comp):
        return self.follower if comp is self.origin else self.origin

    @property
    def collide(self):
        return self._collide

    @collide.setter
    def collide(self, value):
        self._collide = None if value is None else bool(value)
        self.rewire()

    @property
    def colliding(self):
        return self.follower.collide if self._collide is None else self._collide

    @property
    def physical(self):
        return self.follower.physical

    def anchor(self):
        return self.origin._anchor(self.follower.xoffset, self.follower.yoffset)

    def pin(self):
        f = self.follower
        if not (f.pinx or f.piny):
            return f.t.extent()[:2]
        return f._anchor(f.pinx, f.piny)

    @property
    def pinned(self):
        return bool(self.follower.pinx or self.follower.piny)

    def rewire(self):
        want = self.alive and not self.colliding
        if want == self.held:
            return
        self.held = want
        a, b = self.origin.obj, self.follower.obj
        if want:
            _ghost_hold(a, b)
            _ghost_hold(b, a)
        else:
            _ghost_drop(a, b)
            _ghost_drop(b, a)

    def _geometry(self):
        f = self.follower
        A = f.scene.aspect
        ax, ay = self.anchor()
        cx, cy = self.pin()
        dx = (cx - ax) * A
        dy = cy - ay
        return A, ax, ay, cx, cy, dx, dy, math.hypot(dx, dy)

    def capture(self):
        dx, dy, dist = self._geometry()[5:]
        rotation = self.origin.t.rotation
        rel = _wrap(math.degrees(math.atan2(dx, dy)) - rotation) if dist > 1e-9 else 0.0
        self.pose = (dist, rel, _wrap(self.follower.t.rotation - rotation))
        return self.pose

    def error(self, motor):
        f = self.follower
        pose = self.pose or self.capture()
        A, ax, ay, cx, cy, dx, dy, dist = self._geometry()
        rotation = self.origin.t.rotation
        kind = f.kind
        if kind == 'slider':
            heading = math.radians(rotation + f.axis)
            ux, uy = math.sin(heading), math.cos(heading)
            target = dx * ux + dy * uy + (f.vel if motor else 0)
            slide = f.slide
            if slide is not None:
                target = min(max(target, slide[0]), slide[1])
            ex = ax + target * ux / A - cx
            ey = ay + target * uy - cy
            miss = math.hypot(ex * A, ey)
            return (0.0, 0.0, 0.0) if miss < 1e-9 else (ex, ey, miss)
        if kind == 'fixed':
            heading = math.radians(rotation + pose[1])
            ex = ax + pose[0] * math.sin(heading) / A - cx
            ey = ay + pose[0] * math.cos(heading) - cy
            miss = math.hypot(ex * A, ey)
            return (0.0, 0.0, 0.0) if miss < 1e-9 else (ex, ey, miss)
        low, high = _band(f.radius, pose[0])
        arc = _arc(f.range)
        base = 0.0 if f.rest is None else pose[1] if f.rest == 'keep' else f.rest
        mid = arc[0] + base if arc else base
        if dist < 1e-9:
            rel = mid
        else:
            rel = _wrap(math.degrees(math.atan2(dx, dy)) - rotation)
        target_rel = rel + (f.vel if motor else 0)
        if arc is not None:
            off = _wrap(target_rel - mid)
            if abs(off) > arc[1]:
                target_rel = mid + math.copysign(arc[1], off)
        target_dist = min(max(dist, low), high)
        if abs(target_dist - dist) < 1e-9 and abs(_wrap(target_rel - rel)) < 1e-9:
            return 0.0, 0.0, dist
        heading = math.radians(rotation + target_rel)
        ex = ax + target_dist * math.sin(heading) / A - cx
        ey = ay + target_dist * math.cos(heading) - cy
        if math.hypot(ex * A, ey) < 1e-9:
            return 0.0, 0.0, dist
        return ex, ey, dist

    def beyond(self):
        f = self.follower
        pose = self.pose or self.capture()
        A, ax, ay, cx, cy, dx, dy, dist = self._geometry()
        rotation = self.origin.t.rotation
        if f.kind == 'slider':
            if f.slide is None:
                return False
            heading = math.radians(rotation + f.axis)
            s = dx * math.sin(heading) + dy * math.cos(heading)
            return s < f.slide[0] - 1e-6 or s > f.slide[1] + 1e-6
        arc = _arc(f.range)
        if arc is None or f.kind == 'fixed' or dist < 1e-9:
            return False
        base = 0.0 if f.rest is None else pose[1] if f.rest == 'keep' else f.rest
        rel = _wrap(math.degrees(math.atan2(dx, dy)) - rotation)
        return abs(_wrap(rel - arc[0] - base)) > arc[1] + 1e-6

    def spin(self):
        kind = self.follower.kind
        if kind == 'ball':
            return None
        pose = self.pose or self.capture()
        rotation = self.origin.t.rotation
        if kind == 'hinge':
            dx, dy, dist = self._geometry()[5:]
            rel = _wrap(math.degrees(math.atan2(dx, dy)) - rotation) if dist > 1e-9 else pose[1]
            return rotation + pose[2] + _wrap(rel - pose[1])
        return rotation + pose[2]

    def pull(self, ex, ey):
        o, f = self.origin, self.follower
        if o.movable and f.movable:
            total = o.mass + f.mass
            wc, wp = o.mass / total, f.mass / total
        elif f.movable:
            wc, wp = 1.0, 0.0
        elif o.movable:
            wc, wp = 0.0, 1.0
        else:
            return
        A = f.scene.aspect
        k = min(1.0, 1.0 / f.elasticity)
        damp = 1.0 - (1.0 - math.sqrt(k)) ** 2
        pinned = self.pinned and f.kind == 'ball'
        fkick = pinned
        okick = pinned or bool(f.xoffset or f.yoffset)
        fpoint = self.pin()
        opoint = self.anchor()
        fvx, fvy = f._pointvel(fpoint) if fkick else f.velocity
        ovx, ovy = o._pointvel(opoint) if okick else o.velocity
        rx, ry = fvx - ovx, fvy - ovy
        fx = fy = 0.0
        ux, uy = ex * A, ey
        n = math.hypot(ux, uy)
        full = f.kind in ('fixed', 'slider') or n <= 1e-9
        if not full:
            low, high = _band(f.radius, (self.pose or self.capture())[0])
            full = high <= 1e-9
        if full:
            fx = -rx * damp
            fy = -ry * damp
        else:
            along = (rx * A * ux + ry * uy) / n
            if along < 0 or f.kind != 'ball' or high - low <= 1e-9:
                fx = -along * ux / n / A * damp
                fy = -along * uy / n * damp
        for comp, point, w, kick in ((f, fpoint, wc, fkick), (o, opoint, -wp, okick)):
            p = getattr(comp.obj, 'physics', None)
            if p is not None and p.dynamic:
                if w:
                    gx = (ex * k + fx) * w
                    gy = (ey * k + fy) * w
                    if kick:
                        comp._kick(point, gx, gy)
                    else:
                        p.xvel += gx * p.mass
                        p.yvel += gy * p.mass
            else:
                comp._push(ex * w * k, ey * w * k)

@_withparams
class joint():
    _owned = ['joints', 'xoffset', 'yoffset', 'pinx', 'piny', 'jradius', 'range', 'elasticity',
              'durability', 'physical', 'vel', 'collide', 'kind', 'rest', 'axis', 'slide', 'preset']
    _required = [transform]
    _settings = ('preset', 'joints', 'xoffset', 'yoffset', 'pinx', 'piny', 'radius', 'range', 'elasticity',
                 'durability', 'physical', 'vel', 'collide', 'kind', 'rest', 'axis', 'slide')
    _aliases = {'radius': 'jradius'}
    _watch = frozenset(('x', 'y', 'rotation', 'text'))
    _active = False
    presets = {
        'ball': {'kind': 'ball'},
        'rod': {'kind': 'ball', 'radius': 'keep'},
        'rope': {'kind': 'ball', 'radius': (0, 'keep'), 'physical': False},
        'spring': {'kind': 'ball', 'radius': 'keep', 'elasticity': 8},
        'hinge': {'kind': 'hinge', 'radius': 'keep'},
        'fixed': {'kind': 'fixed'},
        'slider': {'kind': 'slider'},
        'neck': {'kind': 'hinge', 'radius': 'keep', 'rest': 'keep', 'range': (-45, 45)},
        'spine': {'kind': 'hinge', 'radius': 'keep', 'rest': 'keep', 'range': (-25, 25)},
        'shoulder': {'kind': 'hinge', 'radius': 'keep', 'rest': 'keep', 'range': (-170, 170)},
        'elbow': {'kind': 'hinge', 'radius': 'keep', 'rest': 'keep', 'range': (-150, 0)},
        'wrist': {'kind': 'hinge', 'radius': 'keep', 'rest': 'keep', 'range': (-70, 70)},
        'hip': {'kind': 'hinge', 'radius': 'keep', 'rest': 'keep', 'range': (-100, 100)},
        'knee': {'kind': 'hinge', 'radius': 'keep', 'rest': 'keep', 'range': (0, 140)},
        'ankle': {'kind': 'hinge', 'radius': 'keep', 'rest': 'keep', 'range': (-40, 40)},
    }

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.t = obj.transform
        self.scene = obj.scene
        self._params = {}
        self._edges = {}
        self._onbreak = []
        self._preset = None
        self._stamp = None
        self._spun = None
        self._joints = _jointlist(self)
        if kwargs.get('preset') is not None:
            self.apply(kwargs['preset'])
        for name in _PARAMS:
            key = 'jradius' if name == 'radius' else name
            if key in kwargs:
                setattr(self, name, kwargs[key])
        def change(attr):
            self._on_change(attr)
        self._pcb = change
        self.t.onchange(change)
        def sibling(other):
            theirs = getattr(other, 'joint', None)
            if theirs is None or theirs is self:
                return False
            for mine in self._edges.values():
                if mine.follower is not self or not mine.alive or mine.colliding:
                    continue
                shared = theirs._edges.get(id(mine.origin.obj))
                if shared is not None and shared.follower is theirs and shared.alive and not shared.colliding:
                    return True
            return False
        self._ghostcb = sibling
        obj._ghosts.append(sibling)
        self._assign(kwargs.get('joints', ()))

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def _value(self, name):
        if name in self._params:
            return self._params[name]
        return _PARAMS[name][0]

    def _store(self, name, value):
        self._params[name] = value
        self._sync({name})

    def _clear(self, name):
        if name in self._params:
            del self._params[name]
            self._sync({name})

    def _sync(self, names):
        edges = [e for e in self._edges.values() if e.follower is self]
        if 'collide' in names:
            for edge in edges:
                edge.rewire()
        if _POSE & names:
            for edge in edges:
                edge.capture()
        if _GEOMETRY & names:
            for edge in edges:
                self._realign(edge)

    @staticmethod
    def mirrored(spec):
        if isinstance(spec, str):
            spec = joint.presets[spec]
        spec = dict(spec)
        if spec.get('range') is not None:
            spec['range'] = tuple(-v for v in spec['range'])
        if spec.get('rest') not in (None, 'keep'):
            spec['rest'] = -spec['rest']
        if spec.get('axis'):
            spec['axis'] = -spec['axis']
        if spec.get('xoffset'):
            spec['xoffset'] = -spec['xoffset']
        return spec

    @property
    def preset(self):
        return self._preset

    @preset.setter
    def preset(self, value):
        self.apply(value)

    def apply(self, preset=None, **settings):
        spec = {}
        if preset is not None:
            if isinstance(preset, str):
                if preset not in joint.presets:
                    raise KeyError('unknown joint preset: ' + preset)
                spec.update(joint.presets[preset])
                self._preset = preset
            else:
                spec.update(preset)
                self._preset = None
        spec.update(settings)
        for key in spec:
            if key not in _PARAMS and key != 'jradius':
                raise KeyError('unknown joint setting: ' + str(key))
        for key, value in spec.items():
            setattr(self, 'radius' if key == 'jradius' else key, value)
        return self

    def attach(self, item, preset=None, link_collide=_KEEP, at=None, **settings):
        if getattr(item, 'transform', None) is None:
            try:
                items = list(item)
            except TypeError:
                raise TypeError('a jointed object needs a transform component') from None
            for each in items:
                if getattr(each, 'transform', None) is None:
                    raise TypeError('a jointed object needs a transform component')
                if each is self.obj:
                    raise ValueError('an object cannot be jointed to itself')
            return [self.attach(each, preset, link_collide, at, **settings) for each in items]
        if getattr(item, 'joint', None) is None:
            item.set(joint)
        item.joint.apply(preset, **settings)
        if at is not None:
            if id(item) not in self._edges:
                self._connect(item)
            self.anchor_at(item, at)
            item.joint._realign(self._edges[id(item)])
        elif id(item) not in self._edges:
            self._joints.append(item)
        if link_collide is not _KEEP:
            self._edges[id(item)].collide = link_collide
        return item.joint

    def _local(self, point):
        # world point -> (xoffset, yoffset) in this object's frame (inverse of _anchor)
        cx, cy = self.t.extent()[:2]
        A = self.scene.aspect
        r = math.radians(self.t.rotation)
        dx, dy = (point[0] - cx) * A, point[1] - cy
        return (dx * math.cos(r) - dy * math.sin(r)) / A, dx * math.sin(r) + dy * math.cos(r)

    def _connect(self, item):
        # link self -> item without moving anything (offsets are expected to be set afterwards)
        edge = _edge(self, item.joint)
        self._edges[id(item)] = edge
        item.joint._edges[id(self.obj)] = edge
        edge.rewire()
        return edge

    def anchor_at(self, item, point):
        # join self and item at one world point: the anchor sits on self and the pin on item,
        # so the pair meets at that point (e.g. the edge of two sticks) instead of at item's centre
        edge = self._edges.get(id(item))
        if edge is None or edge.origin is not self:
            raise KeyError('object is not a follower of this joint')
        f = edge.follower
        f._params['xoffset'], f._params['yoffset'] = self._local(point)
        f._params['pinx'], f._params['piny'] = f._local(point)
        edge.capture()
        return edge

    def group(self):
        # every object connected to this one through joints (this one included)
        seen = {id(self.obj): self.obj}
        queue = [self]
        for comp in queue:
            for edge in list(comp._edges.values()):
                if not edge.alive:
                    continue
                other = edge.other(comp)
                if id(other.obj) not in seen:
                    seen[id(other.obj)] = other.obj
                    queue.append(other)
        return list(seen.values())

    def teleport(self, dx, dy, stop=True):
        # move the whole connected group rigidly. Moving members one by one lets the joints see
        # a huge stretch (the first member is already there, the others are not) and fling them.
        members = self.group()
        joint._active = True
        try:
            for o in members:
                t = o.transform
                t.x += dx
                t.y += dy
                p = getattr(o, 'physics', None)
                if stop and p is not None:
                    p.xvel = p.yvel = p.avel = 0
        finally:
            joint._active = False
        return members

    @staticmethod
    def transfer(old, parts):
        # `old` is being split into `parts` (and then discarded): hand each of its joints to the
        # part that holds the joint point, so that part stays joined to the same partner.
        jt = getattr(old, 'joint', None)
        if jt is None or not jt._edges:
            return
        A = old.scene.aspect
        cells = []
        for part in parts:
            t = getattr(part, 'transform', None)
            cells.append(((wx + 0.5, wy - 0.5) for wx, wy in t.worldcells()) if t is not None else ())
        cells = [list(c) for c in cells]
        plan = []
        for edge in list(jt._edges.values()):
            if not edge.alive:
                continue
            as_origin = edge.origin is jt
            point = edge.anchor() if as_origin else edge.pin()
            best, bd = None, None
            for part, pts in zip(parts, cells):
                if not pts:
                    continue
                d = min(((px - point[0]) * A) ** 2 + (py - point[1]) ** 2 for px, py in pts)
                if bd is None or d < bd - 1e-9 or (abs(d - bd) <= 1e-9 and len(pts) > len(cells[parts.index(best)])):
                    best, bd = part, d
            if best is not None:
                plan.append((edge, as_origin, point, best))
        for edge, as_origin, point, part in plan:
            if getattr(part, 'joint', None) is None:
                part.set(joint)
            pj = part.joint
            if as_origin:
                f = edge.follower
                new = pj._connect(f.obj)
                f._params['xoffset'], f._params['yoffset'] = pj._local(point)
            else:
                o = edge.origin
                new = o._connect(part)
                pj._params.update(jt._params)
                pj._preset = jt._preset
                pj._onbreak = list(jt._onbreak)
                pj._params['pinx'], pj._params['piny'] = pj._local(point)
            new._collide = edge._collide
            new.rewire()
            new.capture()

    def link(self, item):
        edge = self._edges.get(id(item))
        if edge is None:
            raise KeyError('object is not jointed')
        return edge

    def repose(self, item=None):
        for edge in list(self._edges.values()):
            if item is None or edge.other(self).obj is item:
                edge.capture()
        return self

    @staticmethod
    def rope(scene, start=None, end=None, segments=10, char='o', anchor=None, tail=None, pin=None,
             preset='rope', selfcollide=False, anchoroffset=(0, 0), tailoffset=(0, 0), **kwargs):
        if segments < 1:
            raise ValueError('a rope needs at least one segment')
        def endpoint(item, offset):
            if getattr(item, 'joint', None) is None:
                item.set(joint)
            x, y = item.joint._anchor(*offset)
            return x - 0.5, y + 0.5
        if start is None:
            if anchor is None:
                raise ValueError('a rope needs a start point or an anchor')
            start = endpoint(anchor, anchoroffset)
        if end is None:
            if tail is None:
                raise ValueError('a rope needs an end point or a tail')
            end = endpoint(tail, tailoffset)
        chars = char if callable(char) else (lambda i: char)
        pin = anchor is None if pin is None else pin
        parts = []
        last = max(1, segments - 1)
        for i in range(segments):
            k = i / last if segments > 1 else 0
            x = start[0] + (end[0] - start[0]) * k
            y = start[1] + (end[1] - start[1]) * k
            seg = dict(kwargs)
            seg['dynamic'] = not (i == 0 and pin) and seg.get('dynamic', True)
            parts.append(scene.obj().create(chars(i), x, y, **seg))
        links = list(zip(parts, parts[1:]))
        if anchor is not None:
            links.insert(0, (anchor, parts[0]))
        if tail is not None:
            links.append((parts[-1], tail))
        for parent, child in links:
            if getattr(parent, 'joint', None) is None:
                parent.set(joint)
            ends = {}
            if parent is anchor and child is parts[0] and any(anchoroffset):
                ends = {'xoffset': anchoroffset[0], 'yoffset': anchoroffset[1]}
            elif child is tail and parent is parts[-1] and any(tailoffset):
                ends = {'pinx': tailoffset[0], 'piny': tailoffset[1]}
            parent.joint.attach(child, preset, **ends)
        if not selfcollide:
            for i, a in enumerate(parts):
                for b in parts[i + 2:]:
                    if not any(g is b for g in a._ghosts):
                        a._ghosts.append(b)
                    if not any(g is a for g in b._ghosts):
                        b._ghosts.append(a)
        return parts

    @property
    def jradius(self):
        return self.radius

    @jradius.setter
    def jradius(self, value):
        self.radius = value

    @property
    def joints(self):
        return self._joints

    @joints.setter
    def joints(self, value):
        self._assign(value)

    @property
    def movable(self):
        p = getattr(self.obj, 'physics', None)
        return p is None or p.dynamic

    @property
    def mass(self):
        p = getattr(self.obj, 'physics', None)
        return p.mass if p is not None and p.dynamic else 1.0

    @property
    def velocity(self):
        p = getattr(self.obj, 'physics', None)
        if p is None or not p.dynamic:
            return 0.0, 0.0
        return p.xvel / p.mass, p.yvel / p.mass

    def remove(self, item):
        edge = self._edges.get(id(item))
        if edge is None:
            raise ValueError('object is not jointed')
        self._unlink(edge)

    def anchor(self, other):
        edge = self._edges.get(id(other))
        if edge is None:
            raise KeyError('object is not jointed')
        return edge.anchor()

    def onbreak(self, cb):
        self._onbreak.append(cb)
        return cb

    def offbreak(self, cb):
        self._onbreak = [f for f in self._onbreak if f is not cb]

    def on_discard(self):
        self.t.offchange(self._pcb)
        self.obj._ghosts[:] = [g for g in self.obj._ghosts if g is not self._ghostcb]
        for edge in list(self._edges.values()):
            self._unlink(edge)

    def _hierarchy(self):
        up = []
        down = []
        for e in self._edges.values():
            if not e.alive or e.follower.kind == 'ball':
                continue
            if e.follower is self:
                up.append(e.origin.obj)
            else:
                down.append(e.follower.obj)
        return up, down

    def _accepted(self, spec):
        items = []
        seen = set()
        for item in spec:
            if item is self.obj:
                raise ValueError('an object cannot be jointed to itself')
            if getattr(item, 'transform', None) is None:
                raise TypeError('a jointed object needs a transform component')
            if id(item) not in seen:
                seen.add(id(item))
                items.append(item)
        return items

    def _assign(self, spec):
        items = self._accepted(spec)
        wanted = {id(item) for item in items}
        for edge in [e for e in self._edges.values() if id(e.other(self).obj) not in wanted]:
            self._unlink(edge)
        ordered = {}
        fresh = []
        for item in items:
            edge = self._edges.get(id(item))
            if edge is None:
                if getattr(item, 'joint', None) is None:
                    item.set(joint)
                edge = _edge(self, item.joint)
                item.joint._edges[id(self.obj)] = edge
                edge.capture()
                fresh.append(edge)
            ordered[id(item)] = edge
        self._edges = ordered
        for edge in fresh:
            edge.rewire()
        for edge in fresh:
            self._realign(edge)

    def _unlink(self, edge):
        edge.alive = False
        edge.rewire()
        for comp in (edge.origin, edge.follower):
            other = edge.other(comp)
            if comp._edges.get(id(other.obj)) is edge:
                del comp._edges[id(other.obj)]
        f = edge.follower
        p = getattr(f.obj, 'physics', None)
        if p is not None and f.kind != 'ball' and not any(e.follower is f for e in f._edges.values()):
            p.avel = 0
        f._spun = None

    def _break(self, edge):
        o, f = edge.origin, edge.follower
        self._unlink(edge)
        for comp, other in ((o, f.obj), (f, o.obj)):
            for cb in list(comp._onbreak):
                if _argslen(cb):
                    cb(other)
                else:
                    cb()

    def _anchor(self, xoffset, yoffset):
        cx, cy = self.t.extent()[:2]
        A = self.scene.aspect
        r = math.radians(self.t.rotation)
        u = xoffset * A
        v = yoffset
        return (cx + (u * math.cos(r) + v * math.sin(r)) / A,
                cy + (-u * math.sin(r) + v * math.cos(r)))

    def _move(self, dx, dy):
        o = self.obj
        t = o.transform
        p = getattr(o, 'physics', None)
        x, y = t.x, t.y
        if p is not None and p.dynamic and p.solid and not p.phantom:
            def depth(px, py):
                return sum(len(v) for v in p.overlaps(p.getpixels(px, py)).values())
            inside = depth(x, y)
            steps = min(200, max(1, int(math.ceil(max(abs(dx), abs(dy))))))
            sx, sy = dx / steps, dy / steps
            for _ in range(steps):
                moved = False
                if sx:
                    d = depth(x + sx, y)
                    if d == 0 or d < inside:
                        x += sx
                        inside = d
                        moved = True
                if sy:
                    d = depth(x, y + sy)
                    if d == 0 or d < inside:
                        y += sy
                        inside = d
                        moved = True
                if not moved:
                    break
        else:
            x, y = x + dx, y + dy
        if x != t.x:
            t.x = x
        if y != t.y:
            t.y = y

    def _push(self, dx, dy):
        p = getattr(self.obj, 'physics', None)
        if p is not None and p.dynamic:
            p.xvel += dx * p.mass
            p.yvel += dy * p.mass
        else:
            self._move(dx, dy)

    def _pointvel(self, point):
        p = getattr(self.obj, 'physics', None)
        if p is None or not p.dynamic:
            return 0.0, 0.0
        A = self.scene.aspect
        cx, cy, _ = p.body()
        rx, ry = (point[0] - cx - 0.5) * A, point[1] - cy + 0.5
        om = p._omega()
        return p.xvel / p.mass - om * ry / A, p.yvel / p.mass + om * rx

    def _kick(self, point, gx, gy):
        # change the velocity of `point` on this body by (gx, gy), spreading it between
        # linear and angular motion so the point itself moves by about that much
        p = self.obj.physics
        if p._invinertia():
            A = self.scene.aspect
            cx, cy, spread = p.body()
            rx, ry = (point[0] - cx - 0.5) * A, point[1] - cy + 0.5
            n = math.hypot(gx * A, gy)
            if n > 1e-12:
                cross = (rx * gy - ry * gx * A) / n
                s = 1.0 / (1.0 + cross * cross / spread)
                gx *= s
                gy *= s
                p._spin((rx * gy - ry * gx * A) * p.mass)
        p.xvel += gx * p.mass
        p.yvel += gy * p.mass

    def _absorb(self, ex, ey):
        p = getattr(self.obj, 'physics', None)
        if p is None or not p.dynamic:
            return
        A = self.scene.aspect
        ux, uy = ex * A, ey
        n = math.hypot(ux, uy)
        if n < 1e-9:
            return
        ux /= n
        uy /= n
        along = (p.xvel / p.mass * A) * ux + (p.yvel / p.mass) * uy
        if along < 0:
            p.xvel -= along * ux / A * p.mass
            p.yvel -= along * uy * p.mass

    def _order(self):
        depth = {id(self): 0}
        queue = [self]
        seen = set()
        result = []
        for comp in queue:
            for edge in list(comp._edges.values()):
                if edge.physical or edge in seen:
                    continue
                seen.add(edge)
                other = edge.other(comp)
                if id(other) not in depth:
                    depth[id(other)] = depth[id(comp)] + 1
                    queue.append(other)
                    result.append((edge, comp, other))
                elif depth[id(comp)] <= depth[id(other)]:
                    result.append((edge, comp, other))
                else:
                    result.append((edge, other, comp))
        return result

    def _orient(self, edge):
        angle = edge.spin()
        if angle is None:
            return False
        t = self.t
        p = getattr(self.obj, 'physics', None)
        solid = p is not None and p.dynamic and p.solid and not p.phantom and not p.hitbox
        turn = _wrap(angle - t.rotation)
        step = 0 if self._spun is None else _wrap(angle - self._spun)
        self._spun = angle
        if p is not None and p.dynamic:
            want = step * p.mass if edge.physical and abs(step) <= p.rprecision * _SPINPIECES else 0
            if p.avel != want:
                p.avel = want
        if abs(turn) < 1e-6:
            return False
        t.rotation = angle
        if solid and p.overlaps():
            physics._running += 1
            try:
                p._depenetrate()
            finally:
                physics._running -= 1
        return True

    def _fix(self, edge, near, far, motor, strict):
        ex, ey, dist = edge.error(motor)
        f = edge.follower
        if strict and f.durability and dist > f.durability:
            self._break(edge)
            return False
        moved = False
        if ex or ey:
            mover = far if far.movable else near
            if mover.movable:
                dx, dy = (ex, ey) if mover is f else (-ex, -ey)
                mover._absorb(dx, dy)
                mover._move(dx, dy)
                moved = True
        if f._orient(edge):
            moved = True
        return moved

    def _settle(self, motor=False, strict=True, stamp=None):
        if joint._active:
            return
        joint._active = True
        try:
            order = self._order()
            if stamp is not None:
                self._stamp = stamp
                for edge, near, far in order:
                    near._stamp = far._stamp = stamp
            for sweep in range(_SWEEPS):
                moved = False
                first = sweep == 0
                for edge, near, far in order:
                    if edge.alive and self._fix(edge, near, far, first and motor, strict and first):
                        moved = True
                if not moved:
                    break
        finally:
            joint._active = False

    def _realign(self, edge):
        if edge.alive and not edge.physical:
            edge.origin._settle(strict=False)

    def _on_change(self, attr):
        if joint._active or physics._running or not self._edges or attr not in self._watch:
            return
        self._settle()

    def step(self):
        if joint._active or not self._edges:
            return
        owned = [e for e in list(self._edges.values()) if e.origin is self]
        for edge in owned:
            if edge.alive and edge.physical:
                ex, ey, dist = edge.error(False)
                f = edge.follower
                if f.durability and dist > f.durability:
                    self._break(edge)
                else:
                    if ex or ey:
                        if edge.beyond():
                            self._fix(edge, self, f, False, False)
                        else:
                            edge.engaged = True
                            edge.pull(ex, ey)
                    elif edge.engaged:
                        edge.engaged = False
                        edge.pull(0.0, 0.0)
                    f._orient(edge)
        tick = self.scene._ticks
        if self._stamp != tick and any(e.alive and not e.physical for e in owned):
            self._settle(motor=True, stamp=tick)


class light():
    _owned = ['light']
    _required = [transform]
    _watch = frozenset(('x', 'y', 'rotation', 'text', 'rtext', 'htext', 'rotaspect'))
    _settings = ('color', 'alpha', 'radius', 'falloff', 'shadows', 'shadowalpha', 'selfshadow',
                 'cone', 'direction', 'offset', 'mix', 'affect', 'on', 'glow', 'length', 'focus')
    _stamps = {}

    def on_discard(self):
        self.scene.lights = [l for l in self.scene.lights if l is not self]

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.t = obj.transform
        self.scene = obj.scene
        self._version = 0
        self._sig = None
        self._occ = None
        self._boxes = []
        self._origin = (0.0, 0.0)
        self._heading = None
        self._normal = (0.0, 1.0)
        self._color = (255, 255, 255)
        self._alpha = 1.0
        self._radius = 15
        self._falloff = 1.0
        self._shadows = True
        self._shadowalpha = 1.0
        self._selfshadow = False
        self._cone = None
        self._direction = 0
        self._offset = (0, 0)
        self._mix = 0.35
        self._affect = None
        self._on = True
        self._glow = False
        self._length = 0.0
        self._focus = 0.0
        self._glowkey = None
        self._glowrows = []
        self._cfg = kwargs.get('light', True)
        self.light = self._cfg
        def cb(attr):
            if attr in self._watch:
                self._touch()
        self._cb = cb
        self.t.onchange(cb)
        self.scene.lights.append(self)

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def _touch(self):
        self._version += 1
        self._occ = None

    @property
    def light(self):
        return self._cfg
    @light.setter
    def light(self, value):
        self._cfg = value
        if isinstance(value, dict):
            for key, val in value.items():
                if key not in self._settings:
                    raise TypeError('unknown light setting: ' + str(key))
                setattr(self, key, val)

    @property
    def color(self):
        return self._color
    @color.setter
    def color(self, value):
        rgb = self.scene.styler.rgb(value)
        if rgb is None:
            raise ValueError('unknown light color: ' + str(value))
        self._color = rgb
        self._touch()

    @property
    def alpha(self):
        return self._alpha
    @alpha.setter
    def alpha(self, value):
        self._alpha = max(0.0, value)
        self._touch()

    @property
    def radius(self):
        return self._radius
    @radius.setter
    def radius(self, value):
        if value <= 0:
            raise ValueError('radius must be positive')
        self._radius = value
        self._touch()

    @property
    def falloff(self):
        return self._falloff
    @falloff.setter
    def falloff(self, value):
        if value <= 0:
            raise ValueError('falloff must be positive')
        self._falloff = value
        self._touch()

    @property
    def shadows(self):
        return self._shadows
    @shadows.setter
    def shadows(self, value):
        self._shadows = bool(value)
        self._touch()

    @property
    def shadowalpha(self):
        return self._shadowalpha
    @shadowalpha.setter
    def shadowalpha(self, value):
        self._shadowalpha = max(0.0, min(1.0, value))
        self._touch()

    @property
    def selfshadow(self):
        return self._selfshadow
    @selfshadow.setter
    def selfshadow(self, value):
        self._selfshadow = bool(value)
        self._touch()

    @property
    def cone(self):
        return self._cone
    @cone.setter
    def cone(self, value):
        if value is not None and not 0 < value < 360:
            raise ValueError('cone must be between 0 and 360 degrees or None')
        self._cone = value
        self._touch()

    @property
    def direction(self):
        return self._direction
    @direction.setter
    def direction(self, value):
        self._direction = value
        self._touch()

    @property
    def offset(self):
        return self._offset
    @offset.setter
    def offset(self, value):
        x, y = value
        self._offset = (x, y)
        self._touch()

    @property
    def mix(self):
        return self._mix
    @mix.setter
    def mix(self, value):
        self._mix = max(0.0, min(1.0, value))
        self._touch()

    @property
    def affect(self):
        return self._affect
    @affect.setter
    def affect(self, value):
        self._affect = value
        self._touch()

    @property
    def on(self):
        return self._on
    @on.setter
    def on(self, value):
        self._on = bool(value)
        self._touch()

    @property
    def glow(self):
        return self._glow
    @glow.setter
    def glow(self, value):
        self._glow = bool(value)
        self._touch()

    @property
    def length(self):
        return self._length
    @length.setter
    def length(self, value):
        if value < 0:
            raise ValueError('length must not be negative')
        self._length = float(value)
        self._touch()

    @property
    def focus(self):
        return self._focus
    @focus.setter
    def focus(self, value):
        self._focus = max(0.0, min(1.0, value))
        self._touch()

    def _affects(self, o):
        return _matches(self._affect, o)

    def origin(self):
        cx, cy = self.t.extent()[:2]
        A = self.scene.aspect
        r = math.radians(self.t.rotation)
        u = self._offset[0] * A
        v = self._offset[1]
        return (cx + (u * math.cos(r) + v * math.sin(r)) / A,
                cy + (-u * math.sin(r) + v * math.cos(r)))

    def _casters(self):
        ox, oy = self._origin
        span = self._radius + self._length / 2
        reach_x = span / self.scene.aspect + 2
        reach_y = span + 2
        found = []
        pool = list(self.scene.solids)
        listed = {id(o) for o in pool}
        pool.extend(o for o in self.scene.objs
                    if id(o) not in listed and getattr(getattr(o, 'transform', None), '_shadow', None) is not None)
        for o in pool:
            if o is self.obj:
                continue
            t = getattr(o, 'transform', None)
            if t is None:
                continue
            p = getattr(o, 'physics', None)
            if t._shadow is None and (p is None or p.phantom or not p.solid):
                continue
            if t._shadow is None or (t._shadow == 'physics' and p is not None):
                b = p.bounds()
            else:
                cells = t.cells()
                b = (min(c[0] for c in cells), max(c[0] for c in cells),
                     min(c[1] for c in cells), max(c[1] for c in cells)) if cells else None
            if b is None or b[1] < ox - reach_x or b[0] > ox + reach_x or b[3] < oy - reach_y or b[2] > oy + reach_y:
                continue
            found.append((o, t))
        return found

    def _prepare(self):
        self._origin = self.origin()
        occ = {}
        boxes = []
        if self._shadows:
            for o, t in self._casters():
                cells = t.cells()
                for pixel in cells:
                    occ[pixel] = id(o)
                if cells:
                    xs = [c[0] for c in cells]
                    ys = [c[1] for c in cells]
                    boxes.append((min(xs), max(xs), min(ys), max(ys)))
        self._occ = occ
        self._boxes = boxes

    def step(self):
        if not self._on:
            return
        self._origin = self.origin()
        sig = ()
        if self._shadows:
            sig = tuple((id(o), o.transform._x, o.transform._y, o.transform.vx, o.transform.vy,
                         o.transform._pvx, o.transform._pvy, hash(o.transform._text),
                         hash(o.transform._ptext), hash(o.transform._htext), o.transform._shadow,
                         getattr(getattr(o, 'physics', None), 'hitbox', None))
                        for o, t in self._casters())
        if sig != self._sig:
            self._sig = sig
            self._touch()

    def _shadowed(self, cx, cy, owner, origin=None):
        occ = self._occ
        if not occ:
            return False
        ox, oy = origin or self._origin
        dx = cx - ox
        dy = cy - oy
        for bx0, bx1, by0, by1 in self._boxes:
            lo = 0.0
            hi = 1.0
            if dx:
                a = (bx0 - ox) / dx
                b = (bx1 + 1 - ox) / dx
                if a > b:
                    a, b = b, a
                if a > lo:
                    lo = a
                if b < hi:
                    hi = b
            elif ox < bx0 or ox > bx1 + 1:
                continue
            if dy:
                a = (by0 - 1 - oy) / dy
                b = (by1 - oy) / dy
                if a > b:
                    a, b = b, a
                if a > lo:
                    lo = a
                if b < hi:
                    hi = b
            elif oy < by0 - 1 or oy > by1:
                continue
            if lo <= hi + 1e-9:
                break
        else:
            return False
        n = max(1, int(math.ceil(max(abs(cx - ox), abs(cy - oy)) * 2)))
        me = id(self.obj)
        for i in range(1, n):
            f = i / n
            who = occ.get((math.floor(ox + (cx - ox) * f), math.ceil(oy + (cy - oy) * f)))
            if who is not None and who != me and (self._selfshadow or who != owner):
                return True
        return False

    def _facing(self):
        angle = self.t.rotation + self._direction
        if angle != self._heading:
            self._heading = angle
            radians = math.radians(angle)
            self._normal = (math.sin(radians), math.cos(radians))
        return self._normal

    def _foot(self, dx, dy):
        if not self._length:
            return 0.0, 0.0
        nx, ny = self._facing()
        half = self._length / 2
        s = max(-half, min(half, dx * ny - dy * nx))
        return s * ny, -s * nx

    def _source(self, dx, dy, origin=None):
        if not self._length:
            return origin
        ox, oy = origin or self._origin
        qx, qy = self._foot(dx, dy)
        return (ox + qx / self.scene.aspect, oy + qy)

    def _level(self, dx, dy):
        qx, qy = self._foot(dx, dy)
        dx -= qx
        dy -= qy
        dist = math.hypot(dx, dy)
        if dist >= self._radius:
            return 0.0
        amount = self._alpha * (1 - dist / self._radius) ** self._falloff
        if dist > 0.5:
            if self._cone is not None:
                diff = abs(_wrap(math.degrees(math.atan2(dx, dy)) - (self.t.rotation + self._direction)))
                half = self._cone / 2
                if diff >= half:
                    return 0.0
                amount *= min(1.0, (half - diff) / (self._cone * 0.1))
            if self._focus:
                nx, ny = self._facing()
                amount *= 1 - self._focus + self._focus * max(0.0, (dx * nx + dy * ny) / dist)
        return max(amount, 0.0)

    def contribution(self, cx, cy, owner=None):
        if self._occ is None:
            self._prepare()
        ox, oy = self._origin
        dx = (cx - ox) * self.scene.aspect
        dy = cy - oy
        amount = self._level(dx, dy)
        if amount <= 0:
            return 0.0
        if self._shadows and self._shadowed(cx, cy, owner, self._source(dx, dy)):
            amount *= 1 - self._shadowalpha
        return amount

    def glowing(self):
        return self._glow and self._on

    def _stamp(self):
        aspect = self.scene.aspect
        angular = self._cone is not None or self._focus or self._length
        key = (self._radius, self._alpha, self._falloff, aspect, self._cone, self._length, self._focus,
               round((self.t.rotation + self._direction) % 360) if angular else 0)
        stamp = light._stamps.get(key)
        if stamp is None:
            if len(light._stamps) > 64:
                light._stamps.clear()
            span = self._radius + self._length / 2
            reach_x = int(span / aspect) + 1
            reach_y = int(span) + 1
            rows = []
            for j in range(-reach_y, reach_y + 1):
                amounts = [self._level(i * aspect, j) for i in range(-reach_x, reach_x + 1)]
                lit = [k for k, a in enumerate(amounts) if a > 0]
                if lit:
                    rows.append((j, lit[0] - reach_x, amounts[lit[0]:lit[-1] + 1]))
            stamp = light._stamps[key] = (key, rows, reach_x, reach_y)
        return stamp

    def _spot(self):
        if self._occ is None:
            self._prepare()
        return int(math.floor(self._origin[0])), int(math.ceil(self._origin[1]))

    def glowbox(self, camx, camy, xoff, yoff, view):
        gx, gy = self._spot()
        _, _, reach_x, reach_y = self._stamp()
        return (max(view[0], gx - reach_x - camx + xoff),
                max(view[1], camy - gy - reach_y - yoff),
                min(view[2], gx + reach_x - camx + xoff + 1),
                min(view[3], camy - gy + reach_y - yoff + 1))

    def glowkey(self, camx, camy, xoff, yoff, view):
        gx, gy = self._spot()
        return (gx, gy, self._stamp()[0], self._version if self._occ else 0,
                self._color, self._mix, camx, camy, xoff, yoff, view)

    def glowrows(self, camx, camy, xoff, yoff, view):
        key = self.glowkey(camx, camy, xoff, yoff, view)
        if key == self._glowkey:
            return self._glowrows
        gx, gy = self._spot()
        rows = self._stamp()[1]
        aspect = self.scene.aspect
        origin = (gx + 0.5, gy - 0.5)
        clear = 1 - self._shadowalpha
        out = []
        for j, i0, amounts in rows:
            y = camy - gy - j - yoff
            if y < view[1] or y >= view[3]:
                continue
            x = gx + i0 - camx + xoff
            lo = max(view[0] - x, 0)
            hi = min(view[2] - x, len(amounts))
            if lo >= hi:
                continue
            if lo or hi < len(amounts):
                amounts = amounts[lo:hi]
                x += lo
            if self._occ:
                cy = gy + j - 0.5
                base = gx + i0 + lo
                amounts = [a * clear if a and self._shadowed(base + k + 0.5, cy, None,
                                                             self._source((base + k + 0.5 - origin[0]) * aspect, j, origin))
                           else a
                           for k, a in enumerate(amounts)]
            out.append((y, x, amounts))
        self._glowkey = key
        self._glowrows = out
        return out

    @staticmethod
    def shade(scene, obj, text):
        lights = [l for l in scene.lights if l.on and l._affects(obj)]
        ambient = max(0.0, min(1.0, scene.ambient))
        if not lights and ambient >= 1:
            return text
        t = obj.transform
        pixels = t.parse_pixels(text)
        ox, oy = t._origin()
        fgdef = tuple(scene.fgcolor)
        bgdef = tuple(scene.bgcolor)
        owner = id(obj)
        shaded = {}
        changed = False
        for (ci, ri), (char, style) in pixels.items():
            hasbg = bool(style) and t._has_background(style)
            if char == ' ' and not hasbg:
                shaded[(ci, ri)] = (char, style)
                continue
            total = 0.0
            mixsum = 0.0
            red = green = blue = 0.0
            for l in lights:
                c = l.contribution(ox + ci + 0.5, oy - ri - 0.5, owner)
                if c > 0:
                    total += c
                    mixsum += c * l._mix
                    red += c * l._color[0]
                    green += c * l._color[1]
                    blue += c * l._color[2]
            level = min(1.0, ambient + total)
            if level >= 1.0 and total <= 0:
                shaded[(ci, ri)] = (char, style)
                continue
            if total > 0:
                tint = (red / total, green / total, blue / total)
                amount = (mixsum / total) * min(1.0, total)
            else:
                tint = None
                amount = 0.0

            def blend(base):
                out = [bgdef[k] + (base[k] - bgdef[k]) * level for k in range(3)]
                if tint is not None:
                    out = [out[k] + (tint[k] - out[k]) * amount for k in range(3)]
                return tuple(max(0, min(255, int(round(v)))) for v in out)

            fgm = _FGCODE.search(style)
            fg = tuple(int(g) for g in fgm.groups()) if fgm else fgdef
            newstyle = _BGCODE.sub('', _FGCODE.sub('', style))
            bgm = _BGCODE.search(style)
            if bgm:
                newstyle += '\033[48;2;%d;%d;%dm' % blend(tuple(int(g) for g in bgm.groups()))
            if char != ' ':
                newstyle += '\033[38;2;%d;%d;%dm' % blend(fg)
            elif fgm:
                newstyle += fgm.group(0)
            shaded[(ci, ri)] = (char, newstyle)
            changed = True
        if not changed:
            return text
        xs = [p[0] for p in shaded]
        ys = [p[1] for p in shaded]
        return t.build_rows(shaded, min(xs), max(xs), min(ys), max(ys))
