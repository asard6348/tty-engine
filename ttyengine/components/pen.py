from .shared import _SHAPES, _footprint
from .inherit import _lerpable
from .transform import transform

class pen(_lerpable):
    _owned = ['penchar', 'penx', 'peny', 'pradius', 'pshape']
    _required = [transform]
    _settings = ('char', 'x', 'y', 'radius', 'shape')
    _aliases = {'char': 'penchar', 'x': 'penx', 'y': 'peny', 'radius': 'pradius', 'shape': 'pshape'}

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.scene = obj.scene
        self._x = kwargs.get('penx', 0)
        self._y = kwargs.get('peny', 0)
        self._px = self._x
        self._py = self._y
        self.char = kwargs.get('penchar', '█')
        self.pradius = kwargs.get('pradius', 1)
        self.pshape = kwargs.get('pshape', 'circle')
        self.active = False
        self.current_obj = None
        self._pixels = {}
        self._path = []
        self._hits = {}
        self._ox = 0
        self._oy = 0
        self._pcut = None
        self._cut_walls = {}

    @property
    def x(self):
        return self._x
    @x.setter
    def x(self, value):
        self._x = value

    @property
    def y(self):
        return self._y
    @y.setter
    def y(self, value):
        self._y = value

    @property
    def penchar(self):
        return self.char
    @penchar.setter
    def penchar(self, value):
        self.char = value

    @property
    def penx(self):
        return self._x
    @penx.setter
    def penx(self, value):
        self._x = value

    @property
    def peny(self):
        return self._y
    @peny.setter
    def peny(self, value):
        self._y = value

    @property
    def radius(self):
        return self._pradius
    @radius.setter
    def radius(self, value):
        self.pradius = value

    @property
    def shape(self):
        return self._pshape
    @shape.setter
    def shape(self, value):
        self.pshape = value

    @property
    def pradius(self):
        return self._pradius
    @pradius.setter
    def pradius(self, value):
        # same meaning as `r` in cut/cutcommit (1 = a single cell). Values below 1 are treated as 1.
        self._pradius = max(1, value)

    @property
    def pshape(self):
        return self._pshape
    @pshape.setter
    def pshape(self, value):
        if value not in _SHAPES:
            raise ValueError('shape must be one of: ' + ', '.join(_SHAPES))
        self._pshape = value

    def footprint(self, r=None, shape=None):
        return _footprint(self._pradius if r is None else r, self.scene.aspect, self._pshape if shape is None else shape)

    @property
    def char(self):
        return self._char
    @char.setter
    def char(self, value):
        self._char = value
        self._pchar = value

    def down(self, x=None, y=None, char=None, **kwargs):
        if self.active:
            return self.current_obj
        self.active = True
        self._pixels = {}
        if x is not None: self._x = x
        if y is not None: self._y = y
        self._ox = round(self._x)
        self._oy = round(self._y)
        self._px = self._ox
        self._py = self._oy
        self._pchar = char or self.char
        self._pixels = {}
        self._brush(0, 0)
        self._path = [(0, 0)]
        self._hits = {(0, 0): 1}
        for key, value in (('text', self._pchar), ('x', self._ox), ('y', self._oy)):
            kwargs.setdefault(key, value)
        self.current_obj = self.scene.obj().create(**kwargs)
        if self._pradius > 1:
            self._rebuild()
        return self.current_obj

    def trail(self):
        return [(self._ox + x, self._oy + y) for (x, y) in self._pixels]

    def commit(self, **kwargs):
        if self.current_obj is None or self.current_obj not in self.scene.objs:
            return None
        return self.current_obj.create(**kwargs)

    def up(self, **kwargs):
        finished = self.commit(**kwargs)
        self.active = False
        self.current_obj = None
        self._pixels = {}
        return finished

    def drop(self):
        if self.current_obj is not None and self.current_obj in self.scene.objs:
            self.current_obj.discard()
        self.active = False
        self.current_obj = None
        self._pixels = {}

    def move(self, x, y, rebuild=True):
        self._x = x
        self._y = y
        if self.active:
            self._plot(rebuild)

    def _plot(self, rebuild=True):
        nx = round(self._x)
        ny = round(self._y)
        for (ix, iy) in self._line(self._px, self._py, nx, ny):
            self._stamp(ix - self._ox, iy - self._oy)
        self._px = nx
        self._py = ny
        if rebuild:
            self._rebuild()

    def _stamp(self, x, y):
        path = self._path
        if path and path[-1] == (x, y):
            return
        path.append((x, y))
        self._brush(x, y)
        self._hits[(x, y)] = self._hits.get((x, y), 0) + 1
        if len(path) < 3 or self._pradius > 1:
            return
        ax, ay = path[-3]
        bx, by = path[-2]
        if abs(x - ax) == 1 and abs(y - ay) == 1 and (bx, by) in ((ax, y), (x, ay)) and self._hits[(bx, by)] == 1:
            del self._pixels[(bx, by)]
            del self._hits[(bx, by)]
            del path[-2]

    def _brush(self, x, y):
        for dx, dy in self.footprint():
            self._pixels[(x + dx, y + dy)] = self._pchar

    def _line(self, x0, y0, x1, y1):
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        points = []
        while True:
            points.append((x0, y0))
            if x0 == x1 and y0 == y1:
                return points
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def _rebuild(self):
        if not self._pixels or self.current_obj is None or self.current_obj not in self.scene.objs:
            return

        xs = [p[0] for p in self._pixels]
        ys = [p[1] for p in self._pixels]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        rows = []
        for row_y in range(max_y, min_y - 1, -1):
            row = ''
            for col_x in range(min_x, max_x + 1):
                row += self._pixels.get((col_x, row_y), ' ')
            rows.append(row)

        t = self.current_obj.transform
        t.x = self._ox + min_x
        t.y = self._oy + max_y
        t.text = '\n'.join(rows)

    def cut(self, wx, wy, r=0, when=True, shape=None):
        shape = self._pshape if shape is None else shape
        end = (round(wx), round(wy))
        start = self._pcut if self._pcut is not None else end
        self._pcut = end
        cut = False
        for o in list(self.scene.objs):
            if o is self.obj or not hasattr(o, 'transform') or not (when(o) if callable(when) else when):
                continue
            t = o.transform
            if r == 0:
                walls = t.cutline(start, end)
                if walls:
                    entry = self._cut_walls.setdefault(id(o), (o, set()))
                    if entry[1] is not None:
                        entry[1].update(walls)
                    cut = True
            else:
                for ix, iy in self._line(*start, *end):
                    if t.cut(ix, iy, r=r, shape=shape):
                        self._cut_walls.setdefault(id(o), (o, None))
                        cut = True
        return cut

    def cutcommit(self, r=0, callback=None, diagonal=True, keep=False, **kwargs):
        cut_objs = []
        for o, wall_pixels in list(self._cut_walls.values()):
            if o not in self.scene.objs:
                continue
            o.create(**kwargs)
            if r == 0 and wall_pixels:
                o.transform.split_at(wall_pixels, callback=callback, diagonal=diagonal)
            else:
                o.transform.split(callback=callback, diagonal=diagonal)
            cut_objs.append(o)
        self._cut_walls = {}
        if not keep:
            self._pcut = None
        return cut_objs

    def cancel(self):
        self._pcut = None
        self._cut_walls = {}
