import re, shutil, colorsys
from typing import Optional, Union
from functools import lru_cache

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

SIZE_MAP = {
    1: "standard", 2: "big", 3: "slant", 4: "doom", 5: "bubble",
}

DEFAULT_BG = (0,0,0)
DEFAULT_FG = RGB_MAP["default"]
bgrecomp = re.compile(r'\033\[48;2;(\d{1,3});(\d{1,3});(\d{1,3})m')
fgrecomp = re.compile(r'\033\[38;2;(\d{1,3});(\d{1,3});(\d{1,3})m')
recomp = re.compile(r'\x1b\[[0-9;]*m')
_figlet_cache = {}


class Styler:
    """Text styling API.

    `_style` is the plain styling function; `style` is the same function with the `bg` and `fg`
    arguments filled in automatically from `source` (a Scene, which mirrors its Session's colors)
    whenever the caller does not pass them.
    """
    def __init__(self, source=None, bgcolor=DEFAULT_BG, fgcolor=DEFAULT_FG):
        self.source = source # anything exposing .bgcolor and .fgcolor
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
            try:
                from pyfiglet import Figlet
            except ImportError as e:
                raise ImportError(
                    "pyfiglet is required to render figlet-style text (i.e. when "
                    "style() is called with a `size` argument). Install it with "
                    "`pip install pyfiglet`."
                ) from e
            _figlet_cache[key] = Figlet(font=font, width=width)
        return _figlet_cache[key]

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
        """Hue (degrees, wraps around 360), saturation and value (0..1) -> (r, g, b) with 0..255 channels."""
        s = max(0.0, min(1.0, saturation))
        v = max(0.0, min(1.0, value))
        r, g, b = colorsys.hsv_to_rgb((hue % 360) / 360, s, v)
        return (round(r * 255), round(g * 255), round(b * 255))

    @staticmethod
    def getcolor(text:str, back=False, default=None):
        # `default` is the color to report when the text carries no escape of that kind
        # (_style() passes its own bg/fg here so the module-level constants are only a last resort).
        fallback = default if default is not None else (DEFAULT_BG if back else DEFAULT_FG)
        target = "\033[48;2;" if back else "\033[38;2;"
        if target not in text:
            return fallback, ""
        matches = list(bgrecomp.finditer(text) if back else fgrecomp.finditer(text))
        tupl = tuple(int(x) for x in matches[-1].groups()) if matches else fallback
        color = matches[-1].group(0) if matches else ""
        return tupl, color

    def _style(self, text: str, color=None, alpha=None, size=None, width=80, bgcolor=None,
               bgalpha=None, bg=DEFAULT_BG, fg=DEFAULT_FG, onbg=False, reset=True, clean=False,
               bold=False, italic=False, underline=False):
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
        if user_bgcolor is not None or bgalpha is not None:
            _bgalpha = bgalpha if bgalpha is not None else 1.0
            transparent_bg = False
            if bgcolor_rgb is None:
                bgcolor_rgb, match_bgcolor = getcolor(text, True, bg_rgb)
                # No background was given and the text has none either: there is nothing to
                # blend, so stay transparent and let the scene background show through
                # (previously this blended against black and painted a black box).
                transparent_bg = not match_bgcolor
            if transparent_bg:
                ansi_bgcolor = ""
            else:
                rb = int(bg_rgb[0] * (1 - _bgalpha) + bgcolor_rgb[0] * _bgalpha)
                gb = int(bg_rgb[1] * (1 - _bgalpha) + bgcolor_rgb[1] * _bgalpha)
                bb = int(bg_rgb[2] * (1 - _bgalpha) + bgcolor_rgb[2] * _bgalpha)
                ansi_bgcolor = f"\033[48;2;{rb};{gb};{bb}m"
        else:
            bgcolor_rgb, match_bgcolor = getcolor(text, True, bg_rgb)
            ansi_bgcolor = ""
        if user_color is not None or alpha is not None:
            _alpha = alpha if alpha is not None else 1.0
            if color_rgb is None:
                color_rgb, match_color = getcolor(text, False, fg_rgb)
            activebg_rgb = bg_rgb if onbg else bgcolor_rgb
            r = int(activebg_rgb[0] * (1 - _alpha) + color_rgb[0] * _alpha)
            g = int(activebg_rgb[1] * (1 - _alpha) + color_rgb[1] * _alpha)
            b = int(activebg_rgb[2] * (1 - _alpha) + color_rgb[2] * _alpha)
            ansi_color = f"\033[38;2;{r};{g};{b}m"
        else:
            ansi_color = ""
        if clean:
            # re-styling keeps the text attributes it already had
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
        if size is not None:
            ascii_font = SIZE_MAP[max(1, min(5, size))] if isinstance(size, int) else size
            if size >= 1:
                fig = self.getfiglet(font=ascii_font, width=width)
                ascii_art = fig.renderText(ascii_art)
        ansi_attrs = ('\033[1m' if bold else '') + ('\033[3m' if italic else '') + ('\033[4m' if underline else '')
        prefix = ansi_bgcolor + ansi_color + ansi_attrs
        suffix = "\033[0m" if reset else ""
        trailing = '\n' if ascii_art.endswith('\n') else ''

        lines = ascii_art.split('\n')
        while lines and not lines[-1].strip():
            lines.pop()

        styled_text = '\n'.join(prefix + line.rstrip() + suffix for line in lines) + trailing
        return styled_text

    def style(self, *args, **kwargs):
        """`_style` with bg/fg defaulting to the source's bgcolor/fgcolor (positions 7 and 8 count as passed)."""
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


