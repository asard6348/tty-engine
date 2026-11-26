import gc
import importlib
import os
import random
import unittest
import weakref

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

from ttyengine import broadphase
from ttyengine import scene as scene_mod

phys_mod = importlib.import_module("ttyengine.components.physics")

try:
    from ttyengine import _native
except ImportError:
    _native = None


def make_scene():
    sc = scene_mod.Scene()
    sc.termx, sc.termy, sc.dimx, sc.dimy = 100, 40, 100, 40
    return sc


@unittest.skipIf(_native is None, "native extension not built")
class GridParityTests(unittest.TestCase):
    def setUp(self):
        self.saved = broadphase.Grid
        broadphase.Grid = _native.Grid

    def tearDown(self):
        broadphase.Grid = self.saved

    def test_matches_pure_python_under_motion(self):
        rng = random.Random(7)
        sc = make_scene()
        shapes = ["#", "@@", "##\n##", "#" * 40, "#\n" * 30 + "#", "\n".join(["#" * 70] * 70)]
        objs = []
        for _ in range(120):
            o = sc.obj().create(rng.choice(shapes), rng.randint(-80, 80), rng.randint(-60, 60), dynamic=False, solid=True)
            objs.append(o)
        native = sc._broad
        self.assertIsNotNone(native.grid)
        pure = broadphase.Broadphase(sc)
        pure.grid = None
        for step in range(40):
            for o in rng.sample(objs, 25):
                o.transform.x = rng.randint(-80, 80)
                o.transform.y = rng.randint(-60, 60)
            native.stale.update(objs)
            pure.stale.update(objs)
            if step == 20:
                sc.solids.remove(objs.pop(3))
                extra = sc.obj().create("##", 0, 0, dynamic=False, solid=True)
                objs.append(extra)
            for _ in range(60):
                x0 = rng.randint(-120, 100)
                y0 = rng.randint(-100, 80)
                x1 = x0 + rng.choice([0, 1, 5, 20, 90, 400])
                y1 = y0 + rng.choice([0, 1, 5, 20, 90, 400])
                skip = rng.choice(objs + [None])
                self.assertEqual(native.near(x0, x1, y0, y1, skip), pure.near(x0, x1, y0, y1, skip))

    def test_grid_participates_in_gc(self):
        class Holder:
            pass

        holder = Holder()
        holder.grid = _native.Grid()
        holder.grid.place(holder, 0, (0, 0, 0, 0))
        self.assertEqual(holder.grid.query(0, 0, 0, 0), [holder])
        ref = weakref.ref(holder)
        del holder
        gc.collect()
        self.assertIsNone(ref())

    def test_lift_and_reuse_slots(self):
        grid = _native.Grid()
        items = [object() for _ in range(5)]
        for i, item in enumerate(items):
            grid.place(item, i, (i * 20, i * 20 + 1, 0, 1))
        self.assertTrue(grid.lift(items[2]))
        self.assertFalse(grid.lift(items[2]))
        self.assertEqual(grid.query(-5, 200, -5, 5), [items[0], items[1], items[3], items[4]])
        late = object()
        grid.place(late, 9, (40, 41, 0, 1))
        self.assertEqual(grid.query(40, 41, 0, 1), [late])
        self.assertEqual(len(grid), 5)

    def test_pure_fallback_has_no_grid(self):
        broadphase.Grid = None
        sc = make_scene()
        self.assertIsNone(sc._broad.grid)


def build_world(seed, count, shapes, native, flat, mutate_plan=None, shift=0):
    saved = phys_mod._nat_mod
    if not native:
        phys_mod._nat_mod = None
    try:
        sc = make_scene()
        sc.termx, sc.termy, sc.dimx, sc.dimy = 120, 40, 120, 40
        sc.camx, sc.camy = -60, 20
        sc.gravity = (0, -1)
        rng = random.Random(seed)
        sc.obj().create("#" * 118, -59 + shift, -18 + shift, dynamic=False, solid=True)
        sc.obj().create("#\n" * 30, -60 + shift, -18 + shift, dynamic=False, solid=True)
        sc.obj().create("#\n" * 30, 59 + shift, -18 + shift, dynamic=False, solid=True)
        extra = {"slope": False} if flat else {}
        for _ in range(count):
            o = sc.obj().create(rng.choice(shapes), rng.randint(-55, 55) + shift, rng.randint(-10, 18) + shift, dynamic=True, solid=True, **extra)
            if rng.random() < 0.3:
                o.physics.xvel = rng.randint(-3, 3)
        return sc
    finally:
        phys_mod._nat_mod = saved


