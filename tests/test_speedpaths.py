import importlib
import os
import random
import unittest

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

from ttyengine import scene as scene_mod

transform_mod = importlib.import_module("ttyengine.components.transform")

FIELDS = ("text", "vtext", "rtext", "vx", "vy", "rotation")
PRIVATE = ("_text", "_ptext", "_pvx", "_pvy", "_rotorigin", "_rotsize", "_rotangle", "_vrtext", "_rotmaps_ok")


def make_scene():
    sc = scene_mod.Scene()
    sc.termx, sc.termy, sc.dimx, sc.dimy = 100, 40, 100, 40
    return sc


def observe(t):
    seen = [getattr(t, name) for name in FIELDS]
    seen.extend(t.__dict__.get(name) for name in PRIVATE)
    return seen


class RotationMemoTests(unittest.TestCase):
    def test_memo_hit_matches_a_fresh_rotation(self):
        rng = random.Random(3)
        shapes = ["###\n# #\n###", "@@@@", "##\n##", "#", "o", "#####\n  #  \n  #  "]
        for shape in shapes:
            for angle in [rng.choice([3, 7, 11, 45, 90, 137, 200, 271, 333]) for _ in range(6)]:
                sc = make_scene()
                fresh = sc.obj().create(shape, 5, 5, dynamic=False, solid=False)
                fresh.transform.rotation = angle
                expected = observe(fresh.transform)
                before = len(transform_mod._ROTATIONS)
                again = sc.obj().create(shape, 5, 5, dynamic=False, solid=False)
                again.transform.rotation = angle
                self.assertGreaterEqual(len(transform_mod._ROTATIONS), before)
                self.assertEqual(observe(again.transform), expected)
                again.transform.rotation = 0
                again.transform.rotation = angle
                self.assertEqual(observe(again.transform), expected)

    def test_revision_advances_on_every_memo_hit(self):
        sc = make_scene()
        o = sc.obj().create("###\n# #\n###", 0, 0, dynamic=False, solid=False)
        t = o.transform
        for angle in (30, 60, 30, 60, 30):
            before = t._rev
            t.rotation = angle
            self.assertGreater(t._rev, before)


class AutoMassTests(unittest.TestCase):
    def test_automass_follows_text_changes(self):
        sc = make_scene()
        o = sc.obj().create("###", 0, 0, dynamic=False, solid=True)
        self.assertEqual(o.physics.mass, 3)
        o.transform.text = "## \n#"
        self.assertEqual(o.physics.mass, 3)
        o.transform.text = "#"
        self.assertEqual(o.physics.mass, 1)

    def test_explicit_mass_is_not_overwritten(self):
        sc = make_scene()
        o = sc.obj().create("###", 0, 0, dynamic=False, solid=True, mass=7)
        o.transform.text = "#"
        self.assertEqual(o.physics.mass, 7)

    def test_position_writes_still_invalidate_physics_caches(self):
        sc = make_scene()
        o = sc.obj().create("##", 0, 0, dynamic=False, solid=True)
        first = o.physics.bounds()
        o.transform.x = 10
        moved = o.physics.bounds()
        self.assertEqual(moved[0] - first[0], 10)


if __name__ == "__main__":
    unittest.main()
