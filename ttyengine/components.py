#_owned - list of owned variables which will be inspected upon obj().create()
#_required - list of required components to be included upon obj().create()
#_default - bool of the component auto-inclusion upon obj().create()
#def on_discard() - function that will be called upon obj().discard()

#MODULES
import math, re, sys, statistics, inspect

#GLOBAL
_RESET_FG = '\033[22;23;24;39m'
_NEIGHBOURS4 = ((-1, 0), (1, 0), (0, -1), (0, 1))
_NEIGHBOURS8 = _NEIGHBOURS4 + ((-1, -1), (1, -1), (-1, 1), (1, 1))

def _argslen(cb):
    params = inspect.signature(cb).parameters
    l = len(params) - (1 if hasattr(cb, '__self__') else 0)
    return l

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

class _metainit(type):
    def __new__(mcs, name, bases, attrs, **kwargs):
        init_val = kwargs.pop('init', None)
        cls = super().__new__(mcs, name, bases, attrs, **kwargs)
        if init_val:
            cls._target_init = init_val
        return cls
    def __call__(cls, *args, **kwargs):
        inst = super().__call__(*args, **kwargs)
        initfunc = getattr(cls, '_target_init', '_init')
        instinit = getattr(inst, initfunc, None)
        if instinit:
            instinit()
        return inst

class _change_callback(metaclass=_metainit, init='_chinit'):
    def _chinit(self):
        self._onchangecb = {}
        self._changing = False
        def cln():
            discarded = self.obj
            for other in self.obj.scene.objs:
                com = getattr(other, self.__class__.__name__, None)
                if other is discarded or not com or not hasattr(com, '_onchangecb'):
                    continue
                com._onchangecb = {
                    cb:par for cb,par in com._onchangecb.items()
                    if not _closure_refs(cb, discarded)
                }
        if not hasattr(self, 'on_discard'):
            self.on_discard = cln
        else:
            old_func = self.on_discard
            def cln_():
                try:
                    old_func(self) 
                except TypeError:
                    old_func()
                cln()
            self.on_discard = cln_

    def onchange(self, cb, once=False):
        if once:
            match_attr = once if isinstance(once, str) else None
            l = _argslen(cb)
            fired = [False]
            orig = cb
            def wrapped(attr=None, old=None, internal=False):
                if fired[0]: return
                if match_attr is not None and attr != match_attr: return
                fired[0] = True
                if wrapped in self._onchangecb:
                    del self._onchangecb[wrapped]
                if l > 2: orig(attr, old, internal)
                elif l > 1: orig(attr, old)
                elif l > 0: orig(attr)
                else: orig()
            cb = wrapped
            self._onchangecb[cb] = 3
        else:
            self._onchangecb[cb] = _argslen(cb)
        return cb

    def offchange(self, cb):
        self._onchangecb = {f:par for f,par in self._onchangecb.items() if f is not cb}

    def _change(self, attr, old):
        internal = self._changing
        self._changing = True
        try:
            for cb, l in list(self._onchangecb.items()):
                if l > 2:
                    cb(attr, old, internal)
                elif l > 1:
                    cb(attr, old)
                elif l > 0:
                    cb(attr)
                else:
                    cb()
        finally:
            self._changing = internal


