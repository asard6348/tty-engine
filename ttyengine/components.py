#_owned - list of owned variables
#_required - list of required components (optional)
#_default - bool of automatic loading upon calling create in obj instance

#MODULES
import math, re, sys, statistics

#COMPONENTS
class transform():
    _owned = [
        'x', 'y',
        'vx', 'vy',
        'text', 'rtext', 'htext',
        'vtext', 'vrtext', 'vhtext',
        'rotation',
    ]
    _default = True

    def __init__(self, obj, **kwargs):
        self.scene = obj.scene
        raw = kwargs.get('text', '')
        ctext = obj.scene.recomp.sub('', raw) if raw else ''
        self.x = kwargs.get('x', 0)
        self.y = kwargs.get('y', 0)
        self.vx = kwargs.get('vx', 0)
        self.vy = kwargs.get('vy', 0)
        self.vtext = raw
        self.vrtext = raw
        self.vhtext = raw
        self._text = ctext
        self._rtext = ctext
        self._htext = ctext
        self._rotation = kwargs.get('rotation', 0)

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    @property
    def text(self):
        return self._text
    @text.setter
    def text(self, value):
        ctext = self.scene.recomp.sub('', value)
        self.vrtext = value
        self.vhtext = value
        self._htext = ctext
        self._rtext = ctext
        self.rotate(self._rotation)

    @property
    def rtext(self):
        return self._rtext
    @rtext.setter
    def rtext(self, value):
        ctext = self.scene.recomp.sub('', value)
        self.vrtext = value
        self._rtext = ctext
        self.rotate(self._rotation)

    @property
    def htext(self):
        return self._htext
    @htext.setter
    def htext(self, value):
        ctext = self.scene.recomp.sub('', value)
        self.vrtext = value
        self.vhtext = value
        self._htext = ctext
        self._rtext = ctext
        self.rotate(self._rotation)

    @property
    def rotation(self):
        return self._rotation
    @rotation.setter
    def rotation(self, value):
        self._rotation = value
        self.rotate(value)
    
    def rotate(self, angle_degrees):
        #if self.hitbox:
        #    self.scene.dinfo.clear()
        angle = math.radians(angle_degrees)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)

        def cal(txt):
            rows = txt.splitlines()
            crows = self.scene.recomp.sub('', txt).splitlines()
            if not rows or not crows:
                return ''
            new_pixels = {}
            height = len(crows)
            width = max(len(r) for r in crows)
            cx, cy = width / 2, height / 2
            newrows = []
            current_style = ''
            for line in rows:
                newline = []
                for part in self.scene.recomp.split(line):
                    if self.scene.recomp.match(part):
                        current_style += part
                    elif part:
                        for char in part:
                            newline.append((char, current_style))
                newrows.append(newline)
            for y, crow in enumerate(crows):
                for x, char in enumerate(crow):
                    styled = newrows[y][x][1] if y < len(newrows) and x < len(newrows[y]) else ''
                    rel_x, rel_y = x - cx, y - cy
                    ASPECT = 0.5
                    rx_n = rel_x * ASPECT * cos_a - rel_y * sin_a
                    ry_n = rel_x * ASPECT * sin_a + rel_y * cos_a
                    nx = int(round(rx_n / ASPECT + cx))
                    ny = int(round(ry_n + cy))
                    if (nx, ny) not in new_pixels or new_pixels[(nx, ny)][0] == ' ':
                        new_pixels[(nx, ny)] = (char, styled)
            if not new_pixels:
                return ''
            xs = [p[0] for p in new_pixels]
            ys = [p[1] for p in new_pixels]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            res = []
            for y in range(min_y, max_y + 1):
                line = ''
                pstyled = ''
                for x in range(min_x, max_x + 1):
                    if (x, y) in new_pixels:
                        char, styled = new_pixels[(x, y)]
                        line += (styled if styled != pstyled else '') + char
                        pstyled = styled
                    else:
                        line += ('\033[0m' if pstyled else '') + ' '
                        pstyled = ''
                res.append(line)
            return '\n'.join(res)

        self.vtext = cal(self.vrtext)
        self._text = cal(self._rtext)
        self.vx = self.xc(self._rtext) - self.xc(self._text)
        self.vy = -(self.yc(self._rtext) - self.yc(self._text))

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


