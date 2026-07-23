import re, shutil
from pyfiglet import Figlet
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
    "pink": (255, 105, 180),
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
    "brightpink": (255, 182, 193),
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
    "darkpink": (231, 84, 128),
    "black": (0, 0, 0),
    "darkgray": (64, 64, 64),
    "brightblack": (102, 102, 102),
    "gray": (128, 128, 128),
    "brightgray": (192, 192, 192),
    "default": (204, 204, 204),
    "bright": (229, 229, 229),
    "white": (255, 255, 255),
}

SIZE_MAP = {
    1: "standard", 2: "big", 3: "slant", 4: "doom", 5: "bubble",
}

bg = (0,0,0)
fg = RGB_MAP["default"]
bgrecomp = re.compile(r'\033\[48;2;(\d{1,3});(\d{1,3});(\d{1,3})m')
fgrecomp = re.compile(r'\033\[38;2;(\d{1,3});(\d{1,3});(\d{1,3})m')
recomp = re.compile(r'\x1b\[[0-9;]*m')
_figlet_cache = {}

def getfiglet(font, width):
    key = (font, width)
    if key not in _figlet_cache:
        _figlet_cache[key] = Figlet(font=font, width=width)
    return _figlet_cache[key]

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

def getcolor(text:str, back=False):
    target = "\033[48;2;" if back else "\033[38;2;"
    if target not in text:
        return (bg if back else fg), ""
    matches = list(bgrecomp.finditer(text) if back else fgrecomp.finditer(text))
    tupl = tuple(int(x) for x in matches[-1].groups()) if matches else (bg if back else fg)
    color = matches[-1].group(0) if matches else ""
    return tupl, color

def style(text: str, color=None, alpha=None, size=None, width=80, bgcolor=None,
          bgalpha=None, bg=bg, fg=fg, onbg=False, reset=True, clean=False):

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
        if bgcolor_rgb is None:
            bgcolor_rgb, match_bgcolor = getcolor(text, True)
        rb = int(bg_rgb[0] * (1 - _bgalpha) + bgcolor_rgb[0] * _bgalpha)
        gb = int(bg_rgb[1] * (1 - _bgalpha) + bgcolor_rgb[1] * _bgalpha)
        bb = int(bg_rgb[2] * (1 - _bgalpha) + bgcolor_rgb[2] * _bgalpha)
        ansi_bgcolor = f"\033[48;2;{rb};{gb};{bb}m"
    else:
        bgcolor_rgb, match_bgcolor = getcolor(text, True)
        ansi_bgcolor = ""

    if user_color is not None or alpha is not None:
        _alpha = alpha if alpha is not None else 1.0
        if color_rgb is None:
            color_rgb, match_color = getcolor(text)
        activebg_rgb = bg_rgb if onbg else bgcolor_rgb
        r = int(activebg_rgb[0] * (1 - _alpha) + color_rgb[0] * _alpha)
        g = int(activebg_rgb[1] * (1 - _alpha) + color_rgb[1] * _alpha)
        b = int(activebg_rgb[2] * (1 - _alpha) + color_rgb[2] * _alpha)
        ansi_color = f"\033[38;2;{r};{g};{b}m"
    else:
        ansi_color = ""

    if clean:
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
            fig = getfiglet(font=ascii_font, width=width)
            ascii_art = fig.renderText(ascii_art)

    prefix = ansi_bgcolor + ansi_color
    suffix = "\033[0m" if reset else ""
    trailing = '\n' if ascii_art.endswith('\n') else ''
    
    lines = ascii_art.split('\n')
    while lines and not lines[-1].strip():
        lines.pop()
        
    styled_text = '\n'.join(prefix + line.rstrip() + suffix for line in lines) + trailing

    return styled_text

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
