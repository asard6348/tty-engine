#_owned - list of owned variables which will be inspected upon obj().create()
#_required - list of required components to be included upon obj().create()
#_default - bool of the component auto-inclusion upon obj().create()
#def on_discard() - function that will be called upon obj().discard()

#MODULES
import math, re, sys, statistics, inspect

#GLOBAL
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
        self._onchangecb = []
        def cln():
            discarded = self.obj
            for other in self.obj.scene.objs:
                com = getattr(other, self.__class__.__name__, None)
                if other is discarded or not com or not hasattr(com, '_onchangecb'):
                    continue
                com._onchangecb = [
                    cb for cb in com._onchangecb
                    if not _closure_refs(cb, discarded)
                ]
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
            def wrapped(*args, **kwargs):
                self.obj.scene.pending.append(lambda: self._onchangecb.remove(wrapped) if wrapped in self._onchangecb else None)
                return cb(*args, **kwargs)
            wrapped.__signature__ = inspect.signature(cb)
            cb = wrapped
        self._onchangecb.append(cb)
        return cb
    def offchange(self, cb):
        self._onchangecb = [f for f in self._onchangecb if f is not cb]
    def _change(self, attr, old):
        for cb in self._onchangecb:
            l = _argslen(cb)
            if l > 1:
                cb(attr, old)
            elif l > 0:
                cb(attr)
            else:
                cb()