#COMPONENTS
class transform(_change_callback):
    _owned = [
        'x', 'y',
        'vx', 'vy',
        'text', 'rtext', 'htext',
        'vtext', 'vrtext', 'vhtext',
        'rotation',
        'aspect',
    ]
    _default = True

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.scene = obj.scene
        raw = kwargs.get('text', '')
        ctext = obj.scene.recomp.sub('', raw) if raw else ''
        self._x = kwargs.get('x', 0)
        self._y = kwargs.get('y', 0)
        self._vx = kwargs.get('vx', 0)
        self._vy = kwargs.get('vy', 0)
        self.vtext = raw
        self.vrtext = raw
        self.vhtext = raw
        self._text = ctext
        self._rtext = ctext
        self._htext = ctext
        self._rotation = kwargs.get('rotation', 0)
        self._rot_cache_angle = None
        self.aspect = kwargs.get('aspect', 0.5)
        self._onsplit = {}
        self._xlen_cache = None
        self._ylen_cache = None
        self._parse_pixels_key = None
        self._parse_pixels_val = None
        self._centroid_cache = {}
        self._rotmap = None
        self._rotcells = {}
        self._onchangecb = {}
        self._changing = False
        self.rotate(self._rotation, init=True)

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def _invalidate(self):
        self._xlen_cache = None
        self._ylen_cache = None
        self._parse_pixels_key = None
        self._parse_pixels_val = None
        self._centroid_cache = {}
        self._rot_cache_angle = None

    @property
    def x(self):
        return self._x
    @x.setter
    def x(self, value):
        old = self._x
        self._x = value
        self._change('x', old)

    @property
    def y(self):
        return self._y
    @y.setter
    def y(self, value):
        old = self._y
        self._y = value
        self._change('y', old)

    @property
    def vx(self):
        return self._vx
    @vx.setter
    def vx(self, value):
        old = self._vx
        self._vx = value
        self._change('vx', old)

    @property
    def vy(self):
        return self._vy
    @vy.setter
    def vy(self, value):
        old = self._vy
        self._vy = value
        self._change('vy', old)

    @property
    def text(self):
        return self._text
    @text.setter
    def text(self, value):
        old = self._text
        ctext = self.scene.recomp.sub('', value)
        self.vrtext = value
        self.vhtext = value
        self._htext = ctext
        self._rtext = ctext
        self._invalidate()
        self.rotate(self._rotation)
        self._change('text', old)

    @property
    def rtext(self):
        return self._rtext
    @rtext.setter
    def rtext(self, value):
        old = self._rtext
        ctext = self.scene.recomp.sub('', value)
        self.vrtext = value
        self._rtext = ctext
        self._invalidate()
        self.rotate(self._rotation)
        self._change('rtext', old)

    @property
    def htext(self):
        return self._htext
    @htext.setter
    def htext(self, value):
        old = self._htext
        ctext = self.scene.recomp.sub('', value)
        self.vrtext = value
        self.vhtext = value
        self._htext = ctext
        self._rtext = ctext
        self._invalidate()
        self.rotate(self._rotation)
        self._change('htext', old)

    @property
    def rotation(self):
        return self._rotation
    @rotation.setter
    def rotation(self, value):
        old = self._rotation
        oldt = self._text
        self._rotation = value
        self.rotate(value)
        self._change('rotation', old)
        self._change('text', oldt)

    def _pixel_centroid(self, txt):
        cached = self._centroid_cache.get(id(txt))
        if cached is not None and cached[0] == txt:
            return cached[1]
        clean = self.scene.recomp.sub('', txt)
        xs, ys = [], []
        for ri, row in enumerate(clean.splitlines()):
            for ci, char in enumerate(row):
                if char not in (' ', '\n'):
                    xs.append(ci)
                    ys.append(ri)
        result = (sum(xs) / len(xs), sum(ys) / len(ys)) if xs else (0.0, 0.0)
        self._centroid_cache[id(txt)] = (txt, result)
        return result

    def parse_pixels(self, text):
        if self._parse_pixels_key is not None and self._parse_pixels_key == text:
            return self._parse_pixels_val
        pixels = {}
        current_style = ''
        for ri, line in enumerate(text.splitlines()):
            ci = 0
            for part in self.scene.recomp.split(line):
                if not part:
                    continue
                if self.scene.recomp.match(part):
                    if part == '\033[0m':
                        current_style = ''
                    else:
                        current_style += part
                else:
                    for char in part:
                        pixels[(ci, ri)] = (char, current_style)
                        ci += 1
        self._parse_pixels_key = text
        self._parse_pixels_val = pixels
        return pixels

    def build_rows(self, pixels, min_x, max_x, min_y, max_y):
        out_rows = []
        for ri in range(min_y, max_y + 1):
            row = ''
            prev_style = ''
            for ci in range(min_x, max_x + 1):
                if (ci, ri) in pixels:
                    char, style = pixels[(ci, ri)]
                    if style != prev_style:
                        row += ('\033[0m' if prev_style else '') + style
                        prev_style = style
                    row += char
                else:
                    if prev_style:
                        row += '\033[0m'
                        prev_style = ''
                    row += ' '
            if prev_style:
                row += '\033[0m'
            out_rows.append(row)
        return '\n'.join(out_rows)

    def tolocal(self, pixels):
        rx = round(self._x + self.vx)
        ry = round(self._y + self.vy)
        local_pixels = set()
        for gx, gy in pixels:
            local_pixels.add((gx - rx, ry - gy))
        return local_pixels

    def toworld(self, pixels):
        rx = round(self._x + self.vx)
        ry = round(self._y + self.vy)
        local_pixels = set()
        for gx, gy in pixels:
            local_pixels.add((gx + rx, ry + gy))
        return local_pixels

    def rotate(self, angle_degrees, init=False):
        if not init:
            rounded = round(angle_degrees * 20) / 20
            if self._rot_cache_angle == rounded:
                return
            self._rot_cache_angle = rounded

        angle = math.radians(angle_degrees)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        ASPECT = self.aspect

        def cal(txt, record=False):
            crows = self.scene.recomp.sub('', txt).splitlines()
            if not crows:
                if record:
                    self._rotmap = None
                    self._rotcells = {}
                return ''
            height = len(crows)
            width  = max(len(r) for r in crows) if crows else 0
            cx, cy = width / 2, height / 2

            new_pixels = {}
            cells = {}
            for (x, y), (char, style) in self.parse_pixels(txt).items():
                rel_x, rel_y = x - cx, y - cy
                rx_n = rel_x * ASPECT * cos_a - rel_y * sin_a
                ry_n = rel_x * ASPECT * sin_a + rel_y * cos_a
                nx = int(round(rx_n / ASPECT + cx))
                ny = int(round(ry_n + cy))
                if (nx, ny) not in new_pixels or new_pixels[(nx, ny)][0] == ' ':
                    new_pixels[(nx, ny)] = (char, style)
                if record and char != ' ':
                    cells.setdefault((nx, ny), []).append((x, y))

            if not new_pixels:
                if record:
                    self._rotmap = None
                    self._rotcells = {}
                return ''
            all_xs = [p[0] for p in new_pixels]
            ns_ys  = [p[1] for p in new_pixels if new_pixels[p][0] != ' ']
            if not ns_ys:
                if record:
                    self._rotmap = None
                    self._rotcells = {}
                return ''
            min_x, min_y = min(all_xs), min(ns_ys)
            if record:
                self._rotmap = (cx, cy, min_x, min_y, ASPECT, cos_a, sin_a)
                self._rotcells = cells
            return self.build_rows(new_pixels, min_x, max(all_xs), min_y, max(ns_ys))

        self.vtext = cal(self.vrtext)
        self._text = cal(self._rtext, True)
        self._xlen_cache = None
        self._ylen_cache = None

        orig_cx, orig_cy = self._pixel_centroid(self._rtext)
        rot_cx,  rot_cy  = self._pixel_centroid(self._text)
        self.vx = round(orig_cx - rot_cx)
        self.vy = -round(orig_cy - rot_cy)

    def _origin(self):
        return round(self._x + self.vx), round(self._y + self.vy)

    def rtext_to_world(self, ci, ri):
        m = self._rotmap
        if m is None:
            return None
        cx, cy, min_x, min_y, ASPECT, cos_a, sin_a = m
        rel_x = ci - cx
        rel_y = ri - cy
        rx_n = rel_x * ASPECT * cos_a - rel_y * sin_a
        ry_n = rel_x * ASPECT * sin_a + rel_y * cos_a
        nx = int(round(rx_n / ASPECT + cx))
        ny = int(round(ry_n + cy))
        ox, oy = self._origin()
        return ox + (nx - min_x), oy - (ny - min_y)

    def world_to_rtext_all(self, wx, wy):
        m = self._rotmap
        if m is None:
            return []
        ox, oy = self._origin()
        return self._rotcells.get((wx - ox + m[2], oy - wy + m[3]), [])

    def world_to_rtext(self, wx, wy):
        found = self.world_to_rtext_all(wx, wy)
        return found[0] if found else None

    def world_to_rtextf(self, wx, wy):
        m = self._rotmap
        if m is None:
            return None
        cx, cy, min_x, min_y, ASPECT, cos_a, sin_a = m
        ox, oy = self._origin()
        rx_n = (wx - ox + min_x - cx) * ASPECT
        ry_n = oy - wy + min_y - cy
        rel_x = (rx_n * cos_a + ry_n * sin_a) / ASPECT
        rel_y = -rx_n * sin_a + ry_n * cos_a
        return rel_x + cx, rel_y + cy

    def cutline(self, p0, p1):
        a = self.world_to_rtextf(*p0)
        b = self.world_to_rtextf(*p1)
        if a is None or b is None:
            return set()
        width, height = self._rotmap[0] * 2, self._rotmap[1] * 2
        if (max(a[0], b[0]) < -1 or min(a[0], b[0]) > width
                or max(a[1], b[1]) < -1 or min(a[1], b[1]) > height):
            return set()
        steps = max(1, int(math.ceil(max(abs(b[0] - a[0]), abs(b[1] - a[1])) * 2)))
        pixels = self.parse_pixels(self.vrtext)
        walls = set()
        for i in range(steps + 1):
            u = i / steps
            c = (round(a[0] + (b[0] - a[0]) * u), round(a[1] + (b[1] - a[1]) * u))
            if c in pixels and pixels[c][0] != ' ':
                walls.add(c)
        return walls

    def _clear(self, cells):
        styled = self.parse_pixels(self.vrtext)
        hit = [c for c in cells if c in styled and styled[c][0] != ' ']
        if not hit:
            return False
        styled = dict(styled)
        for c in hit:
            styled[c] = (' ', '')
        ref = next((p for p, (char, _) in styled.items() if char != ' '), None)
        before = self.rtext_to_world(*ref) if ref is not None else None
        xs = [p[0] for p in styled]
        ys = [p[1] for p in styled]
        self.rtext = self.build_rows(styled, min(xs), max(xs), min(ys), max(ys))
        after = self.rtext_to_world(*ref) if ref is not None else None
        if before is not None and after is not None:
            if before[0] != after[0]:
                self.x = self._x + before[0] - after[0]
            if before[1] != after[1]:
                self.y = self._y + before[1] - after[1]
        return True

    def cut(self, wx, wy, r=1):
        cells = []
        for dy in range(-(r - 1), r):
            for dx in range(-(r - 1), r):
                cells.extend(self.world_to_rtext_all(wx + dx, wy + dy))
        return self._clear(cells)

    def cutpoints(self, points, r=1):
        cells = []
        for wx, wy in points:
            for dy in range(-(r - 1), r):
                for dx in range(-(r - 1), r):
                    cells.extend(self.world_to_rtext_all(wx + dx, wy + dy))
        return self._clear(cells)

    def _notify_whole(self, callback):
        if callable(callback):
            l = _argslen(callback)
            if l > 1: callback([self.obj], self.obj)
            elif l > 0: callback([self.obj])
            else: callback()

    def _fragments(self, coords, diagonal=True, walls=()):
        walls = set(walls)
        neighbours = _NEIGHBOURS8 if diagonal else _NEIGHBOURS4
        remaining = set(coords)
        components = []
        while remaining:
            group = set()
            stack = [next(iter(remaining))]
            while stack:
                pos = stack.pop()
                if pos not in remaining:
                    continue
                remaining.remove(pos)
                group.add(pos)
                cx, cy = pos
                for dx, dy in neighbours:
                    nxt = (cx + dx, cy + dy)
                    if nxt not in remaining:
                        continue
                    if dx and dy and (cx + dx, cy) in walls and (cx, cy + dy) in walls:
                        continue
                    stack.append(nxt)
            components.append(group)
        return components

    def _spawn_from_components(self, components, pixels, callback=None):
        rotation = self._rotation
        ox, oy = self._x, self._y

        spawns = []
        anchors = []
        pivot = self._rotmap
        for group in components:
            xs = [p[0] for p in group]
            ys = [p[1] for p in group]
            min_x, max_x = min(xs), max(xs) + 1
            min_y, max_y = min(ys), max(ys) + 1
            if pivot is not None and rotation % 360:
                min_x, max_x = min(min_x, round(2 * pivot[0]) - max_x), max(max_x, round(2 * pivot[0]) - min_x)
                min_y, max_y = min(min_y, round(2 * pivot[1]) - max_y), max(max_y, round(2 * pivot[1]) - min_y)
            target = {w for w in (self.rtext_to_world(ci, ri) for ci, ri in group) if w is not None}

            kw = self.obj.kwargs()
            for key in ('mass', 'rtext', 'htext', 'vtext', 'vrtext', 'vhtext', 'vx', 'vy'):
                kw.pop(key, None)
            spawns.append({
                **kw,
                'text': self.build_rows({p: pixels[p] for p in group}, min_x, max_x - 1, min_y, max_y - 1),
                'x': ox + min_x,
                'y': oy - min_y,
                'rotation': rotation,
            })
            anchors.append(([(ci - min_x, ri - min_y) for ci, ri in group], target))

        obj_ref = self.obj
        def do_split(spawns=spawns, anchors=anchors, obj_ref=obj_ref, cb=callback):
            parts = []
            for kw, (local, target) in zip(spawns, anchors):
                part = obj_ref.scene.obj().create(**kw)
                ft = part.transform
                if target:
                    placed = {w for w in (ft.rtext_to_world(*p) for p in local) if w is not None}
                    if placed:
                        dx = round(sum(w[0] for w in target) / len(target) - sum(w[0] for w in placed) / len(placed))
                        dy = round(sum(w[1] for w in target) / len(target) - sum(w[1] for w in placed) / len(placed))
                        best = min(
                            ((sx, sy) for sx in range(dx - 1, dx + 2) for sy in range(dy - 1, dy + 2)),
                            key=lambda s: len({(wx + s[0], wy + s[1]) for wx, wy in placed} ^ target)
                        )
                        ft.x = ft.x + best[0]
                        ft.y = ft.y + best[1]
                parts.append(part)
            if callable(cb):
                l = _argslen(cb)
                if l > 1: cb(parts, obj_ref)
                elif l > 0: cb(parts)
                else: cb()
            for calb, cl in list(self._onsplit.items()):
                if cl > 1: calb(parts, obj_ref)
                elif cl > 0: calb(parts)
                else: calb()
            obj_ref.discard()
        do_split()
        return do_split

    def split(self, callback=None, diagonal=True):
        if getattr(self.obj, 'transform', None) is not self:
            return
        pixels = self.parse_pixels(self.vrtext)
        coords = {pos for pos, (char, _) in pixels.items() if char != ' '}
        if not coords:
            self._notify_whole(callback)
            self.obj.discard()
            return

        components = self._fragments(coords, diagonal)
        if len(components) < 2:
            self._notify_whole(callback)
            return

        self._split_cb = self._spawn_from_components(components, pixels, callback)
        return self._split_cb

    def split_at(self, wall_pixels, callback=None, diagonal=True):
        if getattr(self.obj, 'transform', None) is not self:
            return
        pixels = self.parse_pixels(self.vrtext)
        coords = {pos for pos, (char, _) in pixels.items() if char != ' '}

        valid_walls = set(wall_pixels) & coords
        if not valid_walls:
            self._notify_whole(callback)
            return

        components = self._fragments(coords - valid_walls, diagonal, valid_walls)
        if len(components) < 2:
            self._notify_whole(callback)
            return

        neighbours = _NEIGHBOURS8 if diagonal else _NEIGHBOURS4
        for wp in valid_walls:
            cx, cy = wp
            nearest = None
            for comp in components:
                if any((cx + dx, cy + dy) in comp for dx, dy in neighbours):
                    nearest = comp
                    break
            if nearest is not None:
                nearest.add(wp)

        self._split_cb = self._spawn_from_components(components, pixels, callback)
        return self._split_cb

    def onsplit(self, cb, once=False):
        if once:
            l = _argslen(cb)
            fired = [False]
            orig = cb
            def wrapped(parts=None, obj_ref=None):
                if fired[0]: return
                fired[0] = True
                if wrapped in self._onsplit:
                    del self._onsplit[wrapped]
                if l > 1: orig(parts, obj_ref)
                elif l > 0: orig(parts)
                else: orig()
            cb = wrapped
            self._onsplit[cb] = 2
        else:
            self._onsplit[cb] = _argslen(cb)
        return cb

    def offsplit(self, cb):
        self._onsplit = {f:par for f,par in self._onsplit.items() if f is not cb}

    def xlen(self, text=None):
        if text is None:
            if self._xlen_cache is not None:
                return self._xlen_cache
            text = self._text
            lens = []
            for row in text.splitlines():
                for i, char in enumerate(row):
                    if char != ' ':
                        lens.append(i)
            result = abs(max(lens) - (min(lens) - 1)) if lens else 0
            self._xlen_cache = result
            return result
        lens = []
        for row in text.splitlines():
            for i, char in enumerate(row):
                if char != ' ':
                    lens.append(i)
        return abs(max(lens) - (min(lens) - 1)) if lens else 0

    def ylen(self, text=None):
        if text is None:
            if self._ylen_cache is not None:
                return self._ylen_cache
            text = self._text
            count = 0
            for row in text.splitlines():
                if any(c != ' ' and c != '\n' for c in row):
                    count += 1
            self._ylen_cache = count
            return count
        count = 0
        for row in text.splitlines():
            if any(c != ' ' and c != '\n' for c in row):
                count += 1
        return count

    def xc(self, text=None):
        return self.xlen(text) / 2

    def yc(self, text=None):
        return self.ylen(text) / 2

    def forward(self, move=1, offset=0, angle=None):
        angle = math.radians((self._rotation if angle is None else angle) + offset)
        x = math.sin(angle) * move
        y = math.cos(angle) * self.aspect * move
        return (x, y)

    def point(self, tx, ty, offset=0):
        dx = tx - self._x
        dy = ty - self._y
        ASPECT = self.aspect
        angle = math.degrees(math.atan2(-dy, dx * ASPECT))+90
        return angle + offset

    def aim(self, obj, offset=0):
        return self.point(obj.transform.x, obj.transform.y, offset=offset)

    def alerp(self, angle):
        return (angle - self._rotation + 540) % 360 - 180
    

