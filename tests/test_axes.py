import os
import unittest

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

from ttyengine import axes as axes_mod
from ttyengine import scene as scene_mod


def make_scene(axes=3, gravity=(0, 0)):
    sc = scene_mod.Scene()
    sc.termx, sc.termy, sc.dimx, sc.dimy = 60, 20, 60, 20
    sc.camx, sc.camy = -30, 10
    sc.gravity = gravity
    sc.axes = axes
    return sc


class AxesTests(unittest.TestCase):
    def test_default_is_x_y_z(self):
        sc = scene_mod.Scene()
        self.assertEqual(sc.axes, ('x', 'y', 'z'))
        self.assertEqual(len(sc.axes), 3)
        self.assertIs(sc.axes, axes_mod.DEFAULT)

    def test_count_and_names_agree_and_are_interned(self):
        sc = scene_mod.Scene()
        sc.axes = 5
        self.assertEqual(sc.axes, ('x', 'y', 'z', 'w', 'a4'))
        self.assertIs(sc.axes, axes_mod.get(('x', 'y', 'z', 'w', 'a4')))
        self.assertIs(sc.axes, axes_mod.get(5))

    def test_invalid_axes_are_rejected(self):
        sc = scene_mod.Scene()
        for bad in (2, 0, axes_mod.LIMIT + 1, ('x', 'y'), ('x', 'z', 'y'), ('x', 'y', 'z', 'q')):
            with self.assertRaises(ValueError):
                sc.axes = bad
        for bad in (True, 3.0, 'xyz', None):
            with self.assertRaises(TypeError):
                sc.axes = bad
        self.assertEqual(sc.axes, ('x', 'y', 'z'))

    def test_three_axis_scene_has_no_extra_attributes(self):
        t = make_scene().obj().create('a', 1, 2).transform
        self.assertFalse(hasattr(t, 'w'))
        self.assertNotIn('w', t)
        with self.assertRaises(AttributeError):
            t.w = 1
        with self.assertRaises(KeyError):
            t['w']

    def test_unused_axis_names_stay_plain_object_attributes(self):
        o = make_scene().obj().create('a', 1, 2, w=5, pos='home')
        self.assertEqual((o.w, o.pos), (5, 'home'))
        self.assertEqual(o.transform.pos, (1, 2, 0))
        self.assertFalse(hasattr(o, 'physics'))


class TransformAxesTests(unittest.TestCase):
    def setUp(self):
        self.sc = make_scene(5)
        self.o = self.sc.obj().create('ab', 1, 2, z=3, w=4, a4=5)
        self.t = self.o.transform

    def test_every_access_path_agrees(self):
        t = self.t
        self.assertEqual(t.pos, (1, 2, 3, 4, 5))
        self.assertEqual((t.x, t.y, t.z, t.w, t['a4']), (1, 2, 3, 4, 5))
        self.assertEqual((self.o['w'], self.o['a4']), (4, 5))
        t.w = 40
        t['a4'] = 50
        self.assertEqual(t.pos, (1, 2, 3, 40, 50))

    def test_pos_assigns_leading_axes_only(self):
        t = self.t
        t.pos = (9, 8)
        self.assertEqual(t.pos, (9, 8, 3, 4, 5))
        t.pos = (1, 2, 3, 4, 5)
        t.pos = [7, 7, 7, 7, 7]
        self.assertEqual(t.pos, (7, 7, 7, 7, 7))

    def test_pos_rejects_wrong_lengths(self):
        for bad in ((1,), (), (1, 2, 3, 4, 5, 6)):
            with self.assertRaises(ValueError):
                self.t.pos = bad
        self.assertEqual(self.t.pos, (1, 2, 3, 4, 5))

    def test_callbacks_fire_once_per_axis_with_the_old_value(self):
        seen = []
        self.t.onchange(lambda attr, old: seen.append((attr, old)))
        self.t.x = 10
        self.t.z = 30
        self.t.w = 40
        self.t['a4'] = 50
        self.assertEqual(seen, [('x', 1), ('z', 3), ('w', 4), ('a4', 5)])
        del seen[:]
        self.t.pos = (0, 0, 0)
        self.assertEqual(seen, [('x', 10), ('y', 2), ('z', 30)])

    def test_every_position_write_bumps_the_revision(self):
        t = self.t
        writes = [
            lambda: setattr(t, 'x', 11), lambda: setattr(t, 'y', 12), lambda: setattr(t, 'z', 13),
            lambda: setattr(t, 'w', 14), lambda: setattr(t, 'a4', 15),
            lambda: setattr(t, 'pos', (1, 2, 3)), lambda: t.__setitem__('w', 99),
            lambda: t.lerp(0.5, x=100),
        ]
        for write in writes:
            before = t._rev
            write()
            self.assertGreater(t._rev, before)

    def test_lerp_blends_pos_and_axes(self):
        self.t.lerp(0.5, pos=(11, 12, 13, 14, 15))
        self.assertEqual(self.t.pos, (6, 7, 8, 9, 10))
        self.t.lerp(1, w=0)
        self.assertEqual(self.t.w, 0)

    def test_depth_tracks_front_and_back_through_every_path(self):
        sc = self.sc
        self.t.z = 10
        other = sc.obj().create('c', 0, 0)
        other.transform.front()
        self.assertEqual(other.transform.z, 11)
        self.t.pos = (0, 0, 50)
        other.transform.front()
        self.assertEqual(other.transform.z, 51)
        other.transform.back()
        self.assertEqual(other.transform.z, -1)

    def test_changing_axes_resizes_existing_objects(self):
        self.sc.axes = 4
        self.assertEqual(self.t.pos, (1, 2, 3, 4))
        self.sc.axes = 7
        self.assertEqual(self.t.pos, (1, 2, 3, 4, 0, 0, 0))
        self.sc.axes = 3
        self.assertEqual(self.t.pos, (1, 2, 3))
        self.assertFalse(hasattr(self.t, 'w'))

    def test_clone_and_kwargs_carry_extra_axes(self):
        twin = self.o.clone()
        self.assertEqual(twin.transform.pos, (1, 2, 3, 4, 5))
        late = self.sc.obj().create('d', 0, 0)
        late.set('transform', w=9)
        self.assertEqual(late.kwargs()['w'], 9)

    def test_split_fragments_inherit_extra_axes(self):
        o = self.sc.obj().create('a a', 0, 0, w=6, dynamic=False)
        parts = []
        o.transform.split(lambda made: parts.extend(made))
        self.assertEqual(len(parts), 2)
        self.assertEqual([p.transform.w for p in parts], [6, 6])


