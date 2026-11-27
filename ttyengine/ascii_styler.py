import re, shutil, colorsys, math, itertools
from functools import lru_cache
from . import ansi
from . import cells as _cells
from . import axes as _axes
from . import sprite as _sprite
from . import region as _regions
from .figlet import Figlet, available
from .image_reader import read as readimage

DEFAULT_IMAGE_WIDTH = 80

RGB_MAP = {
    "red": (205, 49, 49),
    "orange": (255, 165, 0),
    "brown": (139, 69, 19),
    "gold": (255, 215, 0),
    "yellow": (229, 229, 16),
    "green": (13, 188, 121),
    "turquoise": (64, 224, 208),
    "cyan": (17, 168, 205),
    "blue": (36, 114, 200),
    "purple": (128, 0, 128),
    "violet": (238, 130, 238),
    "magenta": (188, 63, 188),
    "pink": (255, 105, 180), # 13 colors
    "brightred": (241, 76, 76),
    "brightorange": (255, 200, 0),
    "brightbrown": (205, 133, 63),
    "brightgold": (255, 235, 100),
    "brightyellow": (245, 245, 67),
    "brightgreen": (35, 209, 139),
    "brightturquoise": (127, 255, 212),
    "brightcyan": (41, 184, 219),
    "brightblue": (59, 142, 234),
    "brightpurple": (191, 0, 191),
    "brightviolet": (255, 170, 255),
    "brightmagenta": (214, 112, 214),
    "brightpink": (255, 182, 193), # 13 bright colors
    "darkred": (139, 0, 0),
    "darkorange": (255, 140, 0),
    "darkbrown": (60, 30, 10),
    "darkgold": (184, 134, 11),
    "darkyellow": (139, 139, 0),
    "darkgreen": (0, 100, 0),
    "darkturquoise": (0, 134, 139),
    "darkcyan": (0, 139, 139),
    "darkblue": (0, 0, 139),
    "darkpurple": (75, 0, 130),
    "darkviolet": (148, 0, 211),
    "darkmagenta": (139, 0, 139),
    "darkpink": (231, 84, 128), # 13 dark colors
    "black": (0, 0, 0),
    "darkgray": (64, 64, 64),
    "brightblack": (102, 102, 102),
    "gray": (128, 128, 128),
    "brightgray": (192, 192, 192),
    "default": (204, 204, 204),
    "bright": (229, 229, 229),
    "white": (255, 255, 255), # 8 gray scale colors
}

FONT_MAP = {
    1: "standard", 2: "big", 3: "slant", 4: "doom", 5: "bubble",
}

DEFAULT_BG = (0,0,0)
DEFAULT_FG = RGB_MAP["default"]
bgrecomp = ansi.Pattern(re.escape(ansi.CSI) + r'48;2;(\d{1,3});(\d{1,3});(\d{1,3})m')
fgrecomp = ansi.Pattern(re.escape(ansi.CSI) + r'38;2;(\d{1,3});(\d{1,3});(\d{1,3})m')
recomp = ansi.SGR
ALPHA_FG = 1000
ALPHA_FGBACK = 1300
ALPHA_BG = 1600
alphamark = ansi.Pattern(re.escape(ansi.CSI) + r'(1[0-8]\d\d)m')
_figlet_cache = {}
DEFAULT_SHADES = "                          ..................'''''''''::::::,,,____\"\"\"^^^;;;;;!!!!!+===rrr//(cc?||[[[[jvvJ}{YYn3oe5%%hh$$GGXbmm#&00DKRRR░░░░WW@MMMMMMMMMMMMMMMMMMMMMMMMMM▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓███████████████"


def alphacode(base, alpha):
    return ansi.sgr(base + int(round(max(0.0, min(1.0, alpha)) * 255)))


def alphaparse(text):
    fa = ba = None
    back = False
    for match in alphamark.finditer(text):
        code = int(match.group(1))
        if ALPHA_BG <= code <= ALPHA_BG + 255:
            ba = (code - ALPHA_BG) / 255
        elif ALPHA_FGBACK <= code <= ALPHA_FGBACK + 255:
            fa = (code - ALPHA_FGBACK) / 255
            back = True
        elif ALPHA_FG <= code <= ALPHA_FG + 255:
            fa = (code - ALPHA_FG) / 255
            back = False
    return fa, back, ba


