import colorama
from pyfiglet import Figlet
from typing import Optional, Union
colorama.init(autoreset=True)
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



from blessed import Terminal
term = Terminal()
bg = term.get_bgcolor(bits=8)
bg = (0,0,0) if bg[0]<0 or bg[0]>255 else bg
fg = term.get_fgcolor(bits=8)
fg = (255,255,255) if fg[0]<0 or fg[0]>255 else fg

def rgb(color):
    if isinstance(color, (tuple, list)) and len(color) == 3:
        return tuple(max(0, min(255, int(c))) for c in color)
    if isinstance(color, str):
        return RGB_MAP.get(color.lower(), (255, 255, 255))
    return fg

def style(text:str,color=None,alpha=1.0,size=1):
    color = rgb(color)
    r = int(bg[0] * (1 - alpha) + color[0] * alpha)
    g = int(bg[1] * (1 - alpha) + color[1] * alpha)
    b = int(bg[2] * (1 - alpha) + color[2] * alpha)
    ansi_color = f"\033[38;2;{r};{g};{b}m"
    ascii_font = SIZE_MAP[max(1,min(5,size))] if isinstance(size, int) else size
    fig = Figlet(font=ascii_font, width=term.width)
    ascii_art = fig.renderText(text)
    styled_text = ansi_color + ascii_art + "\033[0m"
    return styled_text