class rendering():
    _owned = ['show', 'renderspaces', 'z']
    _required = [transform]
    _default = True
    def on_discard(self):
        self.scene.discards.append(self.remove(write=False))

    def __init__(self, obj, **kwargs):
        self.t = obj.transform
        self.scene = obj.scene
        self.px = 0
        self.py = 0
        self.ptext = ''
        self.pxoff = 0
        self.pyoff = 0
        self._show = kwargs.get('show', True)
        self.renderspaces = kwargs.get('renderspaces', False)
        self.z = kwargs.get('z', 0)

    @property
    def show(self):
        return self._show

    @show.setter
    def show(self, value):
        self._show = value

    @property
    def z(self):
        return self._z

    @z.setter
    def z(self, value):
        self._z = value
        if self._z > self.scene._lastz: self.scene._lastz = self._z
        if self._z < self.scene._firstz: self.scene._firstz = self._z

    def redraw(self):
        self.ptext = ''

    def front(self):
        self.z = self.scene._lastz +1

    def back(self):
        self.z = self.scene._firstz -1

    def crop_row(self, row, start, end, renderspaces=False):
        bgcolor = (f'\033[48;2;{self.scene.bgcolor[0]};'
                   f'{self.scene.bgcolor[1]};'
                   f'{self.scene.bgcolor[2]}m')
        result = _RESET_FG
        ci = 0
        active_style  = ''
        needs_restyle = False
        in_crop       = False

        for part in self.scene.recomp.split(row):
            if not part:
                continue
            if self.scene.recomp.match(part):
                if part in ('\033[0m', '\033[m'):
                    active_style = ''
                    if in_crop and not needs_restyle:
                        result += part + bgcolor
                else:
                    active_style += part
                    if in_crop and not needs_restyle:
                        result += part
            else:
                for char in part:
                    if ci >= end:
                        if active_style:
                            result += _RESET_FG
                        return result
                    if ci >= start:
                        if not in_crop:
                            in_crop = True
                            if active_style:
                                result += active_style
                        if char == ' ' and not renderspaces:
                            result += '\033[C'
                            needs_restyle = bool(active_style)
                        else:
                            if needs_restyle:
                                result += active_style
                                needs_restyle = False
                            result += char
                    ci += 1

        if active_style:
            result += _RESET_FG
        return result

    def render_rows(self, text, ox, oy, xoff, yoff, erase=False, exclude_rects=None):
        bgcolor = (f'\033[48;2;{self.scene.bgcolor[0]};'
                   f'{self.scene.bgcolor[1]};'
                   f'{self.scene.bgcolor[2]}m')
        out  = ''
        term_w     = self.scene.termx
        term_h     = self.scene.termy
        sim_bottom = -yoff + self.scene.dimy
        sim_right  = xoff + self.scene.dimx
        for i, row in enumerate(text.split('\n')):
            scene_row = oy + 1 + i
            if not (1 <= scene_row <= self.scene.dimy):
                continue
            sy = -yoff + scene_row
            if not (1 <= sy <= min(term_h, sim_bottom)):
                continue
            crop_start = abs(min(0, ox))
            crop_end   = term_w - xoff - max(0, ox)
            if crop_end <= 0:
                continue
            sx = xoff + max(0, ox) + 1
            if sx < 1:
                extra = 1 - sx
                crop_start += extra
                crop_end   -= extra
                sx = 1
            if crop_end <= 0:
                continue
            crop_end = min(crop_end, term_w - (sx - 1))
            crop_end = min(crop_end, sim_right - sx + 1)
            if crop_end <= 0:
                continue

            if exclude_rects:
                segments = []
                seg_start = sx
                seg_crop  = crop_start
                seg_end   = sx + crop_end - 1
                excluded = sorted(
                    [(max(sx, r[0]), min(seg_end, r[2]))
                     for r in exclude_rects
                     if r[1] <= sy <= r[3] and r[0] <= seg_end and r[2] >= sx],
                    key=lambda r: r[0]
                )
                cursor = sx
                ccrop  = crop_start
                for ex1, ex2 in excluded:
                    if cursor < ex1:
                        segments.append((cursor, ccrop, ex1 - cursor))
                    skip = ex2 - cursor + 1
                    cursor = ex2 + 1
                    ccrop += skip
                if cursor <= seg_end:
                    segments.append((cursor, ccrop, seg_end - cursor + 1))
            else:
                segments = [(sx, crop_start, crop_end)]

            for seg_sx, seg_crop_start, seg_crop_end in segments:
                if seg_crop_end <= 0:
                    continue
                if erase:
                    clean   = self.scene.recomp.sub('', row)
                    visible = clean[seg_crop_start:seg_crop_start + seg_crop_end]
                    arow = ''.join(
                        '\033[C' if c == ' ' and not self.renderspaces else ' '
                        for c in visible
                    )
                    out += f'\033[{sy}d\033[{seg_sx}G{arow}'
                else:
                    arow = self.crop_row(row, seg_crop_start, seg_crop_start + seg_crop_end, self.renderspaces)
                    out += f'\033[{sy}d\033[{seg_sx}G{bgcolor}{arow}'
        return out

    def remove(self, write=True):
        if not self.ptext:
            return ''
        bgcolor = (f'\033[48;2;{self.scene.bgcolor[0]};'
                   f'{self.scene.bgcolor[1]};'
                   f'{self.scene.bgcolor[2]}m')
        xoff       = self.scene.dimxoffset
        yoff       = -self.scene.dimyoffset
        term_w     = self.scene.termx
        term_h     = self.scene.termy
        sim_bottom = -self.scene.dimyoffset + self.scene.dimy
        sim_right  = self.scene.dimxoffset + self.scene.dimx
        out = ''
        for i, row in enumerate(self.ptext.split('\n')):
            scene_row = self.py + 1 + i
            if not (1 <= scene_row <= self.scene.dimy):
                continue
            sy = yoff + scene_row
            if not (1 <= sy <= min(term_h, sim_bottom)):
                continue
            sx       = xoff + max(0, self.px) + 1
            max_width = min(
                term_w - (sx - 1),
                sim_right - sx + 1,
            )
            max_width = max(0, max_width)
            if not max_width:
                continue
            clean = self.scene.recomp.sub('', row)
            arow  = ' ' * min(len(clean), max_width)
            out  += f'\033[{sy}d\033[{sx}G{bgcolor}{arow}\033[0m'
        rem = out + '\033[0m'
        if write:
            sys.stdout.write(rem)
            sys.stdout.flush()
            self.ptext = ''
        return rem

    def render(self, write=True, split=False, exclude_rects=None):
        if not self.t.rtext:
            return ('', '') if split else ''
        bgcolor = (f'\033[48;2;{self.scene.bgcolor[0]};'
                   f'{self.scene.bgcolor[1]};{self.scene.bgcolor[2]}m')
        ir = self.scene.iround
        if self._show:
            current = (
                ir(((self.t.x) + (self.t.vx)) - ir(self.scene.camx)),
                -ir(((self.t.y) + (self.t.vy)) - ir(self.scene.camy)),
                self.t.vtext,
                self.scene.dimxoffset,
                self.scene.dimyoffset,
            )
        else:
            current = (0, 0, '', 0, 0)
        previous = (self.px, self.py, self.ptext, self.pxoff, self.pyoff)
        if current == previous:
            return ('', '') if split else ''
        acx, acy, actext, acxoff, acyoff = current
        px, py, ptext, pxoff, pyoff = previous

        remove_output = ''
        if ptext:
            remove_output = f'{bgcolor}{self.render_rows(ptext, px, py, pxoff, pyoff, erase=True, exclude_rects=exclude_rects)}\033[0m'
        draw_output = ''
        if actext:
            draw_output = f'{bgcolor}{self.render_rows(actext, acx, acy, acxoff, acyoff, erase=False, exclude_rects=exclude_rects)}\033[0m'

        self.px, self.py, self.ptext, self.pxoff, self.pyoff = current

        if write:
            sys.stdout.write(remove_output + draw_output)
            sys.stdout.flush()
        return (remove_output, draw_output) if split else remove_output + draw_output