class rendering():
    _owned = ['px', 'py', 'ptext', 'show', 'renderspaces']
    _required = [transform]
    _default = True

    def __init__(self, obj, **kwargs):
        self.t = obj.transform
        self.scene = obj.scene
        self.px = kwargs.get('px', 0)
        self.py = kwargs.get('py', 0)
        self.ptext = kwargs.get('text', '')
        self.show = kwargs.get('show', True)
        self.renderspaces = kwargs.get('renderspaces', False)

    def render(self, write=True, split=False):
        bgcolor = (f'\033[48;2;{self.scene.bgcolor[0]};'
                   f'{self.scene.bgcolor[1]};{self.scene.bgcolor[2]}m')
        acx = round((self.t.x + self.t.vx) - round(self.scene.camx))
        acy = -round((self.t.y + self.t.vy) - round(self.scene.camy))
        actext = self.t.vtext

        # remove
        remove_output = ''
        px, py, ptext = self.px, self.py, self.ptext
        if px != acx or py != acy or ptext != actext:
            rem = f'\033[{int(py)+1}d' if py > 0 else '\033[H'
            for part in self.scene.recomp.split(ptext):
                if not part or self.scene.recomp.match(part):
                    rem += part
                else:
                    for i, row in enumerate(part.splitlines()):
                        rem += f'\033[{int(py)+1+i}d'
                        arow = ''
                        crop = row[abs(min(0, int(px))):abs(max(0, self.scene.dimx - int(px)))]
                        for char in crop:
                            arow += '\033[C' if char == ' ' and not self.renderspaces else ' '
                        final = f'\033[{max(0, int(px))+1}G{arow}'
                        rem += final if 1 <= int(py)+1+i <= self.scene.dimy else ''
            remove_output = f'{bgcolor}{rem}\033[0m'

        # draw
        out = f'\033[{acy+1}d' if acy > 0 else '\033[H'
        for part in self.scene.recomp.split(actext):
            if not part or self.scene.recomp.match(part):
                out += part
            else:
                for i, row in enumerate(part.splitlines()):
                    out += f'\033[{acy+1+i}d'
                    arow = ''
                    crop = row[abs(min(0, acx)):abs(max(0, self.scene.dimx - acx))]
                    for char in crop:
                        arow += '\033[C' if char == ' ' and not self.renderspaces else char
                    final = f'\033[{max(0, acx)+1}G{arow}'
                    out += final if 1 <= acy+1+i <= self.scene.dimy else ''
        draw_output = f'{bgcolor}{out}\033[0m'

        self.px = acx
        self.py = acy
        self.ptext = actext

        if write and self.show:
            sys.stdout.write(remove_output + draw_output)
        return (remove_output, draw_output) if split else remove_output + draw_output