def snapshot(sc):
    out = []
    for o in sc.objs:
        p = getattr(o, "physics", None)
        if p is None:
            continue
        t = o.transform
        out.append((t.x, t.y, t.rotation, p._xvel, p._yvel, p._avel, p.touch, p.sides, p._depenskip, p._good))
    return out


def mutate(sc, rng_seed, frame):
    rng = random.Random(rng_seed * 1000 + frame)
    movers = [o for o in sc.objs if getattr(o, "physics", None) is not None and o.physics.dynamic]
    if not movers:
        return
    target = rng.choice(movers)
    action = rng.randint(0, 3)
    if action == 0:
        target.physics.xvel = rng.randint(-4, 4)
    elif action == 1:
        target.transform.x = rng.randint(-50, 50)
        target.transform.y = rng.randint(-5, 15)
    elif action == 2:
        target.transform.text = rng.choice(["#", "##", "O", "##\n##"])
    else:
        target.physics.bounciness = rng.choice([0, 0.5])


@unittest.skipIf(_native is None or phys_mod._nat_mod is None, "native physics core disabled or not built")
class WorldParityTests(unittest.TestCase):
    shapes = ["O", "#", "##", "##\n##"]

    def compare(self, seed, count, frames, flat, mutate_every=0, shift=0):
        a = build_world(seed, count, self.shapes, True, flat, shift=shift)
        b = build_world(seed, count, self.shapes, False, flat, shift=shift)
        self.assertIn("_nat_world", a.__dict__)
        self.assertNotIn("_nat_world", b.__dict__)
        for frame in range(frames):
            if mutate_every and frame % mutate_every == 0:
                mutate(a, seed, frame)
                mutate(b, seed, frame)
            a.tick(True)
            b.tick(True)
            self.assertEqual(snapshot(a), snapshot(b), "diverged at frame %d" % frame)

    def test_flat_bodies_match_pure_python(self):
        self.compare(1, 40, 100, True)

    def test_sloped_bodies_match_pure_python(self):
        self.compare(2, 30, 80, False)

    def test_user_mutation_mid_run_matches(self):
        self.compare(3, 30, 120, True, mutate_every=5)
        self.compare(4, 25, 100, False, mutate_every=4)

    def test_large_coordinates_match(self):
        self.compare(8, 25, 60, False, shift=10 ** 9)
        self.compare(9, 25, 60, True, shift=-(10 ** 10))
        self.compare(10, 20, 40, False, shift=10 ** 12)

    def test_kernels_match_at_large_offsets(self):
        from ttyengine.components import shared

        def raw(shape):
            return shape[0], [(y, m.to_bytes((m.bit_length() + 7) // 8 or 1, "little")) for y, m in shape[1].items()]

        rng = random.Random(11)
        for big in (10 ** 6, 10 ** 9, 10 ** 12):
            for _ in range(300):
                aspect = rng.choice([0.5, 1.0, 0.45])
                ox, oy = rng.randint(-40, 40) + big, rng.randint(-40, 40) - big
                cells = {(ox + x, oy + y) for x in range(rng.randint(1, 20)) for y in range(rng.randint(1, 10)) if rng.random() < 0.8}
                other = {(x + rng.randint(-5, 5), y + rng.randint(-5, 5)) for x, y in cells}
                if not cells or not other:
                    continue
                a, b = shared._rows_of(cells), shared._rows_of(other)
                point = (ox + rng.randint(0, 20) + 0.5, oy + rng.randint(0, 8) + 0.5)
                nx, ny = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
                expected = shared._contact_normal_cells(a, b, point, nx, ny, True, True, aspect)
                self.assertEqual(_native.contact_normal(raw(a), raw(b), point, nx, ny, True, True, aspect), expected)
                self.assertEqual(_native.mtv(list(cells), list(other), aspect), shared._mtv_cells(cells, other, aspect))

    def test_touch_callbacks_fall_back_and_match(self):
        def make(o, kind, hits):
            def callback(other, cells):
                hits[0] += 1
                pp = getattr(other, "physics", None)
                if kind == 0 and pp is not None:
                    pp.yvel = pp.yvel + 2
                elif kind == 1:
                    o.transform.x = o.transform.x + 1
                elif kind == 2 and other.transform.text != "O":
                    other.transform.text = "O"

            return callback

        counts = []
        worlds = []
        for native in (True, False):
            sc = build_world(5, 25, self.shapes, native, False)
            hits = [0]
            for k, o in enumerate(sc.objs[3:9]):
                o.physics._touch_callbacks.append(make(o, k % 4, hits))
            worlds.append(sc)
            counts.append(hits)
        for frame in range(100):
            worlds[0].tick(True)
            worlds[1].tick(True)
            self.assertEqual(snapshot(worlds[0]), snapshot(worlds[1]), "diverged at frame %d" % frame)
        self.assertEqual(counts[0], counts[1])
        self.assertGreater(counts[0][0], 0)

    def test_ghosts_match(self):
        calls = []
        worlds = []
        for native in (True, False):
            sc = build_world(12, 30, self.shapes, native, False)
            bodies = [o for o in sc.objs if getattr(o, "physics", None) is not None and o.physics.dynamic]
            counter = [0]

            def make(owner, counter=counter):
                def callback(partner):
                    counter[0] += 1
                    return counter[0] % 5 == 0

                return callback

            for k in range(0, 12, 2):
                bodies[k].physics.ghost(bodies[k + 1])
            bodies[13].physics.ghost(bodies[14])
            bodies[14].physics.ghost(bodies[13])
            bodies[15].physics.ghost(make(bodies[15]))
            bodies[16].physics.ghost(make(bodies[16]))
            worlds.append(sc)
            calls.append(counter)
        for frame in range(100):
            worlds[0].tick(True)
            worlds[1].tick(True)
            self.assertEqual(snapshot(worlds[0]), snapshot(worlds[1]), "diverged at frame %d" % frame)
        self.assertEqual(calls[0], calls[1])

    def test_sprite_bodies_match(self):
        from ttyengine.ascii_styler import Styler

        worlds = []
        for native in (True, False):
            saved = phys_mod._nat_mod
            if not native:
                phys_mod._nat_mod = None
            try:
                sc = make_scene()
                sc.termx, sc.termy, sc.dimx, sc.dimy = 120, 40, 120, 40
                sc.camx, sc.camy = -60, 20
                sc.gravity = (0, -1)
                rng = random.Random(4)
                sc.obj().create("#" * 118, -59, -18, dynamic=False, solid=True)
                for _ in range(12):
                    sp = Styler.sprite([rng.choice(["##\n##", "#", "###\n# #"]), rng.choice(["@@", "O"])])
                    sc.obj().create(None, rng.randint(-40, 40), rng.randint(-8, 15), sprite=sp, dynamic=True, solid=True)
                for _ in range(8):
                    sc.obj().create(rng.choice(self.shapes), rng.randint(-40, 40), rng.randint(-8, 15), dynamic=True, solid=True)
                worlds.append(sc)
            finally:
                phys_mod._nat_mod = saved
        for frame in range(80):
            worlds[0].tick(True)
            worlds[1].tick(True)
            self.assertEqual(snapshot(worlds[0]), snapshot(worlds[1]), "diverged at frame %d" % frame)

    def test_discarded_bodies_are_released(self):
        a = build_world(6, 20, self.shapes, True, True)
        b = build_world(6, 20, self.shapes, False, True)
        for frame in range(60):
            if frame == 20:
                for sc in (a, b):
                    movers = [o for o in sc.objs if getattr(o, "physics", None) is not None and o.physics.dynamic]
                    for o in movers[:5]:
                        o.discard()
            a.tick(True)
            b.tick(True)
            self.assertEqual(snapshot(a), snapshot(b), "diverged at frame %d" % frame)


if __name__ == "__main__":
    unittest.main()