class physics(_change_callback):
    _owned = [
        'xvel', 'yvel', 'avel',
        'dynamic',
        'bounciness',
        'mass', 'automass',
        'solid',
        'hitbox',
        'touch',
        'phantom',
    ]
    _required = [transform]
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

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.t = obj.transform
        self.scene = obj.scene
        self._axises = ('x', 'y')
        self.aspect = (1, self.t.aspect)
        self._xvel = kwargs.get('xvel', 0)
        self._yvel = kwargs.get('yvel', 0)
        self._avel = kwargs.get('avel', 0)
        self.dynamic = kwargs.get('dynamic', True)
        self.bounciness = kwargs.get('bounciness', 0)
        self.mass = kwargs.get('mass', None)
        self.automass = kwargs.get('automass', self.mass is None)
        def masscal(prop='text'):
            if self.automass and prop.endswith('text'):
                self.mass = sum(1 for c in self.t._rtext if c not in (' ', '\n'))
        if self.mass is None:
            masscal()
        self.t.onchange(masscal)
        self.solid = kwargs.get('solid', True)
        self.hitbox = kwargs.get('hitbox', False)
        self.phantom = kwargs.get('phantom', False)
        self.touch = (False, False)
        self._touch_callbacks = []
        self._pixel_cache = None
        self.t.onchange(self._dirty)

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

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

    def _dirty(self):
        self._pixel_cache = None

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

    def getpixels(self, x=None, y=None, text=None):
        default_call = x is None and y is None and text is None
        if default_call and self._pixel_cache is not None:
            return self._pixel_cache

        x = self.t.x if x is None else x
        y = self.t.y if y is None else y
        text = self.t._text if text is None else text
        text = self.t._htext if self.hitbox else text
        rx = round(x + self.t.vx) if not self.hitbox else round(x)
        ry = round(y + self.t.vy) if not self.hitbox else round(y)
        pixels = set()
        for i, row in enumerate(text.splitlines()):
            for j, char in enumerate(row):
                if (char != ' ' and char != '\n' and not self.hitbox) or self.hitbox:
                    pixels.add((rx + j, ry - i))

        if default_call:
            self._pixel_cache = pixels
        return pixels

    def collides(self, objs, x=None, y=None, text=None):
        pixels1 = self.getpixels(x, y, text)
        if not pixels1:
            return {}

        # bbox of self for fast rejection
        p1_xs = [p[0] for p in pixels1]
        p1_ys = [p[1] for p in pixels1]
        bx1_min, bx1_max = min(p1_xs), max(p1_xs)
        by1_min, by1_max = min(p1_ys), max(p1_ys)

        if not isinstance(objs, list):
            objs = [objs]

        result = {}
        for obj2 in objs:
            if obj2 is self.obj:
                continue
            pixels2 = obj2.physics.getpixels()
            if not pixels2:
                continue
            # bbox pre-rejection
            p2_xs = [p[0] for p in pixels2]
            p2_ys = [p[1] for p in pixels2]
            if (max(p2_xs) < bx1_min or min(p2_xs) > bx1_max or
                    max(p2_ys) < by1_min or min(p2_ys) > by1_max):
                continue
            intersection = pixels1 & pixels2
            if intersection:
                result[obj2] = intersection
                if not self.phantom:
                    break
        return result

    def armratio(self, points, o, pos=None):
        xi = [p[0] for p in points]
        yi = [p[1] for p in points]
        center = (statistics.mean(xi), statistics.mean(yi))
        arms = []
        for ia, a in enumerate(self._axises):
            poss = o.transform[a] if pos is None else (pos[ia] if isinstance(pos, list) else pos)
            xc = o.transform[a + 'c']()
            if xc == 0:
                arms.append(0.0)
                continue
            ratio = (center[ia] - (poss + xc if ia != 1 else poss - xc)) / xc
            arms.append(round(ratio, 1))
        return arms

    def physics(self, axises=None, aspect=None):
        axises = self._axises if axises is None else axises
        aspect = self.aspect if aspect is None else aspect
        self._dirty()
        actualmass = self.mass

        for ia, a in enumerate(axises): # per-axis step
            opp_ia = 1 - ia
            self[a + 'vel'] *= self.scene.drag
            self[a + 'vel'] += self.scene.gravity[ia] * actualmass
            c = 1 if self[a + 'vel'] > 0 else -1 if self[a + 'vel'] < 0 else 0
            #c *= aspect[ia] if ia < len(aspect) and aspect[ia] else 1
            ch = abs(self[a + 'vel']) / actualmass
            tch = list(self.touch)
            if abs(self[a + 'vel']) > actualmass * 0.1:
                tch[ia] = False
            self.touch = tuple(tch)

            while ch > 0: # step
                step = min(self.scene.precision, ch)
                t = {a: self.t[a] + c * step}
                collisions = self.collides(self.scene.solids, **t)

                # phantom: full sweep for callbacks
                if self.phantom:
                    pixels1 = self.getpixels(**t)
                    for solid_obj in self.scene.solids:
                        if solid_obj is self.obj or solid_obj in collisions:
                            continue
                        solid_p = getattr(solid_obj, 'physics', None)
                        if solid_p is None:
                            continue
                        pixels2 = solid_p.getpixels()
                        intersection = pixels1 & pixels2
                        if intersection:
                            collisions[solid_obj] = intersection

                physical_col = None
                for obj2, intersection in list(collisions.items()):
                    obj2p = getattr(obj2, 'physics', None)
                    if obj2p is None:
                        continue
                    # callbacks
                    for cb in list(self._touch_callbacks):
                        cb(obj2, intersection)
                    if getattr(self.obj, 'physics', None) is not self:
                        return
                    for cb in list(obj2p._touch_callbacks):
                        cb(self.obj, intersection)
                    if getattr(self.obj, 'physics', None) is not self:
                        return
                    if getattr(obj2, 'physics', None) is not obj2p:
                        continue
                    # only resolve physics when both solid and neither phantom
                    if self.solid and not self.phantom and not obj2p.phantom:
                        if physical_col is None:
                            physical_col = (obj2, obj2p, intersection)

                if physical_col is not None:
                    obj2, obj2p, intersection = physical_col
                    othermass = obj2p.mass
                    totalmass = actualmass + othermass

                    pos_list = [self.t.x, self.t.y]
                    pos_list[ia] = self.t[a] + c * step
                    td = self.armratio(intersection, self.obj, pos_list) # arm ratio
                    otd = self.armratio(intersection, obj2)

                    vel_self_before = self[a + 'vel'] # torque
                    vel_obj2_before = obj2p[a + 'vel']
                    resting = self.touch[ia] and abs(self[a + 'vel']) / actualmass < 0.5
                    if obj2p.dynamic and not obj2p.hitbox and not resting:
                        obj2p.avel += actualmass * (otd[opp_ia] * (
                            (vel_obj2_before - vel_self_before) if ia == 1
                            else -(vel_obj2_before - vel_self_before)))
                    if not self.hitbox and not resting:
                        self.avel += actualmass * (td[opp_ia] * (
                            (vel_self_before - vel_obj2_before) if ia == 1
                            else -(vel_self_before - vel_obj2_before)))

                    if obj2p.dynamic: # linear push
                        av1 = self[a + 'vel'] / actualmass
                        av2 = obj2p[a + 'vel'] / othermass
                        new_av1 = ((actualmass - othermass) * av1 + (1 + self.bounciness) * othermass * av2) / totalmass
                        new_av2 = ((othermass - actualmass) * av2 + (1 + obj2p.bounciness) * actualmass * av1) / totalmass
                        self[a + 'vel'] = new_av1 * actualmass
                        obj2p[a + 'vel'] = new_av2 * othermass
                    else:
                        e = max(self.bounciness, obj2p.bounciness)
                        self[a + 'vel'] *= -e

                    tch = list(self.touch)
                    tch[ia] = True
                    self.touch = tuple(tch)
                    break # only break on physical collision

                self.t[a] += c * step
                ch -= step

        # depenetration
        cols = self.collides(self.scene.solids)
        if self.solid and cols and not self.phantom:
            non_phantom = {o: px for o, px in cols.items() if not o.physics.phantom}
            if non_phantom:
                all_inter = set()
                for px in non_phantom.values():
                    all_inter |= px
                my_px = self.getpixels()
                my_cx  = sum(p[0] for p in my_px)    / len(my_px)
                my_cy  = sum(p[1] for p in my_px)    / len(my_px)
                inter_cx = sum(p[0] for p in all_inter) / len(all_inter)
                inter_cy = sum(p[1] for p in all_inter) / len(all_inter)
                inter_w = max(p[0] for p in all_inter) - min(p[0] for p in all_inter) + 1
                inter_h = max(p[1] for p in all_inter) - min(p[1] for p in all_inter) + 1
                if inter_w <= inter_h:
                    self.t.x += inter_w * (1 if my_cx >= inter_cx else -1)
                else:
                    self.t.y += inter_h * (1 if my_cy >= inter_cy else -1)

        self.avel *= self.scene.drag # rotation
        self.t.rotation += self.avel / actualmass
        cols = self.collides(self.scene.solids)
        if cols and self.solid and not self.phantom:
            non_phantom = {o: px for o, px in cols.items() if not o.physics.phantom}
            if non_phantom:
                obj2 = next(iter(non_phantom))
                intersection = non_phantom[obj2]
                td = self.armratio(intersection, self.obj)
                self.t.rotation -= self.avel / actualmass
                self.avel *= -self.bounciness # bounce
                orx, ory = self.xvel, self.yvel
                self.t.x += self.xvel / actualmass
                self.t.y += self.yvel / actualmass
                self.t.rotation += self.avel / actualmass
                if self.collides(self.scene.solids) and self.solid: # slide
                    self.t.x -= orx / actualmass
                    self.t.y -= ory / actualmass
                    self.t.rotation -= self.avel / actualmass
                    self.xvel -= self.avel * td[1] / actualmass
                    self.yvel += self.avel * td[0] / actualmass

