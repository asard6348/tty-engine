#_owned - list of owned variables which will be inspected upon obj().create()
#_required - list of required components to be included upon obj().create()
#_default - bool of the component auto-inclusion upon obj().create()
#def on_discard() - function that will be called upon obj().discard()

#MODULES
import math, re, sys, statistics, inspect

#GLOBAL
_RESET_FG = '\033[22;23;24;39m'
_NEIGHBOURS4 = ((-1, 0), (1, 0), (0, -1), (0, 1))
_NEIGHBOURS8 = _NEIGHBOURS4 + ((-1, -1), (1, -1), (-1, 1), (1, 1))
_NEIGHBOURS_HALF = ((1, 0), (0, 1), (1, 1), (-1, 1))
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
    ]
    _default = True

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
        self._anim = None
        self._onsplit = {}
        self._xlen_cache = None
        self._ylen_cache = None
        self._parse_pixels_key = None
        self._parse_pixels_val = None
        self._centroid_cache = {}
        self._bg_cache = {}
        self._rotmap = None
        self._rotcells = {}
        self._rotsrc = {}
        self._rotsize = (0, 0)
        self._rotorigin = (0, 0)
        self._onchangecb = {}
        self._changing = False
        self._vrtext = self._restyle(raw)
        self.rotate(self._rotation, init=True)

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
        old = getattr(self, '_' + key)
        setattr(self, '_' + key, value)
        self._style_cache = {}
        self._vrtext = self._restyle(self._vbase)
        self._vrotate()
        self._change(key, old)

    def _styled(self, style):
        cached = self._style_cache.get(style)
        if cached is None:
            sample = self.scene.styler.style(style + 'x', color=self._fg, alpha=self._alpha,
                                             bgcolor=self._bg, bgalpha=self._bgalpha, clean=True)
            cached = sample[:sample.index('x')]
            self._style_cache[style] = cached
        return cached

    def _restyle(self, base):
        if self._fg is None and self._bg is None and self._alpha is None and self._bgalpha is None:
            return base
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

        def layout(source):
            glyphs = [p for p, px in source.items() if px[0] != ' ']
            if not glyphs:
                return None
            count = len(glyphs)
            cx = sum(p[0] for p in glyphs) / count
            cy = sum(p[1] for p in glyphs) / count

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

        def render(source, lay, record=False, size=(0, 0)):
            glyphs, cx, cy, placed, extra, min_x, max_x, min_y, max_y = lay
            new_pixels = {}
            cells = {}
            sources = {}
            for group in (placed, extra):
                for cell, src in group.items():
                    new_pixels[cell] = source[src]
                    if record:
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
                self._rotcells = cells
                self._rotsrc = sources
                self._rotsize = size
                self._rotorigin = (min_x, min_y)
            return self.build_rows(new_pixels, min_x, max_x, min_y, max_y)

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

    def _vrotate(self):
        layout, render = self._rotator(self._rotation)
        self._vrender(layout, render, self._plain_layout)

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
        self._plain_layout = plain_layout
        self._vrender(layout, render, plain_layout)
        if plain_layout is not None:
            self._text = render(plain_source, plain_layout, True, (max(len(r) for r in crows), len(crows)))
        else:
            self._text = ''
            self._rotmap = None
            self._rotcells = {}
            self._rotsrc = {}
            self._rotsize = (0, 0)
            self._rotorigin = (0, 0)
        self._xlen_cache = None
        self._ylen_cache = None

        self.vx = self._rotorigin[0]
        self.vy = -self._rotorigin[1]

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
        self.rtext = self.build_rows(styled, min(xs), max(xs), min(ys), max(ys))
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

    def cut(self, wx, wy, r=1):
        cells = []
        for dy in range(-(r - 1), r):
            for dx in range(-(r - 1), r):
                cells.extend(self.world_to_rtext_all(wx + dx, wy + dy))
        return self._clear(cells)

    def cutpoints(self, points, r=1):
        cells = []
        for wx, wy in points:
            for dy in range(-(r - 1), r):
                for dx in range(-(r - 1), r):
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
        def do_split(spawns=spawns, anchors=anchors, obj_ref=obj_ref, cb=callback, motion=motion):
            parts = []
            for kw, target in zip(spawns, anchors):
                part = obj_ref.scene.obj().create(**kw)
                ft = part.transform
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

    def point(self, tx, ty, offset=0):
        dx = tx - self._x
        dy = ty - self._y
        ASPECT = self.scene.aspect
        angle = math.degrees(math.atan2(-dy, dx * ASPECT))+90
        return angle + offset

    def aim(self, obj, offset=0):
        return self.point(obj.transform.x, obj.transform.y, offset=offset)

    def alerp(self, angle):
        return (angle - self._rotation + 540) % 360 - 180

    @property
    def animating(self):
        return self._anim is not None

    def _frame(self, frame):
        p = getattr(self.obj, 'physics', None)
        keep = p.mass if p is not None and p.automass else None
        self.rtext = self.vhtext if frame is None else frame
        if keep is not None:
            p.mass = keep

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

    def tick(self):
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
    def on_discard(self):
        rect = self.rect()
        if rect:
            self.scene.dirtyrects.append(rect)
        self.scene.discards.append(self.remove(write=False))

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.t = obj.transform
        self.scene = obj.scene
        self._litkey = None
        self._lit = ''
        self.px = 0
        self.py = 0
        self.ptext = ''
        self.pxoff = 0
        self.pyoff = 0
        self._show = kwargs.get('show', True)
        self.renderspaces = kwargs.get('renderspaces', False)
        self.z = kwargs.get('z', 0)

    @property
    def show(self):
        return self._show

    @show.setter
    def show(self, value):
        self._show = value

    @property
    def z(self):
        return self._z

    @z.setter
    def z(self, value):
        self._z = value
        if self._z > self.scene._lastz: self.scene._lastz = self._z
        if self._z < self.scene._firstz: self.scene._firstz = self._z

    def redraw(self):
        self.ptext = ''

    def _shown(self):
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

    def _current(self):
        if not self._show:
            return (0, 0, '', 0, 0)
        ir = self.scene.iround
        return (
            ir(((self.t.x) + (self.t.vx)) - ir(self.scene.camx)),
            -ir(((self.t.y) + (self.t.vy)) - ir(self.scene.camy)),
            self._shown(),
            self.scene.dimxoffset,
            self.scene.dimyoffset,
        )

    def changed(self):
        return bool(self.t.rtext) and self._current() != (self.px, self.py, self.ptext, self.pxoff, self.pyoff)

    def _rect(self, x, y, text):
        if not text:
            return None
        rows = self.scene.recomp.sub('', text).split('\n')
        return (x, y, x + max(len(row) for row in rows), y + len(rows))

    def rect(self):
        return self._rect(self.px, self.py, self.ptext)

    def rects(self):
        current = self._current()
        return [r for r in (self.rect(), self._rect(current[0], current[1], current[2])) if r]

    def front(self):
        self.z = self.scene._lastz +1

    def back(self):
        self.z = self.scene._firstz -1

    def crop_row(self, row, start, end, renderspaces=False):
        bgcolor = (f'\033[48;2;{self.scene.bgcolor[0]};'
                   f'{self.scene.bgcolor[1]};'
                   f'{self.scene.bgcolor[2]}m')
        result = _RESET_FG
        ci = 0
        active_style  = ''
        needs_restyle = False
        in_crop       = False

        for part in self.scene.recomp.split(row):
            if not part:
                continue
            if self.scene.recomp.match(part):
                if part in ('\033[0m', '\033[m'):
                    active_style = ''
                    if in_crop and not needs_restyle:
                        result += part + bgcolor
                else:
                    active_style += part
                    if in_crop and not needs_restyle:
                        result += part
            else:
                for char in part:
                    if ci >= end:
                        if active_style:
                            result += _RESET_FG
                        return result
                    if ci >= start:
                        if not in_crop:
                            in_crop = True
                            if active_style:
                                result += active_style
                        if char == ' ' and not renderspaces:
                            result += '\033[C'
                            needs_restyle = bool(active_style)
                        else:
                            if needs_restyle:
                                result += active_style
                                needs_restyle = False
                            result += char
                    ci += 1

        if active_style:
            result += _RESET_FG
        return result

    def render_rows(self, text, ox, oy, xoff, yoff, erase=False, exclude_rects=None):
        bgcolor = (f'\033[48;2;{self.scene.bgcolor[0]};'
                   f'{self.scene.bgcolor[1]};'
                   f'{self.scene.bgcolor[2]}m')
        out  = ''
        term_w     = self.scene.termx
        term_h     = self.scene.termy
        sim_bottom = -yoff + self.scene.dimy
        sim_right  = xoff + self.scene.dimx
        for i, row in enumerate(text.split('\n')):
            scene_row = oy + 1 + i
            if not (1 <= scene_row <= self.scene.dimy):
                continue
            sy = -yoff + scene_row
            if not (1 <= sy <= min(term_h, sim_bottom)):
                continue
            crop_start = abs(min(0, ox))
            crop_end   = term_w - xoff - max(0, ox)
            if crop_end <= 0:
                continue
            sx = xoff + max(0, ox) + 1
            if sx < 1:
                extra = 1 - sx
                crop_start += extra
                crop_end   -= extra
                sx = 1
            if crop_end <= 0:
                continue
            crop_end = min(crop_end, term_w - (sx - 1))
            crop_end = min(crop_end, sim_right - sx + 1)
            if crop_end <= 0:
                continue

            if exclude_rects:
                segments = []
                seg_start = sx
                seg_crop  = crop_start
                seg_end   = sx + crop_end - 1
                excluded = sorted(
                    [(max(sx, r[0]), min(seg_end, r[2]))
                     for r in exclude_rects
                     if r[1] <= sy <= r[3] and r[0] <= seg_end and r[2] >= sx],
                    key=lambda r: r[0]
                )
                cursor = sx
                ccrop  = crop_start
                for ex1, ex2 in excluded:
                    if cursor < ex1:
                        segments.append((cursor, ccrop, ex1 - cursor))
                    skip = ex2 - cursor + 1
                    cursor = ex2 + 1
                    ccrop += skip
                if cursor <= seg_end:
                    segments.append((cursor, ccrop, seg_end - cursor + 1))
            else:
                segments = [(sx, crop_start, crop_end)]

            for seg_sx, seg_crop_start, seg_crop_end in segments:
                if seg_crop_end <= 0:
                    continue
                if erase:
                    clean   = self.scene.recomp.sub('', row)
                    visible = clean[seg_crop_start:seg_crop_start + seg_crop_end]
                    arow = ''.join(
                        '\033[C' if c == ' ' and not self.renderspaces else ' '
                        for c in visible
                    )
                    out += f'\033[{sy}d\033[{seg_sx}G{arow}'
                else:
                    arow = self.crop_row(row, seg_crop_start, seg_crop_start + seg_crop_end, self.renderspaces)
                    out += f'\033[{sy}d\033[{seg_sx}G{bgcolor}{arow}'
        return out

    def remove(self, write=True):
        if not self.ptext:
            return ''
        bgcolor = (f'\033[48;2;{self.scene.bgcolor[0]};'
                   f'{self.scene.bgcolor[1]};'
                   f'{self.scene.bgcolor[2]}m')
        xoff       = self.scene.dimxoffset
        yoff       = -self.scene.dimyoffset
        term_w     = self.scene.termx
        term_h     = self.scene.termy
        sim_bottom = -self.scene.dimyoffset + self.scene.dimy
        sim_right  = self.scene.dimxoffset + self.scene.dimx
        out = ''
        for i, row in enumerate(self.ptext.split('\n')):
            scene_row = self.py + 1 + i
            if not (1 <= scene_row <= self.scene.dimy):
                continue
            sy = yoff + scene_row
            if not (1 <= sy <= min(term_h, sim_bottom)):
                continue
            sx       = xoff + max(0, self.px) + 1
            max_width = min(
                term_w - (sx - 1),
                sim_right - sx + 1,
            )
            max_width = max(0, max_width)
            if not max_width:
                continue
            clean = self.scene.recomp.sub('', row)
            arow  = ' ' * min(len(clean), max_width)
            out  += f'\033[{sy}d\033[{sx}G{bgcolor}{arow}\033[0m'
        rem = out + '\033[0m'
        if write:
            sys.stdout.write(rem)
            sys.stdout.flush()
            self.ptext = ''
        return rem

    def render(self, write=True, split=False, exclude_rects=None):
        if not self.t.rtext:
            return ('', '') if split else ''
        bgcolor = (f'\033[48;2;{self.scene.bgcolor[0]};'
                   f'{self.scene.bgcolor[1]};{self.scene.bgcolor[2]}m')
        current = self._current()
        previous = (self.px, self.py, self.ptext, self.pxoff, self.pyoff)
        if current == previous:
            return ('', '') if split else ''
        acx, acy, actext, acxoff, acyoff = current
        px, py, ptext, pxoff, pyoff = previous

        remove_output = ''
        if ptext:
            remove_output = f'{bgcolor}{self.render_rows(ptext, px, py, pxoff, pyoff, erase=True, exclude_rects=exclude_rects)}\033[0m'
        draw_output = ''
        if actext:
            draw_output = f'{bgcolor}{self.render_rows(actext, acx, acy, acxoff, acyoff, erase=False, exclude_rects=exclude_rects)}\033[0m'

        self.px, self.py, self.ptext, self.pxoff, self.pyoff = current

        if write:
            sys.stdout.write(remove_output + draw_output)
            sys.stdout.flush()
        return (remove_output, draw_output) if split else remove_output + draw_output


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
                self.mass = sum(1 for c in self.t._rtext if c not in (' ', '\n'))
        if self.mass is None:
            masscal()
        self.t.onchange(masscal)
        self.solid = kwargs.get('solid', True)
        self.hitbox = kwargs.get('hitbox', False)
        self.phantom = kwargs.get('phantom', False)
        self.slope = kwargs.get('slope', True)
        self.touch = (False, False)
        self._touch_callbacks = []
        self._pixel_cache = None
        self._bounds_cache = None
        self._body_cache = None
        self.t.onchange(self._dirty)

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

    def _dirty(self):
        self._pixel_cache = None
        self._bounds_cache = None
        self._body_cache = None

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

    def getpixels(self, x=None, y=None, text=None):
        default_call = x is None and y is None and text is None
        if default_call and self._pixel_cache is not None:
            return self._pixel_cache

        x = self.t.x if x is None else x
        y = self.t.y if y is None else y
        text = self.t._text if text is None else text
        text = self.t._htext if self.hitbox else text
        rx = round(x + self.t.vx) if not self.hitbox else round(x)
        ry = round(y + self.t.vy) if not self.hitbox else round(y)
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
            pixels = self.getpixels()
            if self._bounds_cache is not None:
                return self._bounds_cache
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
            intersection = pixels1 & p2.getpixels()
            if intersection:
                result[obj2] = intersection
                if not self.phantom and not full:
                    break
        return result

    def overlaps(self, pixels=None):
        pixels = self.getpixels() if pixels is None else pixels
        b1 = self.bounds(pixels)
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
        shifted = self._shifted(dx, dy)
        for obj2 in self.scene.solids:
            if obj2 is self.obj or obj2 in exclude:
                continue
            p2 = getattr(obj2, 'physics', None)
            if p2 is None or p2.phantom or not p2.solid:
                continue
            b2 = p2.bounds()
            if b2 is None or b2[1] < b[0] + dx or b2[0] > b[1] + dx or b2[3] < b[2] + dy or b2[2] > b[3] + dy:
                continue
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
        n = len(pixels)
        mx = sum(p[0] for p in pixels) / n
        my = sum(p[1] for p in pixels) / n
        if nx is None:
            return (mx, my)
        cx, cy, _ = self.body()
        if ny:
            xs = [p[0] for p in pixels]
            return (max(min(xs) - 0.5, min(max(xs) + 0.5, cx)), my)
        ys = [p[1] for p in pixels]
        return (mx, max(min(ys) - 0.5, min(max(ys) + 0.5, cy)))

    def _gradient(self, pixels, center, sign):
        A = self.scene.aspect
        cx, cy = center
        sx = sy = 0.0
        for x in range(math.ceil(cx - 2.5), math.floor(cx + 2.5) + 1):
            for y in range(math.ceil(cy - 2.5), math.floor(cy + 2.5) + 1):
                if (x, y) in pixels:
                    sx += (x - cx) * A
                    sy += y - cy
        length = math.hypot(sx, sy)
        if length < 1e-9:
            return None
        return sign * sx / length, sign * sy / length

    def _contact_normal(self, other, point, nx, ny, inside):
        if not self.slope or not other.slope:
            return nx, ny
        shift = 0.5 if inside else -0.5
        cx, cy = point
        if abs(nx) > abs(ny):
            cx += shift * (1 if nx > 0 else -1)
        else:
            cy += shift * (1 if ny > 0 else -1)
        center = (round(cx * 2) / 2, round(cy * 2) / 2)
        go = self._gradient(other.getpixels(), center, -1)
        gs = self._gradient(self.getpixels(), center, 1)
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

    def _mtv(self, other_pixels):
        mine = self.getpixels()
        A = self.scene.aspect
        best = None
        for dx, dy, cost in ((1, 0, A), (-1, 0, A), (0, 1, 1.0), (0, -1, 1.0)):
            for k in range(1, 64):
                if not ({(p[0] + dx * k, p[1] + dy * k) for p in mine} & other_pixels):
                    score = k * cost - (0.01 if dy == 1 else 0)
                    if best is None or score < best[0]:
                        best = (score, dx, dy, k)
                    break
        return best

    def _depenetrate(self):
        for _ in range(12):
            found = self.overlaps()
            if not found:
                return
            obj2 = max(found, key=lambda o: len(found[o]))
            p2 = obj2.physics
            best = self._mtv(p2.getpixels())
            if best is None:
                return
            _, dx, dy, k = best
            if p2.dynamic:
                mine_share = int(min(k, max(1, math.ceil(k * p2.mass / (self.mass + p2.mass)))))
                theirs_share = k - mine_share
            else:
                mine_share, theirs_share = k, 0
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

    def _probe(self):
        touch = [False, False]
        if self.solid and not self.phantom:
            mine = self.getpixels()
            for ia in (0, 1):
                for s in (1, -1):
                    dx, dy = (s, 0) if ia == 0 else (0, s)
                    for obj2 in self._blocked(dx, dy):
                        p2 = obj2.physics
                        theirs = p2.getpixels()
                        if not mine.isdisjoint(theirs):
                            continue
                        contact = [p for p in mine if (p[0] + dx, p[1] + dy) in theirs]
                        if not contact:
                            continue
                        touch[ia] = True
                        group = self.cluster(p2, dx, dy) if p2.dynamic else None
                        point = self._contact_point(contact, -dx, -dy)
                        cn = self._contact_normal(p2, point, -dx, -dy, False)
                        self._solve(p2, group, point, cn[0], cn[1])
        self.touch = tuple(touch)
        if abs(self._xvel) < 1e-9: self._xvel = 0
        if abs(self._yvel) < 1e-9: self._yvel = 0
        if abs(self._avel) < 1e-9: self._avel = 0

    def physics(self, axises=None):
        axises = self._axises if axises is None else axises
        actualmass = self.mass
        gravity = self.gravity
        drag = self.drag
        precision = self.precision
        self._dirty()

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
                self.t.rotation += da

        self._depenetrate()
        self._probe()

