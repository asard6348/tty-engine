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