class pen():
    _owned = ['penchar', 'penx', 'peny']
    _required = [transform]

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.scene = obj.scene
        self._x = kwargs.get('penx', 0)
        self._y = kwargs.get('peny', 0)
        self._px = self._x
        self._py = self._y
        self.char = kwargs.get('penchar', '█')
        self.active = False
        self.current_obj = None
        self._pixels = {}
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
        self._pixels[(0, 0)] = self._pchar
        for key, value in (('text', self._pchar), ('x', self._ox), ('y', self._oy)):
            kwargs.setdefault(key, value)
        self.current_obj = self.scene.obj().create(**kwargs)
        return self.current_obj

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

    def move(self, x, y):
        self._x = x
        self._y = y
        if self.active:
            self._plot()

    def _plot(self):
        nx = round(self._x)
        ny = round(self._y)
        for (ix, iy) in self._line(self._px, self._py, nx, ny):
            self._pixels[(ix - self._ox, iy - self._oy)] = self._pchar
        self._px = nx
        self._py = ny
        self._rebuild()

    def _line(self, x0, y0, x1, y1):
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        seen = set()
        points = []
        for i in range(steps + 1):
            t = i / steps
            p = (round(x0 + t * (x1 - x0)), round(y0 + t * (y1 - y0)))
            if p not in seen:
                seen.add(p)
                points.append(p)
        return points

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
        t.rtext = '\n'.join(rows)

    def cut(self, wx, wy, r=0, when=True):
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
                    if t.cut(ix, iy, r=r):
                        self._cut_walls.setdefault(id(o), (o, None))
                        cut = True
        return cut

    def cutcommit(self, r=0, callback=None, diagonal=True, **kwargs):
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
        self._pcut = None
        return cut_objs

    def cancel(self):
        self._pcut = None
        self._cut_walls = {}

