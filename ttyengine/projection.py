import math

from . import cells as _cells

EPS = 1e-6


def spin(vec, planes):
    for i, j, c, s in planes:
        a = vec[i]
        b = vec[j]
        vec[i] = a * c - b * s
        vec[j] = a * s + b * c
    return vec


class camera:
    __slots__ = ('n', 'a', 'f', 'planes', 'cam', 'xoff', 'yoff', 'cx', 'cy', 'view', 'dc', 'dr', 'hx', 'hy', 'flat')

    def __init__(self, sc, view):
        n = self.n = sc._axes.n
        self.a = a = sc.aspect or 0.5
        self.f = sc.perspective
        self.planes = planes = sc._planes()
        self.cam = [sc.camx, sc.camy] + list(sc._camext)
        self.xoff = sc.dimxoffset
        self.yoff = sc.dimyoffset
        self.view = view
        self.cx = (view[0] + view[2]) / 2
        self.cy = (view[1] + view[3]) / 2
        self.dc = spin([a] + [0.0] * (n - 1), planes)
        self.dr = spin([0.0, -1.0] + [0.0] * (n - 2), planes)
        self.hx = 0.5 * (abs(self.dc[0]) + abs(self.dr[0])) / a
        self.hy = 0.5 * (abs(self.dc[1]) + abs(self.dr[1]))
        self.flat = all(abs(v) < EPS for v in (self.dc[1], self.dc[2], self.dr[0], self.dr[2])) and self.dc[0] > 0 and self.dr[1] < 0

    def point(self, origin):
        u = self.base(origin)
        if self.f:
            den = self.f - u[2]
            if den <= EPS:
                return None
            s = self.f / den
        else:
            s = 1.0
        return self.cx + u[0] * s / self.a, self.cy - u[1] * s, s

    def base(self, origin):
        cam = self.cam
        u = [0.0] * self.n
        u[0] = (origin[0] + 0.5 - cam[0] + self.xoff - self.cx) * self.a
        u[1] = origin[1] + self.yoff - cam[1] + self.cy - 0.5
        for k in range(2, self.n):
            u[k] = (origin[k] if k < len(origin) else 0) - cam[k]
        return spin(u, self.planes)


class depthbuffer:
    __slots__ = ('cells', 'cam')

    def __init__(self, cam):
        self.cells = {}
        self.cam = cam

    def plane(self, origin, plane):
        cam = self.cam
        f = cam.f
        a = cam.a
        cx = cam.cx
        cy = cam.cy
        x0, y0, x1, y1 = cam.view
        xb, yb, zb = cam.base(origin)[:3]
        dcx, dcy, dcz = cam.dc[:3]
        drx, dry, drz = cam.dr[:3]
        hx0 = cam.hx
        hy0 = cam.hy
        buf = self.cells
        get = buf.get
        floor = math.floor
        ceil = math.ceil
        for (c, r), cell in plane.items():
            z = zb + c * dcz + r * drz
            if f:
                den = f - z
                if den <= EPS:
                    continue
                s = f / den
            else:
                s = 1.0
            pc = cx + (xb + c * dcx + r * drx) * s / a
            pr = cy - (yb + c * dcy + r * dry) * s
            hx = hx0 * s
            hy = hy0 * s
            c0 = ceil(pc - hx - 0.5)
            c1 = ceil(pc + hx - 0.5)
            if c1 <= c0:
                c0 = floor(pc)
                c1 = c0 + 1
            r0 = ceil(pr - hy - 0.5)
            r1 = ceil(pr + hy - 0.5)
            if r1 <= r0:
                r0 = floor(pr)
                r1 = r0 + 1
            if c0 < x0:
                c0 = x0
            if c1 > x1:
                c1 = x1
            if r0 < y0:
                r0 = y0
            if r1 > y1:
                r1 = y1
            if c0 >= c1 or r0 >= r1:
                continue
            for rr in range(r0, r1):
                for cc in range(c0, c1):
                    key = (rr, cc)
                    held = get(key)
                    if held is None or z >= held[0]:
                        buf[key] = (z, cell)

    def text(self):
        x0, y0, x1, y1 = self.cam.view
        rows = [[None] * (x1 - x0) for _ in range(y1 - y0)]
        for (r, c), (_, cell) in self.cells.items():
            rows[r - y0][c - x0] = cell
        return _cells.build(rows)
