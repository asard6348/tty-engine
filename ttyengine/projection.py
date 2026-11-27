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
    __slots__ = ('n', 'a', 'f', 'planes', 'cam', 'xoff', 'yoff', 'cx', 'cy', 'view', 'dc', 'dr', 'far', 'fog')

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
        self.far = sc.renderdistance
        self.fog = (sc.fogstart, sc.fog) if sc.fog else None

    def iso(self, point):
        cam = self.cam
        u = [0.0] * self.n
        u[0] = (point[0] - cam[0] + self.xoff - self.cx) * self.a
        u[1] = point[1] + self.yoff - cam[1] + self.cy
        for k in range(2, self.n):
            u[k] = (point[k] if k < len(point) else 0) - cam[k]
        return u

    def base(self, origin):
        point = [origin[0] + 0.5, origin[1] - 0.5]
        point.extend(origin[2:])
        return spin(self.iso(point), self.planes)

    def rig(self, origin, turns, pivot):
        n = self.n
        a = self.a
        pc, pr, mid = pivot
        centre = [origin[0] + pc, origin[1] - pr] + [0] * (n - 2)
        local = [(0.5 - pc) * a, pr - 0.5] + [0.0] * (n - 2)
        for k in range(2, n):
            centre[k] = mid[k - 2]
            local[k] = (origin[k] if k < len(origin) else 0) - mid[k - 2]
        shift = self.iso(centre)
        moved = spin(local, turns)
        base = spin([shift[k] + moved[k] for k in range(n)], self.planes)
        dc = spin(spin([a] + [0.0] * (n - 1), turns), self.planes)
        dr = spin(spin([0.0, -1.0] + [0.0] * (n - 2), turns), self.planes)
        return base, dc, dr

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


def _dot(a, b):
    return sum([x * y for x, y in zip(a, b)])


class depthbuffer:
    __slots__ = ('cells', 'cam')

    def __init__(self, cam):
        self.cells = {}
        self.cam = cam

    def plane(self, origin, plane):
        cam = self.cam
        self.splat(plane, cam.base(origin), cam.dc, cam.dr)

    def splat(self, plane, base, dcv, drv):
        cam = self.cam
        f = cam.f
        a = cam.a
        cx = cam.cx
        cy = cam.cy
        x0, y0, x1, y1 = cam.view
        xb, yb, zb = base[:3]
        dcx, dcy, dcz = dcv[:3]
        drx, dry, drz = drv[:3]
        hx0 = 0.5 * (abs(dcx) + abs(drx)) / a
        hy0 = 0.5 * (abs(dcy) + abs(dry))
        tilted = abs(dcy) > 1e-9 or abs(drx) > 1e-9
        far = cam.far
        measured = bool(far or cam.fog)
        if measured:
            bb = _dot(base, base)
            bc = 2 * _dot(base, dcv)
            br = 2 * _dot(base, drv)
            cc = _dot(dcv, dcv)
            rr = _dot(drv, drv)
            cr = 2 * _dot(dcv, drv)
        buf = self.cells
        get = buf.get
        floor = math.floor
        ceil = math.ceil
        for (c, r), cell in plane.items():
            dist = 0.0
            if measured:
                dist = math.sqrt(max(0.0, bb + c * bc + r * br + c * c * cc + r * r * rr + c * r * cr))
                if far and dist > far:
                    continue
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
            c0 = ceil(pc - hx - 0.5 - 1e-9)
            c1 = ceil(pc + hx - 0.5 - 1e-9)
            if c1 <= c0:
                c0 = floor(pc)
                c1 = c0 + 1
            r0 = ceil(pr - hy - 0.5 - 1e-9)
            r1 = ceil(pr + hy - 0.5 - 1e-9)
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
            if tilted:
                ax = dcx * s / a
                ay = -dcy * s
                bx = drx * s / a
                by = -dry * s
                det = ax * by - ay * bx
                hits = []
                if abs(det) > 1e-9:
                    for rr_ in range(r0, r1):
                        for cc_ in range(c0, c1):
                            qx = cc_ + 0.5 - pc
                            qy = rr_ + 0.5 - pr
                            u = (qx * by - qy * bx) / det
                            v = (ax * qy - ay * qx) / det
                            if -0.5 - 1e-9 <= u <= 0.5 + 1e-9 and -0.5 - 1e-9 <= v < 0.5 + 1e-9:
                                hits.append((rr_, cc_))
                if not hits:
                    hits.append((min(max(floor(pr), y0), y1 - 1), min(max(floor(pc), x0), x1 - 1)))
                for key in hits:
                    held = get(key)
                    if held is None or z >= held[0]:
                        buf[key] = (z, cell, dist)
                continue
            for rr_ in range(r0, r1):
                for cc_ in range(c0, c1):
                    key = (rr_, cc_)
                    held = get(key)
                    if held is None or z >= held[0]:
                        buf[key] = (z, cell, dist)

    def text(self, fade=None):
        x0, y0, x1, y1 = self.cam.view
        rows = [[None] * (x1 - x0) for _ in range(y1 - y0)]
        fog = self.cam.fog
        for (r, c), (_, cell, dist) in self.cells.items():
            if fog is not None and fade is not None:
                start, end = fog
                amount = (dist - start) / (end - start) if end > start else (1.0 if dist >= end else 0.0)
                if amount > 0:
                    cell = fade(cell, amount)
            rows[r - y0][c - x0] = cell
        return _cells.build(rows)