#COMPONENTS
class transform(_change_callback):
    _owned = [
        'x', 'y',
        'vx', 'vy',
        'text', 'rtext', 'htext',
        'vtext', 'vrtext', 'vhtext',
        'rotation',
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
        self._aspect = 0.5
        self._onsplit = []
 
    def __getitem__(self, key):
        return getattr(self, key)
 
    def __setitem__(self, key, value):
        setattr(self, key, value)
 
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
        self._rot_cache_angle = None
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
        self._rot_cache_angle = None
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
        self._rot_cache_angle = None
        self.rotate(self._rotation)
        self._change('htext', old)
 
    @property
    def rotation(self):
        return self._rotation
    @rotation.setter
    def rotation(self, value):
        old = self._rotation
        self._rotation = value
        self.rotate(value)
        self._change('rotation', old)

    def _pixel_centroid(self, txt):
        clean = self.scene.recomp.sub('', txt)
        xs, ys = [], []
        for ri, row in enumerate(clean.splitlines()):
            for ci, char in enumerate(row):
                if char not in (' ', '\n'):
                    xs.append(ci)
                    ys.append(ri)
        if not xs:
            return 0.0, 0.0
        return sum(xs) / len(xs), sum(ys) / len(ys)
 
    def parse_pixels(self, text):
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
 
    def rotate(self, angle_degrees):
        rounded = round(angle_degrees * 20) / 20
        if self._rot_cache_angle == rounded:
            return
        self._rot_cache_angle = rounded

        angle = math.radians(angle_degrees)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)

        def cal(txt):
            crows = self.scene.recomp.sub('', txt).splitlines()
            if not crows:
                return ''
            height = len(crows)
            width  = max(len(r) for r in crows) if crows else 0
            cx, cy = width / 2, height / 2

            new_pixels = {}
            for (x, y), (char, style) in self.parse_pixels(txt).items():
                rel_x, rel_y = x - cx, y - cy
                ASPECT = self._aspect
                rx_n = rel_x * ASPECT * cos_a - rel_y * sin_a
                ry_n = rel_x * ASPECT * sin_a + rel_y * cos_a
                nx = int(round(rx_n / ASPECT + cx))
                ny = int(round(ry_n + cy))
                if (nx, ny) not in new_pixels or new_pixels[(nx, ny)][0] == ' ':
                    new_pixels[(nx, ny)] = (char, style)

            if not new_pixels:
                return ''
            
            all_xs = [p[0] for p in new_pixels]
            ns_ys  = [p[1] for p in new_pixels if new_pixels[p][0] != ' ']
            if not ns_ys:
                return ''
            return self.build_rows(new_pixels, min(all_xs), max(all_xs), min(ns_ys), max(ns_ys))

        self.vtext = cal(self.vrtext)
        self._text = cal(self._rtext)

        orig_cx, orig_cy = self._pixel_centroid(self._rtext)
        rot_cx,  rot_cy  = self._pixel_centroid(self._text)
        self.vx = round(orig_cx - rot_cx)
        self.vy = -round(orig_cy - rot_cy)

    def _get_rot_cache(self):
        key = (round(self._rotation * 20), hash(self._rtext))
        if getattr(self, '_rot_cache_key', None) == key:
            return self._rot_cache_val
        crows = self.scene.recomp.sub('', self._rtext).splitlines()
        if not crows:
            self._rot_cache_key = key
            self._rot_cache_val = ({}, 0, 0, 0, 0)
            return self._rot_cache_val
        height_r = len(crows)
        width_r = max(len(r) for r in crows)
        cx_r, cy_r = width_r / 2, height_r / 2
        angle = math.radians(self._rotation)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        ASPECT = self._aspect
        rot_positions = {}
        for ri, row in enumerate(crows):
            for ci, char in enumerate(row):
                if char not in (' ', '\n'):
                    rel_x = ci - cx_r
                    rel_y = ri - cy_r
                    rx_n = rel_x * ASPECT * cos_a - rel_y * sin_a
                    ry_n = rel_x * ASPECT * sin_a + rel_y * cos_a
                    nx = int(round(rx_n / ASPECT + cx_r))
                    ny = int(round(ry_n + cy_r))
                    if (nx, ny) not in rot_positions:
                        rot_positions[(nx, ny)] = (ci, ri)
        min_x = min(p[0] for p in rot_positions) if rot_positions else 0
        min_y = min(p[1] for p in rot_positions) if rot_positions else 0
        val = (rot_positions, min_x, min_y, cx_r, cy_r)
        self._rot_cache_key = key
        self._rot_cache_val = val
        return val

    def world_to_rtext(self, wx, wy):
        rot_positions, min_x, min_y, cx_r, cy_r = self._get_rot_cache()
        if not rot_positions:
            return None
        ox = round(self._x + self.vx)
        oy = round(self._y + self.vy)
        nx = wx - ox + min_x
        ny = oy - wy + min_y
        result = rot_positions.get((nx, ny))
        if result is not None:
            return result
        for ddx, ddy in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,-1),(-1,1),(1,1)):
            result = rot_positions.get((nx + ddx, ny + ddy))
            if result is not None:
                return result
        return None

    def rtext_to_world(self, ci, ri):
        rot_positions, min_x, min_y, cx_r, cy_r = self._get_rot_cache()
        if not rot_positions:
            return None
        angle = math.radians(self._rotation)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        ASPECT = self._aspect
        rel_x = ci - cx_r
        rel_y = ri - cy_r
        rx_n = rel_x * ASPECT * cos_a - rel_y * sin_a
        ry_n = rel_x * ASPECT * sin_a + rel_y * cos_a
        nx = int(round(rx_n / ASPECT + cx_r))
        ny = int(round(ry_n + cy_r))
        ox = round(self._x + self.vx)
        oy = round(self._y + self.vy)
        wx = ox + (nx - min_x)
        wy = oy - (ny - min_y)
        return wx, wy

    def cut(self, wx, wy, r=1):
        styled_pixels = self.parse_pixels(self.vrtext)
        changed = False
        for dy in range(-(r - 1), r):
            for dx in range(-(r - 1), r):
                result = self.world_to_rtext(wx + dx, wy + dy)
                if result is None:
                    continue
                ci, ri = result
                if (ci, ri) in styled_pixels and styled_pixels[(ci, ri)][0] != ' ':
                    styled_pixels[(ci, ri)] = (' ', '')
                    changed = True
        if changed:
            coords = list(styled_pixels)
            xs = [p[0] for p in coords]
            ys = [p[1] for p in coords]
            self.rtext = self.build_rows(styled_pixels, min(xs), max(xs), min(ys), max(ys))
        return changed

    def _spawn_from_components(self, components, pixels, callback=None):
        rot_positions, rot_min_x, rot_min_y, cx_r, cy_r = self._get_rot_cache()
        angle = math.radians(self._rotation)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        ASPECT = self._aspect
        ox = round(self._x + self.vx)
        oy = round(self._y + self.vy)

        spawns = []
        for group in components:
            min_x = min_y = None
            max_x = max_y = None
            sum_wx = sum_wy = 0
            sum_ci = sum_ri = 0
            group_pixels = {}

            for ci, ri in group:
                if min_x is None or ci < min_x: min_x = ci
                if max_x is None or ci > max_x: max_x = ci
                if min_y is None or ri < min_y: min_y = ri
                if max_y is None or ri > max_y: max_y = ri
                group_pixels[(ci, ri)] = pixels[(ci, ri)]
                rel_x = ci - cx_r
                rel_y = ri - cy_r
                rx_n = rel_x * ASPECT * cos_a - rel_y * sin_a
                ry_n = rel_x * ASPECT * sin_a + rel_y * cos_a
                nx = int(round(rx_n / ASPECT + cx_r))
                ny = int(round(ry_n + cy_r))
                sum_wx += ox + (nx - rot_min_x)
                sum_wy += oy - (ny - rot_min_y)
                sum_ci += ci
                sum_ri += ri

            n = len(group)
            wcx = sum_wx / n
            wcy = sum_wy / n
            fcx = (max_x - min_x + 1) / 2.0
            fcy = (max_y - min_y + 1) / 2.0
            frag_orig_cx = sum_ci / n - min_x
            frag_orig_cy = sum_ri / n - min_y

            sum_frx = sum_fry = 0
            frag_rot_min_x = frag_rot_min_y = None
            for ci, ri in group:
                li  = ci - min_x
                lri = ri - min_y
                rel_x = li  - fcx
                rel_y = lri - fcy
                rx_n = rel_x * ASPECT * cos_a - rel_y * sin_a
                ry_n = rel_x * ASPECT * sin_a + rel_y * cos_a
                frx = int(round(rx_n / ASPECT + fcx))
                fry = int(round(ry_n + fcy))
                sum_frx += frx
                sum_fry += fry
                if frag_rot_min_x is None or frx < frag_rot_min_x: frag_rot_min_x = frx
                if frag_rot_min_y is None or fry < frag_rot_min_y: frag_rot_min_y = fry

            frag_rot_cx = sum_frx / n
            frag_rot_cy = sum_fry / n
            vx_new = round(frag_orig_cx - frag_rot_cx)
            vy_new = -round(frag_orig_cy - frag_rot_cy)
            fx = wcx - vx_new - (frag_rot_cx - frag_rot_min_x)
            fy = wcy - vy_new + (frag_rot_cy - frag_rot_min_y)

            kw = self.obj.kwargs()
            del kw['mass']
            spawns.append({
                **kw,
                'text': self.build_rows(group_pixels, min_x, max_x, min_y, max_y),
                'x': fx,
                'y': fy,
                'rotation': self._rotation,
            })

        obj_ref = self.obj
        def do_split(spawns=spawns, obj_ref=obj_ref, cb=callback):
            parts = []
            for kw in spawns:
                parts.append(obj_ref.scene.obj().create(**kw))
            if callable(cb):
                l = _argslen(cb)
                if l > 0: cb(parts)
                else: cb()
            for calb in self._onsplit:
                cl = _argslen(calb)
                if cl > 0: calb(parts)
                else: calb()
            obj_ref.discard()
        self.scene.pending.append(do_split)
        return do_split

    def split(self, callback=None):
        if getattr(self, '_split_cb', None) in self.scene.pending:
            return
        pixels = self.parse_pixels(self.vrtext)
        coords = {pos for pos, (char, _) in pixels.items() if char != ' '}
        if not coords and not self.obj.discard in self.scene.pending:
            if callable(callback):
                l = _argslen(callback)
                if l > 0: self.scene.pending.append(lambda: callback([self.obj]))
                else: self.scene.pending.append(callback)
            self.scene.pending.append(self.obj.discard)
            return

        remaining = set(coords)
        components = []
        while remaining:
            start = next(iter(remaining))
            group = set()
            stack = [start]
            while stack:
                pos = stack.pop()
                if pos not in remaining:
                    continue
                remaining.remove(pos)
                group.add(pos)
                cx, cy = pos
                for dx, dy in ((-1,0),(1,0),(0,-1),(0,1)):
                    if (cx+dx, cy+dy) in remaining:
                        stack.append((cx+dx, cy+dy))
            components.append(group)

        if len(components) < 2:
            if callable(callback):
                l = _argslen(callback)
                if l > 0: self.scene.pending.append(lambda: callback([self.obj]))
                else: self.scene.pending.append(callback)
            return

        self._split_cb = self._spawn_from_components(components, pixels, callback)
        return self._split_cb

    def split_at(self, wall_pixels, callback=None):
        if getattr(self, '_split_cb', None) in self.scene.pending:
            return
        pixels = self.parse_pixels(self.vrtext)
        coords = {pos for pos, (char, _) in pixels.items() if char != ' '}

        valid_walls = wall_pixels & coords
        if not valid_walls:
            if callable(callback):
                l = _argslen(callback)
                if l > 0: self.scene.pending.append(lambda: callback([self.obj]))
                else: self.scene.pending.append(callback)
            return

        remaining = coords - valid_walls
        components = []
        while remaining:
            start = next(iter(remaining))
            group = set()
            stack = [start]
            while stack:
                pos = stack.pop()
                if pos not in remaining:
                    continue
                remaining.remove(pos)
                group.add(pos)
                cx, cy = pos
                for dx, dy in ((-1,0),(1,0),(0,-1),(0,1)):
                    if (cx+dx, cy+dy) in remaining:
                        stack.append((cx+dx, cy+dy))
            components.append(group)

        if len(components) < 2:
            if callable(callback):
                l = _argslen(callback)
                if l > 0: self.scene.pending.append(lambda: callback([self.obj]))
                else: self.scene.pending.append(callback)
            return

        for wp in valid_walls:
            nearest = min(components, key=lambda g: min(
                abs(wp[0]-p[0]) + abs(wp[1]-p[1]) for p in g
            ))
            nearest.add(wp)

        self._split_cb = self._spawn_from_components(components, pixels, callback)
        return self._split_cb

    def onsplit(self, cb, once=False):
        if once:
            def wrapped(*args, **kwargs):
                self.obj.scene.pending.append(lambda: self._onsplit.remove(wrapped) if wrapped in self._onsplit else None)
                return cb(*args, **kwargs)
            wrapped.__signature__ = inspect.signature(cb)
            cb = wrapped
        self._onsplit.append(cb)
        return cb
    
    def offsplit(self, cb):
        self._onsplit = [f for f in self._onsplit if f is not cb]
 
    def xlen(self, text=None):
        text = self._text if text is None else text
        lens = []
        for row in text.splitlines():
            for i, char in enumerate(row):
                if char != ' ':
                    lens.append(i)
        return abs(max(lens) - (min(lens) - 1)) if lens else 0
 
    def ylen(self, text=None):
        text = self._text if text is None else text
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
        y = math.cos(angle) * self._aspect * move
        return (x, y)

    def point(self, tx, ty, offset=0):
        dx = tx - self._x
        dy = ty - self._y
        ASPECT = self._aspect
        angle = math.degrees(math.atan2(-dy, dx * ASPECT))+90
        return angle + offset

    def aim(self, obj, offset=0):
        return self.point(obj.transform.x, obj.transform.y, offset=offset)
    

