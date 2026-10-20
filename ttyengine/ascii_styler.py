import re, shutil, colorsys
from typing import Optional, Union
from functools import lru_cache
from .figlet import Figlet, available
from .image_reader import read as readimage

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
bgrecomp = re.compile(r'\033\[48;2;(\d{1,3});(\d{1,3});(\d{1,3})m')
fgrecomp = re.compile(r'\033\[38;2;(\d{1,3});(\d{1,3});(\d{1,3})m')
recomp = re.compile(r'\x1b\[[0-9;]*m')
ALPHA_FG = 1000
ALPHA_FGBACK = 1300
ALPHA_BG = 1600
alphamark = re.compile(r'\033\[(1[0-8]\d\d)m')
_figlet_cache = {}
DEFAULT_SHADES = "█"#" .:-=+*#%@"


def alphacode(base, alpha):
    return '\033[%dm' % (base + int(round(max(0.0, min(1.0, alpha)) * 255)))


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
    @lru_cache(maxsize=512)
    def rgb(color):
        if isinstance(color, (tuple, list)):
            color = tuple(color)
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
        target = "\033[48;2;" if back else "\033[38;2;"
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
                ansi_bgcolor = f"\033[48;2;{rb};{gb};{bb}m"
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
            ansi_color = f"\033[38;2;{r};{g};{b}m"
        else:
            ansi_color = ""
            if old_fa is not None:
                fg_mark = alphacode(ALPHA_FGBACK if old_back else ALPHA_FG, old_fa)
        if clean:
            bold      = bold      or '\033[1m' in text
            italic    = italic    or '\033[3m' in text
            underline = underline or '\033[4m' in text
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
        ansi_attrs = ('\033[1m' if bold else '') + ('\033[3m' if italic else '') + ('\033[4m' if underline else '')
        prefix = ansi_bgcolor + ansi_color + ansi_attrs + bg_mark + fg_mark
        suffix = "\033[0m" if reset else ""
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
    def fill(color=None, width=None, height=None, xoffset=0, yoffset=0, termx=None, termy=None):
        if termx is None or termy is None:
            termx, termy = shutil.get_terminal_size()
        width  = width  or termx
        height = height or termy
        x_start = max(0, xoffset)
        y_start = max(0, yoffset)
        x_end   = min(termx, xoffset + width)
        y_end   = min(termy, yoffset + height)
        if x_end <= x_start or y_end <= y_start:
            return ""
        draw_width = x_end - x_start
        if color is None:
            row_str = "\033[0m" + " " * draw_width
            return "".join(
                f"\033[{row + 1};{x_start + 1}H{row_str}"
                for row in range(y_start, y_end)
            )
        r, g, b = int(color[0]), int(color[1]), int(color[2])
        row_str = f"\033[48;2;{r};{g};{b}m" + " " * draw_width + "\033[0m"
        return "".join(
            f"\033[{row + 1};{x_start + 1}H{row_str}"
            for row in range(y_start, y_end)
        )

    @staticmethod
    def image(path, width=None, height=None, shades=DEFAULT_SHADES, aspect=0.5, color=None):
        if not shades:
            raise ValueError("shades must not be empty")
        if color is None:
            color = len(shades) == 1
        iw, ih, px = readimage(path)
        if width is None and height is None:
            termx, termy = shutil.get_terminal_size()
            width = min(termx, int(termy * iw / (ih * aspect)))
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
                if color:
                    sa = [t + w for t, w in zip(sa, a)]
            row = []
            current = None
            for cx in range(width):
                x0 = cx * iw // width
                x1 = max(x0 + 1, (cx + 1) * iw // width)
                norm = (x1 - x0) * (y1 - y0) * 255
                red = sum(sr[x0:x1]) / norm
                green = sum(sg[x0:x1]) / norm
                blue = sum(sb[x0:x1]) / norm
                level = (54 * red + 183 * green + 19 * blue) / 65280
                char = shades[min(top, int(level * len(shades)))]
                if color:
                    if not sum(sa[x0:x1]):
                        char = ' '
                    elif char != ' ':
                        rgb = (round(red), round(green), round(blue))
                        if rgb != current:
                            row.append("\033[38;2;%d;%d;%dm" % rgb)
                            current = rgb
                row.append(char)
            line = ''.join(row).rstrip(' ')
            lines.append(line + "\033[0m" if current else line)
        return '\n'.join(lines)

class Shapes:
    @staticmethod
    def ellipse(rx, ry, char='o', filled=False, thickness=1):
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
    def circle(radius, char='o', filled=False, thickness=1, aspect=0.5):
        return Shapes.ellipse(radius * (1 / aspect), radius, char, filled, thickness)

    @staticmethod
    def block(width, height=None, char='█', filled=False, thickness=1, aspect=0.5):
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
    def triangle(height, base=None, char='█', filled=False, thickness=1, aspect=0.5, direction='up'):
        height = max(1, round(height))
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
    def diamond(radius, char='█', filled=False, thickness=1, aspect=0.5):
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
    def line(length, char='█', thickness=1, vertical=False):
        length = max(1, round(length))
        thickness = max(1, round(thickness))
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
