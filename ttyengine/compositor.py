import re
import math
from itertools import groupby
from operator import itemgetter
from .ascii_styler import alphamark, alphaparse, bgrecomp, fgrecomp

COVER = {' ': 0.0, '█': 1.0, '▓': 0.75, '▒': 0.5, '░': 0.25, '▀': 0.5, '▄': 0.5, '▌': 0.5, '▐': 0.5}
_kinds = {}


def scene_of(item):
    return getattr(item, 'scene', item)


def kind(active):
    found = _kinds.get(active)
    if found is None:
        if len(_kinds) > 4096:
            _kinds.clear()
        fa, back, ba = alphaparse(active)
        if fa is None and ba is None:
            found = 0
        else:
            own = bgrecomp.search(active) is not None
            found = 2 if (ba is not None and own) or (fa is not None and (back or not own)) else 1
        _kinds[active] = found
    return found


def clamp(color):
    return tuple(max(0, min(255, int(round(v)))) for v in color)


class Compositor:
    runs = re.compile(b'\x01(?:\x00{0,3}\x01)*')
    sgr = re.compile(r'\033\[([0-9;]*)m')

    def __init__(self):
        self.front = None
        self.width = 0
        self.height = 0
        self.known = {}
        self.glows = {}
        self.styles = {}
        self.bgfound = {}
        self.palettes = {}
        self.glasses = {}
        self.region = None
        self.rotated = {}

    def invalidate(self):
        self.front = None

    @staticmethod
    def vacate(old, new, bounds):
        ox, oy, ow, oh = old
        nx, ny, nw, nh = new
        tw, th = bounds
        out = ['\033[0m']
        for y in range(max(0, oy), min(oy + oh, th)):
            a, b = max(0, ox), min(ox + ow, tw)
            if ny <= y < ny + nh:
                segs = ((a, min(b, nx)), (max(a, nx + nw), b))
            else:
                segs = ((a, b),)
            for s, e in segs:
                if s < e:
                    out.append(f'\033[{y + 1};{s + 1}H' + ' ' * (e - s))
        return ''.join(out) if len(out) > 1 else ''

    def stale(self, width, height):
        return self.front is None or self.width != width or self.height != height

    @staticmethod
    def bgstyle(color):
        return f'\033[48;2;{int(color[0])};{int(color[1])};{int(color[2])}m'

    @staticmethod
    def parse(scene, text, spaces):
        bg = Compositor.bgstyle(scene.bgcolor)
        rows = []
        for row in text.split('\n'):
            cells = []
            active = ''
            for part in scene.recomp.split(row):
                if not part:
                    continue
                if scene.recomp.match(part):
                    if part in ('\033[0m', '\033[m'):
                        active = ''
                    elif part.startswith('\033[') and part.endswith('m'):
                        active += part
                    continue
                shape = kind(active)
                if shape == 2:
                    for char in part:
                        cells.append((char, active, True) if spaces or char != ' ' else None)
                    continue
                style = bg + (alphamark.sub('', active) if shape else active)
                for char in part:
                    cells.append((char, style) if spaces or char != ' ' else None)
            runs = []
            glass = []
            at = 0
            for width, group in groupby(cells, key=lambda cell: 0 if cell is None else len(cell)):
                items = list(group)
                if width == 2:
                    runs.append((at, items))
                elif width == 3:
                    glass.append((at, [(cell[0], cell[1]) for cell in items]))
                at += len(items)
            rows.append((len(cells), runs, glass))
        return rows

    def palette(self, style, base, front):
        key = (style, base, front)
        found = self.palettes.get(key)
        if found is None:
            if len(self.palettes) > 4096:
                self.palettes.clear()
            backs = bgrecomp.findall(style)
            fronts = fgrecomp.findall(style)
            found = self.palettes[key] = (
                tuple(int(v) for v in backs[-1]) if backs else base,
                tuple(int(v) for v in fronts[-1]) if fronts else front,
            )
        return found

    def see(self, scene, under, char, active):
        base = tuple(scene.bgcolor)
        front = tuple(scene.fgcolor)
        fa, back, ba = alphaparse(active)
        backs = bgrecomp.findall(active)
        fronts = fgrecomp.findall(active)
        own = bool(backs)
        if char == ' ' and not own:
            return None, None
        if (char == ' ' or (fa is not None and fa <= 0)) and (not own or (ba is not None and ba <= 0)):
            return None, None
        ubg, ufg = self.palette(under[1], base, front)
        cover = COVER.get(under[0], 0.0)
        seen = tuple(ubg[k] + (ufg[k] - ubg[k]) * cover for k in range(3))
        reach = COVER.get(under[0], 0.5)
        glyph = tuple(ubg[k] + (ufg[k] - ubg[k]) * reach for k in range(3))
        if own:
            baked = tuple(int(v) for v in backs[-1])
            ground = baked if ba is None else tuple(baked[k] + (seen[k] - base[k]) * (1 - ba) for k in range(3))
        else:
            baked = None
            ground = seen
        style = self.bgstyle(clamp(ground)) + alphamark.sub('', fgrecomp.sub('', bgrecomp.sub('', active)))
        share = None
        if fronts:
            paint = tuple(int(v) for v in fronts[-1])
            if fa is not None:
                old, new = (base, glyph) if back or not own else (baked, ground)
                paint = tuple(paint[k] + (new[k] - old[k]) * (1 - fa) for k in range(3))
                if back or not own:
                    share = (1 - fa) * (1 - reach)
                    if share <= 0:
                        share = None
            style += '\033[38;2;%d;%d;%dm' % clamp(paint)
        return (char, style), share

    def glass(self, scene, under, char, active):
        key = (under, char, active, tuple(scene.bgcolor), tuple(scene.fgcolor))
        found = self.glasses.get(key)
        if found is None:
            if len(self.glasses) > 20000:
                self.glasses.clear()
            found = self.glasses[key] = self.see(scene, under, char, active)
        return found

    def seep(self, glow, rest, base, share):
        match = bgrecomp.search(glow)
        if match is None:
            return rest
        goal = [int(v) for v in match.groups()]

        def shift(found):
            old = [int(v) for v in found.groups()]
            return '\033[38;2;%d;%d;%dm' % clamp(old[k] + (goal[k] - base[k]) * share for k in range(3))
        return fgrecomp.sub(shift, rest)

    @staticmethod
    def view(sc, width, height):
        return (
            max(0, sc.dimxoffset),
            max(0, -sc.dimyoffset),
            min(width, sc.termx, sc.dimxoffset + sc.dimx),
            min(height, sc.termy, -sc.dimyoffset + sc.dimy),
        )

    def tint(self, base, red, green, blue, level):
        key = (base, red, green, blue, level)
        style = self.styles.get(key)
        if style is None:
            if len(self.styles) > 50000:
                self.styles.clear()
            amount = level / 256
            style = self.styles[key] = self.bgstyle((
                max(0, min(255, int(round(base[0] + (red - base[0]) * amount)))),
                max(0, min(255, int(round(base[1] + (green - base[1]) * amount)))),
                max(0, min(255, int(round(base[2] + (blue - base[2]) * amount)))),
            ))
        return style

    def hasbg(self, style):
        found = self.bgfound.get(style)
        if found is None:
            if len(self.bgfound) > 4096:
                self.bgfound.clear()
            found = False
            for match in self.sgr.finditer(style):
                params = match.group(1).split(';')
                i = 0
                while i < len(params):
                    code = int(params[i]) if params[i] else 0
                    if code == 48 or 40 <= code <= 47 or 100 <= code <= 107:
                        found = True
                        break
                    if code == 38:
                        i += 3 if i + 1 < len(params) and params[i + 1] == '5' else 5
                    else:
                        i += 1
                if found:
                    break
            self.bgfound[style] = found
        return found

    def shine(self, scene, back, spans, lit, plain, warm=None):
        bg = self.bgstyle(scene.bgcolor)
        base = tuple(scene.bgcolor)
        groups = {}
        for light, rows in lit:
            gkey = (light._color, light._mix)
            grows = groups.get(gkey)
            if grows is None:
                grows = groups[gkey] = {}
            for y, x, amounts in rows:
                span = spans.get(y)
                if span is None:
                    continue
                lo = max(span[0] - x, 0)
                hi = min(span[1] - x, len(amounts))
                if lo >= hi:
                    continue
                if lo or hi < len(amounts):
                    amounts = amounts[lo:hi]
                start = x + lo
                stop = start + len(amounts)
                entry = grows.get(y)
                if entry is None:
                    entry = grows[y] = [[0.0] * len(back[y]), start, stop]
                else:
                    if start < entry[1]:
                        entry[1] = start
                    if stop > entry[2]:
                        entry[2] = stop
                row = entry[0]
                for xx, amount in enumerate(amounts, start):
                    row[xx] += amount
        ys = set()
        for grows in groups.values():
            ys.update(grows)
        for y in ys:
            line = back[y]
            entries = [(color, mix, grows[y]) for (color, mix), grows in groups.items() if y in grows]
            if len(entries) == 1:
                color, mix, (row, first, last) = entries[0]
                lut = self.styles.get((base, color))
                if lut is None:
                    lut = self.styles[(base, color)] = [None] * 257
                for x in range(first, last):
                    total = row[x]
                    if total <= 0:
                        continue
                    level = int(mix * (total if total < 1.0 else 1.0) * 256 + 0.5)
                    glow = lut[level]
                    if glow is None:
                        glow = lut[level] = self.tint(base, color[0], color[1], color[2], level)
                    char, style = line[x]
                    if style == bg:
                        line[x] = (char, glow)
                    elif style.startswith(bg):
                        rest = style[len(bg):]
                        if not self.hasbg(rest):
                            if warm:
                                entry = warm.get((y, x))
                                if entry is not None and entry[1] == line[x]:
                                    rest = self.seep(glow, rest, base, entry[0])
                            line[x] = (char, glow + rest)
                    elif style == '' or style == plain:
                        line[x] = (char, glow)
                continue
            first = min(e[2][1] for e in entries)
            last = max(e[2][2] for e in entries)
            for x in range(first, last):
                total = mixsum = red = green = blue = 0.0
                for color, mix, (row, a, b) in entries:
                    if a <= x < b:
                        amount = row[x]
                        if amount > 0:
                            total += amount
                            mixsum += amount * mix
                            red += amount * color[0]
                            green += amount * color[1]
                            blue += amount * color[2]
                if total <= 0:
                    continue
                glow = self.tint(base, int(round(red / total)), int(round(green / total)), int(round(blue / total)),
                                 int(mixsum / total * min(1.0, total) * 256 + 0.5))
                char, style = line[x]
                if style == bg:
                    line[x] = (char, glow)
                elif style.startswith(bg):
                    rest = style[len(bg):]
                    if not self.hasbg(rest):
                        if warm:
                            entry = warm.get((y, x))
                            if entry is not None and entry[1] == line[x]:
                                rest = self.seep(glow, rest, base, entry[0])
                        line[x] = (char, glow + rest)
                elif style == '' or style == plain:
                    line[x] = (char, glow)

    def sync(self, items, active, width, height):
        rects = []
        seen = set()
        glowing = set()
        known = self.known
        for w in items:
            sc = scene_of(w)
            live = w in active
            if live:
                ir = sc.iround
                camx = ir(sc.camx)
                camy = ir(sc.camy)
                xoff = sc.dimxoffset
                yoff = sc.dimyoffset
                bgcolor = sc.bgcolor
            for o in sc.objs:
                r = getattr(o, 'rendering', None)
                if r is None:
                    continue
                seen.add(r)
                if not live or not r.t.rtext:
                    continue
                state = known.get(r)
                if state is None:
                    state = known[r] = [(0, 0, '', 0, 0), None, [], 0]
                current = r.state(camx, camy, xoff, yoff)
                previous = state[0]
                if previous == current:
                    continue
                if previous[2]:
                    x, y, _, xo, yo = previous
                    rects.append((x + xo, y - yo, x + xo + state[3], y - yo + len(state[2])))
                if current[2]:
                    key = (current[2], r.renderspaces, bgcolor)
                    if state[1] != key:
                        state[1] = key
                        state[2] = self.parse(sc, current[2], r.renderspaces)
                        state[3] = max(row[0] for row in state[2])
                    x, y, _, xo, yo = current
                    rects.append((x + xo, y - yo, x + xo + state[3], y - yo + len(state[2])))
                state[0] = current
            if live:
                view = self.view(sc, width, height)
                for light in sc.lights:
                    if not light.glowing():
                        continue
                    glowing.add(light)
                    key = (light.glowkey(camx, camy, xoff, yoff, view), bgcolor)
                    previous = self.glows.get(light)
                    if previous is None or previous[0] != key:
                        if previous is not None:
                            rects.append(previous[1])
                        box = light.glowbox(camx, camy, xoff, yoff, view)
                        rects.append(box)
                        self.glows[light] = (key, box)
            else:
                glowing.update(light for light in sc.lights if light in self.glows)
        for light in [light for light in self.glows if light not in glowing]:
            rects.append(self.glows.pop(light)[1])
        for r in [r for r in known if r not in seen]:
            state = known.pop(r)
            if state[0][2]:
                x, y, _, xo, yo = state[0]
                rects.append((x + xo, y - yo, x + xo + state[3], y - yo + len(state[2])))
        return rects

    def layers(self, items, width, height, autobg):
        layers = []
        for w in items:
            sc = scene_of(w)
            view = self.view(sc, width, height)
            ext = self.extent(sc, view) if sc.camrotation % 360.0 else view
            bg = self.bgstyle(sc.bgcolor) if autobg and getattr(w, 'autobg', True) else None
            sprites = []
            for r in sorted([o.rendering for o in sc.objs if hasattr(o, 'rendering')], key=lambda r: r.z):
                state = self.known.get(r)
                if state is None or not state[0][2]:
                    continue
                key = (state[0][2], r.renderspaces, sc.bgcolor)
                if state[1] != key:
                    state[1] = key
                    state[2] = self.parse(sc, state[0][2], r.renderspaces)
                    state[3] = max(row[0] for row in state[2])
                x, y, _, xo, yo = state[0]
                sprites.append((x + xo, y - yo, state[2]))
            lit = []
            if view[0] < view[2] and view[1] < view[3]:
                camx = sc.iround(sc.camx)
                camy = sc.iround(sc.camy)
                for light in sc.lights:
                    if light.glowing():
                        rows = light.glowrows(camx, camy, sc.dimxoffset, sc.dimyoffset, ext)
                        if rows:
                            lit.append((light, rows))
            layers.append((view, ext, bg, sprites, sc, lit))
        return layers

    def paint(self, back, spans, view, bg, sprites, sc, lit, plain, top, bottom, right):
        vx0, vy0, vx1, vy1 = view
        warm = {}
        if bg is not None:
            cell = (' ', bg)
            for y in range(max(vy0, top), min(vy1, bottom)):
                span = spans.get(y)
                if span is None:
                    continue
                a = max(vx0, span[0])
                b = min(vx1, span[1])
                if a < b:
                    back[y][a:b] = [cell] * (b - a)
        for x, y, grid in sprites:
            if y >= bottom or y + len(grid) <= top or x >= right:
                continue
            for i, (rowwidth, runs, glass) in enumerate(grid):
                ry = y + i
                if ry < vy0 or ry >= vy1:
                    continue
                span = spans.get(ry)
                if span is None:
                    continue
                a = max(vx0, span[0], x)
                b = min(vx1, span[1], x + rowwidth)
                if a >= b:
                    continue
                line = back[ry]
                for offset, cells in runs:
                    s = max(a, x + offset)
                    e = min(b, x + offset + len(cells))
                    if s < e:
                        line[s:e] = cells[s - x - offset:e - x - offset]
                for offset, cells in glass:
                    s = max(a, x + offset)
                    e = min(b, x + offset + len(cells))
                    for xx in range(s, e):
                        char, active = cells[xx - x - offset]
                        cell, share = self.glass(sc, line[xx], char, active)
                        if cell is not None:
                            line[xx] = cell
                            if share is not None:
                                warm[(ry, xx)] = (share, cell)
        if lit:
            self.shine(sc, back, spans, lit, plain, warm)

    @staticmethod
    def extent(sc, view):
        aspect = sc.aspect or 0.5
        cx = (view[0] + view[2]) / 2
        cy = (view[1] + view[3]) / 2
        radius = math.hypot((view[2] - view[0]) / 2 * aspect, (view[3] - view[1]) / 2)
        rx = int(math.ceil(radius / aspect))
        ry = int(math.ceil(radius))
        return (int(math.floor(cx)) - rx, int(math.floor(cy)) - ry, int(math.ceil(cx)) + rx, int(math.ceil(cy)) + ry)

    @staticmethod
    def turn(back, local, spans, view, ext, sc, angle, clear):
        vx0, vy0, vx1, vy1 = view
        ex0, ey0, ex1, ey1 = ext
        aspect = sc.aspect or 0.5
        rad = math.radians(angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        cx = (vx0 + vx1) / 2
        cy = (vy0 + vy1) / 2
        ew = ex1 - ex0
        eh = ey1 - ey0
        for y, (lo, hi) in spans.items():
            if y < vy0 or y >= vy1:
                continue
            a = max(lo, vx0)
            b = min(hi, vx1)
            if a >= b:
                continue
            line = back[y]
            dy = y + 0.5 - cy
            for x in range(a, b):
                dx = (x + 0.5 - cx) * aspect
                sx = int(math.floor((dx * cos_a - dy * sin_a) / aspect + cx)) - ex0
                sy = int(math.floor(dx * sin_a + dy * cos_a + cy)) - ey0
                if sx < 0 or sx >= ew or sy < 0 or sy >= eh:
                    continue
                cell = local[sy][sx]
                if cell is not clear:
                    line[x] = cell

    def compose(self, items, active, region, bounds, outer, autobg):
        regx, regy, width, height = region
        rects = self.sync(items, active, width, height)
        prefix = ''
        moved = self.region is not None and self.region != region
        if moved:
            prefix = self.vacate(self.region, region, bounds)
        self.region = region
        if moved or self.stale(width, height):
            self.front = [[None] * width for _ in range(height)]
            self.width = width
            self.height = height
            rects = [(0, 0, width, height)]
        dirty = bool(rects)
        for w in items:
            sc = scene_of(w)
            if w not in active:
                continue
            angle = sc.camrotation % 360.0
            previous = self.rotated.get(sc)
            if not angle and previous is None:
                continue
            view = self.view(sc, width, height)
            key = (angle, sc.aspect, view)
            if key != previous or dirty:
                rects.append(view)
            if angle:
                self.rotated[sc] = key
            else:
                del self.rotated[sc]
        spans = {}
        for x0, y0, x1, y1 in rects:
            x0 = max(0, x0)
            y0 = max(0, y0)
            x1 = min(width, x1)
            y1 = min(height, y1)
            if x0 >= x1 or y0 >= y1:
                continue
            for y in range(y0, y1):
                span = spans.get(y)
                if span is None:
                    spans[y] = [x0, x1]
                else:
                    if x0 < span[0]: span[0] = x0
                    if x1 > span[1]: span[1] = x1
        if not spans:
            return prefix
        top = min(spans)
        bottom = max(spans) + 1
        right = max(s[1] for s in spans.values())
        base = (' ', self.bgstyle(outer) if outer is not None else '')
        back = {y: [base] * width for y in spans}
        clear = (' ', base[1])
        for view, ext, bg, sprites, sc, lit in self.layers(items, width, height, autobg):
            angle = sc.camrotation % 360.0
            if angle and view[0] < view[2] and view[1] < view[3]:
                ex0, ey0, ex1, ey1 = ext
                ew = ex1 - ex0
                eh = ey1 - ey0
                local = {y: [clear] * ew for y in range(eh)}
                full = {y: [0, ew] for y in range(eh)}
                moved_sprites = [(x - ex0, y - ey0, grid) for x, y, grid in sprites]
                moved_lit = [(light, [(y - ey0, x - ex0, amounts) for y, x, amounts in rows]) for light, rows in lit]
                self.paint(local, full, (0, 0, ew, eh), bg, moved_sprites, sc, moved_lit, base[1], 0, eh, ew)
                self.turn(back, local, spans, view, ext, sc, angle, clear)
            else:
                self.paint(back, spans, view, bg, sprites, sc, lit, base[1], top, bottom, right)
        out = []
        style = None
        for y in sorted(spans):
            lo, hi = spans[y]
            new = back[y][lo:hi]
            old = self.front[y][lo:hi]
            if new == old:
                continue
            mask = bytes([a != b for a, b in zip(new, old)])
            for run in self.runs.finditer(mask):
                start, end = run.span()
                out.append(f'\033[{regy + y + 1};{regx + lo + start + 1}H')
                for cellstyle, group in groupby(new[start:end], key=itemgetter(1)):
                    if cellstyle != style:
                        style = cellstyle
                        out.append('\033[0m' + style)
                    out.append(''.join([cell[0] for cell in group]))
                self.front[y][lo + start:lo + end] = new[start:end]
        if not out:
            return prefix
        out.append('\033[0m')
        return prefix + ''.join(out)