class force():
    _owned = ['affect', 'cap', 'force', 'position', 'radius', 'torque']
    _required = [transform]

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

    @staticmethod
    def _resolve(value, o):
        if callable(value):
            return value(o) if _argslen(value) else value()
        return value

    @staticmethod
    def _center(o):
        t = o.transform
        return t.x + t.vx + t.xc(), t.y + t.vy - t.yc()

    def targets(self):
        affect = self.affect
        if affect is None:
            candidates = list(self.scene.objs)
        elif hasattr(affect, 'transform'):
            candidates = [affect]
        else:
            candidates = list(affect)
        alive = {id(o) for o in self.scene.objs}
        return [
            o for o in candidates
            if o is not self.obj and id(o) in alive
            and hasattr(o, 'transform') and hasattr(o, 'physics') and o.physics.dynamic
        ]

    def apply(self, x=None, y=None):
        affected = []
        aspect = self.t.aspect
        for o in self.targets():
            cx, cy = self._center(o)
            if self.position is None:
                px, py = self._center(self.obj)
            else:
                px, py = self._resolve(self.position, o)
            if x is not None: px = x
            if y is not None: py = y
            dx = cx - px
            dy = cy - py
            dist = math.sqrt((dx * aspect) ** 2 + dy ** 2)
            if self.radius is not None and dist > self.radius:
                continue

            value = self._resolve(self.force, o)
            if isinstance(value, (tuple, list)):
                fx, fy = value
            else:
                if dist == 0 or not value:
                    continue
                strength = value / (4 * math.pi * dist)
                if self.cap is not None:
                    strength = max(-self.cap, min(self.cap, strength))
                direction = math.atan2(dy, dx * aspect)
                fx = strength * math.cos(direction) / aspect
                fy = strength * math.sin(direction)

            o.physics.xvel += fx
            o.physics.yvel += fy

            if self.torque and dist and not o.physics.hitbox:
                arm_x = o.transform.xc()
                arm_y = o.transform.yc()
                hit_x = -dx / (dist / (arm_x + 1e-6))
                hit_y = dy / (dist / (arm_y + 1e-6))
                hit_x = max(-arm_x, min(arm_x, hit_x))
                hit_y = max(-arm_y, min(arm_y, hit_y))
                o.physics.avel += hit_x * fy - hit_y * fx
            affected.append(o)
        return affected