class PhysicsAxesTests(unittest.TestCase):
    def test_free_axes_drift_without_colliding(self):
        sc = make_scene(5)
        a = sc.obj().create('o', 0, 0, zvel=2, wvel=-1)
        b = sc.obj().create('#', 9, 9, dynamic=False)
        sc.tick(True)
        self.assertEqual(a.transform.pos, (0, 0, 2, -1, 0))
        sc.tick(True)
        self.assertEqual(a.transform.pos, (0, 0, 4, -2, 0))
        self.assertEqual(a.physics.vel, (0, 0, 2, -1, 0))
        self.assertEqual(b.transform.pos, (9, 9, 0, 0, 0))

    def test_gravity_and_drag_apply_to_free_axes(self):
        sc = make_scene(4)
        sc.gravity = (0, 0, -1, 0.5)
        o = sc.obj().create('o', 0, 0, xvel=0)
        sc.tick(True)
        sc.tick(True)
        self.assertEqual(o.transform.pos, (0, 0, -3, 1.5))
        sc.drag = 0.5
        o.physics.vel = (0, 0, 0, 0)
        o.physics.gravity = (0, 0)
        o.physics.zvel = 8
        sc.tick(True)
        self.assertEqual(o.physics.zvel, 4)

    def test_default_scene_never_touches_z(self):
        sc = make_scene()
        o = sc.obj().create('o', 3, 3, xvel=1, yvel=1, z=7)
        for _ in range(5):
            sc.tick(True)
        self.assertEqual(o.transform.z, 7)
        self.assertEqual(o.physics.vel, (o.physics.xvel, o.physics.yvel, 0))

    def test_extra_axes_never_block_movement(self):
        sc = make_scene(4)
        wall = sc.obj().create('#\n#\n#', 5, 0, dynamic=False, solid=True, z=9, w=9)
        mover = sc.obj().create('o', 0, -1, xvel=1, solid=True)
        for _ in range(8):
            sc.tick(True)
        self.assertLessEqual(mover.transform.x, 4)
        self.assertEqual(wall.transform.pos[:2], (5, 0))

    def test_gravity_length_is_checked_against_the_axes(self):
        sc = make_scene(4)
        o = sc.obj().create('o', 0, 0, xvel=0)
        for ok in ((0, 1), (0, 1, 2), (0, 1, 2, 3)):
            o.physics.gravity = ok
            self.assertEqual(o.physics.gravity, ok)
        for bad in ((1,), (), (1, 2, 3, 4, 5)):
            with self.assertRaises(ValueError):
                o.physics.gravity = bad
        with self.assertRaises(ValueError):
            sc.obj().create('o', 0, 0, gravity=(1,))

    def test_vel_accessors(self):
        sc = make_scene(4)
        o = sc.obj().create('o', 0, 0, xvel=1)
        ph = o.physics
        ph.vel = (3, 4, 5, 6)
        self.assertEqual((ph.xvel, ph.yvel, ph.zvel, ph.wvel), (3, 4, 5, 6))
        self.assertEqual(ph['wvel'], 6)
        with self.assertRaises(ValueError):
            ph.vel = (1,)
        with self.assertRaises(ValueError):
            ph.vel = (1, 2, 3, 4, 5)
        sc.axes = 3
        self.assertEqual(ph.vel, (3, 4, 5))
        self.assertFalse(hasattr(ph, 'wvel'))

    def test_velocity_callbacks_fire_by_axis_name(self):
        sc = make_scene(4)
        ph = sc.obj().create('o', 0, 0, xvel=1).physics
        seen = []
        ph.onchange(lambda attr, old: seen.append((attr, old)))
        ph.zvel = 2
        ph.wvel = 3
        ph.vel = (1, 0, 2, 9)
        self.assertEqual(seen, [('zvel', 0), ('wvel', 0), ('xvel', 1), ('yvel', 0), ('zvel', 2), ('wvel', 3)])

    def test_depth_changes_leave_physics_caches_alone(self):
        sc = make_scene(4)
        o = sc.obj().create('o', 0, 0, xvel=0)
        sc.tick(True)
        sc._broad.stale.clear()
        o.transform.z = 4
        o.transform.w = 4
        self.assertNotIn(o, sc._broad.stale)
        o.transform.x = 4
        self.assertIn(o, sc._broad.stale)


