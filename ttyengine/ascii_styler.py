import re, shutil
from pyfiglet import Figlet
from typing import Optional, Union
RGB_MAP = {
    "black": (0, 0, 0), "red": (255, 0, 0), "green": (0, 255, 0),
    "yellow": (255, 255, 0), "blue": (0, 0, 255), "magenta": (255, 0, 255),
    "cyan": (0, 255, 255), "white": (255, 255, 255),
    "brightblack": (128, 128, 128), "brightred": (255, 100, 100),
    "brightgreen": (100, 255, 100), "brightyellow": (255, 255, 100),
    "brightblue": (100, 100, 255), "brightmagenta": (255, 100, 255),
    "brightcyan": (100, 255, 255), "brightwhite": (255, 255, 255),
}
SIZE_MAP = {
    1: "standard", 2: "big", 3: "slant", 4: "doom", 5: "bubble",
}



bg = (0,0,0)
fg = (255,255,255)
recomp = re.compile(r'(\x1b\[[0-9;]*[a-zA-Z])')

def rgb(color):
    if isinstance(color, (tuple, list)) and len(color) == 3:
        return tuple(max(0, min(255, int(c))) for c in color)
    if isinstance(color, str):
        return RGB_MAP.get(color.lower(), (255, 255, 255))
    return None

def style(text:str,color=None,alpha=1.0,size=None,width=80,bgcolor=None,bgalpha=1.0):
    bgcolor = rgb(bgcolor)
    if not bgcolor is None:
        rb = int(bg[0] * (1 - bgalpha) + bgcolor[0] * bgalpha)
        gb = int(bg[1] * (1 - bgalpha) + bgcolor[1] * bgalpha)
        bb = int(bg[2] * (1 - bgalpha) + bgcolor[2] * bgalpha)
        ansi_bgcolor = f"\033[48;2;{rb};{gb};{bb}m"
    else:
        for part in recomp.split(text):
            if(re.match(part, "\033[48;2")):
                bgcolor = part
                break
        bgcolor = bg if bgcolor is None else bgcolor
        ansi_bgcolor = ""
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
    styled_text = ansi_bgcolor + ansi_color + ascii_art + "\033[0m"
    return styled_text

def fill(color=None, width=None, height=None):
    color = rgb(color) if color is not None else None
    if color is None:
        return ""
    r, g, b = int(color[0]), int(color[1]), int(color[2])
    ansi_color = f"\033[48;2;{r};{g};{b}m"
    if width is None or height is None:
        w, h = shutil.get_terminal_size()
        width  = width  or w
        height = height or h
    row_str = ansi_color + " " * width
    return "".join(f"\033[{row+1};1H{row_str}" for row in range(height))
