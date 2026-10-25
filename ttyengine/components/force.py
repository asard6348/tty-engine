import math
from .shared import _NEIGHBOURS4, _argslen
from .inherit import _lerpable
from .transform import transform

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

class force(_lerpable):
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
