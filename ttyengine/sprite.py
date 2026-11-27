import itertools
import math

from . import axes as _ax
from . import cells as _cells


def _depth(item):
    if isinstance(item, str):
        return 0
    if not isinstance(item, (list, tuple)) or not item:
        raise TypeError('sprite layers must be strings or non-empty sequences of them')
    found = {_depth(part) for part in item}
    if len(found) != 1:
        raise ValueError('every branch of a sprite must nest to the same depth')
    return found.pop() + 1


def _freeze(item):
    return item if isinstance(item, str) else tuple(_freeze(part) for part in item)


def _index(name):
    if isinstance(name, int) and not isinstance(name, bool):
        found = name
    else:
        try:
            found = _ax.NAMES.index(name)
        except ValueError:
            raise ValueError('unknown axis %r' % (name,)) from None
    if not 2 <= found < _ax.LIMIT:
        raise ValueError('sprites stack along axes beyond x and y, got %r' % (name,))
    return found


class sprite:
    __slots__ = ('rank', 'axes', 'steps', 'cells', 'spaces', 'size', 'spec', '_points', '_planes', '_flat', '_slabs')

    def __init__(self, layers, axes=None, step=1, spaces=False):
        depth = _depth(layers)
        if axes is None:
            axes = _ax.NAMES[2:2 + depth]
        elif isinstance(axes, (str, int)):
            axes = (axes,)
        found = tuple(_index(name) for name in axes)
        if len(found) != depth or len(set(found)) != depth:
            raise ValueError('a sprite nested %d deep needs %d distinct axes, got %d' % (depth, depth, len(found)))
        steps = tuple(step) if isinstance(step, (list, tuple)) else (step,) * depth
        if len(steps) != depth:
            raise ValueError('a sprite nested %d deep needs %d steps, got %d' % (depth, depth, len(steps)))
        self.rank = 2 + depth
        self.axes = found
        self.steps = tuple(float(s) if s != int(s) else int(s) for s in steps)
        self.spaces = bool(spaces)
        self.spec = (_freeze(layers), tuple(_ax.NAMES[i] for i in found), self.steps, self.spaces)
        self.cells = {}
        width = [0] * self.rank
        self._walk(layers, ())
        for coord in self.cells:
            for i, value in enumerate(coord):
                if value + 1 > width[i]:
                    width[i] = value + 1
        self.size = tuple(width)
        self._points = None
        self._planes = None
        self._flat = None
        self._slabs = {}

    def _walk(self, item, path):
        if isinstance(item, str):
            for r, row in enumerate(_cells.parse(item)):
                for c, cell in enumerate(row):
                    if self.spaces or not _cells.blank(cell):
                        self.cells[(c, r) + path] = cell
            return
        for i, part in enumerate(item):
            self._walk(part, path + (i,))

    def __len__(self):
        return len(self.cells)

    def __repr__(self):
        return 'sprite(rank=%d, axes=%s, size=%s, cells=%d)' % (
            self.rank, ','.join(_ax.NAMES[i] for i in self.axes), self.size, len(self.cells))

    def offset(self, coord):
        out = [coord[0], -coord[1]]
        for i, axis in enumerate(self.axes):
            while len(out) <= axis:
                out.append(0)
            out[axis] += coord[2 + i] * self.steps[i]
        return tuple(out)

    @property
    def points(self):
        if self._points is None:
            self._points = tuple((self.offset(coord), cell[0], cell[1]) for coord, cell in self.cells.items())
        return self._points

    @property
    def planes(self):
        if self._planes is None:
            found = {}
            for coord, cell in self.cells.items():
                found.setdefault(coord[2:], {})[coord[0], coord[1]] = cell
            self._planes = tuple(
                (self.offset((0, 0) + path), plane) for path, plane in sorted(found.items()))
        return self._planes

    def slabs(self, solid):
        found = self._slabs.get(solid)
        if found is None:
            groups = {}
            for coord, cell in self.cells.items():
                if cell[0] == ' ':
                    continue
                off = self.offset(coord)
                key = tuple([off[i] if i < len(off) else 0 for i in solid])
                groups.setdefault(key, set()).add((off[0], off[1]))
            found = self._slabs[solid] = tuple((key, frozenset(cells)) for key, cells in groups.items())
        return found

    def centre(self):
        if not self.cells:
            return (0.0, 0.0)
        cols = [coord[0] for coord in self.cells]
        rows = [coord[1] for coord in self.cells]
        found = [(min(cols) + max(cols) + 1) / 2, -(max(rows) + 1) / 2]
        offsets = [self.offset(coord) for coord in self.cells]
        for axis in self.axes:
            while len(found) <= axis:
                found.append(0.0)
            values = [off[axis] for off in offsets if len(off) > axis]
            found[axis] = (min(values) + max(values)) / 2
        return tuple(found)

    def footprint(self):
        if self._flat is None:
            best = {}
            for offset, char, style in self.points:
                pad = offset + (0,) * (_ax.LIMIT - len(offset))
                key = (offset[0], -offset[1])
                held = best.get(key)
                if held is None or pad[2:] > held[0]:
                    best[key] = (pad[2:], (char, style))
            if not best:
                self._flat = ''
            else:
                rows = [[None] * (max(c for c, _ in best) + 1) for _ in range(max(r for _, r in best) + 1)]
                for (c, r), (_, cell) in best.items():
                    rows[r][c] = cell
                self._flat = _cells.build(rows)
        return self._flat


