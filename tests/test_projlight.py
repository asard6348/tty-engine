import os
import re
import unittest

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

from ttyengine import scene as scene_mod
from ttyengine.ascii_styler import Styler


def make_scene(**cam):
    sc = scene_mod.Scene()
    sc.termx, sc.termy, sc.dimx, sc.dimy = 60, 20, 60, 20
    sc.camx, sc.camy = -30, 10
    sc.gravity = (0, 0)
    sc.ambient = 0.2
    for key, value in cam.items():
        setattr(sc, key, value)
    return sc


def paint(sc):
    sc.tick(True)
    return sc.render(full=True)


def level(out, char):
    m = re.search(r'\x1b\[38;2;(\d+);(\d+);(\d+)m(?:\x1b\[[0-9;]*m)*' + re.escape(char), out)
    return int(m.group(1)) if m else None


class ProjectedLightTests(unittest.TestCase):
    def build(self, lightz, thingz=0, **cam):
        sc = make_scene(**cam)
        sc.obj().create('o', 0, 0, z=lightz, light=dict(radius=12, shadows=False))
        sc.obj().create('X', 2, 0, z=thingz)
        return sc

    def test_depth_dims_the_light(self):
        near = level(paint(self.build(0, camxrotation=1e-9)), 'X')
        far = level(paint(self.build(8, camxrotation=1e-9)), 'X')
        self.assertIsNotNone(near)
        self.assertGreater(near, far or 0)

    def test_flat_scenes_ignore_depth(self):
        a = paint(self.build(0))
        b = paint(self.build(8))
        self.assertEqual(level(a, 'X'), level(b, 'X'))

    def test_sprite_layers_light_by_depth(self):
        def front(lightz):
            sc = make_scene(camxrotation=1e-9)
            sc.obj().create('o', 0, 0, z=lightz, light=dict(radius=12, shadows=False))
            sc.obj().create(None, 2, 0, z=0, sprite=Styler.sprite(['A', 'B'], step=6))
            return level(paint(sc), 'B') or 0
        self.assertGreater(front(6), front(0))

    def test_halo_follows_the_projected_centre(self):
        sc = make_scene(camyrotation=90)
        l = sc.obj().create('o', 0, 0, z=4, light=dict(radius=5, glow=True, shadows=False))
        sc.tick(True)
        rows = l.light.halo(__import__('ttyengine.projection', fromlist=['x']).camera(sc, (0, 0, 60, 20)), (0, 0, 60, 20))[1]
        cols = [x + i for _, x, a in rows for i in range(len(a))]
        self.assertTrue(cols)
        self.assertGreater((min(cols) + max(cols)) / 2, 33)

    def test_perspective_scales_the_halo(self):
        from ttyengine import projection
        def width(z):
            sc = make_scene(perspective=10)
            l = sc.obj().create('o', 0, 0, z=z, light=dict(radius=2, glow=True, shadows=False))
            sc.tick(True)
            rows = l.light.halo(projection.camera(sc, (0, 0, 60, 20)), (0, 0, 60, 20))[1]
            return len(rows)
        self.assertGreater(width(5), width(0))

    def test_light_behind_the_eye_has_no_halo(self):
        from ttyengine import projection
        sc = make_scene(perspective=10)
        l = sc.obj().create('o', 0, 0, z=12, light=dict(radius=5, glow=True))
        sc.tick(True)
        self.assertEqual(l.light.halo(projection.camera(sc, (0, 0, 60, 20)), (0, 0, 60, 20)), (None, []))

    def test_renders_with_glowing_lights(self):
        sc = make_scene(camyrotation=30, perspective=20)
        sc.obj().create('o', 0, 0, z=3, light=dict(radius=6, glow=True))
        sc.obj().create('X', 3, 0)
        self.assertTrue(paint(sc))
        sc.camyrotation = 0
        sc.perspective = 0
        self.assertTrue(paint(sc))


class ProjectedShadowTests(unittest.TestCase):
    def lit(self, wallz, targetz=0, project=True):
        sc = make_scene()
        if project:
            sc.camxrotation = 1e-9
        sc.obj().create('o', 0, 0, z=0, light=dict(radius=20, shadows=True))
        sc.obj().create('#', 3, 0, z=wallz, dynamic=False, solid=True)
        sc.obj().create('X', 7, 0, z=targetz)
        return level(paint(sc), 'X') or 0

    def test_wall_in_the_beam_casts_a_shadow(self):
        self.assertLess(self.lit(0), self.lit(0, project=False) + 1)
        self.assertLess(self.lit(0), self.lit(6))

    def test_wall_at_another_depth_lets_the_light_through(self):
        self.assertEqual(self.lit(6), self.lit(40))

    def test_wall_between_light_and_target_in_depth_shadows(self):
        self.assertLess(self.lit(4, 8), self.lit(40, 8))

    def test_flat_scene_shadows_ignore_depth(self):
        self.assertEqual(self.lit(0, project=False), self.lit(6, project=False))

if __name__ == '__main__':
    unittest.main()