class physics():
    _owned = [
        'xvel', 'yvel', 'avel',
        'dynamic',
        'bounciness',
        'mass',
        'solid',
        'hitbox',
        'touch',
    ]
    _required = [transform]

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.t = obj.transform
        self.scene = obj.scene
        self.xvel = kwargs.get('xvel', 0)
        self.yvel = kwargs.get('yvel', 0)
        self.avel = kwargs.get('avel', 0)
        self.dynamic = kwargs.get('dynamic', True)
        self.bounciness = kwargs.get('bounciness', 0)
        self.mass = kwargs.get('mass', None)
        if self.mass is None:
            self.mass = sum(1 for c in self.t._text if c not in (' ', '\n'))
        self.solid = kwargs.get('solid', True)
        self.hitbox = kwargs.get('hitbox', False)
        self.touch = (False, False)

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

    def getpixels(self, x=None, y=None, text=None):
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
        return pixels

    def collides(self, objs, x=None, y=None, text=None):
        pixels1 = self.getpixels(x, y, text)
        if not isinstance(objs, list):
            objs = [objs]
        for obj2 in objs:
            if obj2 is not self.obj:
                intersection = pixels1 & obj2.physics.getpixels()
                if intersection:
                    return True, obj2, intersection
        return False, None

    def physics(self, axises=('x', 'y')):
        def armratio(points, o, pos=None):
            xi = [p[0] for p in points]
            yi = [p[1] for p in points]
            center = (statistics.mean(xi), statistics.mean(yi))
            arms = []
            for ia, a in enumerate(axises):
                poss = o.transform[a] if pos is None else (pos[ia] if isinstance(pos, list) else pos)
                ratio = (center[ia] - (poss + o.transform[a + 'c']() if ia != 1 else poss - o.transform[a + 'c']())) / o.transform[a + 'c']()
                arms.append(ratio)
            return arms

        actualmass = abs(self.mass) + 1
        for ia, a in enumerate(axises):
            opp_ia = 1 - ia
            self[a + 'vel'] *= self.scene.drag
            self[a + 'vel'] += self.scene.gravity[ia] * actualmass
            c = 1 if self[a + 'vel'] > 0 else -1 if self[a + 'vel'] < 0 else 0
            ch = abs(self[a + 'vel']) / actualmass
            tch = list(self.touch)
            tch[ia] = False
            self.touch = tuple(tch)
            while ch > 0:
                step = min(self.scene.precision, ch)
                t = {a: self.t[a] + c * step}
                col = self.collides(self.scene.solids, **t)
                if col[0] and self.solid:
                    obj2 = col[1]
                    obj2p = obj2.physics
                    othermass = abs(obj2p.mass) + 1
                    totalmass = actualmass + othermass
                    td = armratio(col[2], self.obj, self.t[a] + c * step)
                    otd = armratio(col[2], obj2)
                    touchdelta = td[ia] if not self.hitbox else 0
                    if obj2p.dynamic and not obj2p.hitbox:
                        obj2p.avel += self.mass * (otd[opp_ia] * (
                            (obj2p[a + 'vel'] - self[a + 'vel']) if ia == 1
                            else -(obj2p[a + 'vel'] - self[a + 'vel'])))
                    if not self.hitbox:
                        self.avel += self.mass * (td[opp_ia] * (
                            (self[a + 'vel'] - obj2p[a + 'vel']) if ia == 1
                            else -(self[a + 'vel'] - obj2p[a + 'vel'])))
                    if obj2p.dynamic:
                        power = (actualmass / totalmass) * (1 - abs(touchdelta))
                        obj2p[a + 'vel'] += self[a + 'vel'] * power
                        self[a + 'vel'] *= max(touchdelta, (actualmass - othermass) / totalmass)
                    else:
                        self[a + 'vel'] *= -self.bounciness * (1 - abs(touchdelta))
                    tch = list(self.touch)
                    tch[ia] = True
                    self.touch = tuple(tch)
                    break
                self.t[a] += c * step
                ch -= step

        self.avel *= self.scene.drag
        self.t.rotation += self.avel / actualmass
        colr = self.collides(self.scene.solids)
        if colr[0] and self.solid:
            td = armratio(colr[2], self.obj)
            self.t.rotation -= self.avel / actualmass
            slide_cap = 0.5
            self.xvel = max(min(self.xvel + self.avel * abs(td[0]) / actualmass, slide_cap), -slide_cap)
            self.yvel = max(min(self.yvel + abs(self.avel) * td[1] / actualmass, slide_cap), -slide_cap)
            orx, ory = self.xvel, self.yvel
            self.t.x += self.xvel
            self.t.y += self.yvel
            self.t.rotation += self.avel / actualmass
            if self.collides(self.scene.solids)[0] and self.solid:
                self.t.x -= self.xvel
                self.t.y -= self.yvel
                self.xvel, self.yvel = orx, ory
                self.t.rotation -= self.avel / actualmass
                self.avel *= -self.bounciness
                self.t.rotation += self.avel / actualmass