def build(layers, axes=None, step=1, spaces=False):
    return sprite(layers, axes, step, spaces)


def _spin(vec, planes, back=False):
    for i, j, c, s in (reversed(planes) if back else planes):
        if back:
            s = -s
        a = vec[i]
        b = vec[j]
        vec[i] = a * c - b * s
        vec[j] = a * s + b * c
    return vec


def rotate(held, planes, aspect=0.5, limit=2000000):
    if not held.cells:
        return held
    centre = held.centre()
    pc = centre[0]
    pr = -centre[1]
    mid = {axis: centre[axis] for axis in held.axes}
    steps = dict(zip(held.axes, held.steps))
    touched = {k for i, j, _, _ in planes for k in (i, j) if k >= 2}
    axes = tuple(sorted(set(held.axes) | touched))
    top = max((axes[-1] if axes else 1), 1) + 1
    steps.update({axis: 1 for axis in axes if axis not in steps})
    half = [aspect / 2, 0.5] + [steps.get(axis, 1) / 2 if axis >= 2 else 0.5 for axis in range(2, top)]
    columns = []
    for j in range(top):
        unit = [0.0] * top
        unit[j] = 1.0
        columns.append(_spin(unit, planes))
    reach = [sum([abs(columns[j][k]) * half[j] for j in range(top)]) for k in range(top)]
    low = [float('inf')] * top
    high = [float('-inf')] * top
    for coord in held.cells:
        off = held.offset(coord)
        vec = [0.0] * top
        vec[0] = (coord[0] + 0.5 - pc) * aspect
        vec[1] = pr - coord[1] - 0.5
        for axis in range(2, len(off)):
            vec[axis] = off[axis] - mid.get(axis, 0)
        _spin(vec, planes)
        for k in range(top):
            if vec[k] - reach[k] < low[k]:
                low[k] = vec[k] - reach[k]
            if vec[k] + reach[k] > high[k]:
                high[k] = vec[k] + reach[k]
    ncols = max(1, int(math.ceil((high[0] - low[0]) / aspect - 1e-9)))
    nrows = max(1, int(math.ceil(high[1] - low[1] - 1e-9)))
    counts = [max(1, int(math.ceil((high[axis] - low[axis]) / steps[axis] - 1e-9))) for axis in axes]
    volume = ncols * nrows
    for count in counts:
        volume *= count
    if volume > limit:
        raise ValueError('the rotated sprite would hold %d cells' % volume)
    cells = {}
    src = held.cells
    for index in itertools.product(*[range(count) for count in counts]):
        base = [0.0] * top
        for axis, i in zip(axes, index):
            base[axis] = low[axis] + (i + 0.5) * steps[axis]
        for r in range(nrows):
            for c in range(ncols):
                vec = list(base)
                vec[0] = low[0] + (c + 0.5) * aspect
                vec[1] = high[1] - r - 0.5
                _spin(vec, planes, True)
                key = [int(round(vec[0] / aspect + pc - 0.5)), int(round(pr - 0.5 - vec[1]))]
                for axis in held.axes:
                    key.append(int(round((vec[axis] + mid[axis]) / steps[axis])))
                for axis in range(2, top):
                    if axis not in mid and abs(vec[axis]) >= 0.5:
                        key = None
                        break
                found = src.get(tuple(key)) if key is not None else None
                if found is not None:
                    cells[(c, r) + index] = found
    if not any([count > 1 for count in counts]):
        rows = [[None] * ncols for _ in range(nrows)]
        for key, cell in cells.items():
            rows[key[1]][key[0]] = cell
        return _cells.build(rows)
    return _assemble(cells, axes, counts, [steps[axis] for axis in axes], ncols, nrows, held.spaces)


def _assemble(cells, axes, counts, steps, ncols, nrows, spaces):
    planes = {}
    for key, cell in cells.items():
        planes.setdefault(key[2:], {})[key[0], key[1]] = cell

    def build(prefix):
        depth = len(prefix)
        if depth == len(counts):
            plane = planes.get(prefix, {})
            rows = [[None] * ncols for _ in range(nrows)]
            for (c, r), cell in plane.items():
                rows[r][c] = cell
            return _cells.build(rows)
        return tuple(build(prefix + (i,)) for i in range(counts[depth]))

    return sprite(build(()), tuple(_ax.NAMES[axis] for axis in axes), tuple(steps), spaces)


