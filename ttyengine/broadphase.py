import os
from itertools import chain

try:
    from ._native import Grid
except ImportError:
    Grid = None

if os.environ.get('TTYENGINE_PURE'):
    Grid = None

SHIFT = 3
LIMIT = 64
SCAN = 4096


class Broadphase:
    def __init__(self, scene):
        self.scene = scene
        self.source = None
        self.count = 0
        self.order = {}
        self.boxes = {}
        self.cells = {}
        self.large = set()
        self.stale = set()
        self.grid = Grid() if Grid is not None else None

    def touch(self, obj):
        self.stale.add(obj)

    def _span(self, box):
        return box[0] >> SHIFT, box[1] >> SHIFT, box[2] >> SHIFT, box[3] >> SHIFT

    def _place(self, obj):
        body = getattr(obj, 'physics', None)
        box = body.bounds() if body is not None else None
        self.boxes[obj] = box
        if box is None:
            return
        if self.grid is not None:
            self.grid.place(obj, self.order[obj], box)
            return
        cx0, cx1, cy0, cy1 = self._span(box)
        if (cx1 - cx0 + 1) * (cy1 - cy0 + 1) > LIMIT:
            self.large.add(obj)
            return
        cells = self.cells
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                bucket = cells.get((cx, cy))
                if bucket is None:
                    cells[(cx, cy)] = {obj}
                else:
                    bucket.add(obj)

    def _lift(self, obj):
        box = self.boxes.pop(obj, None)
        if box is None:
            return
        if self.grid is not None:
            self.grid.lift(obj)
            return
        if obj in self.large:
            self.large.discard(obj)
            return
        cx0, cx1, cy0, cy1 = self._span(box)
        cells = self.cells
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                bucket = cells.get((cx, cy))
                if bucket is not None:
                    bucket.discard(obj)
                    if not bucket:
                        del cells[(cx, cy)]

    def _rebuild(self, solids):
        self.source = solids
        self.order = {}
        self.boxes = {}
        self.cells = {}
        self.large = set()
        self.stale = set()
        if self.grid is not None:
            self.grid.clear()
        order = self.order
        for index, obj in enumerate(solids):
            order.setdefault(obj, index)
            if obj not in self.boxes:
                self._place(obj)
        self.count = len(solids)

    def _grow(self, solids):
        order = self.order
        for index in range(self.count, len(solids)):
            obj = solids[index]
            if obj in order:
                continue
            order[obj] = index
            self._place(obj)
        self.count = len(solids)

    def _refresh(self):
        stale = self.stale
        self.stale = set()
        boxes = self.boxes
        for obj in stale:
            if obj not in boxes:
                continue
            body = getattr(obj, 'physics', None)
            box = body.bounds() if body is not None else None
            if box != boxes[obj]:
                self._lift(obj)
                self._place(obj)

    def sync(self):
        solids = self.scene.solids
        size = len(solids)
        if solids is not self.source or size < self.count:
            self._rebuild(solids)
            return
        if size > self.count:
            self._grow(solids)
        if self.stale:
            self._refresh()

    def near(self, x0, x1, y0, y1, skip=None):
        solids = self.scene.solids
        if self.stale or solids is not self.source or len(solids) != self.count:
            self.sync()
        if self.grid is not None:
            return self.grid.query(x0, x1, y0, y1, skip)
        cells = self.cells
        large = self.large
        if not cells and not large:
            return []
        boxes = self.boxes
        cx0, cx1, cy0, cy1 = x0 >> SHIFT, x1 >> SHIFT, y0 >> SHIFT, y1 >> SHIFT
        if cx0 == cx1 and cy0 == cy1:
            pool = cells.get((cx0, cy0))
            if large:
                pool = chain(large, pool) if pool else large
            if not pool:
                return []
        elif (cx1 - cx0 + 1) * (cy1 - cy0 + 1) > SCAN:
            pool = self.order
        else:
            pool = set(large)
            for cx in range(cx0, cx1 + 1):
                for cy in range(cy0, cy1 + 1):
                    bucket = cells.get((cx, cy))
                    if bucket:
                        pool.update(bucket)
        found = []
        for o in pool:
            box = boxes.get(o)
            if box is None or o is skip or box[1] < x0 or box[0] > x1 or box[3] < y0 or box[2] > y1:
                continue
            found.append(o)
        if len(found) > 1:
            found.sort(key=self.order.__getitem__)
        return found
