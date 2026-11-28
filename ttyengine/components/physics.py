import math
import os
import re
from itertools import repeat
from .. import axes as _ax
from ..projection import spin
from .shared import _RELIEF, _argslen, _closure_refs, _contact_normal_cells, _contact_point_cells, _mtv_cells, _offsets, _spread
from .inherit import _change_callback, _keyed, _lerpable
from .transform import transform

try:
    from .. import _native as _nat_mod
except ImportError:
    _nat_mod = None
if os.environ.get('TTYENGINE_PURE'):
    _nat_mod = None

_APPLY = [False]
_NAT_LIMIT = 1e11
_CB = [0]

_RUN = re.compile(r'[^ ]+')
_SWEEP = 4.0
_NOISE = 2.0
_JUMP = 60.0
_JUMP_CELLS = 40


class _moved(set):
    dx = dy = 0


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
        slot = self._nslot
        if slot is not None:
            self._nslot = None
            sc = self.scene
            sc._nat_world.release(slot)
            sc._nat_slots.pop(slot, None)
            sc._nat_ids.pop(id(self.obj), None)
            sc._nat_dirty.discard(self)
            sc._nat_stale = True
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
        self._nd = None
        self._nslot = None
        self._nspans = None
        self._axises = ('x', 'y')
        self._xvel = kwargs.get('xvel', 0)
        self._yvel = kwargs.get('yvel', 0)
        self._ev = [kwargs.get(key + 'vel', 0) for key in obj.scene._axes.names[2:]]
        self._avel = kwargs.get('avel', 0)
        self.dynamic = kwargs.get('dynamic', True)
        self.bounciness = kwargs.get('bounciness', 0)
        self.friction = kwargs.get('friction', 0)
        gravity = kwargs.get('gravity', None)
        self._gravity = self._checkgravity(gravity)
        self._drag = kwargs.get('drag', None)
        self._adrag = kwargs.get('adrag', None)
        self._precision = kwargs.get('precision', None)
        self._rauto = kwargs.get('rprecision') is None
        self._rprecision = 3 if self._rauto else kwargs['rprecision']
        if (self._precision is not None and self._precision <= 0) or self._rprecision <= 0:
            raise ValueError('precision and rprecision must be positive')
        self.mass = kwargs.get('mass', None)
        self.automass = kwargs.get('automass', self.mass is None)
        if self.mass is None:
            self.mass = sum(1 for c in self.t._htext if c not in (' ', '\n'))
        self.solid = kwargs.get('solid', True)
        self.hitbox = kwargs.get('hitbox', False)
        self.phantom = kwargs.get('phantom', False)
        self.slope = kwargs.get('slope', True)
        self.bouncethreshold = kwargs.get('bouncethreshold', None)
        self.touch = (False, False)
        self.sides = (False, False, False, False)
        self._touch_callbacks = []
        self._pixel_cache = None
        self._slab_cache = None
        self._rows_cache = None
        self._pivot_cache = None
        self._bounds_cache = None
        self._body_cache = None
        self._stats = None
        self._ext_cache = None
        self._span_cache = None
        self._good = None
        self._depenskip = 0
        def dirty(attr):
            if self.automass and attr.endswith('text'):
                self.mass = sum(1 for c in self.t._htext if c not in (' ', '\n'))
            if attr not in _ax.FREE:
                self._dirty(attr)
        self.t.onchange(dirty)
        self._ncbs = (dirty,)
        self._nok = False
        sc = self.scene
        if _nat_mod is not None:
            if '_nat_world' not in sc.__dict__:
                sc._nat_world = _nat_mod.World()
                sc._nat_dirty = set()
                sc._nat_slots = {}
                sc._nat_ids = {}
                sc._nat_bodies = []
                sc._nat_live = False
                sc._nat_stale = True
            self._nd = sc._nat_dirty

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
        self._gravity = self._checkgravity(value)
        self._change('gravity', old)

    def _checkgravity(self, value):
        if value is None:
            return None
        value = tuple(value)
        if not 2 <= len(value) <= self.scene._axes.n:
            raise ValueError('gravity must be an (x, y) pair, with one more value per extra axis, or None')
        return value

    @property
    def vel(self):
        return (self._xvel, self._yvel) + tuple(self._ev)
    @vel.setter
    def vel(self, value):
        value = list(value)
        if not 2 <= len(value) <= self.scene._axes.n:
            raise ValueError('vel takes between 2 and %d values, got %d' % (self.scene._axes.n, len(value)))
        self.xvel = value[0]
        self.yvel = value[1]
        for key, val in zip(_ax.NAMES[2:], value[2:]):
            setattr(self, key + 'vel', val)

    def _fit(self, n):
        ev = self._ev
        if len(ev) < n - 2:
            ev.extend([0] * (n - 2 - len(ev)))
        else:
            del ev[n - 2:]

    def _drift(self, gravity, drag, mass):
        t = self.t
        names = _ax.NAMES
        for i, v in enumerate(self._ev):
            g = gravity[i + 2] if len(gravity) > i + 2 else 0
            if not v and not g:
                continue
            v = v * drag + g * mass
            if abs(v) < 1e-9:
                v = 0
            key = names[i + 2]
            setattr(self, key + 'vel', v)
            if v:
                if i + 2 in self.scene._solidaxes:
                    self._advance(i + 2, v)
                else:
                    t[key] += v / mass

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
        if value is not None and value <= 0:
            raise ValueError('rprecision must be positive or None')
        old = self._rprecision
        self._rauto = value is None
        self._rprecision = 3 if value is None else value
        self._change('rprecision', old)

    def _dirty(self, attr=None):
        self._pixel_cache = None
        self._rows_cache = None
        self._pivot_cache = None
        self._bounds_cache = None
        self._body_cache = None
        if attr != 'x' and attr != 'y':
            self._ext_cache = None
        self.scene._broad.stale.add(self.obj)
        nd = self._nd
        if nd is not None and not _APPLY[0]:
            nd.add(self)

    def _change(self, attr, old):
        nd = self._nd
        if nd is not None and not _APPLY[0]:
            nd.add(self)
        _change_callback._change(self, attr, old)

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

    def _pivot(self):
        shape = self.rowmask()
        cached = self._pivot_cache
        if cached is not None and cached[0] is shape:
            return cached[1]
        ox, rows = shape[0], shape[1]
        count = sx = sy = 0
        for y, mask in rows.items():
            c, offset, _ = _spread(mask)
            count += c
            sx += c * ox + offset
            sy += c * y
        found = None
        if count:
            cx = sx / count
            cy = sy / count
            A = self.t.aspect
            far = 0.0
            for y, mask in rows.items():
                lo = ox + (mask & -mask).bit_length() - 1
                hi = ox + mask.bit_length() - 1
                reach = math.hypot(max(abs(lo - cx), abs(hi - cx)) * A, y - cy)
                if reach > far:
                    far = reach
            found = (cx, cy, far, count)
        self._pivot_cache = (shape, found)
        return found

    def _turn_clear(self):
        pivot = self._pivot()
        if pivot is None:
            return False
        cx, cy, far = pivot[:3]
        A = self.t.aspect
        far += _SWEEP
        rx = int(far / A) + 1
        ry = int(far) + 1
        return not self.scene._broad.near(math.floor(cx) - rx, math.ceil(cx) + rx, math.floor(cy) - ry, math.ceil(cy) + ry, self.obj)

    def _turn_free(self, da, remaining):
        pivot = self._pivot()
        if pivot is None or pivot[3] < _JUMP_CELLS:
            return 0
        ox, rows = self.rowmask()[:2]
        arc = (pivot[2] + 1.0) * math.radians(abs(da))
        most = min(remaining, max(1, int(_JUMP / abs(da))))
        if most < 2:
            return 0
        A = self.t.aspect
        reach = arc * most + _NOISE
        rx = int(reach / A) + 1
        ry = int(reach) + 1
        ys = rows.keys()
        y0 = min(ys)
        y1 = max(ys)
        x0 = ox + min((m & -m).bit_length() - 1 for m in rows.values())
        x1 = ox + max(m.bit_length() - 1 for m in rows.values())
        obstacles = []
        for obj2 in self.scene._broad.near(x0 - rx, x1 + rx, y0 - ry, y1 + ry, self.obj):
            p2 = getattr(obj2, 'physics', None)
            if p2 is None or p2.phantom or not p2.solid:
                continue
            obstacles.append(p2.rowmask()[:2])
        if not obstacles:
            return most
        count = most
        while count >= 2:
            if self._clear_of(rows, ox, obstacles, arc * count + _NOISE, A, y0, y1):
                return count
            count //= 2
        return 0

    @staticmethod
    def _clear_of(rows, ox, obstacles, reach, A, y0, y1):
        rc = int(reach / A) + 1
        rr = int(reach) + 1
        base = min(ox, min(o[0] for o in obstacles)) - rc
        grown = {}
        for ox2, rows2 in obstacles:
            shift = ox2 - base
            for y, mask in rows2.items():
                if y < y0 - rr or y > y1 + rr:
                    continue
                mask <<= shift
                left = right = mask
                covered = 0
                while covered < rc:
                    step = min(covered + 1, rc - covered)
                    left |= left << step
                    right |= right >> step
                    covered += step
                grown[y] = grown.get(y, 0) | left | right
        if not grown:
            return True
        shift = ox - base
        for y, mask in rows.items():
            mask <<= shift
            for yo in range(y - rr, y + rr + 1):
                other = grown.get(yo)
                if other and mask & other:
                    return False
        return True

    def _turn_step(self):
        step = self._rprecision
        if not self._rauto:
            return step
        pivot = self._pivot()
        if pivot is None:
            return step
        far = pivot[2]
        if far < 0.5:
            return max(step, 90.0)
        return max(step, math.degrees(self.precision * self.t.aspect / far))

    def _lane(self, axis):
        ext = self._extent()
        if not ext:
            return None
        t = self.t
        if self.hitbox:
            ox = oy = 0
        else:
            ox, oy = t._pvx, t._pvy
        p = t._p
        if axis == 'x':
            base = p[0] + ox
            row = round(p[1] + oy)
            return base, ext[0], ext[1], row - ext[3], row - ext[2]
        base = p[1] + oy
        col = round(p[0] + ox)
        return base, -ext[3], -ext[2], col + ext[0], col + ext[1]

    def _sweep(self, axis, direction, distance):
        lane = self._lane(axis)
        if lane is None:
            return []
        base, lo_off, hi_off, cross_lo, cross_hi = lane
        end = base + direction * distance
        lo = min(round(base), round(end)) - 1
        hi = max(round(base), round(end)) + 1
        if axis == 'x':
            return self.scene._broad.near(lo + lo_off, hi + hi_off, cross_lo, cross_hi, self.obj)
        return self.scene._broad.near(cross_lo, cross_hi, lo + lo_off, hi + hi_off, self.obj)

    def _free(self, pool, axis, direction):
        if not pool:
            return math.inf
        lane = self._lane(axis)
        if lane is None:
            return math.inf
        base, lo_off, hi_off, cross_lo, cross_hi = lane
        here = round(base)
        low, high = here + lo_off, here + hi_off
        room = math.inf
        for obj2 in pool:
            p2 = getattr(obj2, 'physics', None)
            if p2 is None:
                continue
            b2 = p2.bounds()
            if b2 is None:
                continue
            if axis == 'x':
                m0, m1, c0, c1 = b2[0], b2[1], b2[2], b2[3]
            else:
                m0, m1, c0, c1 = b2[2], b2[3], b2[0], b2[1]
            if c1 < cross_lo or c0 > cross_hi:
                continue
            if m1 >= low and m0 <= high:
                return 0.0
            if direction > 0:
                if m1 < low:
                    continue
                reach = (m0 - hi_off) - 0.5 - base
            else:
                if m0 > high:
                    continue
                reach = base - ((m1 - lo_off) + 0.5)
            reach -= 1.0
            if reach < room:
                room = reach
        return room

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

    def unghost(self, other):
        pairs = [(self.obj, other)]
        if hasattr(other, '_ghosts'):
            pairs.append((other, self.obj))
        removed = False
        for owner, partner in pairs:
            held = owner.__dict__.get('_ghostrefs')
            if held and id(partner) in held:
                continue
            kept = [g for g in owner._ghosts if g is not partner]
            if len(kept) != len(owner._ghosts):
                owner._ghosts[:] = kept
                removed = True
        return removed

    def _spans(self, text, hitbox):
        cached = self._span_cache
        if cached is not None and cached[1] is text and cached[0] == hitbox:
            return cached[2]
        rows = []
        for i, row in enumerate(text.splitlines()):
            if hitbox:
                if row:
                    rows.append((i, ((0, len(row)),)))
            else:
                spans = tuple(m.span() for m in _RUN.finditer(row))
                if spans:
                    rows.append((i, spans))
        rows = tuple(rows)
        self._span_cache = (hitbox, text, rows)
        return rows

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
        for i, spans in self._spans(text, self.hitbox):
            y = ry - i
            for a, b in spans:
                if b - a > 4:
                    pixels.update(zip(range(rx + a, rx + b), repeat(y)))
                else:
                    for x in range(rx + a, rx + b):
                        pixels.add((x, y))

        if default_call:
            self._pixel_cache = pixels
            self._bounds_cache = None
        return pixels

    def rowmask(self):
        cached = self._rows_cache
        if cached is None:
            t = self.t
            if self.hitbox:
                text = t._htext
                ox = oy = 0
            else:
                text = t._ptext
                ox, oy = t._pvx, t._pvy
            rx = round(t.x + ox)
            ry = round(t.y + oy)
            rows = {}
            for i, spans in self._spans(text, self.hitbox):
                bits = 0
                for a, b in spans:
                    bits |= ((1 << (b - a)) - 1) << a
                rows[ry - i] = bits
            cached = self._rows_cache = (rx, rows, (rx, tuple(rows.items())))
        return cached

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

    def _slabs(self, dx=0, dy=0, mine=None):
        t = self.t
        p = t._p
        solid = self.scene._solidaxes
        base = tuple([p[i] for i in solid])
        held = t._sprite
        if t._turns and not self.hitbox:
            return self._spun(base, solid, round(p[0]) + dx, round(p[1]) + dy)
        if held is None or (self.hitbox and t._htext != t._rtext):
            if mine is None:
                mine = self._shifted(dx, dy) if dx or dy else self.getpixels()
            if held is None:
                return ((base, mine),)
            return tuple([(tuple([a + b for a, b in zip(base, at)]), mine) for at, _ in held.slabs(solid)]) or ((base, mine),)
        turned = t.rotation % 360 or t._flip is not None
        if turned and not self.hitbox:
            rx, ry = t._origin()
        else:
            rx, ry = round(p[0]), round(p[1])
        rx += dx
        ry += dy
        key = (rx, ry, solid, held, self.hitbox, t._rev if turned and not self.hitbox else 0)
        cache = self._slab_cache
        if cache is None or cache[0] != key:
            if turned and not self.hitbox:
                groups = {}
                for off, plane in t.planes():
                    at = tuple([off[i] if i < len(off) else 0 for i in solid])
                    groups.setdefault(at, set()).update((rx + c, ry - r) for (c, r), cell in plane.items() if cell[0] != ' ')
                found = tuple([(tuple([a + b for a, b in zip(base, at)]), cells) for at, cells in groups.items() if cells])
            elif self.hitbox:
                groups = {}
                for off, plane in held.planes:
                    at = tuple([off[i] if i < len(off) else 0 for i in solid])
                    rows = {}
                    for (c, r), cell in plane.items():
                        rows[r] = max(rows.get(r, 0), c + 1)
                    groups.setdefault(at, set()).update((rx + c, ry - r) for r, width in rows.items() for c in range(width))
                found = tuple([(tuple([a + b for a, b in zip(base, at)]), cells) for at, cells in groups.items()])
            else:
                found = tuple([(tuple([a + b for a, b in zip(base, off)]), {(rx + c, ry + r) for c, r in cells})
                               for off, cells in held.slabs(solid)])
            cache = self._slab_cache = (key, found)
        return cache[1]

    def _spun(self, base, solid, rx, ry):
        t = self.t
        key = (rx, ry, solid, t._rev)
        cache = self._slab_cache
        if cache is not None and cache[0] == key:
            return cache[1]
        layers, (pc, pr, mid) = t.parts()
        turns = t.spun()
        a = self.scene.aspect or 0.5
        n = len(t._p)
        mids = [0.0, 0.0] + [v - t._p[k + 2] for k, v in enumerate(mid)]
        groups = {}
        for offset, plane in layers:
            for (c, r), cell in plane.items():
                if cell[0] == ' ':
                    continue
                vec = [(c + 0.5 - pc) * a, pr - r - 0.5] + [0.0] * (n - 2)
                for k in range(2, n):
                    vec[k] = (offset[k] if k < len(offset) else 0) - mids[k]
                spin(vec, turns)
                at = tuple([round(vec[i] * 2) / 2 + mids[i] for i in solid])
                x = rx + pc + vec[0] / a
                y = ry - pr + vec[1]
                groups.setdefault(at, set()).add((math.floor(x), math.floor(y) + 1))
        found = tuple([(tuple([a_ + b for a_, b in zip(base, at)]), cells) for at, cells in groups.items()])
        self._slab_cache = (key, found)
        return found

    def _pairs(self, other, dx=0, dy=0, mine=None):
        found = []
        theirs = other._slabs()
        for ca, pa in self._slabs(dx, dy, mine):
            for cb, pb in theirs:
                for a, b in zip(ca, cb):
                    if abs(a - b) >= 1:
                        break
                else:
                    found.append((pa, pb, ca, cb))
        return found

    def _meet(self, other, mine=None, dx=0, dy=0):
        found = set()
        for pa, pb, _, _ in self._pairs(other, dx, dy, mine):
            found |= pa & pb
        return found

    def _visible(self, other, dx=0, dy=0):
        mine = set()
        theirs = set()
        for pa, pb, _, _ in self._pairs(other, dx, dy):
            mine |= pa
            theirs |= pb
        return mine, theirs

    def _escape(self, other):
        solid = self.scene._solidaxes
        found = None
        for pa, pb, ca, cb in self._pairs(other):
            if pa.isdisjoint(pb):
                continue
            for j, (a, b) in enumerate(zip(ca, cb)):
                delta = a - b
                depth = 1 - abs(delta)
                if found is None or depth < found[0]:
                    found = (depth, solid[j], 1 if delta >= 0 else -1)
        return found

    def _advance(self, i, v):
        key = _ax.NAMES[i]
        t = self.t
        mass = self.mass
        if not self.solid or self.phantom:
            t[key] += v / mass
            return
        ch = abs(v) / mass
        c = 1 if v > 0 else -1
        precision = self.precision
        while ch > 0:
            step = min(precision, ch)
            t[key] += c * step
            hit = self.overlaps()
            if hit:
                t[key] -= c * step
                for obj2, intersection in list(hit.items()):
                    if self._notify(obj2, intersection) == 0:
                        return
                for obj2 in hit:
                    p2 = getattr(obj2, 'physics', None)
                    if p2 is not None:
                        self._rebound(i, c, p2)
                return
            ch -= step

    def _rebound(self, i, c, other):
        k = i - 2
        ma = self.mass
        ua = self._ev[k] / ma
        if other.dynamic and k < len(other._ev):
            mb = other.mass
            ub = other._ev[k] / mb
            invb = 1.0 / mb
        else:
            ub = 0.0
            invb = 0.0
        vn = (ua - ub) * c
        if vn <= 0:
            return
        e = max(self.bounciness, other.bounciness)
        limits = [v for v in (self.bouncethreshold, other.bouncethreshold) if v is not None]
        if vn < (min(limits) if limits else self.scene.bouncethreshold):
            e = 0.0
        j = (1 + e) * vn / (1.0 / ma + invb)
        name = _ax.NAMES[i] + 'vel'
        setattr(self, name, (ua - j / ma * c) * ma)
        if invb:
            setattr(other, name, (ub + j * invb * c) * mb)

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

        if objs is self.scene.solids:
            objs = self.scene._broad.near(b1[0], b1[1], b1[2], b1[3], self.obj)
        elif not isinstance(objs, list):
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
            if self.scene._solidaxes:
                t = self.t
                intersection = self._meet(p2, pixels1, round(t.x if x is None else x) - round(t.x), round(t.y if y is None else y) - round(t.y))
            else:
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
        for obj2 in self.scene._broad.near(b1[0], b1[1], b1[2], b1[3], self.obj):
            p2 = getattr(obj2, 'physics', None)
            if p2 is None or p2.phantom or not p2.solid:
                continue
            b2 = p2.bounds()
            if b2 is None or b2[1] < b1[0] or b2[0] > b1[1] or b2[3] < b1[2] or b2[2] > b1[3]:
                continue
            if pixels is None:
                pixels = self.getpixels()
            if self.scene._solidaxes:
                inter = self._meet(p2, pixels, getattr(pixels, 'dx', 0), getattr(pixels, 'dy', 0))
            else:
                inter = pixels & p2.getpixels()
            if inter and not self._ghosted(obj2, inter):
                found[obj2] = inter
        return found

    def _shape_stats(self, rows, A):
        cached = self._stats
        if cached is not None and cached[0] is rows and cached[1] == A:
            return cached[2]
        n = sx = si = 0
        for i, spans in rows:
            for a, b in spans:
                k = b - a
                n += k
                sx += (a + b - 1) * k // 2
                si += i * k
        spread = 0.0
        if n:
            cxr = sx / n
            cyr = -si / n
            total = 0.0
            for i, spans in rows:
                dy = -i - cyr
                dy2 = dy * dy
                for a, b in spans:
                    for c in range(a, b):
                        d = (c - cxr) * A
                        total += d * d + dy2
            spread = total / n
        stats = (n, sx, si, spread)
        self._stats = (rows, A, stats)
        return stats

    def body(self):
        cached = self._body_cache
        if cached is None:
            t = self.t
            hitbox = self.hitbox
            if hitbox:
                text = t._htext
                ox = oy = 0
            else:
                text = t._ptext
                ox, oy = t._pvx, t._pvy
            A = t.aspect
            n, sx, si, spread = self._shape_stats(self._spans(text, hitbox), A)
            if n == 0:
                cached = (0.0, 0.0, 1.0)
            else:
                rx = round(t.x + ox)
                ry = round(t.y + oy)
                cached = ((n * rx + sx) / n, (n * ry - si) / n, spread + (A * A + 1) / 12)
            self._body_cache = cached
        return cached

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
        moved = _moved((p[0] + dx, p[1] + dy) for p in self.getpixels())
        moved.dx = dx
        moved.dy = dy
        return moved

    def _ghosted(self, other, intersection=None):
        for owner, partner in ((self.obj, other), (other, self.obj)):
            for ghost in list(getattr(owner, '_ghosts', ())):
                if ghost is partner:
                    return True
                if callable(ghost):
                    _CB[0] += 1
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

    def _blocked(self, dx, dy, exclude=(), pool=None):
        b = self.bounds()
        hits = []
        if b is None:
            return hits
        shifted = None
        if pool is None:
            pool = self.scene._broad.near(b[0] + dx, b[1] + dx, b[2] + dy, b[3] + dy, self.obj)
        for obj2 in pool:
            if obj2 in exclude:
                continue
            p2 = getattr(obj2, 'physics', None)
            if p2 is None or p2.phantom or not p2.solid:
                continue
            b2 = p2.bounds()
            if b2 is None or b2[1] < b[0] + dx or b2[0] > b[1] + dx or b2[3] < b[2] + dy or b2[2] > b[3] + dy:
                continue
            if shifted is None:
                shifted = self._shifted(dx, dy)
            inter = self._meet(p2, shifted, dx, dy) if self.scene._solidaxes else shifted & p2.getpixels()
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
            total = _acc(m.mass for m in group)
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
                vbx = _acc(m.xvel / m.mass * m.t.aspect * m.mass for m in group) / total
                vby = _acc(m.yvel for m in group) / total
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
        va_ = ra[0] * ny - ra[1] * nx
        vb_ = rb[0] * ny - rb[1] * nx
        can = va_ * va_ * ia
        cbn = vb_ * vb_ * invib
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
                vbx = _acc(m.xvel * m.t.aspect / 1.0 for m in group) / total
                vby = _acc(m.yvel for m in group) / total
            vt = (vax - vbx) * tx + (vay - vby) * ty
            ta_ = ra[0] * ty - ra[1] * tx
            tb_ = rb[0] * ty - rb[1] * tx
            cat = ta_ * ta_ * ia
            cbt = tb_ * tb_ * invib
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
        total = _acc(m.mass for m in group)
        for m in group:
            share = m.mass / total
            m._impulse(jx * share, jy * share)

    def _contact_point(self, pixels, nx=None, ny=None):
        return _contact_point_cells(pixels, nx, ny, self.body()[:2])

    def _contact_normal(self, other, point, nx, ny, inside):
        return _contact_normal_cells(self.rowmask(), other.rowmask(), point, nx, ny, inside,
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
            best = self._mtv(self._visible(p2)[1] if self.scene._solidaxes else p2.getpixels())
            if best is None:
                break
            _, dx, dy, k = best
            if self.scene._solidaxes:
                push = self._escape(p2)
                if push is not None and push[0] < k:
                    depth, axis, sign = push
                    key = _ax.NAMES[axis]
                    movable = p2.dynamic and not any(obj2 is a for a in pinned)
                    share = depth * p2.mass / (self.mass + p2.mass) if movable else depth
                    self.t[key] += sign * share
                    if movable:
                        p2.t[key] -= sign * (depth - share)
                    for body, way in ((self, sign), (p2, -sign)):
                        if (body is self or movable) and getattr(body, key + 'vel') * way < 0:
                            setattr(body, key + 'vel', 0)
                    continue
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
            reach = self.bounds()
            pool = None
            if reach is not None:
                pool = self.scene._broad.near(reach[0] - 1, reach[1] + 1, reach[2] - 1, reach[3] + 1, self.obj)
            for ia in (0, 1):
                for s in (1, -1):
                    dx, dy = (s, 0) if ia == 0 else (0, s)
                    for obj2 in (self._blocked(dx, dy, pool=pool) if pool is None or pool else ()):
                        p2 = obj2.physics
                        if self.scene._solidaxes:
                            mine, theirs = self._visible(p2)
                        else:
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
                            pool = None
        self.touch = tuple(touch)
        self.sides = tuple(sides)
        if abs(self._xvel) < 1e-9: self._xvel = 0
        if abs(self._yvel) < 1e-9: self._yvel = 0
        if abs(self._avel) < 1e-9: self._avel = 0

    def _nsync(self, w):
        sc = self.scene
        t = self.t
        slot = self._nslot
        if slot is None:
            slot = self._nslot = w.alloc()
            self._nspans = None
            sc._nat_slots[slot] = self
            sc._nat_ids[id(self.obj)] = slot
        hitbox = self.hitbox
        if hitbox:
            text = t._htext
            ox = oy = 0
        else:
            text = t._ptext
            ox, oy = t._pvx, t._pvy
        spans = self._spans(text, hitbox)
        send = None
        if spans is not self._nspans:
            send = spans
            self._nspans = spans
        g = self.gravity
        mass = self._mass
        bt = self.bouncethreshold
        obj = self.obj
        ok = (len(g) == 2
              and getattr(obj, 'joint', None) is None and len(t._onchangecb) == 1
              and self._ncbs[0] in t._onchangecb
              and not self._onchangecb and not any(self._ev)
              and isinstance(mass, (int, float)) and mass > 0 and self.precision > 0
              and -_NAT_LIMIT < t.x < _NAT_LIMIT and -_NAT_LIMIT < t.y < _NAT_LIMIT)
        ids = sc._nat_ids
        held = getattr(obj, '_ghosts', None) or ()
        calls = False
        mates = []
        for ghost in held:
            if callable(ghost):
                calls = True
            else:
                mate = ids.get(id(ghost))
                if mate is not None:
                    mates.append(mate)
        self._nok = ok
        w.sync(slot, [
            1.0 if self.solid else 0.0, 1.0 if self.phantom else 0.0, 1.0 if self.dynamic else 0.0,
            1.0 if hitbox else 0.0, 1.0 if self.slope else 0.0, 1.0 if ok else 0.0,
            self.bounciness, self.friction, float('nan') if bt is None else bt,
            mass if ok else 1.0, self.drag, self.adrag, self.precision,
            g[0] if ok else 0.0, g[1] if ok else 0.0, t.aspect,
            self._xvel, self._yvel, self._avel, t.x, t.y, ox, oy, self._depenskip,
            0.0 if self._touch_callbacks else 1.0, 1.0 if calls else 0.0,
        ], send, mates)

    def _nat_apply(self, writes, extra, touched):
        sc = self.scene
        slots = sc._nat_slots
        t = self.t
        if touched is not None:
            self._touched = {id(slots[n].obj) for n in touched}
        _APPLY[0] = True
        try:
            if touched is not None:
                self._dirty('x')
            for slot, mask, x, y, xv, yv, av in writes:
                p = slots[slot]
                pt = p.t
                if mask & 3:
                    pos = pt._p
                    rev = pt._rev
                    if mask & 1:
                        pos[0] = x
                        rev += 1
                    if mask & 2:
                        pos[1] = y
                        rev += 1
                    pt.__dict__['_rev'] = rev
                    p._dirty('x')
                if mask & 4:
                    p._xvel = _keep(p._xvel, xv)
                if mask & 8:
                    p._yvel = _keep(p._yvel, yv)
                if mask & 16:
                    p._avel = _keep(p._avel, av)
            if not extra[8]:
                self.touch = (extra[0], extra[1])
                self.sides = (extra[2], extra[3], extra[4], extra[5])
            self._depenskip = extra[6]
            if extra[7]:
                self._good = (t.x, t.y, t.rotation)
        finally:
            _APPLY[0] = False

    def _nat_try(self):
        sc = self.scene
        if not sc.__dict__.get('_nat_live') or sc._solidaxes:
            return 0
        w = sc._nat_world
        if sc._nat_stale or sc._nat_dirty:
            _nat_flush(sc, w)
        if self._nslot is None:
            return 0
        found = w.step(self._nslot)
        if found is None:
            return 0
        writes, extra, touched = found
        self._nat_apply(writes, extra, touched)
        return 2 if extra[8] else 1

    def _nat_finish(self):
        sc = self.scene
        if not sc.__dict__.get('_nat_live') or sc._solidaxes:
            return False
        w = sc._nat_world
        if sc._nat_stale or sc._nat_dirty:
            _nat_flush(sc, w)
        ids = sc._nat_ids
        touched = [ids[i] for i in self._touched if i in ids]
        found = w.finish(self._nslot, touched)
        if found is None:
            return False
        self._nat_apply(found[0], found[1], None)
        return True

    def physics(self, axises=None):
        physics._running += 1
        try:
            sc = self.scene
            if axises is None:
                state = self._nat_try()
                if state == 1:
                    return
                if state == 2:
                    before = _CB[0]
                    degrees = self.avel / self.mass
                    aborted = bool(degrees) and self._rotate(degrees)
                    if _CB[0] != before:
                        sc._nat_stale = True
                    if aborted:
                        return
                    if not self._nat_finish():
                        self._depenetrate()
                        self._probe()
                        if _CB[0] != before:
                            sc._nat_stale = True
                    return
            before = _CB[0]
            self._physics(axises)
            if _CB[0] != before and sc.__dict__.get('_nat_live'):
                sc._nat_stale = True
        finally:
            physics._running -= 1

    def _notify(self, obj2, intersection, once=False):
        obj2p = getattr(obj2, 'physics', None)
        if obj2p is None:
            return 1
        if once and id(obj2) in self._touched:
            return 2
        self._touched.add(id(obj2))
        if self._touch_callbacks or obj2p._touch_callbacks:
            _CB[0] += 1
        for cb in list(self._touch_callbacks):
            cb(obj2, intersection)
        if getattr(self.obj, 'physics', None) is not self:
            return 0
        for cb in list(obj2p._touch_callbacks):
            cb(self.obj, intersection)
        if getattr(self.obj, 'physics', None) is not self:
            return 0
        return 1 if getattr(obj2, 'physics', None) is not obj2p else 2

    def _rotate(self, degrees):
        pieces = max(1, int(math.ceil(abs(degrees) / self._turn_step())))
        da = degrees / pieces
        check = self.solid and not self.phantom and not self.hitbox
        if pieces > 1 and (not check or self._turn_clear()):
            angle = self.t.rotation
            for _ in range(pieces):
                angle = angle + da
            self.t.rotation = angle
            pieces = 0
        remaining = pieces
        while remaining > 0:
            if check and remaining > 1:
                jump = self._turn_free(da, remaining)
                if jump:
                    angle = self.t.rotation
                    for _ in range(jump):
                        angle = angle + da
                    self.t.rotation = angle
                    remaining -= jump
                    continue
            remaining -= 1
            before = self.t.rotation
            self.t.rotation = before + da
            hit = self.overlaps() if check else None
            if not hit:
                continue
            for obj2, intersection in list(hit.items()):
                if self._notify(obj2, intersection, True) == 0:
                    return True
            contacts = []
            for obj2, intersection in hit.items():
                if getattr(obj2, 'physics', None) is None:
                    continue
                mtv = self._mtv(self._visible(obj2.physics)[1] if self.scene._solidaxes else obj2.physics.getpixels())
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
                    return True
        return False

    def _physics(self, axises=None):
        axises = self._axises if axises is None else axises
        self._touched = set()
        actualmass = self.mass
        gravity = self.gravity
        drag = self.drag
        precision = self.precision
        self._dirty('x')
        if len(gravity) > 2 or any(self._ev):
            self._drift(gravity, drag, actualmass)

        for ia, a in enumerate(axises):
            self[a + 'vel'] *= drag
            self[a + 'vel'] += gravity[ia] * actualmass
            c = 1 if self[a + 'vel'] > 0 else -1 if self[a + 'vel'] < 0 else 0
            ch = abs(self[a + 'vel']) / actualmass
            d = (c, 0) if ia == 0 else (0, c)

            pool = None
            while ch > 0:
                if pool is None:
                    pool = self._sweep(a, c, ch)
                free = self._free(pool, a, c)
                if free >= precision:
                    pos = self.t[a]
                    went = 0.0
                    while ch > 0:
                        step = min(precision, ch)
                        if went + step > free:
                            break
                        pos += c * step
                        ch -= step
                        went += step
                    if went:
                        self.t[a] = pos
                    if ch <= 0:
                        break
                step = min(precision, ch)
                t = {a: self.t[a] + c * step}
                collisions = self.collides(pool, full=True, **t)
                if collisions:
                    pool = None

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
        if degrees and self._rotate(degrees):
            return
        self._depenetrate()
        self._probe()


def _acc(values):
    total = 0
    for v in values:
        total += v
    return total


def _keep(old, new):
    if type(old) is int and new == new and abs(new) < 1e15 and new == int(new):
        return int(new)
    return new


def _nat_flush(sc, w):
    if sc._nat_stale:
        _nat_refresh(sc, w)
        return
    dirty = sc._nat_dirty
    for p in list(dirty):
        if p._nslot is None:
            _nat_refresh(sc, w)
            return
        p._nsync(w)
    dirty.clear()


def _nat_refresh(sc, w):
    key, snap, phys = sc._roster()[:3]
    bodies = []
    for i in phys:
        p = getattr(snap[i], 'physics', None)
        if p is not None:
            bodies.append(p)
    sc._nat_bodies = bodies
    w.set_scene(sc.bouncethreshold)
    for p in bodies:
        if p._nslot is None:
            p._nslot = w.alloc()
            p._nspans = None
            sc._nat_slots[p._nslot] = p
            sc._nat_ids[id(p.obj)] = p._nslot
    for p in bodies:
        p._nsync(w)
    order = []
    for o in sc.solids:
        p = getattr(o, 'physics', None)
        if p is not None and p._nslot is not None:
            order.append(p._nslot)
    w.set_order(order)
    sc._nat_dirty.clear()
    sc._nat_stale = False


def _nat_begin(sc):
    if '_nat_world' not in sc.__dict__:
        return
    sc._nat_stale = True
    sc._nat_live = True


def _nat_end(sc):
    if '_nat_world' in sc.__dict__:
        sc._nat_live = False


def _extra_velocity(i):
    name = _ax.NAMES[i] + 'vel'
    def fget(self):
        try:
            return self._ev[i - 2]
        except IndexError:
            raise AttributeError(name) from None
    def fset(self, value):
        ev = self._ev
        if i - 2 >= len(ev):
            raise AttributeError('the scene has no %s axis' % _ax.NAMES[i])
        old = ev[i - 2]
        ev[i - 2] = value
        self._change(name, old)
    return property(fget, fset)


for _i in range(2, _ax.LIMIT):
    setattr(physics, _ax.NAMES[_i] + 'vel', _extra_velocity(_i))