def _spots(part, position, keep):
    own = dict(zip(part.axes, part.steps))
    found = []
    for coord, cell in part.cells.items():
        if not (part.spaces or cell[0] != ' ' or (keep is not None and keep(cell[1]))):
            continue
        vals = [0.0] * len(position)
        for i, axis in enumerate(part.axes):
            vals[position[axis]] = coord[2 + i] * own[axis]
        found.append((coord[0], coord[1], vals, cell))
    return found


def _middle(spots):
    use = [spot for spot in spots if spot[3][0] != ' '] or spots
    if not use:
        return None
    cols = [spot[0] for spot in use]
    rows = [spot[1] for spot in use]
    mid = [(min(cols) + max(cols)) / 2, (min(rows) + max(rows)) / 2]
    for k in range(len(use[0][2])):
        values = [spot[2][k] for spot in use]
        mid.append((min(values) + max(values)) / 2)
    return mid


def merge(parts, center=True, keep=None):
    axes = set()
    steps = {}
    for held, shift in parts:
        for axis, step in zip(held.axes, held.steps):
            axes.add(axis)
            steps.setdefault(axis, step)
        axes.update(axis for axis, amount in shift.items() if axis >= 2 and amount)
    axes = sorted(axes)
    position = {axis: i for i, axis in enumerate(axes)}
    for axis in axes:
        steps.setdefault(axis, 1)
    floor = math.floor
    placed = {}
    anchor = None
    for number, (held, shift) in enumerate(parts):
        spots = _spots(held, position, keep)
        move = [0, 0] + [0.0] * len(axes)
        if number:
            move[0] = int(round(shift.get(0, 0)))
            move[1] = -int(round(shift.get(1, 0)))
            for axis in axes:
                move[2 + position[axis]] = shift.get(axis, 0)
            mid = _middle(spots)
            if center and anchor is not None and mid is not None:
                move[0] += floor(anchor[0] - mid[0] + 0.5)
                move[1] += floor(anchor[1] - mid[1] + 0.5)
                for axis in axes:
                    k = 2 + position[axis]
                    step = steps[axis]
                    move[k] += floor((anchor[k] - mid[k]) / step + 0.5) * step
        else:
            anchor = _middle(spots)
        for col, row, vals, cell in spots:
            key = [col + move[0], row + move[1]]
            for k, axis in enumerate(axes):
                key.append(int(round((vals[k] + move[2 + k]) / steps[axis])))
            placed[tuple(key)] = cell
    if not placed:
        return None
    low = [min(key[i] for key in placed) for i in range(2 + len(axes))]
    cells = {tuple(key[i] - low[i] for i in range(len(key))): cell for key, cell in placed.items()}
    ncols = max(key[0] for key in cells) + 1
    nrows = max(key[1] for key in cells) + 1
    counts = [max(key[2 + k] for key in cells) + 1 for k in range(len(axes))]
    spaces = any(held.spaces for held, _ in parts)
    if not any(count > 1 for count in counts):
        rows = [[None] * ncols for _ in range(nrows)]
        for key, cell in cells.items():
            rows[key[1]][key[0]] = cell
        return _cells.build(rows)
    return _assemble(cells, tuple(axes), counts, [steps[axis] for axis in axes], ncols, nrows, spaces)


def scale(held, factors):
    if not held.cells:
        return held
    size = held.size
    counts = [max(1, int(round(n * f))) for n, f in zip(size, factors)]
    volume = 1
    for n in counts:
        volume *= n
    if volume > 2000000:
        raise ValueError('the scaled sprite would hold %d cells' % volume)

    def span(k, j):
        f = factors[k]
        n = size[k]
        if f < 1:
            lo = int(j / f)
            return lo, min(n, max(lo + 1, int(math.ceil((j + 1) / f))))
        lo = int((j + 0.5) / f)
        return (lo, lo + 1) if k == 0 else (min(n - 1, lo), min(n - 1, lo) + 1)

    order = [1, 0] + list(range(2, len(size)))
    src = held.cells
    cells = {}
    for index in itertools.product(*[range(n) for n in counts]):
        found = [span(k, index[k]) for k in range(len(size))]
        mid = [(index[k] + 0.5) / factors[k] for k in range(len(size))]
        best = None
        near = 0.0
        for pick in itertools.product(*[range(*found[k]) for k in order]):
            key = [0] * len(size)
            for k, value in zip(order, pick):
                key[k] = value
            cell = src.get(tuple(key))
            if cell is None or _cells.blank(cell):
                continue
            dist = 0.0
            for k in range(len(size)):
                dist += (key[k] + 0.5 - mid[k]) ** 2
            if best is None or dist < near:
                best, near = cell, dist
        if best is not None:
            cells[index] = best
    return _assemble(cells, held.axes, counts[2:], list(held.steps), counts[0], counts[1], held.spaces)
