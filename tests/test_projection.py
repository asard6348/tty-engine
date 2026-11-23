import os
import re
import unittest

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

from ttyengine import scene as scene_mod
from ttyengine import sprite as sprite_mod
from ttyengine.ascii_styler import Styler


def make_scene():
    sc = scene_mod.Scene()
    sc.termx, sc.termy, sc.dimx, sc.dimy = 60, 20, 60, 20
    sc.camx, sc.camy = -30, 10
    return sc


def shown(sc):
    sc.tick(True)
    found = {}
    for m in re.finditer(r'\x1b\[(\d+);(\d+)H((?:[^\x1b]|\x1b\[[0-9;]*m)*)', sc.render(full=True)):
        row, col = int(m.group(1)), int(m.group(2))
        for i, ch in enumerate(re.sub(r'\x1b\[[0-9;]*m', '', m.group(3))):
            if ch != ' ':
                found[(row, col + i)] = ch
    return found


def column(found, char):
    return sorted(k for k, v in found.items() if v == char)


class ScaleTests(unittest.TestCase):
    def test_enlarge_repeats_cells(self):
        self.assertEqual(Styler.scale('ab\ncd', 2), 'aabb\naabb\nccdd\nccdd')

    def test_axes_scale_independently(self):
        self.assertEqual(Styler.scale('ab', 2, 3), 'aabb\naabb\naabb')

    def test_shrink_keeps_visible_cells(self):
        self.assertEqual(Styler.scale('aabb\naabb', 0.5), 'ab')

    def test_styles_survive(self):
        text = '\x1b[31mab\x1b[0m'
        self.assertEqual(Styler.scale(Styler.scale(text, 2), 0.5), text)

    def test_rejects_bad_factors(self):
        for bad in (0, -1, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                Styler.scale('a', bad)


class SpriteTests(unittest.TestCase):
    def test_rank_follows_nesting(self):
        self.assertEqual(Styler.sprite(['a', 'b']).rank, 3)
        self.assertEqual(Styler.sprite([['a', 'b'], ['c', 'd']]).rank, 4)

    def test_default_axes_and_footprint(self):
        sp = Styler.sprite(['ab\ncd', 'ef\ngh', 'ij'])
        self.assertEqual(sp.axes, (2,))
        self.assertEqual(sp.footprint(), 'ij\ngh')

    def test_custom_axes_and_steps(self):
        sp = Styler.sprite(['a', 'b'], axes='w', step=3)
        offsets = sorted(o for o, _, _ in sp.points)
        self.assertEqual(offsets, [(0, 0, 0, 0), (0, 0, 0, 3)])

    def test_uneven_nesting_is_refused(self):
        with self.assertRaises(ValueError):
            Styler.sprite(['a', ['b']])
        with self.assertRaises(ValueError):
            Styler.sprite(['a'], axes=('z', 'w'))
        with self.assertRaises(ValueError):
            Styler.sprite(['a'], axes='x')

    def test_object_carries_sprite_and_clones_it(self):
        sc = make_scene()
        sp = Styler.sprite(['a', 'b'])
        o = sc.obj().create(None, 1, 2, sprite=sp)
        self.assertIs(o.transform.sprite, sp)
        self.assertIsInstance(sp, sprite_mod.sprite)
        self.assertIs(o.clone().transform.sprite, sp)

    def test_foreign_sprite_attribute_is_untouched(self):
        sc = make_scene()
        o = sc.obj().create('a', 0, 0, sprite='mine')
        self.assertEqual(o.sprite, 'mine')
        self.assertIsNone(o.transform.sprite)


class CameraTests(unittest.TestCase):
    def build(self, **cam):
        sc = make_scene()
        for key, value in cam.items():
            setattr(sc, key, value)
        sc.obj().create('A', 0, 0)
        sc.obj().create('B', 5, 0, z=3)
        return sc

    def test_neutral_camera_is_not_projected(self):
        sc = self.build()
        self.assertFalse(sc.projected())
        self.assertEqual(column(shown(sc), 'B'), [(11, 36)])

    def test_zrotation_is_the_legacy_roll(self):
        a = self.build(camzrotation=90)
        b = self.build(camrotation=90)
        self.assertEqual(a.camzrotation, 90)
        self.assertEqual(shown(a), shown(b))
        self.assertFalse(a.projected())

    def test_projected_roll_matches_legacy_roll(self):
        legacy = self.build(camzrotation=90)
        proj = self.build(camzrotation=90, camxrotation=1e-9)
        self.assertTrue(proj.projected())
        self.assertEqual(column(shown(legacy), 'B'), column(shown(proj), 'B'))

    def test_perspective_alone_keeps_the_focal_plane(self):
        sc = self.build(perspective=50)
        self.assertEqual(column(shown(sc), 'A'), [(11, 31)])

    def test_yrotation_swings_depth_into_width(self):
        sc = make_scene()
        sc.obj().create(None, 0, 0, sprite=Styler.sprite(['a', 'b', 'c'], step=2))
        self.assertEqual(shown(sc), {(11, 31): 'c'})
        sc.camyrotation = 90
        self.assertEqual(shown(sc), {(11, 31): 'a', (11, 35): 'b', (11, 39): 'c'})

    def test_xrotation_swings_depth_into_height(self):
        sc = make_scene()
        sc.obj().create(None, 0, 0, sprite=Styler.sprite(['a', 'b', 'c'], step=2))
        sc.camxrotation = 90
        self.assertEqual(shown(sc), {(11, 31): 'a', (13, 31): 'b', (15, 31): 'c'})

    def test_near_layers_hide_far_ones_and_grow_with_perspective(self):
        sc = make_scene()
        sc.obj().create(None, 0, 0, sprite=Styler.sprite(['a', 'b', 'c'], step=2))
        sc.perspective = 10
        self.assertEqual(set(shown(sc).values()), {'c'})
        self.assertGreater(len(shown(sc)), 1)

    def test_objects_behind_the_eye_are_culled(self):
        sc = make_scene()
        sc.obj().create('A', 0, 0, z=20)
        sc.perspective = 10
        self.assertEqual(shown(sc), {})

    def test_custom_planes(self):
        sc = make_scene()
        sc.axes = 4
        sc.obj().create(None, 0, 0, sprite=Styler.sprite(['a', 'b'], axes='w', step=2))
        self.assertEqual(shown(sc), {(11, 31): 'b'})
        sc.camturn('x', 'w', 90)
        self.assertEqual(len(shown(sc)), 2)
        self.assertEqual(sc.camturn('x', 'w'), 90)

    def test_bad_planes_and_perspective(self):
        sc = make_scene()
        with self.assertRaises(ValueError):
            sc.camturn('x', 'x', 10)
        with self.assertRaises(ValueError):
            sc.camturn('x', 'w', 10)
        with self.assertRaises(ValueError):
            sc.perspective = -1

    def test_callbacks_fire(self):
        sc = make_scene()
        seen = []
        sc.oncam(lambda *a: seen.append(a))
        sc.camxrotation = 10
        sc.camyrotation = 20
        sc.perspective = 5
        self.assertEqual(len(seen), 3)

    def test_leaving_projection_restores_the_flat_view(self):
        sc = self.build()
        before = shown(sc)
        sc.camxrotation = 40
        shown(sc)
        sc.camxrotation = 0
        self.assertEqual(shown(sc), before)

    def test_unprojected_objects_stay_flat(self):
        sc = make_scene()
        sc.obj().create('H', 0, 0, projected=False)
        sc.obj().create('P', 0, 3)
        sc.camyrotation = 90
        found = shown(sc)
        self.assertEqual(column(found, 'H'), [(11, 31)])
        self.assertEqual(column(found, 'P'), [(8, 31)])


if __name__ == '__main__':
    unittest.main()
