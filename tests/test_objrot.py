import os
import re
import unittest

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

from ttyengine import scene as scene_mod
from ttyengine import sprite as sprite_mod
from ttyengine.ascii_styler import Styler
from ttyengine.fog import fader
from test_nphysics import make_scene as make_solid, run
from test_projection import make_scene, shown, column


def flat(found):
    rows = {}
    for (r, c), ch in found.items():
        rows.setdefault(r, {})[c] = ch
    return rows


class RotationTests(unittest.TestCase):
    def test_zrotation_matches_legacy_rotation(self):
        a, b = make_scene(), make_scene()
        a.obj().create('ab\ncd', 0, 0, rotation=90)
        b.obj().create('ab\ncd', 0, 0, zrotation=90)
        self.assertEqual(shown(a), shown(b))

    def test_x_and_y_rotation_are_right_handed(self):
        sc = make_scene()
        sc.axes = 3
        o = sc.obj().create('A\nB\nC', 0, 0, xrotation=90)
        shown(sc)
        self.assertEqual(o.transform.xrotation, 90)
        self.assertEqual(o.transform.turns, {'y,z': 90.0})
        o.transform.yrotation = 30
        self.assertEqual(o.transform.turns, {'y,z': 90.0, 'z,x': 30.0})

    def test_turns_prune_with_axes(self):
        sc = make_scene()
        sc.axes = 4
        o = sc.obj().create('x', 0, 0, turns={'x,w': 20})
        self.assertEqual(o.transform.turns, {'x,w': 20.0})
        sc.axes = 3
        self.assertEqual(o.transform.turns, {})

    def test_vertical_object_turned_flat_by_xrotation(self):
        sc = make_scene()
        sc.axes = 3
        sc.obj().create('#\n#\n#\n#', 0, 0, xrotation=90)
        found = shown(sc)
        self.assertEqual(len(set(r for r, _ in found)), 1)

    def test_full_turn_is_identity(self):
        a, b = make_scene(), make_scene()
        for sc, r in ((a, 0), (b, 360)):
            sc.axes = 3
            sc.obj().create('ab\ncd', 3, 2, xrotation=r, yrotation=r)
        self.assertEqual(shown(a), shown(b))

    def test_physics_uses_turned_cells(self):
        sc = make_solid()
        bar = sc.obj().create('####', 0, -1, solid=True, dynamic=False, w=0, turns={'x,w': 90})
        slabs = bar.physics._slabs()
        self.assertGreater(len(slabs), 1)
        self.assertTrue(all(len(cells) == 1 for _, cells in slabs))
        bar.transform.turns = {}
        self.assertEqual(len(bar.physics._slabs()), 1)

    def test_turned_bar_blocks_only_where_it_reaches(self):
        sc = make_solid()
        sc.obj().create('####', 6, 0, dynamic=False, solid=True, w=0, turns={'x,w': 90})
        near = sc.obj().create('o', 0, 0, xvel=1, solid=True, w=0)
        far = sc.obj().create('o', 0, -2, xvel=1, solid=True, w=6)
        run(sc, 14)
        self.assertLess(near.transform.x, 8)
        self.assertGreater(far.transform.x, 8)


class StylerRotateTests(unittest.TestCase):
    def test_quarter_turn(self):
        self.assertEqual(Styler.rotate('AAAA\nBBBB\nCCCC', zrotation=90), 'CCBBAA\nCCBBAA')

    def test_no_rotation_returns_source(self):
        self.assertEqual(Styler.rotate('ab', 0), 'ab')

    def test_round_trip(self):
        src = 'AAAA\nBBBB\nCCCC'
        out = Styler.rotate(Styler.rotate(src, yrotation=90), yrotation=-90)
        self.assertEqual(out, src)

    def test_sprite_in_flattens_to_text(self):
        sp = Styler.sprite(['AB', 'CD', 'EF'])
        self.assertEqual(Styler.rotate(sp, yrotation=90), 'ABDDFF')

    def test_sprite_in_keeps_extra_layers(self):
        out = Styler.rotate('AAAA\nBBBB\nCCCC', yrotation=90)
        self.assertEqual(out.footprint(), 'AA\nBB\nCC')


class CentreTests(unittest.TestCase):
    def test_sprite_centre(self):
        sp = Styler.sprite(['abcd', 'efgh'], axes='w', step=2)
        cx, cy, cz, cw = (list(sp.centre()) + [0, 0, 0, 0])[:4]
        self.assertEqual((cx, cy), (2.0, -0.5))
        self.assertEqual(cw, 1.0)

    def test_transform_centre_is_world_position(self):
        sc = make_scene()
        sc.axes = 4
        o = sc.obj().create('abcd\nefgh', 10, 20, w=5)
        centre = o.transform.centre()
        self.assertEqual(centre[0], 12.0)
        self.assertEqual(centre[1], 19.0)
        self.assertEqual(o.transform.centre(local=True)[0], 2.0)

    def test_follow_centres_the_camera_on_a_sprite(self):
        sc = make_scene()
        sc.axes = 4
        sp = Styler.sprite(['abcd', 'efgh'], axes='w', step=2)
        o = sc.obj().create(None, 10, 20, w=5, sprite=sp)
        sc.follow(o, depth=True)
        c = o.transform.centre()
        self.assertEqual((sc.camx, sc.camy), (c[0] - sc.dimx / 2, c[1] + sc.dimy / 2))
        self.assertEqual(sc.cam[3], c[3])


class FogTests(unittest.TestCase):
    def test_defaults(self):
        sc = make_scene()
        self.assertEqual((sc.renderdistance, sc.fog, sc.fogstart), (0, 0, 0))

    def test_validation(self):
        sc = make_scene()
        for name in ('renderdistance', 'fog', 'fogstart'):
            with self.assertRaises((ValueError, TypeError)):
                setattr(sc, name, -1)
        with self.assertRaises((ValueError, TypeError)):
            sc.fogcolor = 'red'

    def test_renderdistance_culls_far_objects(self):
        sc = make_scene()
        sc.obj().create('a', 0, 0)
        sc.obj().create('b', 20, 0)
        self.assertEqual(sorted(shown(sc).values()), ['a', 'b'])
        sc.perspective = 1000
        sc.renderdistance = 5
        self.assertEqual(sorted(shown(sc).values()), ['a'])

    def test_fader(self):
        sc = make_scene()
        sc.bgcolor = (0, 0, 0)
        f = fader(sc)
        cell = ('x', '\x1b[38;2;200;100;50m')
        self.assertEqual(f(cell, 0), cell)
        gone = f(cell, 1)
        self.assertIn('38;2;0;0;0', gone[1])
        mid = f(cell, 0.5)
        self.assertIn('38;2;100;50;25', mid[1])

    def test_fog_darkens_with_distance(self):
        sc = make_scene()
        sc.perspective = 1000
        sc.bgcolor = (0, 0, 0)
        sc.fogstart, sc.fog = 2, 20
        sc.obj().create('a', 0, 0, fgcolor=(200, 200, 200))
        sc.obj().create('b', 18, 0, fgcolor=(200, 200, 200))
        sc.tick(True)
        out = sc.render(full=True)
        far = re.search(r'38;2;(\d+);\d+;\d+mb', out)
        self.assertLess(int(far.group(1)), 200)
        self.assertGreater(int(far.group(1)), 0)
        self.assertIsNone(re.search(r'38;2;\d+;\d+;\d+ma', out))

    def test_fog_in_projected_signature(self):
        sc = make_scene()
        self.assertFalse(sc.projected())
        sc.fog = 5
        self.assertTrue(sc.projected())


if __name__ == '__main__':
    unittest.main()