class pen():
    _owned = ['penchar', 'penx', 'peny']
    _required = [transform]

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.scene = obj.scene
        self._x = kwargs.get('penx', 0)
        self._y = kwargs.get('peny', 0)
        self._px = self._x
        self._py = self._y
        self.char = kwargs.get('penchar', '█')
        self.active = False
        self.current_obj = None
        self._pixels = {}
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
        self._pixels[(0, 0)] = self._pchar
        for key, value in (('text', self._pchar), ('x', self._ox), ('y', self._oy)):
            kwargs.setdefault(key, value)
        self.current_obj = self.scene.obj().create(**kwargs)
        return self.current_obj

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

    def move(self, x, y):
        self._x = x
        self._y = y
        if self.active:
            self._plot()

    def _plot(self):
        nx = round(self._x)
        ny = round(self._y)
        for (ix, iy) in self._line(self._px, self._py, nx, ny):
            self._pixels[(ix - self._ox, iy - self._oy)] = self._pchar
        self._px = nx
        self._py = ny
        self._rebuild()

    def _line(self, x0, y0, x1, y1):
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        seen = set()
        points = []
        for i in range(steps + 1):
            t = i / steps
            p = (round(x0 + t * (x1 - x0)), round(y0 + t * (y1 - y0)))
            if p not in seen:
                seen.add(p)
                points.append(p)
        return points

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
        t.rtext = '\n'.join(rows)

    def cut(self, wx, wy, r=0, when=True):
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
                    if t.cut(ix, iy, r=r):
                        self._cut_walls.setdefault(id(o), (o, None))
                        cut = True
        return cut

    def cutcommit(self, r=0, callback=None, diagonal=True, **kwargs):
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
        self._pcut = None
        return cut_objs

    def cancel(self):
        self._pcut = None
        self._cut_walls = {}

