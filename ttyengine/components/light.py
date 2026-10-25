import math
from .. import ansi
from .shared import _wrap, _ALPHAS, _BGCODE, _FGCODE, _rebake, _unbake
from .inherit import _keyed, _lerpable
from .transform import transform
from .force import _matches

class light(_lerpable, _keyed):
    _angles = frozenset(('direction',))
    _colors = frozenset(('color',))
    _owned = ['light']
    _required = [transform]
    _watch = frozenset(('x', 'y', 'rotation', 'text', 'rtext', 'htext', 'aspect'))
    _settings = ('color', 'alpha', 'radius', 'falloff', 'shadows', 'shadowalpha', 'selfshadow',
                 'cone', 'direction', 'offset', 'mix', 'affect', 'on', 'glow', 'length', 'focus', 'translucent')
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
        self._thin = {}
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
        self._translucent = True
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
    def translucent(self):
        return self._translucent
    @translucent.setter
    def translucent(self, value):
        self._translucent = bool(value)
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
        thin = {}
        boxes = []
        if self._shadows:
            for o, t in self._casters():
                cells = t.cells()
                ops = t.opacities() if self._translucent else None
                if ops:
                    ox, oy = t._origin()
                    for pixel in cells:
                        value = ops.get((pixel[0] - ox, oy - pixel[1]))
                        if value is None:
                            occ[pixel] = id(o)
                            thin.pop(pixel, None)
                        elif pixel in occ and pixel not in thin:
                            continue
                        else:
                            old = thin.get(pixel)
                            thin[pixel] = value if old is None else 1 - (1 - old) * (1 - value)
                            occ[pixel] = id(o)
                else:
                    for pixel in cells:
                        occ[pixel] = id(o)
                    if thin:
                        for pixel in cells:
                            thin.pop(pixel, None)
                if cells:
                    xs = [c[0] for c in cells]
                    ys = [c[1] for c in cells]
                    boxes.append((min(xs), max(xs), min(ys), max(ys)))
        self._occ = occ
        self._thin = thin
        self._boxes = boxes

    def step(self):
        if not self._on:
            return
        self._origin = self.origin()
        sig = ()
        if self._shadows:
            sig = tuple((id(o), o.transform._x, o.transform._y, o.transform.vx, o.transform.vy,
                         o.transform._pvx, o.transform._pvy, hash(o.transform._text),
                         hash(o.transform._ptext), hash(o.transform._htext), hash(o.transform.vtext),
                         o.transform._shadow,
                         getattr(getattr(o, 'physics', None), 'hitbox', None))
                        for o, t in self._casters())
        if sig != self._sig:
            self._sig = sig
            self._touch()

    def _shadowed(self, cx, cy, owner, origin=None):
        occ = self._occ
        if not occ:
            return 0.0
        ox, oy = origin or self._origin
        dx = cx - ox
        dy = cy - oy
        hit = False
        first = 1.0
        last = 0.0
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
                hit = True
                if lo < first:
                    first = lo
                if hi > last:
                    last = hi
        if not hit:
            return 0.0
        n = max(1, int(math.ceil(max(abs(cx - ox), abs(cy - oy)) * 2)))
        me = id(self.obj)
        thin = self._thin
        crossed = None
        for i in range(max(1, int(first * n) - 1), min(n, int(last * n) + 3)):
            f = i / n
            key = (math.floor(ox + (cx - ox) * f), math.ceil(oy + (cy - oy) * f))
            who = occ.get(key)
            if who is not None and who != me and (self._selfshadow or who != owner):
                opacity = thin.get(key)
                if opacity is None:
                    return 1.0
                if crossed is None:
                    crossed = {}
                if opacity > crossed.get(who, 0.0):
                    crossed[who] = opacity
        if crossed is None:
            return 0.0
        clear = 1.0
        for opacity in crossed.values():
            clear *= 1 - opacity
        return 1 - clear

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
        if self._shadows:
            blocked = self._shadowed(cx, cy, owner, self._source(dx, dy))
            if blocked:
                amount *= 1 - self._shadowalpha * blocked
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
                softened = []
                for k, a in enumerate(amounts):
                    if a:
                        blocked = self._shadowed(base + k + 0.5, cy, None,
                                                 self._source((base + k + 0.5 - origin[0]) * aspect, j, origin))
                        if blocked:
                            a *= 1 - self._shadowalpha * blocked
                    softened.append(a)
                amounts = softened
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

            fa, back, ba = _ALPHAS(style) if style else (None, False, None)
            fgm = _FGCODE.search(style)
            fg = tuple(int(g) for g in fgm.groups()) if fgm else fgdef
            newstyle = _BGCODE.sub('', _FGCODE.sub('', style))
            bgm = _BGCODE.search(style)
            bgold = bgnew = bgdef
            if bgm:
                bgold = tuple(int(g) for g in bgm.groups())
                if ba is not None:
                    bgnew = _rebake(bgdef, blend(_unbake(bgold, bgdef, ba)), ba)
                else:
                    bgnew = blend(bgold)
                newstyle += ansi.bg(*bgnew)
            if char != ' ':
                if fa is not None:
                    refold, refnew = (bgdef, bgdef) if back or not bgm else (bgold, bgnew)
                    fgnew = _rebake(refnew, blend(_unbake(fg, refold, fa)), fa)
                else:
                    fgnew = blend(fg)
                newstyle += ansi.fg(*fgnew)
            elif fgm:
                newstyle += fgm.group(0)
            shaded[(ci, ri)] = (char, newstyle)
            changed = True
        if not changed:
            return text
        xs = [p[0] for p in shaded]
        ys = [p[1] for p in shaded]
        return t.build_rows(shaded, min(xs), max(xs), min(ys), max(ys))
