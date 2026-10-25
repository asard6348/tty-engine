import math
from .. import ansi
from ..ascii_styler import alphamark
from .shared import _ALPHAS, _BGCODE, _NEIGHBOURS4, _NEIGHBOURS8, _NEIGHBOURS_HALF, _SGR, _argslen, _check_shadow, _contact_normal_cells, _contact_point_cells, _easing, _footprint, _mtv_cells, _styleprop
from .inherit import _change_callback, _keyed, _lerpable

class transform(_change_callback, _lerpable, _keyed):
    _angles = frozenset(('rotation',))
    _colors = frozenset(('fg', 'bg'))
    _owned = [
        'x', 'y',
        'vx', 'vy',
        'text', 'rtext', 'htext',
        'vtext', 'vrtext', 'vhtext',
        'rotation',
        'aspect',
        'fg', 'bg', 'alpha', 'bgalpha',
        'flip',
        'shadow',
    ]
    _default = True
    _settings = ('x', 'y', 'text', 'rtext', 'htext', 'rotation', 'aspect', 'fg', 'bg', 'alpha', 'bgalpha',
                 'flip', 'shadow')

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
        self._opacity_cache = None
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
        self._aspect = kwargs.get('aspect', None)
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
    def aspect(self):
        return self.scene.aspect if self._aspect is None else self._aspect
    @aspect.setter
    def aspect(self, value):
        old = self._aspect
        oldt = self._text
        self._aspect = value
        self._invalidate()
        self.rotate(self._rotation)
        self._change('aspect', old)
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
                    if part == ansi.RESET:
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
                        row += (ansi.RESET if prev_style else '') + style
                        prev_style = style
                    row += char
                else:
                    if prev_style:
                        row += ansi.RESET
                        prev_style = ''
                    row += ' '
            if prev_style:
                row += ansi.RESET
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
        ASPECT = self.aspect
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
            resample = not ident and len({px[1] for px in source.values() if px[0] != ' '}) > 1
            for group in (placed, extra):
                for cell, src in group.items():
                    chosen = source[src]
                    if resample:
                        rx = (cell[0] - cx) * ASPECT
                        ry = cell[1] - cy
                        near = source.get((floor((rx * ja + ry * jb) / ASPECT + cx + 0.5 + 1e-7),
                                           floor(rx * jc + ry * jd + cy + 0.5 + 1e-7)))
                        if near is not None and near[0] == chosen[0]:
                            chosen = near
                    new_pixels[cell] = chosen
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
        key = (angle_degrees, self._htext, self._flip, self.aspect)
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
        offsets = _footprint(r, self.aspect, shape)
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
            if self._aspect is not None:
                kw['aspect'] = self._aspect
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
                from .joint import joint
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

    def extent(self, local=False):
        rows = self._text.splitlines()
        cols = [i for row in rows for i, char in enumerate(row) if char != ' ']
        px, py = (0, 0) if local else (self._x + self.vx, self._y + self.vy)
        if not cols:
            return px, py, 0, 0
        lo, hi = min(cols), max(cols) + 1
        return (px + (lo + hi) / 2, py - len(rows) / 2,
                (hi - lo) / 2, len(rows) / 2)

    def center(self, local=False):
        return self.extent(local)[:2]

    def forward(self, move=1, offset=0, angle=None):
        angle = math.radians((self._rotation if angle is None else angle) + offset)
        x = math.sin(angle) * move
        y = math.cos(angle) * self.aspect * move
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
        ASPECT = self.aspect
        angle = math.degrees(math.atan2(-dy, dx * ASPECT))+90
        return angle + offset

    def aim(self, obj, offset=0):
        return self.point(*obj.transform.pivot(), offset=offset)

    def alerp(self, angle):
        return (angle - self._rotation + 540) % 360 - 180

    @staticmethod
    def _bearing(normal):
        if isinstance(normal, (tuple, list)):
            return math.degrees(math.atan2(normal[0], normal[1]))
        return normal

    def approaching(self, normal, angle=None):
        heading = self._rotation if angle is None else angle
        return math.cos(math.radians(heading - self._bearing(normal))) < 0

    def bounce(self, normal, angle=None, incoming_only=False):
        heading = self._rotation if angle is None else angle
        if incoming_only and not self.approaching(normal, heading):
            return heading
        return (2 * self._bearing(normal) - heading + 180) % 360

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

    def _lerpbase(self, key):
        if key in ('alpha', 'bgalpha'):
            return 1.0
        if key == 'fg':
            return tuple(self.scene.fgcolor)
        if key == 'bg':
            return tuple(self.scene.bgcolor)
        return None

    def _lerpkeep(self, key, value):
        if key in ('alpha', 'bgalpha') and value is not None:
            value = max(0.0, value)
            return None if value >= 1 else value
        return value

    def opacities(self):
        text = self.vtext
        cached = self._opacity_cache
        if cached is not None and cached[0] is text:
            return cached[1]
        found = {}
        if text and alphamark.search(text):
            recomp = self.scene.recomp
            for ri, row in enumerate(text.splitlines()):
                ci = 0
                active = ''
                for part in recomp.split(row):
                    if not part:
                        continue
                    if recomp.match(part):
                        active = '' if part in ansi.RESETS else active + part
                        continue
                    fa, _, ba = _ALPHAS(active)
                    if fa is not None or ba is not None:
                        own = _BGCODE.search(active) is not None
                        value = (1.0 if ba is None else ba) if own else (1.0 if fa is None else fa)
                        if value < 1.0:
                            for k, char in enumerate(part):
                                if own or char != ' ':
                                    found[(ci + k, ri)] = value
                    ci += len(part)
        self._opacity_cache = (text, found)
        return found
