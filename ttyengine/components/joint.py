import math, collections.abc
from .shared import _argslen, _wrap
from .inherit import _keyed, _lerpable
from .transform import transform
from .physics import physics

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

def _check_snap(value):
    if value < 0:
        raise ValueError('snap must not be negative')
    return value

_PARAMS = {
    'xoffset': (0, None),
    'yoffset': (0, None),
    'radius': (0, _check_radius),
    'range': (None, _check_range),
    'elasticity': (1, _check_elasticity),
    'durability': (0, _check_durability),
    'snap': (0, _check_snap),
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
        A = f.t.aspect
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
        A = f.t.aspect
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
        gx = ex * k + fx
        gy = ey * k + fy
        bodies = []
        for comp, point, w, kick in ((f, fpoint, wc, fkick), (o, opoint, -wp, okick)):
            p = getattr(comp.obj, 'physics', None)
            if p is not None and p.dynamic:
                if w:
                    bodies.append((comp, point, 1.0 if w > 0 else -1.0, kick))
            else:
                comp._push(ex * w * k, ey * w * k)
        if not bodies:
            return
        reduced = 1.0 / sum(1.0 / comp._effective(point, gx, gy, kick) for comp, point, _, kick in bodies)
        for comp, point, sign, kick in bodies:
            comp._kick(point, gx * reduced * sign, gy * reduced * sign, kick)

@_withparams
class joint(_lerpable, _keyed):
    _angles = frozenset(('rest', 'axis'))
    _owned = ['joints', 'xoffset', 'yoffset', 'pinx', 'piny', 'jradius', 'range', 'elasticity',
              'durability', 'snap', 'physical', 'vel', 'collide', 'kind', 'rest', 'axis', 'slide', 'preset']
    _required = [transform]
    _settings = ('preset', 'joints', 'xoffset', 'yoffset', 'pinx', 'piny', 'radius', 'range', 'elasticity',
                 'durability', 'snap', 'physical', 'vel', 'collide', 'kind', 'rest', 'axis', 'slide')
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
        self._resolved = None
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
        A = self.t.aspect
        r = math.radians(self.t.rotation)
        dx, dy = (point[0] - cx) * A, point[1] - cy
        return (dx * math.cos(r) - dy * math.sin(r)) / A, dx * math.sin(r) + dy * math.cos(r)

    def _seam(self, other, cells):
        edge = self._edges.get(id(other))
        if edge is None or not edge.alive or not edge.colliding:
            return False
        A = self.t.aspect
        points = (edge.anchor(), edge.pin())
        frontier = [c for c in cells
                    if any(math.hypot((c[0] + 0.5 - p[0]) * A, c[1] - 0.5 - p[1]) <= 1.5 for p in points)]
        if not frontier:
            return False
        seen = set(frontier)
        while frontier:
            x, y = frontier.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (x + dx, y + dy)
                    if n in cells and n not in seen:
                        seen.add(n)
                        frontier.append(n)
        return len(seen) == len(cells)

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
        A = old.transform.aspect
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
        edge.follower._spun = None

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
        A = self.t.aspect
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
        x0, y0 = x, y
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
        return x - x0, y - y0

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
        A = self.t.aspect
        cx, cy, _ = p.body()
        rx, ry = (point[0] - cx - 0.5) * A, point[1] - cy + 0.5
        om = p._omega()
        return p.xvel / p.mass - om * ry / A, p.yvel / p.mass + om * rx

    def _effective(self, point, gx, gy, kick):
        p = self.obj.physics
        if not kick or not p._invinertia():
            return p.mass
        A = self.t.aspect
        cx, cy, spread = p.body()
        rx, ry = (point[0] - cx - 0.5) * A, point[1] - cy + 0.5
        n = math.hypot(gx * A, gy)
        if n <= 1e-12:
            return p.mass
        cross = (rx * gy - ry * gx * A) / n
        return p.mass / (1.0 + cross * cross / spread)

    def _kick(self, point, jx, jy, kick=True):
        p = self.obj.physics
        if kick and p._invinertia():
            A = self.t.aspect
            cx, cy, _ = p.body()
            rx, ry = (point[0] - cx - 0.5) * A, point[1] - cy + 0.5
            p._spin(rx * jy - ry * jx * A)
        p.xvel += jx
        p.yvel += jy

    def _relax(self, other, ex, ey):
        p = getattr(self.obj, 'physics', None)
        if p is None or not p.dynamic:
            return
        A = self.t.aspect
        ux, uy = ex * A, ey
        n = math.hypot(ux, uy)
        if n < 1e-9:
            return
        ux /= n
        uy /= n
        q = getattr(other.obj, 'physics', None)
        shared = q is not None and q.dynamic
        B = other.t.aspect
        bx, by = (other.velocity[0] * B / A, other.velocity[1]) if shared else (0.0, 0.0)
        closing = ((p.xvel / p.mass - bx) * A) * ux + (p.yvel / p.mass - by) * uy
        if closing >= 0:
            return
        reduced = 1.0 / (1.0 / p.mass + 1.0 / q.mass) if shared else p.mass
        j = -closing * reduced
        p.xvel += j * ux / A
        p.yvel += j * uy
        if shared:
            q.xvel -= j * ux / B
            q.yvel -= j * uy

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
            other = near if mover is far else far
            if mover.movable:
                dx, dy = (ex, ey) if mover is f else (-ex, -ey)
                mover._relax(other, dx, dy)
                gx, gy = mover._move(dx, dy)
                moved = True
                rx, ry = dx - gx, dy - gy
                if other.movable and (rx or ry) and math.hypot(rx * self.t.aspect, ry) > 1e-6:
                    other._relax(mover, -rx, -ry)
                    other._move(-rx, -ry)
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

    def _network(self):
        seen = {id(self): self}
        queue = [self]
        edges = []
        marked = set()
        for comp in queue:
            for edge in list(comp._edges.values()):
                if not edge.alive or id(edge) in marked:
                    continue
                marked.add(id(edge))
                edges.append(edge)
                other = edge.other(comp)
                if id(other) not in seen:
                    seen[id(other)] = other
                    queue.append(other)
        return list(seen.values()), edges

    def _resolve(self):
        tick = self.scene._ticks
        if self._resolved == tick:
            return
        members, edges = self._network()
        for member in members:
            member._resolved = tick
        edges = [e for e in edges if e.physical]
        for _ in range(_SWEEPS):
            moved = False
            for edge in edges:
                if not edge.alive:
                    continue
                ex, ey, dist = edge.error(False)
                if not (ex or ey):
                    continue
                f = edge.follower
                if edge.beyond() or (f.snap and math.hypot(ex * f.t.aspect, ey) > f.snap):
                    if edge.origin._fix(edge, edge.origin, f, False, False):
                        moved = True
            if not moved:
                break

    def step(self):
        if joint._active or not self._edges:
            return
        owned = [e for e in list(self._edges.values()) if e.origin is self]
        if any(e.alive and e.physical for e in owned):
            self._resolve()
        for edge in owned:
            if edge.alive and edge.physical:
                ex, ey, dist = edge.error(False)
                f = edge.follower
                if f.durability and dist > f.durability:
                    self._break(edge)
                else:
                    if ex or ey:
                        if edge.beyond() or (f.snap and math.hypot(ex * self.t.aspect, ey) > f.snap):
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
