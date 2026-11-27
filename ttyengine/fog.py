from . import ansi
from .components.light import _rebake, _style_parts, _STYLES, _unbake

_STEPS = 32


class fader:
    def __init__(self, sc):
        self.fgdef = tuple(sc.fgcolor)
        self.bgdef = tuple(sc.bgcolor)
        self.target = tuple(sc.fogcolor) if sc.fogcolor is not None else self.bgdef
        self.cache = {}

    def __call__(self, cell, amount):
        step = min(_STEPS, int(amount * _STEPS + 0.5))
        if step <= 0:
            return cell
        key = (cell, step)
        found = self.cache.get(key)
        if found is None:
            if len(self.cache) > 16384:
                self.cache.clear()
            found = self.cache[key] = self.fade(cell, 1.0 - step / _STEPS)
        return found

    def fade(self, cell, level):
        char, style = cell
        fgdef, bgdef, target = self.fgdef, self.bgdef, self.target

        def blend(base):
            return tuple(max(0, min(255, int(round(target[k] + (base[k] - target[k]) * level)))) for k in range(3))

        parts = _STYLES.get(style)
        if parts is None:
            parts = _style_parts(style)
        fa, back, ba, fgfound, fgtext, bgfound, newstyle = parts
        fg = fgfound if fgfound is not None else fgdef
        bgold = bgnew = bgdef
        if bgfound is not None:
            bgold = bgfound
            if ba is not None:
                bgnew = _rebake(bgdef, blend(_unbake(bgold, bgdef, ba)), ba)
            else:
                bgnew = blend(bgold)
            newstyle += ansi.bg(*bgnew)
        if char != ' ':
            if fa is not None:
                refold, refnew = (bgdef, bgdef) if back or bgfound is None else (bgold, bgnew)
                fgnew = _rebake(refnew, blend(_unbake(fg, refold, fa)), fa)
            else:
                fgnew = blend(fg)
            newstyle += ansi.fg(*fgnew)
        elif fgtext is not None:
            newstyle += fgtext
        return (char, newstyle)
