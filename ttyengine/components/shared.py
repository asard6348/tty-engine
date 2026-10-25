import math, inspect, functools
from .. import ansi
from ..ascii_styler import alphaparse, bgrecomp, fgrecomp

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

_SGR = ansi.SGR
_ALPHAS = functools.lru_cache(maxsize=4096)(alphaparse)
_HOLD = object()

def _unbake(baked, ref, alpha):
    if alpha <= 0:
        return baked
    return tuple((baked[k] - ref[k] * (1 - alpha)) / alpha for k in range(3))

def _rebake(ref, source, alpha):
    return tuple(max(0, min(255, int(round(ref[k] * (1 - alpha) + source[k] * alpha)))) for k in range(3))
_FGCODE = fgrecomp
_BGCODE = bgrecomp

def _argslen(cb):
    params = inspect.signature(cb).parameters
    return len(params)

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

_RELIEF = 1

def _wrap(angle):
    return (angle + 180) % 360 - 180