class rendering():
    _owned = ['show', 'renderspaces']
    _required = [transform]
    _default = True
    def on_discard(self):
        self.remove()

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
        self._dirty = True
        self.t.onchange(self._markdirty)

    @property
    def show(self):
        return self._show

    @show.setter
    def show(self, value):
        self._show = value
        self._markdirty()

    def _markdirty(self):
        self._dirty = True

    def crop_row(self, row, start, end, renderspaces=False):
        bgcolor = (f'\033[48;2;{self.scene.bgcolor[0]};'
                   f'{self.scene.bgcolor[1]};'
                   f'{self.scene.bgcolor[2]}m')
        result = '\033[39m'
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
                            result += '\033[39m'
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
            result += '\033[39m'
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
            return
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
        bgcolor = (f'\033[48;2;{self.scene.bgcolor[0]};'
                   f'{self.scene.bgcolor[1]};{self.scene.bgcolor[2]}m')
        acx = round((self.t.x + self.t.vx) - round(self.scene.camx))
        acy = -round((self.t.y + self.t.vy) - round(self.scene.camy))
        actext = self.t.vtext
        acxoff = self.scene.dimxoffset
        acyoff = self.scene.dimyoffset
        
        px, py, ptext, pxoff, pyoff = self.px, self.py, self.ptext, self.pxoff, self.pyoff
        remove_output = ''
        if px != acx or py != acy or ptext != actext or pxoff != acxoff or pyoff != acyoff or self._dirty:
            remove_output = f'{bgcolor}{self.render_rows(ptext, px, py, acxoff, acyoff, erase=True, exclude_rects=exclude_rects)}\033[0m'
        elif not self._dirty:
            return ('', '') if split else ''
        draw_output = f'{bgcolor}{self.render_rows(actext, acx, acy, acxoff, acyoff, erase=False, exclude_rects=exclude_rects)}\033[0m'

        self.px    = acx
        self.py    = acy
        self.ptext = actext
        self.pxoff = acxoff
        self.pyoff = acyoff
        self._dirty = False

        if write:
            if self._show:
                sys.stdout.write(remove_output + draw_output)
            else:
                sys.stdout.write(remove_output)
            sys.stdout.flush()
        return (remove_output, draw_output) if split else remove_output + draw_output


