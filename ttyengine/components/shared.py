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
_SPREAD = {}
_WINDOWS = {}

def _spread(mask):
    found = _SPREAD.get(mask)
    if found is None:
        count = total = square = 0
        rest = mask
        while rest:
            low = rest & -rest
            k = low.bit_length() - 1
            count += 1
            total += k
            square += k * k
            rest ^= low
        found = (count, total, square)
        if len(_SPREAD) >= 65536:
            _SPREAD.clear()
        _SPREAD[mask] = found
    return found

def _window(fx, fy, aspect):
    key = (fx, fy, aspect)
    found = _WINDOWS.get(key)
    if found is None:
        span = int(_REACH / aspect) + 2
        rows = {}
        for yrel in range(-4, 5):
            dy = yrel - fy
            bits = 0
            for j in range(2 * span + 1):
                u = (j - span - fx) * aspect
                if math.sqrt(u * u + dy * dy) <= _REACH:
                    bits |= 1 << j
            if bits:
                rows[yrel] = bits
        found = (span, rows)
        if len(_WINDOWS) >= 512:
            _WINDOWS.clear()
        _WINDOWS[key] = found
    return found

def _rows_of(cells):
    if not cells:
        return (0, {}, (0, ()))
    origin = min(p[0] for p in cells)
    rows = {}
    for x, y in cells:
        rows[y] = rows.get(y, 0) | (1 << (x - origin))
    return (origin, rows, (origin, tuple(rows.items())))

def _aligned(mask, origin, base):
    shift = base - origin
    return mask >> shift if shift >= 0 else mask << -shift

_NORMALS = {}
_NORMAL_COST = [0]
_NORMAL_BUDGET = 400000
_MISSING = object()

def _gradient_rows(shape, center, sign, aspect):
    cost = len(shape[1]) + 4
    if cost > 512:
        return _fit_rows(shape, center, sign, aspect)
    key = (shape[2], center, sign, aspect)
    found = _NORMALS.get(key, _MISSING)
    if found is _MISSING:
        found = _fit_rows(shape, center, sign, aspect)
        if _NORMAL_COST[0] + cost > _NORMAL_BUDGET:
            _NORMALS.clear()
            _NORMAL_COST[0] = 0
        _NORMALS[key] = found
        _NORMAL_COST[0] += cost
    return found

def _fit_rows(shape, center, sign, aspect):
    origin, masks, _ = shape
    cx, cy = center
    ix = math.floor(cx)
    iy = math.floor(cy)
    span, template = _window(cx - ix, cy - iy, aspect)
    base = ix - span
    xlo = math.ceil(cx - _REACH / aspect)
    xhi = math.floor(cx + _REACH / aspect)
    ylo = math.ceil(cy - _REACH)
    yhi = math.floor(cy + _REACH)
    keep = ((1 << (xhi - xlo + 1)) - 1) << (xlo - base)
    edge_base = base - 1
    get = masks.get
    spread = _spread
    total = filled = 0
    sum_x = 0
    sum_y = 0
    n = ex = ey = exx = eyy = exy = 0
    for y in range(ylo, yhi + 1):
        window = template.get(y - iy)
        if window is None:
            continue
        window &= keep
        if not window:
            continue
        total += spread(window)[0]
        row = get(y)
        if not row:
            continue
        shift = base - origin
        here = row >> shift if shift >= 0 else row << -shift
        hit = here & window
        if not hit:
            continue
        count, offset, _ = spread(hit)
        filled += count
        sum_x += count * base + offset
        sum_y += count * y
        above = get(y + 1, 0)
        below = get(y - 1, 0)
        shift = edge_base - origin
        if shift >= 0:
            centre = row >> shift
            up = above >> shift
            down = below >> shift
        else:
            centre = row << -shift
            up = above << -shift
            down = below << -shift
        rim = centre & (window << 1) & ~(centre & (centre << 1) & (centre >> 1) & up & down)
        if rim:
            count, offset, square = spread(rim)
            cells_x = count * edge_base + offset
            n += count
            ex += cells_x
            ey += count * y
            exx += count * edge_base * edge_base + 2 * edge_base * offset + square
            eyy += count * y * y
            exy += y * cells_x
    if not filled:
        return None
    sx = (sum_x - filled * cx) * aspect
    sy = sum_y - filled * cy
    length = math.sqrt(sx * sx + sy * sy)
    if length < 1e-9:
        return None
    gx, gy = sign * sx / length, sign * sy / length
    if n >= 3:
        sxx = (n * exx - ex * ex) * aspect * aspect / n
        syy = (n * eyy - ey * ey) / n
        sxy = (n * exy - ex * ey) * aspect / n
        hd = (sxx - syy) / 2
        half = math.sqrt(hd * hd + sxy * sxy)
        major = (sxx + syy) / 2 + half
        minor = (sxx + syy) / 2 - half
        if major > 3 * max(minor, 1e-9):
            angle = 0.5 * math.atan2(2 * sxy, sxx - syy)
            nx, ny = -math.sin(angle), math.cos(angle)
            if nx * gx + ny * gy < 0:
                nx, ny = -nx, -ny
            gx, gy = nx, ny
    return gx, gy, filled / total

def _gradient_cells(pixels, center, sign, aspect):
    return _gradient_rows(pixels if isinstance(pixels, tuple) else _rows_of(pixels), center, sign, aspect)

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

def _rowmasks(pixels, origin):
    rows = {}
    for x, y in pixels:
        rows[y] = rows.get(y, 0) | (1 << (x - origin))
    return rows

def _mtv_cells(mine, other_pixels, aspect):
    if not mine or not other_pixels:
        best = None
        for dx, dy, cost in ((1, 0, aspect), (-1, 0, aspect), (0, 1, 1.0), (0, -1, 1.0)):
            score = cost - (0.01 if dy == 1 else 0)
            if best is None or score < best[0]:
                best = (score, dx, dy, 1)
        return best
    origin = min(min(p[0] for p in mine), min(p[0] for p in other_pixels))
    mrows = _rowmasks(mine, origin)
    orows = _rowmasks(other_pixels, origin)
    best = None
    for dx, dy, cost in ((1, 0, aspect), (-1, 0, aspect), (0, 1, 1.0), (0, -1, 1.0)):
        for k in range(1, 64):
            sx = dx * k
            sy = dy * k
            hit = False
            for y, m in mrows.items():
                o = orows.get(y + sy)
                if o and ((m << sx) if sx >= 0 else (m >> -sx)) & o:
                    hit = True
                    break
            if not hit:
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

_ARGS = {}

def _argslen(cb):
    try:
        found = _ARGS.get(cb)
    except TypeError:
        return len(inspect.signature(cb).parameters)
    if found is None:
        if len(_ARGS) >= 256:
            _ARGS.clear()
        found = _ARGS[cb] = len(inspect.signature(cb).parameters)
    return found

def pure(fn):
    fn._pure = True
    return fn

def _impure(callbacks):
    for cb in callbacks:
        if not getattr(cb, '_pure', False):
            return True
    return False

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