class Shapes:
    """Text shape generators. Each returns a multi-line string (empty cells are spaces).

    `char` may be a styled string, e.g. Styler.style('X', 'red').
    `aspect` is the width/height ratio of a character cell (Transform.aspect, 0.5 by default);
    it keeps round shapes round on screen.
    """
    @staticmethod
    def ellipse(rx, ry, char='o', filled=False, thickness=0.15):
        rx = round(rx)
        ry = round(ry)
        if rx < 1 or ry < 1:
            return char
        rows = []
        for dy in range(-ry, ry + 1):
            row = ''
            for dx in range(-rx, rx + 1):
                val = (dx / rx) ** 2 + (dy / ry) ** 2
                hit = val < 1 + thickness if filled else abs(val - 1) < thickness
                row += char if hit else ' '
            rows.append(row)
        return '\n'.join(rows)

    @staticmethod
    def circle(radius, char='o', aspect=0.5, filled=False, thickness=0.15):
        """Circle of `radius` rows (the width is stretched by 1/aspect). Ring by default, `filled` for a disc."""
        return Shapes.ellipse(radius * (1 / aspect), radius, char, filled, thickness)

    @staticmethod
    def block(width, height=None, char='█', hollow=False, aspect=0.5):
        """Rectangle. Without `height` it is made square on screen (height = width * aspect)."""
        width = max(1, round(width))
        height = max(1, round(width * aspect) if height is None else round(height))
        rows = []
        for i in range(height):
            if hollow and 0 < i < height - 1:
                rows.append(char + ' ' * (width - 2) + char if width > 1 else char)
            else:
                rows.append(char * width)
        return '\n'.join(rows)

    @staticmethod
    def triangle(height, base=None, char='█', filled=True, aspect=0.5, direction='up'):
        """Isosceles triangle. `base` defaults to the width that looks as wide as it is tall."""
        height = max(1, round(height))
        if base is None:
            base = height / aspect
        half = max(0, round((base - 1) / 2))
        widths = [2 * round(half * i / (height - 1) if height > 1 else 0) + 1 for i in range(height)]
        full = widths[-1]
        rows = []
        for i, w in enumerate(widths):
            if filled or i == height - 1 or w < 2:
                body = char * w
            else:
                body = char + ' ' * (w - 2) + char
            rows.append(' ' * ((full - w) // 2) + body)
        if direction == 'down':
            rows.reverse()
        return '\n'.join(rows)

    @staticmethod
    def diamond(radius, char='█', filled=True, aspect=0.5):
        ry = max(1, round(radius))
        rx = max(1, round(radius * (1 / aspect)))
        rows = []
        for dy in range(-ry, ry + 1):
            hw = round(rx * (1 - abs(dy) / ry))
            w = 2 * hw + 1
            body = char * w if filled or w < 2 else char + ' ' * (w - 2) + char
            rows.append(' ' * (rx - hw) + body)
        return '\n'.join(rows)

    @staticmethod
    def line(length, char='█', vertical=False):
        length = max(1, round(length))
        return '\n'.join([char] * length) if vertical else char * length


# Module-level shortcuts so `from ttyengine.ascii_styler import style, fill` keeps working.
_default_styler = Styler()
rgb = Styler.rgb
hsv = Styler.hsv
getcolor = Styler.getcolor
getfiglet = Styler.getfiglet
fill = Styler.fill
style = _default_styler._style
