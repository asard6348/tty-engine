import os
import unittest

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

from ttyengine import scene as scene_mod
from ttyengine.ascii_styler import Styler


def make_scene(axes=4, solid=('w',)):
    sc = scene_mod.Scene()
    sc.termx, sc.termy, sc.dimx, sc.dimy = 60, 20, 60, 20
    sc.camx, sc.camy = -30, 10
    sc.gravity = (0, 0)
    sc.axes = axes
    sc.solidaxes = solid
    return sc


def run(sc, ticks):
    for _ in range(ticks):
        sc.tick(True)


class SolidAxesTests(unittest.TestCase):
    def test_default_and_validation(self):
        sc = scene_mod.Scene()
        self.assertEqual(sc.solidaxes, ())
        sc.axes = 4
        sc.solidaxes = 'w'
        self.assertEqual(sc.solidaxes, ('w',))
        sc.solidaxes = ('z', 'w', 'w')
        self.assertEqual(sc.solidaxes, ('z', 'w'))
        for bad in ('x', 'y', 'a4', 7, True):
            with self.assertRaises(ValueError):
                sc.solidaxes = bad
        sc.axes = 3
        self.assertEqual(sc.solidaxes, ('z',))
        sc.solidaxes = None
        self.assertEqual(sc.solidaxes, ())

    def test_other_depth_passes_through(self):
        sc = make_scene()
        sc.obj().create('#\n#\n#', 5, 0, dynamic=False, solid=True, w=9)
        mover = sc.obj().create('o', 0, -1, xvel=1, solid=True, w=0)
        run(sc, 12)
        self.assertGreater(mover.transform.x, 6)

    def test_same_depth_blocks(self):
        sc = make_scene()
        sc.obj().create('#\n#\n#', 5, 0, dynamic=False, solid=True, w=0)
        mover = sc.obj().create('o', 0, -1, xvel=1, solid=True, w=0.5)
        run(sc, 12)
        self.assertLessEqual(mover.transform.x, 4)

    def test_depth_gap_of_one_is_clear(self):
        sc = make_scene()
        sc.obj().create('#\n#\n#', 5, 0, dynamic=False, solid=True, w=1)
        mover = sc.obj().create('o', 0, -1, xvel=1, solid=True, w=0)
        run(sc, 12)
        self.assertGreater(mover.transform.x, 6)

    def test_motion_along_a_solid_axis_stops_at_a_wall(self):
        sc = make_scene()
        sc.obj().create('#', 0, 0, dynamic=False, solid=True, w=5)
        mover = sc.obj().create('o', 0, 0, solid=True, w=0, wvel=1)
        run(sc, 30)
        self.assertLess(mover.transform['w'], 5)
        self.assertGreater(mover.transform['w'], 3)
        self.assertEqual(mover.physics.wvel, 0)

    def test_free_axis_still_drifts_through(self):
        sc = make_scene(4, ())
        sc.obj().create('#', 0, 0, dynamic=False, solid=True, w=5)
        mover = sc.obj().create('o', 0, 0, solid=True, w=0, wvel=1)
        run(sc, 30)
        self.assertGreater(mover.transform['w'], 6)

    def test_bounce_reverses_the_axis_velocity(self):
        sc = make_scene()
        sc.obj().create('#', 0, 0, dynamic=False, solid=True, w=5)
        mover = sc.obj().create('o', 0, 0, solid=True, w=0, wvel=1, bounciness=1)
        run(sc, 30)
        self.assertLess(mover.physics.wvel, 0)
        self.assertLess(mover.transform['w'], 5)

    def test_dynamic_bodies_exchange_axis_momentum(self):
        sc = make_scene()
        a = sc.obj().create('o', 0, 0, solid=True, w=0, wvel=2)
        b = sc.obj().create('o', 0, 0, solid=True, w=4, bounciness=1)
        run(sc, 40)
        self.assertGreater(b.physics.wvel, 0)
        self.assertLess(a.physics.wvel, b.physics.wvel)
        self.assertLess(a.transform['w'], b.transform['w'])

    def test_touch_callbacks_fire_for_axis_contacts(self):
        sc = make_scene()
        seen = []
        sc.obj().create('#', 0, 0, dynamic=False, solid=True, w=3)
        mover = sc.obj().create('o', 0, 0, solid=True, w=0, wvel=1)
        mover.physics.ontouch(lambda other: seen.append(other))
        run(sc, 20)
        self.assertTrue(seen)

    def test_sprite_layers_collide_layer_by_layer(self):
        sc = make_scene()
        sp = Styler.sprite(['#', ' ', '#'], axes='w', step=2, spaces=True)
        body = sc.obj().create(None, 0, 0, sprite=sp, dynamic=False, solid=True)
        self.assertEqual(len(body.physics._slabs()), 2)
        probe = sc.obj().create('o', 0, 0, solid=True, w=2)
        self.assertEqual(len(probe.physics.overlaps()), 0)
        probe.transform['w'] = 4
        self.assertEqual(len(probe.physics.overlaps()), 1)
        probe.transform['w'] = 0
        self.assertEqual(len(probe.physics.overlaps()), 1)

    def test_sprite_layers_differ_in_shape(self):
        sc = make_scene()
        sp = Styler.sprite(['#  ', '  #'], axes='w', step=2)
        sc.obj().create(None, 0, 0, sprite=sp, dynamic=False, solid=True)
        left = sc.obj().create('o', 0, 0, solid=True, w=0)
        right = sc.obj().create('o', 2, 0, solid=True, w=0)
        self.assertEqual(len(left.physics.overlaps()), 1)
        self.assertEqual(len(right.physics.overlaps()), 0)
        right.transform['w'] = 2
        self.assertEqual(len(right.physics.overlaps()), 1)
        left.transform['w'] = 2
        self.assertEqual(len(left.physics.overlaps()), 0)

    def test_two_solid_axes(self):
        sc = make_scene(5, ('z', 'w'))
        sc.obj().create('#', 0, 0, dynamic=False, solid=True, z=0, w=0)
        probe = sc.obj().create('o', 0, 0, solid=True, z=0, w=3)
        self.assertEqual(len(probe.physics.overlaps()), 0)
        probe.transform['w'] = 0
        self.assertEqual(len(probe.physics.overlaps()), 1)
        probe.transform['z'] = 2
        self.assertEqual(len(probe.physics.overlaps()), 0)

    def test_plane_motion_is_gated_by_the_solid_axis(self):
        sc = make_scene()
        sc.obj().create('#\n#\n#', 5, 0, dynamic=False, solid=True, w=0)
        mover = sc.obj().create('o', 0, -1, xvel=1, solid=True, w=0)
        run(sc, 12)
        blocked = mover.transform.x
        mover.transform.x = 0
        mover.physics.xvel = 1
        mover.transform['w'] = 3
        run(sc, 12)
        self.assertLessEqual(blocked, 4)
        self.assertGreater(mover.transform.x, 6)


    def test_overlap_resolves_along_the_shallow_axis(self):
        sc = make_scene()
        a = sc.obj().create('o', 0, 0, dynamic=False, solid=True, w=0)
        b = sc.obj().create('o', 0, 0, solid=True, w=0.8)
        run(sc, 6)
        self.assertEqual((b.transform.x, b.transform.y), (0, 0))
        self.assertGreaterEqual(b.transform['w'] - a.transform['w'], 1 - 1e-9)

    def test_even_overlap_still_resolves_in_the_plane(self):
        sc = make_scene()
        sc.obj().create('oo', 0, 0, dynamic=False, solid=True, w=0)
        b = sc.obj().create('oo', 1, 0, solid=True, w=0)
        run(sc, 6)
        self.assertEqual(b.transform['w'], 0)
        self.assertGreaterEqual(b.transform.x, 2)

    def test_rotated_layer_matches_the_plain_body(self):
        sc = make_scene()
        for angle in (0, 33, 90, 200):
            plain = sc.obj().create('AB\nCD\nEF', 3, 2, rotation=angle, solid=True)
            layered = sc.obj().create(None, 3, 2, sprite=Styler.sprite(['AB\nCD\nEF'], axes='w'), rotation=angle, solid=True)
            self.assertEqual(layered.physics._slabs()[0][1], plain.physics.getpixels(), angle)
            plain.discard()
            layered.discard()

    def test_hitbox_layers_use_their_own_rectangles(self):
        sc = make_scene()
        sp = Styler.sprite(['#\n#', '###'], axes='w', step=2)
        body = sc.obj().create(None, 0, 0, sprite=sp, dynamic=False, solid=True, hitbox=True)
        slabs = dict(body.physics._slabs())
        self.assertEqual(len(slabs[(0,)]), 2)
        self.assertEqual(len(slabs[(2,)]), 3)
        far = sc.obj().create('o', 2, 0, solid=True, w=0)
        near = sc.obj().create('o', 2, 0, solid=True, w=2)
        self.assertEqual(len(far.physics.overlaps()), 0)
        self.assertEqual(len(near.physics.overlaps()), 1)

    def test_custom_hitbox_applies_to_every_layer(self):
        sc = make_scene()
        sp = Styler.sprite(['#', '#'], axes='w', step=3)
        body = sc.obj().create(None, 0, 0, sprite=sp, dynamic=False, solid=True, hitbox=True)
        body.transform.htext = '###\n###'
        body.transform.rtext = '#'
        slabs = dict(body.physics._slabs())
        self.assertEqual(sorted(slabs), [(0,), (3,)])
        self.assertEqual(len(slabs[(3,)]), 6)
        near = sc.obj().create('o', 2, -1, solid=True, w=3)
        gap = sc.obj().create('o', 2, -1, solid=True, w=1.5)
        self.assertEqual(len(near.physics.overlaps()), 1)
        self.assertEqual(len(gap.physics.overlaps()), 0)

if __name__ == '__main__':
    unittest.main()
