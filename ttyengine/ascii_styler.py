import re, shutil
from pyfiglet import Figlet
from typing import Optional, Union
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



bg = (0,0,0)
fg = RGB_MAP["default"]
recomp = re.compile(r'(\x1b\[[0-9;]*[a-zA-Z])')

def rgb(color):
    if isinstance(color, (tuple, list)):
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

def style(text:str,color=None,alpha=1.0,size=None,width=80,bgcolor=None,bgalpha=1.0,bg=bg,fg=fg,reset=True):
    bgcolor = rgb(bgcolor)
    if not bgcolor is None:
        rb = int(bg[0] * (1 - bgalpha) + bgcolor[0] * bgalpha)
        gb = int(bg[1] * (1 - bgalpha) + bgcolor[1] * bgalpha)
        bb = int(bg[2] * (1 - bgalpha) + bgcolor[2] * bgalpha)
        ansi_bgcolor = f"\033[48;2;{rb};{gb};{bb}m"
    else:
        for part in recomp.split(text):
            if(part.startswith("\033[48;2")):
                components = part[2:-1].split(';')
                bgcolor = tuple(int(x) for x in components[2:])
                break
        bgcolor = bg if not isinstance(bgcolor, tuple) else bgcolor
        ansi_bgcolor = ""
    if color is None and alpha is not None: color = fg
    color = rgb(color)
    if not color is None:
        r = int(bgcolor[0] * (1 - alpha) + color[0] * alpha)
        g = int(bgcolor[1] * (1 - alpha) + color[1] * alpha)
        b = int(bgcolor[2] * (1 - alpha) + color[2] * alpha)
        ansi_color = f"\033[38;2;{r};{g};{b}m"
    else:
        ansi_color = ""
    if(not size is None):
        ascii_font = SIZE_MAP[max(1,min(5,size))] if isinstance(size, int) else size
        if(size>=1):
            fig = Figlet(font=ascii_font, width=width)
            ascii_art = fig.renderText(text)
        else:
            ascii_art = text
    else:
        ascii_art = text
    styled_text = ansi_bgcolor + ansi_color + ascii_art
    if reset: styled_text += "\033[0m"
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
