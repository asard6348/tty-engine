import math
from .shared import _RELIEF, _argslen, _closure_refs, _contact_normal_cells, _contact_point_cells, _mtv_cells, _offsets
from .inherit import _change_callback, _keyed, _lerpable
from .transform import transform

class physics(_change_callback, _lerpable, _keyed):
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
        'bouncethreshold',
    ]
    _required = [transform]
    _settings = ('xvel', 'yvel', 'avel', 'dynamic', 'bounciness', 'friction', 'mass', 'automass', 'solid',
                 'hitbox', 'phantom', 'gravity', 'drag', 'adrag', 'precision', 'rprecision', 'slope',
                 'bouncethreshold')
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
            self.mass = sum(1 for c in self.t._htext if c not in (' ', '\n'))
        self.t.onchange(masscal)
        self.solid = kwargs.get('solid', True)
        self.hitbox = kwargs.get('hitbox', False)
        self.phantom = kwargs.get('phantom', False)
        self.slope = kwargs.get('slope', True)
        self.bouncethreshold = kwargs.get('bouncethreshold', None)
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
                A = self.t.aspect
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
        A = self.t.aspect
        return self.xvel / self.mass * A, self.yvel / self.mass

    def _omega(self):
        return -math.radians(self.avel / self.mass)

    def _impulse(self, jx, jy, rx=0.0, ry=0.0):
        A = self.t.aspect
        self.xvel += jx / A
        self.yvel += jy
        if rx or ry:
            self._spin(rx * jy - ry * jx)

    def _spin(self, torque):
        inv = self._invinertia()
        if inv and torque:
            self.avel -= math.degrees(torque * inv) * self.mass

    def _arm(self, point):
        A = self.t.aspect
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
        if intersection:
            jt = getattr(self.obj, 'joint', None)
            if jt is not None and jt._seam(other, intersection):
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
        A = self.t.aspect
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
                vbx = sum(m.xvel / m.mass * m.t.aspect * m.mass for m in group) / total
                vby = sum(m.yvel for m in group) / total
                invib = 0.0
            e_other = max(m.bounciness for m in group)
            mu_other = max(m.friction for m in group)

        vn = (vax - vbx) * nx + (vay - vby) * ny
        if vn >= 0:
            return False

        e = max(self.bounciness, e_other) if restitution is None else restitution
        limits = [t for t in (self.bouncethreshold, other.bouncethreshold) if t is not None]
        if -vn < (min(limits) if limits else self.scene.bouncethreshold):
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
                vbx = sum(m.xvel * m.t.aspect / 1.0 for m in group) / total
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
                                     self.slope and other.slope, self.t.aspect)

    def normal(self, other, local=None):
        return self.t.normal(other, local)

    def _mtv(self, other_pixels):
        return _mtv_cells(self.getpixels(), other_pixels, self.t.aspect)

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
        for dx, dy in _offsets(6, self.t.aspect):
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
        if self.phantom or not self.solid:
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
                        if self._solve(p2, group, point, cn[0], cn[1]):
                            cells = {(p[0] + dx, p[1] + dy) for p in contact}
                            if self._notify(obj2, cells, True) == 0:
                                return
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

    def _notify(self, obj2, intersection, once=False):
        obj2p = getattr(obj2, 'physics', None)
        if obj2p is None:
            return 1
        if once and id(obj2) in self._touched:
            return 2
        self._touched.add(id(obj2))
        for cb in list(self._touch_callbacks):
            cb(obj2, intersection)
        if getattr(self.obj, 'physics', None) is not self:
            return 0
        for cb in list(obj2p._touch_callbacks):
            cb(self.obj, intersection)
        if getattr(self.obj, 'physics', None) is not self:
            return 0
        return 1 if getattr(obj2, 'physics', None) is not obj2p else 2

    def _physics(self, axises=None):
        axises = self._axises if axises is None else axises
        self._touched = set()
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
                    state = self._notify(obj2, intersection)
                    if state == 0:
                        return
                    if state == 1:
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
                before = self.t.rotation
                self.t.rotation = before + da
                hit = self.overlaps() if check else None
                if not hit:
                    continue
                for obj2, intersection in list(hit.items()):
                    if self._notify(obj2, intersection, True) == 0:
                        return
                contacts = []
                for obj2, intersection in hit.items():
                    if getattr(obj2, 'physics', None) is None:
                        continue
                    mtv = self._mtv(obj2.physics.getpixels())
                    if mtv is None:
                        continue
                    contacts.append((obj2.physics, self._contact_point(intersection, mtv[1], mtv[2]), mtv[1], mtv[2]))
                self.t.rotation = before
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
                self.t.rotation = before + da
            if not check:
                for obj2, intersection in list(self.collides(self.scene.solids, full=True).items()):
                    if self._notify(obj2, intersection, True) == 0:
                        return

        self._depenetrate()
        self._probe()