class CameraAxesTests(unittest.TestCase):
    def test_cam_is_a_vector_over_camx_camy(self):
        sc = make_scene(4)
        sc.cam = (5, 6, 7, 8)
        self.assertEqual(sc.cam, (5, 6, 7, 8))
        self.assertEqual((sc.camx, sc.camy), (5, 6))
        sc.camx = 1
        sc.cam = (2, 3)
        self.assertEqual(sc.cam, (2, 3, 7, 8))
        with self.assertRaises(ValueError):
            sc.cam = (1,)
        with self.assertRaises(ValueError):
            sc.cam = (1, 2, 3, 4, 5)

    def test_cam_callbacks_report_axis_names(self):
        sc = make_scene(4)
        seen = []
        sc._oncamcb[lambda attr, old: seen.append((attr, old))] = 2
        sc.cam = (0, 0, 1, 2)
        self.assertEqual(seen, [('x', -30), ('y', 10), ('z', 0), ('w', 0)])

    def test_axes_resize_the_camera(self):
        sc = make_scene(5)
        sc.cam = (1, 2, 3, 4, 5)
        sc.axes = 4
        self.assertEqual(sc.cam, (1, 2, 3, 4))
        sc.axes = 3
        sc.axes = 5
        self.assertEqual(sc.cam, (1, 2, 3, 0, 0))


class RenderAxesTests(unittest.TestCase):
    def build(self, axes, w=None):
        sc = make_scene(axes, gravity=(0, -1))
        sc.obj().create('#' * 50, -25, -8, dynamic=False, solid=True)
        for i in range(6):
            kw = {} if w is None else {'w': w + i}
            sc.obj().create('ab\ncd', i * 7 - 18, 4, xvel=0.5, bounciness=0.6, solid=True, z=i % 3, **kw)
        return sc

    def frames(self, sc, n=25):
        out = []
        for _ in range(n):
            sc.tick(True)
            out.append(sc.render())
        return out

    def test_extra_axes_do_not_change_the_picture(self):
        plain = self.frames(self.build(3))
        for axes in (4, 7):
            self.assertEqual(self.frames(self.build(axes, w=5)), plain)

    def test_depth_still_orders_drawing(self):
        def shot(*items):
            sc = make_scene(4)
            for char, z, w in items:
                sc.obj().create(char, 0, 0, dynamic=False, z=z, w=w)
            sc.tick(True)
            return sc.render(full=True), sc
        both, sc = shot(('L', 1, 9), ('H', 2, 0))
        self.assertEqual(both, shot(('H', 2, 0))[0])
        self.assertNotEqual(both, shot(('L', 1, 9))[0])
        sc.objs[1].transform.z = 0
        sc.tick(True)
        self.assertEqual(sc.render(full=True), shot(('L', 1, 9))[0])


if __name__ == "__main__":
    unittest.main()