class physics(_change_callback):
    _owned = [
        'xvel', 'yvel', 'avel',
        'dynamic',
        'bounciness',
        'mass',
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
        self._aspect = (1, self.t._aspect)
        self._xvel = kwargs.get('xvel', 0)
        self._yvel = kwargs.get('yvel', 0)
        self._avel = kwargs.get('avel', 0)
        self.dynamic = kwargs.get('dynamic', True)
        self.bounciness = kwargs.get('bounciness', 0)
        self.mass = kwargs.get('mass', None)
        if self.mass is None:
            self.mass = sum(1 for c in self.t._text if c not in (' ', '\n'))
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

    def _dirty(self):
        self._pixel_cache = None

    def ontouch(self, callback, when=None, once=False):
        l = _argslen(callback)
        def wrapped(obj2, intersection):
            if when is None or when(obj2):
                if l > 1: callback(obj2, intersection)
                elif l > 0: callback(obj2)
                else: callback()
                if once: self.scene.pending.append(lambda: self._touch_callbacks.remove(wrapped) if wrapped in self._touch_callbacks else None)
        self._touch_callbacks.append(wrapped)
        return callback

    def offtouch(self, callback):
        self._touch_callbacks = [
            cb for cb in self._touch_callbacks if cb.__closure__ and
            cb.__closure__[0].cell_contents is not callback
        ]

    def alerp(self, angle):
        return (angle - self.t.rotation + 540) % 360 - 180

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
            return False, {}

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
        return bool(result), result

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
        aspect = self._aspect if aspect is None else aspect
        self._dirty()
        actualmass = max(abs(self.mass), 1)

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
                hit, collisions = self.collides(self.scene.solids, **t)

                # phantom: full sweep for callbacks
                if self.phantom:
                    pixels1 = self.getpixels(**t)
                    for solid_obj in self.scene.solids:
                        if solid_obj is self.obj or solid_obj in collisions:
                            continue
                        pixels2 = solid_obj.physics.getpixels()
                        intersection = pixels1 & pixels2
                        if intersection:
                            collisions[solid_obj] = intersection

                physical_col = None
                for obj2, intersection in collisions.items():
                    # callbacks
                    for cb in self._touch_callbacks:
                        cb(obj2, intersection)
                    for cb in obj2.physics._touch_callbacks:
                        cb(self.obj, intersection)
                    # only resolve physics when both solid and neither phantom
                    if self.solid and not self.phantom and not obj2.physics.phantom:
                        if physical_col is None:
                            physical_col = (obj2, intersection)

                if physical_col is not None:
                    obj2, intersection = physical_col
                    obj2p = obj2.physics
                    othermass = max(abs(obj2p.mass), 1)
                    totalmass = actualmass + othermass

                    pos_list = [self.t.x, self.t.y]
                    pos_list[ia] = self.t[a] + c * step
                    td = self.armratio(intersection, self.obj, pos_list) # arm ratio
                    otd = self.armratio(intersection, obj2)

                    vel_self_before = self[a + 'vel'] # torque
                    vel_obj2_before = obj2p[a + 'vel']
                    resting = self.touch[ia] and abs(self[a + 'vel']) / actualmass < 0.5
                    if obj2p.dynamic and not obj2p.hitbox and not resting:
                        obj2p.avel += self.mass * (otd[opp_ia] * (
                            (vel_obj2_before - vel_self_before) if ia == 1
                            else -(vel_obj2_before - vel_self_before)))
                    if not self.hitbox and not resting:
                        self.avel += self.mass * (td[opp_ia] * (
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
        hit, cols = self.collides(self.scene.solids)
        if self.solid and hit and not self.phantom:
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
        hit, cols = self.collides(self.scene.solids)
        if hit and self.solid and not self.phantom:
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
                if self.collides(self.scene.solids)[0] and self.solid: # slide
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
        self._pcut_x = 0
        self._pcut_y = 0
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
            return
        self.active = True
        self._pixels = {}
        if x: self._x = x
        if y: self._y = y
        self._ox = round(self._x)
        self._oy = round(self._y)
        self._px = self._ox
        self._py = self._oy
        self._pchar = char or self.char
        self._pixels[(0, 0)] = self._pchar
        kwargs.update({k: v for k,v in {'text': self._pchar, 'x': x or self._ox, 'y': y or self._oy}.items() if k not in kwargs})
        self.current_obj = self.scene.obj().create(**kwargs)

    def up(self, **kwargs):
        self.active = False
        if self.current_obj is not None:
            self.current_obj.create(**kwargs)
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
        ASPECT = 1/self.obj.transform._aspect
        dx = abs(x1 - x0)
        dy = abs(y1 - y0) * ASPECT
        steps = max(int(max(dx, dy)), 1)
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
        if not self._pixels or self.current_obj is None:
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

        self.current_obj.transform.x = self._ox + min_x
        self.current_obj.transform.y = self._oy + max_y

        self.current_obj.transform.rtext = '\n'.join(rows)

    def cut(self, wx, wy, r=0, when=True):
        for ix, iy in self._line(self._pcut_x, self._pcut_y, round(wx), round(wy)):
            for o in list(self.scene.objs):
                if o is self.obj or not hasattr(o, 'transform') or not (when(o) if callable(when) else when):
                    continue
                if r == 0:
                    result = o.transform.world_to_rtext(ix, iy)
                    if result is not None:
                        ci, ri = result
                        plain = self.scene.recomp.sub('', o.transform._rtext).splitlines()
                        if 0 <= ri < len(plain) and 0 <= ci < len(plain[ri]) and plain[ri][ci] != ' ':
                            if id(o) not in self._cut_walls:
                                self._cut_walls[id(o)] = (o, set())
                            self._cut_walls[id(o)][1].add((ci, ri))
                else:
                    if o.transform.cut(ix, iy, r=r):
                        if id(o) not in self._cut_walls:
                            self._cut_walls[id(o)] = (o, None)
        self._pcut_x = round(wx)
        self._pcut_y = round(wy)

    def commit(self, r=0, **kwargs):
        cut_objs = {}
        for o, wall_pixels in self._cut_walls.values():
            if o not in self.scene.objs:
                continue
            o.create(**kwargs)
            if r == 0:
                cuts = o.transform.split_at(wall_pixels)
            else:
                cuts = o.transform.split()
            cut_objs[o] = cuts if not cuts is None else []
        self._cut_walls = {}
        return cut_objs

    def cancel(self):
        self._pcut_x = 0
        self._pcut_y = 0
        self._cut_walls = {}

class explosion():
    _owned = ['exradius', 'exforce']
    _required = [transform]

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.t = obj.transform
        self.scene = obj.scene
        self.radius = kwargs.get('exradius', 10)
        self.force = kwargs.get('exforce', 5)

    def circle(self, radius, char='o'):
        rx = round(radius * (1/self.t._aspect))
        ry = round(radius)
        if rx<1 or ry<1:
            return char
        rows = []
        for dy in range(-ry, ry + 1):
            row = ''
            for dx in range(-rx, rx + 1):
                val = (dx / rx) ** 2 + (dy / ry) ** 2
                row += char if abs(val - 1) < 0.15 else ' '
            rows.append(row)
        return '\n'.join(rows)

    def explode(self, x=None, y=None, radius=None, force=None):
        r = radius if radius is not None else self.radius
        f = force if force is not None else self.force
        ex = x if x is not None else self.t.x
        ey = y if y is not None else self.t.y

        for o in list(self.scene.objs):
            if o is self.obj or not hasattr(o, 'transform') or not hasattr(o, 'physics'):
                continue
            if not o.physics.dynamic:
                continue
            
            ox = o.transform.x + o.transform.xc()
            oy = o.transform.y - o.transform.yc()
            dx = ox - ex
            dy = oy - ey
            ASPECT = self.t._aspect
            dist = math.sqrt((dx * ASPECT) ** 2 + dy ** 2)
            if dist > r or dist == 0:
                continue

            strength = f * (1 - dist / r)
            fx = (dx / dist) * strength
            fy = (dy / dist) * strength
            o.physics.xvel += fx
            o.physics.yvel += fy

            if not o.physics.hitbox:
                arm_x = o.transform.xc()
                arm_y = o.transform.yc()

                hit_x = -dx / (dist / (arm_x + 1e-6))
                hit_y =  dy / (dist / (arm_y + 1e-6))
                hit_x = max(-arm_x, min(arm_x, hit_x))
                hit_y = max(-arm_y, min(arm_y, hit_y))

                torque = hit_x * fy - hit_y * fx
                o.physics.avel += torque
