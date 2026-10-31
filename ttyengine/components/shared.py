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

_REACH = 3.5

def _window_cells(pixels, center, aspect):
    cx, cy = center
    for x in range(math.ceil(cx - _REACH / aspect), math.floor(cx + _REACH / aspect) + 1):
        for y in range(math.ceil(cy - _REACH), math.floor(cy + _REACH) + 1):
            if (x, y) in pixels and math.hypot((x - cx) * aspect, y - cy) <= _REACH:
                yield x, y

def _gradient_cells(pixels, center, sign, aspect):
    cx, cy = center
    sx = sy = 0.0
    filled = total = 0
    for x in range(math.ceil(cx - _REACH / aspect), math.floor(cx + _REACH / aspect) + 1):
        for y in range(math.ceil(cy - _REACH), math.floor(cy + _REACH) + 1):
            if math.hypot((x - cx) * aspect, y - cy) > _REACH:
                continue
            total += 1
            if (x, y) in pixels:
                filled += 1
                sx += (x - cx) * aspect
                sy += y - cy
    length = math.hypot(sx, sy)
    if length < 1e-9:
        return None
    gx, gy = sign * sx / length, sign * sy / length
    edge = [(x, y) for x, y in _window_cells(pixels, center, aspect)
            if any((x + dx, y + dy) not in pixels for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
    if len(edge) >= 3:
        mx = sum(p[0] for p in edge) * aspect / len(edge)
        my = sum(p[1] for p in edge) / len(edge)
        sxx = sum((p[0] * aspect - mx) ** 2 for p in edge)
        syy = sum((p[1] - my) ** 2 for p in edge)
        sxy = sum((p[0] * aspect - mx) * (p[1] - my) for p in edge)
        half = math.hypot((sxx - syy) / 2, sxy)
        major = (sxx + syy) / 2 + half
        minor = (sxx + syy) / 2 - half
        if major > 3 * max(minor, 1e-9):
            angle = 0.5 * math.atan2(2 * sxy, sxx - syy)
            nx, ny = -math.sin(angle), math.cos(angle)
            if nx * gx + ny * gy < 0:
                nx, ny = -nx, -ny
            gx, gy = nx, ny
    return gx, gy, filled / total

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
    faces = [g for g in (go, gs) if g is not None and g[0] * nx + g[1] * ny >= 0.25]
    if not faces:
        return nx, ny
    fullest = max(g[2] for g in faces)
    faces = [g for g in faces if g[2] >= fullest - 0.08]
    g = max(faces, key=lambda g: g[0] * nx + g[1] * ny)
    return g[0], g[1]

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