class force():
    _owned = ['affect', 'cap', 'force', 'position', 'radius', 'torque', 'shield']
    _required = [transform]

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

    @staticmethod
    def _resolve(value, o):
        if callable(value):
            return value(o) if _argslen(value) else value()
        return value

    @staticmethod
    def _center(o):
        return o.transform.extent()[:2]

    def targets(self):
        affect = self.affect
        if affect is None:
            candidates = list(self.scene.objs)
        elif hasattr(affect, 'transform'):
            candidates = [affect]
        else:
            candidates = list(affect)
        alive = {id(o) for o in self.scene.objs}
        return [
            o for o in candidates
            if o is not self.obj and id(o) in alive
            and hasattr(o, 'transform') and hasattr(o, 'physics') and o.physics.dynamic
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

class _jointlist(list):
    def __init__(self, owner):
        super().__init__()
        self._owner = owner

    def append(self, item):
        if self._owner._accept(item):
            super().append(item)
            self._owner._attach(item)

    def extend(self, items):
        for item in list(items):
            self.append(item)

    def insert(self, index, item):
        if self._owner._accept(item):
            super().insert(index, item)
            self._owner._attach(item)

    def remove(self, item):
        super().remove(item)
        self._owner._detach(item)

    def pop(self, index=-1):
        item = super().pop(index)
        self._owner._detach(item)
        return item

    def clear(self):
        for item in list(self):
            self.remove(item)

    def __iadd__(self, items):
        self.extend(items)
        return self

    def __setitem__(self, index, value):
        items = list(self)
        items[index] = value
        self.clear()
        self.extend(items)

    def __delitem__(self, index):
        items = list(self)
        del items[index]
        self.clear()
        self.extend(items)

class joint():
    _owned = ['joints', 'xoffset', 'yoffset', 'jradius', 'range', 'elasticity',
              'durability', 'physical', 'ratio', 'vel', 'collide']
    _required = [transform]
    _watch = frozenset(('x', 'y', 'rotation', 'text', 'rtext', 'htext', 'rotaspect'))

    def on_discard(self):
        self._joints.clear()

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.t = obj.transform
        self.scene = obj.scene
        self._state = {}
        self._busy = False
        self._onbreak = []
        self._joints = _jointlist(self)
        def parent_cb(attr):
            self._on_parent(attr)
        self._pcb = parent_cb
        self.t.onchange(self._pcb)
        self.xoffset = kwargs.get('xoffset', 0)
        self.yoffset = kwargs.get('yoffset', 0)
        self.radius = kwargs.get('jradius', 0)
        self.range = kwargs.get('range', None)
        self.elasticity = kwargs.get('elasticity', 1)
        self.durability = kwargs.get('durability', 0)
        self.physical = kwargs.get('physical', False)
        self.ratio = kwargs.get('ratio', 0)
        self.vel = kwargs.get('vel', 0)
        self.collide = kwargs.get('collide', False)
        self._joints.extend(kwargs.get('joints', ()))

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    @property
    def joints(self):
        return self._joints
    @joints.setter
    def joints(self, value):
        items = list(value)
        self._joints.clear()
        self._joints.extend(items)

    @property
    def radius(self):
        return self._radius
    @radius.setter
    def radius(self, value):
        if value is None:
            value = 0
        if isinstance(value, (int, float)):
            band = (value, value)
        else:
            values = list(value)
            band = (min(values), max(values))
        if band[0] < 0:
            raise ValueError('radius must not be negative')
        self._radius = value
        self._band = band

    @property
    def jradius(self):
        return self.radius
    @jradius.setter
    def jradius(self, value):
        self.radius = value

    @property
    def range(self):
        return self._range
    @range.setter
    def range(self, value):
        if value is None:
            self._arc = None
        else:
            values = list(value)
            low, high = min(values), max(values)
            self._arc = None if high - low >= 360 else ((low + high) / 2, (high - low) / 2)
        self._range = value

    @property
    def elasticity(self):
        return self._elasticity
    @elasticity.setter
    def elasticity(self, value):
        if value <= 0:
            raise ValueError('elasticity must be positive')
        self._elasticity = value

    @property
    def durability(self):
        return self._durability
    @durability.setter
    def durability(self, value):
        if value < 0:
            raise ValueError('durability must not be negative')
        self._durability = value

    @property
    def ratio(self):
        return self._ratio
    @ratio.setter
    def ratio(self, value):
        self._ratio = max(0.0, min(1.0, value))

    def onbreak(self, cb):
        self._onbreak.append(cb)
        return cb

    def offbreak(self, cb):
        self._onbreak = [f for f in self._onbreak if f is not cb]

    def _accept(self, item):
        if item is self.obj:
            raise ValueError('an object cannot be jointed to itself')
        if getattr(item, 'transform', None) is None:
            raise TypeError('a joint target needs a transform component')
        return not any(j is item for j in self._joints)

    def _attach(self, item):
        cb = self._childcb(item)
        item.transform.onchange(cb)
        drop = self._dropcb(item)
        item.ondiscard(drop)
        added = []
        if not self.collide:
            for owner, partner in ((self.obj, item), (item, self.obj)):
                if not any(g is partner for g in owner._ghosts):
                    owner._ghosts.append(partner)
                    added.append((owner, partner))
        self._state[id(item)] = (cb, drop, added)
        if not self.physical and not self._busy:
            self._busy = True
            try:
                self._solve(item, False, False)
            finally:
                self._busy = False

    def _detach(self, item):
        state = self._state.pop(id(item), None)
        if state is None:
            return
        cb, drop, added = state
        transform_ = getattr(item, 'transform', None)
        if transform_ is not None:
            transform_.offchange(cb)
        item.offdiscard(drop)
        for owner, partner in added:
            owner._ghosts[:] = [g for g in owner._ghosts if g is not partner]

    def _childcb(self, item):
        def cb(attr):
            self._on_child(item, attr)
        return cb

    def _dropcb(self, item):
        def drop():
            if any(j is item for j in self._joints):
                self._joints.remove(item)
        return drop

    def _break(self, item):
        self._joints.remove(item)
        for cb in list(self._onbreak):
            if _argslen(cb):
                cb(item)
            else:
                cb()

    def _on_parent(self, attr):
        if self._busy or self.physical or attr not in self._watch:
            return
        self._busy = True
        try:
            for item in list(self._joints):
                self._solve(item, False)
        finally:
            self._busy = False

    def _on_child(self, item, attr):
        if self._busy or self.physical or attr not in self._watch:
            return
        self._busy = True
        try:
            self._solve(item, False)
        finally:
            self._busy = False

    def step(self):
        if self._busy:
            return
        self._busy = True
        try:
            for item in list(self._joints):
                self._solve(item, True)
        finally:
            self._busy = False

    def anchor(self):
        cx, cy = self.t.extent()[:2]
        A = self.scene.aspect
        r = math.radians(self.t.rotation)
        u = self.xoffset * A
        v = self.yoffset
        return (cx + (u * math.cos(r) + v * math.sin(r)) / A,
                cy + (-u * math.sin(r) + v * math.cos(r)))

    @staticmethod
    def _movable(o):
        p = getattr(o, 'physics', None)
        return p is None or p.dynamic

    def _solve(self, item, motor, strict=True):
        if getattr(item, 'transform', None) is None:
            return
        A = self.scene.aspect
        ax, ay = self.anchor()
        cx, cy = item.transform.extent()[:2]
        dx = (cx - ax) * A
        dy = cy - ay
        dist = math.hypot(dx, dy)
        if strict and self._durability and dist > self._durability:
            self._break(item)
            return

        low, high = self._band
        arc = self._arc
        if dist < 1e-9:
            rel = arc[0] if arc else 0.0
        else:
            rel = _wrap(math.degrees(math.atan2(dx, dy)) - self.t.rotation)
        target_rel = rel + (self.vel if motor else 0)
        if arc is not None:
            mid, half = arc
            off = _wrap(target_rel - mid)
            if abs(off) > half:
                target_rel = mid + math.copysign(half, off)
        target_dist = min(max(dist, low), high)
        if abs(target_dist - dist) < 1e-9 and abs(_wrap(target_rel - rel)) < 1e-9:
            return

        heading = math.radians(self.t.rotation + target_rel)
        ex = ax + target_dist * math.sin(heading) / A - cx
        ey = ay + target_dist * math.cos(heading) - cy
        if math.hypot(ex * A, ey) < 1e-9:
            return

        child_free = self._movable(item)
        parent_free = self._movable(self.obj)
        if child_free and parent_free:
            wc, wp = 1.0 - self._ratio, self._ratio
        elif child_free:
            wc, wp = 1.0, 0.0
        elif parent_free:
            wc, wp = 0.0, 1.0
        else:
            return

        if self.physical:
            k = 1.0 / self._elasticity
            self._push(item, ex * wc * k, ey * wc * k)
            self._push(self.obj, -ex * wp * k, -ey * wp * k)
            self._damp(item, ex, ey, wc, wp, k)
        else:
            if wc:
                self._absorb(item, ex, ey)
                self._move(item, ex * wc, ey * wc)
            if wp:
                self._absorb(self.obj, -ex, -ey)
                self._move(self.obj, -ex * wp, -ey * wp)

    def _move(self, o, dx, dy):
        t = o.transform
        p = getattr(o, 'physics', None)
        x, y = t.x, t.y
        if p is not None and p.dynamic and p.solid and not p.phantom and not p.overlaps():
            steps = min(200, max(1, int(math.ceil(max(abs(dx), abs(dy))))))
            sx, sy = dx / steps, dy / steps
            for _ in range(steps):
                moved = False
                if sx and not p.overlaps(p.getpixels(x + sx, y)):
                    x += sx
                    moved = True
                if sy and not p.overlaps(p.getpixels(x, y + sy)):
                    y += sy
                    moved = True
                if not moved:
                    break
        else:
            x, y = x + dx, y + dy
        if x != t.x:
            t.x = x
        if y != t.y:
            t.y = y

    def _push(self, o, dx, dy):
        p = getattr(o, 'physics', None)
        if p is not None and p.dynamic:
            p.xvel += dx * p.mass
            p.yvel += dy * p.mass
        else:
            self._move(o, dx, dy)

    def _absorb(self, o, ex, ey):
        p = getattr(o, 'physics', None)
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

    @staticmethod
    def _vel_of(o):
        p = getattr(o, 'physics', None)
        if p is None or not p.dynamic:
            return 0.0, 0.0
        return p.xvel / p.mass, p.yvel / p.mass

    def _damp(self, item, ex, ey, wc, wp, k):
        A = self.scene.aspect
        ux, uy = ex * A, ey
        n = math.hypot(ux, uy)
        if n < 1e-9:
            return
        ux /= n
        uy /= n
        cvx, cvy = self._vel_of(item)
        pvx, pvy = self._vel_of(self.obj)
        along = ((cvx - pvx) * A) * ux + (cvy - pvy) * uy
        if along >= 0:
            return
        fx = -along * ux / A * k
        fy = -along * uy * k
        for o, w in ((item, wc), (self.obj, -wp)):
            p = getattr(o, 'physics', None)
            if p is not None and p.dynamic and w:
                p.xvel += fx * w * p.mass
                p.yvel += fy * w * p.mass


class light():
    _owned = ['light']
    _required = [transform]
    _watch = frozenset(('x', 'y', 'rotation', 'text', 'rtext', 'htext', 'rotaspect'))
    _settings = ('color', 'alpha', 'radius', 'falloff', 'shadows', 'shadowalpha', 'selfshadow',
                 'cone', 'direction', 'offset', 'mix', 'affect', 'on')

    def on_discard(self):
        self.scene.lights = [l for l in self.scene.lights if l is not self]

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.t = obj.transform
        self.scene = obj.scene
        self._version = 0
        self._sig = None
        self._occ = None
        self._origin = (0.0, 0.0)
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

    def _affects(self, o):
        a = self._affect
        if a is None:
            return True
        if hasattr(a, 'transform'):
            return a is o
        return any(x is o for x in a)

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
        reach_x = self._radius / self.scene.aspect + 2
        reach_y = self._radius + 2
        found = []
        for o in self.scene.solids:
            if o is self.obj:
                continue
            p = getattr(o, 'physics', None)
            if p is None or p.phantom or not p.solid:
                continue
            b = p.bounds()
            if b is None or b[1] < ox - reach_x or b[0] > ox + reach_x or b[3] < oy - reach_y or b[2] > oy + reach_y:
                continue
            found.append((o, p))
        return found

    def _prepare(self):
        self._origin = self.origin()
        occ = {}
        if self._shadows:
            for o, p in self._casters():
                for pixel in p.getpixels():
                    occ[pixel] = id(o)
        self._occ = occ

    def step(self):
        if not self._on:
            return
        self._origin = self.origin()
        sig = ()
        if self._shadows:
            sig = tuple((id(o), o.transform._x, o.transform._y, o.transform.vx, o.transform.vy,
                         hash(o.transform._text), hash(o.transform._htext), p.hitbox)
                        for o, p in self._casters())
        if sig != self._sig:
            self._sig = sig
            self._touch()

    def _shadowed(self, cx, cy, owner):
        ox, oy = self._origin
        n = max(1, int(math.ceil(max(abs(cx - ox), abs(cy - oy)) * 2)))
        occ = self._occ
        me = id(self.obj)
        for i in range(1, n):
            f = i / n
            who = occ.get((math.floor(ox + (cx - ox) * f), math.ceil(oy + (cy - oy) * f)))
            if who is not None and who != me and (self._selfshadow or who != owner):
                return True
        return False

    def contribution(self, cx, cy, owner=None):
        if self._occ is None:
            self._prepare()
        ox, oy = self._origin
        A = self.scene.aspect
        dx = (cx - ox) * A
        dy = cy - oy
        dist = math.hypot(dx, dy)
        if dist >= self._radius:
            return 0.0
        amount = self._alpha * (1 - dist / self._radius) ** self._falloff
        if self._cone is not None and dist > 0.5:
            diff = abs(_wrap(math.degrees(math.atan2(dx, dy)) - (self.t.rotation + self._direction)))
            half = self._cone / 2
            if diff >= half:
                return 0.0
            amount *= min(1.0, (half - diff) / (self._cone * 0.1))
        if amount <= 0:
            return 0.0
        if self._shadows and self._shadowed(cx, cy, owner):
            amount *= 1 - self._shadowalpha
        return amount

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