@lru_cache(maxsize=512)
def _rgb(color):
    return Styler._rgb_uncached(color)


class Styler:
    def __init__(self, source=None, bgcolor=DEFAULT_BG, fgcolor=DEFAULT_FG):
        self.source = source
        self._bgcolor = bgcolor
        self._fgcolor = fgcolor
        self.shapes = Shapes

    @property
    def bgcolor(self):
        return self._bgcolor if self.source is None else self.source.bgcolor
    @bgcolor.setter
    def bgcolor(self, value):
        if self.source is None: self._bgcolor = value
        else: self.source.bgcolor = value

    @property
    def fgcolor(self):
        return self._fgcolor if self.source is None else self.source.fgcolor
    @fgcolor.setter
    def fgcolor(self, value):
        if self.source is None: self._fgcolor = value
        else: self.source.fgcolor = value

    @staticmethod
    def getfiglet(font, width):
        key = (font, width)
        if key not in _figlet_cache:
            _figlet_cache[key] = Figlet(font=font, width=width)
        return _figlet_cache[key]

    @staticmethod
    def fonts():
        return available()

    @staticmethod
    def rgb(color):
        if isinstance(color, list):
            color = tuple(color)
        try:
            hash(color)
            return _rgb(color)
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _rgb_uncached(color):
        if isinstance(color, tuple):
            if len(color) == 3:
                return tuple(max(0, min(255, int(c))) for c in color)
            elif len(color) == 2:
                rainbow = max(1, min(3, color[1]))
                start = (max(1, min(4, color[1]))-1) * 13
                rainbow *= 13
                if color[1] > 3: rainbow += 8
                for i,c in enumerate(RGB_MAP.values()):
                    if i in range(start, rainbow) and i==color[0]:
                        return c
            elif len(color) == 1:
                for i,c in enumerate(RGB_MAP.values()):
                    if i==color[0]:
                        return c
        elif isinstance(color, (float,int)):
            for i,c in enumerate(RGB_MAP.values()):
                if i==round(color):
                    return c
        elif isinstance(color, str):
            return RGB_MAP.get(color.lower(), None)
        return None

    @staticmethod
    def hsv(hue, saturation=1.0, value=1.0):
        s = max(0.0, min(1.0, saturation))
        v = max(0.0, min(1.0, value))
        r, g, b = colorsys.hsv_to_rgb((hue % 360) / 360, s, v)
        return (round(r * 255), round(g * 255), round(b * 255))

    @staticmethod
    def getcolor(text:str, back=False, default=None):
        fallback = default if default is not None else (DEFAULT_BG if back else DEFAULT_FG)
        target = ansi.CSI + ("48;2;" if back else "38;2;")
        if target not in text:
            return fallback, ""
        matches = list(bgrecomp.finditer(text) if back else fgrecomp.finditer(text))
        tupl = tuple(int(x) for x in matches[-1].groups()) if matches else fallback
        color = matches[-1].group(0) if matches else ""
        return tupl, color

    def _style(self, text: str, color=None, alpha=None, font=None, width=80, bgcolor=None,
               bgalpha=None, bg=DEFAULT_BG, fg=DEFAULT_FG, onbg=False, reset=True, clean=False,
               bold=False, italic=False, underline=False, size=None):
        rgb = self.rgb
        getcolor = self.getcolor
        if alpha is not None:
            alpha = max(0.0, min(1.0, alpha))
        if bgalpha is not None:
            bgalpha = max(0.0, min(1.0, bgalpha))
        bg_rgb  = rgb(bg)  or bg
        fg_rgb  = rgb(fg)  or fg
        match_bgcolor = ""
        match_color   = ""
        user_color  = color
        user_bgcolor = bgcolor
        bgcolor_rgb = rgb(bgcolor)
        color_rgb   = rgb(color)
        old_fa, old_back, old_ba = alphaparse(text) if clean else (None, False, None)
        fg_mark = ""
        bg_mark = ""
        if user_bgcolor is not None or bgalpha is not None:
            _bgalpha = bgalpha if bgalpha is not None else 1.0
            bg_marked = _bgalpha
            transparent_bg = False
            if bgcolor_rgb is None:
                bgcolor_rgb, match_bgcolor = getcolor(text, True, bg_rgb)
                transparent_bg = not match_bgcolor
                if old_ba is not None:
                    bg_marked = _bgalpha * old_ba
            if transparent_bg:
                ansi_bgcolor = ""
            else:
                if bg_marked < 1:
                    bg_mark = alphacode(ALPHA_BG, bg_marked)
                rb = int(bg_rgb[0] * (1 - _bgalpha) + bgcolor_rgb[0] * _bgalpha)
                gb = int(bg_rgb[1] * (1 - _bgalpha) + bgcolor_rgb[1] * _bgalpha)
                bb = int(bg_rgb[2] * (1 - _bgalpha) + bgcolor_rgb[2] * _bgalpha)
                ansi_bgcolor = ansi.bg(rb, gb, bb)
        else:
            bgcolor_rgb, match_bgcolor = getcolor(text, True, bg_rgb)
            ansi_bgcolor = ""
            if match_bgcolor and old_ba is not None and old_ba < 1:
                bg_mark = alphacode(ALPHA_BG, old_ba)
        if user_color is not None or alpha is not None:
            _alpha = alpha if alpha is not None else 1.0
            fg_marked = _alpha
            fg_back = bool(onbg)
            if color_rgb is None:
                color_rgb, match_color = getcolor(text, False, fg_rgb)
                if old_fa is not None:
                    fg_marked = _alpha * old_fa
                    if alpha is None:
                        fg_back = old_back
            if fg_marked < 1:
                fg_mark = alphacode(ALPHA_FGBACK if fg_back else ALPHA_FG, fg_marked)
            activebg_rgb = bg_rgb if onbg else bgcolor_rgb
            r = int(activebg_rgb[0] * (1 - _alpha) + color_rgb[0] * _alpha)
            g = int(activebg_rgb[1] * (1 - _alpha) + color_rgb[1] * _alpha)
            b = int(activebg_rgb[2] * (1 - _alpha) + color_rgb[2] * _alpha)
            ansi_color = ansi.fg(r, g, b)
        else:
            ansi_color = ""
            if old_fa is not None:
                fg_mark = alphacode(ALPHA_FGBACK if old_back else ALPHA_FG, old_fa)
        if clean:
            bold      = bold      or ansi.BOLD in text
            italic    = italic    or ansi.ITALIC in text
            underline = underline or ansi.UNDERLINE in text
            ascii_art = recomp.sub('', text)
            if not ansi_bgcolor:
                ansi_bgcolor = match_bgcolor
            if not ansi_color:
                ansi_color   = match_color
        else:
            ascii_art = text
        if font is None:
            font = size
        if font is not None and (not isinstance(font, int) or font >= 1):
            name = FONT_MAP[max(1, min(5, font))] if isinstance(font, int) else font
            ascii_art = self.getfiglet(font=name, width=width).renderText(ascii_art)
        ansi_attrs = (ansi.BOLD if bold else '') + (ansi.ITALIC if italic else '') + (ansi.UNDERLINE if underline else '')
        prefix = ansi_bgcolor + ansi_color + ansi_attrs + bg_mark + fg_mark
        suffix = ansi.RESET if reset else ""
        trailing = '\n' if ascii_art.endswith('\n') else ''

        lines = ascii_art.split('\n')
        while lines and not lines[-1].strip():
            lines.pop()

        styled_text = '\n'.join(prefix + line.rstrip() + suffix for line in lines) + trailing
        return styled_text

    def style(self, *args, **kwargs):
        if len(args) <= 7 and 'bg' not in kwargs:
            kwargs['bg'] = self.bgcolor
        if len(args) <= 8 and 'fg' not in kwargs:
            kwargs['fg'] = self.fgcolor
        return self._style(*args, **kwargs)

    @staticmethod
    def fill(color=None, width=None, height=None, xoffset=0, yoffset=0, termx=None, termy=None, region=None):
        if termx is None or termy is None:
            termx, termy = shutil.get_terminal_size()
        if region is not None:
            xoffset, yoffset, width, height = _regions.resolve(region, termx, termy)
        width  = termx if width is None else int(width)
        height = termy if height is None else int(height)
        xoffset = int(xoffset)
        yoffset = int(yoffset)
        x_start = max(0, xoffset)
        y_start = max(0, yoffset)
        x_end   = min(termx, xoffset + width)
        y_end   = min(termy, yoffset + height)
        if x_end <= x_start or y_end <= y_start:
            return ""
        draw_width = x_end - x_start
        if color is None:
            row_str = ansi.RESET + " " * draw_width
            return "".join(
                ansi.move(row + 1, x_start + 1) + row_str
                for row in range(y_start, y_end)
            )
        rgb = Styler.rgb(color)
        if rgb is None:
            raise ValueError('unknown color: %r' % (color,))
        r, g, b = rgb
        row_str = ansi.bg(r, g, b) + " " * draw_width + ansi.RESET
        return "".join(
            ansi.move(row + 1, x_start + 1) + row_str
            for row in range(y_start, y_end)
        )

    @staticmethod
    def image(path, width=None, height=None, shades=DEFAULT_SHADES, aspect=0.5, color=None, bgcolor=None):
        if not shades:
            raise ValueError("shades must not be empty")
        if aspect <= 0:
            raise ValueError("aspect must be positive")
        if color is None:
            color = len(shades) == 1
        backdrop = None
        if bgcolor is not None:
            backdrop = Styler.rgb(bgcolor)
            if backdrop is None:
                raise ValueError('unknown color: %r' % (bgcolor,))
        coverage = bool(color) or backdrop is not None
        iw, ih, px = readimage(path)
        if width is None and height is None:
            width = min(iw, DEFAULT_IMAGE_WIDTH)
        if width is None:
            width = round(height * iw / (ih * aspect))
        if height is None:
            height = round(width * ih / iw * aspect)
        width = max(1, int(width))
        height = max(1, int(height))
        top = len(shades) - 1
        lines = []
        for cy in range(height):
            y0 = cy * ih // height
            y1 = max(y0 + 1, (cy + 1) * ih // height)
            sr = [0] * iw
            sg = [0] * iw
            sb = [0] * iw
            sa = [0] * iw
            for y in range(y0, y1):
                o = y * iw * 4
                r = px[o:o + iw * 4:4]
                g = px[o + 1:o + iw * 4:4]
                b = px[o + 2:o + iw * 4:4]
                a = px[o + 3:o + iw * 4:4]
                sr = [t + v * w for t, v, w in zip(sr, r, a)]
                sg = [t + v * w for t, v, w in zip(sg, g, a)]
                sb = [t + v * w for t, v, w in zip(sb, b, a)]
                if coverage:
                    sa = [t + w for t, w in zip(sa, a)]
            row = [] if backdrop is None else [ansi.bg(*backdrop)]
            current = None
            for cx in range(width):
                x0 = cx * iw // width
                x1 = max(x0 + 1, (cx + 1) * iw // width)
                norm = (x1 - x0) * (y1 - y0) * 255
                red = sum(sr[x0:x1]) / norm
                green = sum(sg[x0:x1]) / norm
                blue = sum(sb[x0:x1]) / norm
                opaque = sum(sa[x0:x1]) if coverage else 1
                if backdrop is not None:
                    clear = 1 - opaque / norm
                    red += backdrop[0] * clear
                    green += backdrop[1] * clear
                    blue += backdrop[2] * clear
                level = (54 * red + 183 * green + 19 * blue) / 65280
                char = shades[min(top, int(level * len(shades)))]
                if coverage:
                    if not opaque:
                        char = ' '
                    elif color and char != ' ':
                        rgb = (round(red), round(green), round(blue))
                        if rgb != current:
                            row.append(ansi.fg(*rgb))
                            current = rgb
                row.append(char)
            line = ''.join(row)
            if backdrop is None:
                line = line.rstrip(' ')
            lines.append(line + ansi.RESET if current or backdrop is not None else line)
        return '\n'.join(lines)
    @staticmethod
    def sprite(layers, axes=None, step=1, spaces=False):
        return _sprite.build(layers, axes, step, spaces)

    @staticmethod
    def rotate(source, xrotation=0, yrotation=0, zrotation=0, turns=None, aspect=0.5):
        planes = []
        if zrotation % 360:
            rad = math.radians(-zrotation)
            planes.append((0, 1, math.cos(rad), math.sin(rad)))
        found = {(1, 2): xrotation, (2, 0): yrotation}
        for key, angle in (turns or {}).items():
            first, second = key.split(',')
            found[(_axes.NAMES.index(first), _axes.NAMES.index(second))] = angle
        for (i, j), angle in sorted(found.items()):
            if angle % 360:
                rad = math.radians(angle)
                planes.append((i, j, math.cos(rad), math.sin(rad)))
        held = source if isinstance(source, _sprite.sprite) else _sprite.sprite(source)
        if not planes:
            return source
        return _sprite.rotate(held, planes, aspect)

    @staticmethod
    def scale(text, x, y=None, *depth, **named):
        y = x if y is None else y
        if not (math.isfinite(x) and math.isfinite(y)) or x <= 0 or y <= 0:
            raise ValueError('scale factors must be finite and positive')
        if isinstance(text, _sprite.sprite):
            if len(depth) > len(text.axes):
                raise ValueError('the sprite has %d extra axes, got %d factors' % (len(text.axes), len(depth)))
            factors = [x, y] + [x] * len(text.axes)
            for i, value in enumerate(depth):
                factors[2 + i] = value
            for key, value in named.items():
                if key not in _axes.NAMES or _axes.NAMES.index(key) not in text.axes:
                    raise ValueError('the sprite has no axis %r' % (key,))
                factors[2 + text.axes.index(_axes.NAMES.index(key))] = value
            if not all(math.isfinite(f) and f > 0 for f in factors):
                raise ValueError('scale factors must be finite and positive')
            return _sprite.scale(text, factors)
        if depth or named:
            raise ValueError('only sprites have more than two axes to scale')
        rows = _cells.parse(text)
        if not rows:
            return ''
        height = len(rows)
        width = max(len(row) for row in rows)
        out = []
        for j in range(max(1, round(height * y))):
            cy = (j + 0.5) / y
            if y < 1:
                r0, r1 = int(j / y), min(height, max(int(j / y) + 1, math.ceil((j + 1) / y)))
            else:
                r0 = min(height - 1, int(cy))
                r1 = r0 + 1
            line = []
            for i in range(max(1, round(width * x))):
                cx = (i + 0.5) / x
                if x < 1:
                    c0, c1 = int(i / x), max(int(i / x) + 1, math.ceil((i + 1) / x))
                else:
                    c0 = int(cx)
                    c1 = c0 + 1
                best = None
                near = 0.0
                for r in range(r0, r1):
                    row = rows[r]
                    for c in range(c0, min(c1, len(row))):
                        cell = row[c]
                        if _cells.blank(cell):
                            continue
                        dist = (c + 0.5 - cx) ** 2 + (r + 0.5 - cy) ** 2
                        if best is None or dist < near:
                            best, near = cell, dist
                line.append(best)
            out.append(line)
        return _cells.build(out)


_VOLUME_LIMIT = 2000000


def _list(value):
    return isinstance(value, (list, tuple))


def _per_axis(step, count):
    if _list(step):
        if len(step) != count:
            raise ValueError('step needs %d values, got %d' % (count, len(step)))
        found = [float(s) for s in step]
    else:
        found = [float(step)] * count
    for s in found:
        if not s > 0:
            raise ValueError('step must be positive')
    return found


def _volume(counts):
    total = 1
    for n in counts:
        total *= n
    if total > _VOLUME_LIMIT:
        raise ValueError('the shape would hold %d cells' % total)


def _body(counts, inside):
    _volume(counts)
    return {index for index in itertools.product(*[range(n) for n in counts]) if inside(index)}


def _carve(body, rank, thickness, filled, surface):
    if filled and not surface:
        return body
    span = range(rank) if filled else range(2)
    out = set()
    for cell in body:
        for axis in span:
            if any(cell[:axis] + (cell[axis] + gap,) + cell[axis + 1:] not in body for gap in _gaps(thickness)):
                out.add(cell)
                break
    return out


def _gaps(thickness):
    return [g for n in range(1, thickness + 1) for g in (-n, n)]


def _stack(cells, counts, char, axes, step):
    def layer(extra):
        return '\n'.join(
            ''.join(char if (x, y) + extra in cells else ' ' for x in range(counts[0]))
            for y in range(counts[1]))

    def build(prefix):
        if len(prefix) == len(counts) - 2:
            return layer(prefix)
        return tuple(build(prefix + (i,)) for i in range(counts[2 + len(prefix)]))

    return _sprite.build(build(()), axes, step, False)


def _solid(counts, inside, char, filled, thickness, surface, axes, step):
    thickness = max(1, round(thickness))
    body = _body(counts, inside)
    return _stack(_carve(body, len(counts), thickness, filled, surface), counts, char, axes, step)


class Shapes:
    @staticmethod
    def ellipse(rx, ry=None, char='o', filled=False, thickness=1, surface=False, axes=None, step=1):
        if _list(rx):
            if ry is not None:
                raise ValueError('with the radii in a sequence, pass char and the other options by keyword')
            radii = list(rx)
        elif ry is None:
            raise ValueError('an ellipse needs a radius for every axis')
        else:
            radii = [rx, ry]
        if len(radii) < 2:
            raise ValueError('an ellipse needs at least two radii')
        if len(radii) > 2:
            radii = [max(0, round(r)) for r in radii]
            offs = [r + 0.5 for r in radii]
            counts = [2 * r + 1 for r in radii]

            def inside(index):
                return sum([((i - r) / o) ** 2 for i, r, o in zip(index, radii, offs)]) <= 1

            return _solid(counts, inside, char, filled, thickness, surface, axes, step)
        rx, ry = radii
        rx = round(rx)
        ry = round(ry)
        if rx < 1 or ry < 1:
            return char
        thickness = max(1, thickness)
        ox, oy = rx + 0.5, ry + 0.5
        ix, iy = ox - thickness, oy - thickness
        rows = []
        for dy in range(-ry, ry + 1):
            row = ''
            for dx in range(-rx, rx + 1):
                hit = (dx / ox) ** 2 + (dy / oy) ** 2 <= 1
                if hit and not filled and ix > 0 and iy > 0:
                    hit = (dx / ix) ** 2 + (dy / iy) ** 2 >= 1
                row += char if hit else ' '
            rows.append(row)
        return '\n'.join(rows)

    @staticmethod
    def circle(radius, char='o', filled=False, thickness=1, aspect=0.5, surface=False, dims=2, axes=None, step=1):
        if dims < 2:
            raise ValueError('dims must be at least 2')
        if dims == 2:
            return Shapes.ellipse(radius * (1 / aspect), radius, char, filled, thickness)
        steps = _per_axis(step, dims - 2)
        radii = [radius * (1 / aspect), radius] + [radius / s for s in steps]
        return Shapes.ellipse(radii, None, char, filled, thickness, surface, axes, step)

    @staticmethod
    def block(width, height=None, char='█', filled=False, thickness=1, aspect=0.5, surface=False, axes=None, step=1):
        if _list(width):
            if height is not None:
                raise ValueError('with the sizes in a sequence, pass char and the other options by keyword')
            sizes = list(width)
            if not sizes:
                raise ValueError('a block needs at least one size')
            width = sizes[0]
            height = sizes[1] if len(sizes) > 1 else None
            if len(sizes) > 2:
                counts = [max(1, round(n)) for n in sizes]
                return _solid(counts, lambda index: True, char, filled, thickness, surface, axes, step)
        width = max(1, round(width))
        height = max(1, round(width * aspect) if height is None else round(height))
        thickness = max(1, round(thickness))
        rows = []
        for i in range(height):
            if filled or i < thickness or i >= height - thickness or width <= 2 * thickness:
                rows.append(char * width)
            else:
                rows.append(char * thickness + ' ' * (width - 2 * thickness) + char * thickness)
        return '\n'.join(rows)

    @staticmethod
    def triangle(height, base=None, char='█', filled=False, thickness=1, aspect=0.5, direction='up',
                 surface=False, dims=None, axes=None, step=1):
        height = max(1, round(height))
        bases = list(base) if _list(base) else [base]
        rank = max(len(bases) + 1, dims or 2)
        if rank > 2:
            steps = _per_axis(step, rank - 2)
            bases += [None] * (rank - 1 - len(bases))
            defaults = [height / aspect] + [height / s for s in steps]
            bases = [d if b is None else b for b, d in zip(bases, defaults)]
            halves = [max(0, round((b - 1) / 2)) for b in bases]
            counts = [2 * halves[0] + 1, height] + [2 * h + 1 for h in halves[1:]]

            def inside(index):
                depth = height - 1 - index[1] if direction == 'down' else index[1]
                reach = depth / (height - 1) if height > 1 else 0
                spans = [index[0]] + list(index[2:])
                return all(abs(i - h) <= round(h * reach) for i, h in zip(spans, halves))

            return _solid(counts, inside, char, filled, thickness, surface, axes, step)
        base = bases[0]
        thickness = max(1, round(thickness))
        if base is None:
            base = height / aspect
        half = max(0, round((base - 1) / 2))
        widths = [2 * round(half * i / (height - 1) if height > 1 else 0) + 1 for i in range(height)]
        full = widths[-1]
        rows = []
        for i, w in enumerate(widths):
            if filled or i >= height - thickness or w <= 2 * thickness:
                body = char * w
            else:
                body = char * thickness + ' ' * (w - 2 * thickness) + char * thickness
            rows.append(' ' * ((full - w) // 2) + body)
        if direction == 'down':
            rows.reverse()
        return '\n'.join(rows)

    @staticmethod
    def diamond(radius, char='█', filled=False, thickness=1, aspect=0.5, surface=False, dims=2, axes=None, step=1):
        if dims < 2:
            raise ValueError('dims must be at least 2')
        if dims > 2:
            steps = _per_axis(step, dims - 2)
            radii = [max(1, round(radius * (1 / aspect))), max(1, round(radius))] + [max(1, round(radius / s)) for s in steps]
            counts = [2 * r + 1 for r in radii]

            def inside(index):
                return sum([abs(i - r) / r for i, r in zip(index, radii)]) <= 1 + 1e-9

            return _solid(counts, inside, char, filled, thickness, surface, axes, step)
        ry = max(1, round(radius))
        rx = max(1, round(radius * (1 / aspect)))
        thickness = max(1, round(thickness))
        rows = []
        for dy in range(-ry, ry + 1):
            hw = round(rx * (1 - abs(dy) / ry))
            w = 2 * hw + 1
            if filled or w <= 2 * thickness:
                body = char * w
            else:
                body = char * thickness + ' ' * (w - 2 * thickness) + char * thickness
            rows.append(' ' * (rx - hw) + body)
        return '\n'.join(rows)

    @staticmethod
    def line(length, char='█', thickness=1, vertical=False, axis=None, step=1):
        length = max(1, round(length))
        thickness = max(1, round(thickness))
        if axis is not None:
            found = axis if isinstance(axis, int) and not isinstance(axis, bool) else _axes.NAMES.index(axis)
            if found == 1:
                vertical = True
            elif found == 0:
                vertical = False
            else:
                layer = '\n'.join([char * thickness] * thickness)
                return _sprite.build((layer,) * length, (_axes.NAMES[found],), step, False)
        if vertical:
            return '\n'.join([char * thickness] * length)
        return '\n'.join([char * length] * thickness)


_default_styler = Styler()
rgb = Styler.rgb
hsv = Styler.hsv
getcolor = Styler.getcolor
getfiglet = Styler.getfiglet
fonts = Styler.fonts
fill = Styler.fill
image = Styler.image
style = _default_styler._style
