import os
import struct
import tempfile
import unittest
import zlib

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

from ttyengine import ascii_styler
from ttyengine import scene as scene_mod
from ttyengine import sprite as sprite_mod

Shapes = ascii_styler.Shapes
Styler = ascii_styler.Styler


def png_file(directory, width, height, pixel):
    raw = b''.join(b'\x00' + b''.join(bytes(pixel(x, y)) for x in range(width)) for y in range(height))

    def chunk(kind, data):
        body = kind + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xffffffff)

    data = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
    path = os.path.join(directory, 'texture.png')
    with open(path, 'wb') as handle:
        handle.write(data)
    return path


def make_object(text='a', **kwargs):
    sc = scene_mod.Scene()
    sc.termx, sc.termy, sc.dimx, sc.dimy = 60, 20, 60, 20
    return sc.obj().create(text, 0, 0, **kwargs).transform


def layer_cells(sp, z):
    return {(c, r) for (c, r, k), cell in sp.cells.items() if k == z}


class MergeTests(unittest.TestCase):
    def test_strings_still_merge_to_a_string(self):
        t = make_object()
        found = t.merge('ab\ncd', ('X', 1, 0))
        self.assertIsInstance(found, str)
        self.assertEqual(found, t.merge('ab\ncd', ('X', 1, 0, 0)))

    def test_textured_sprites_merge_into_one_sprite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = png_file(directory, 8, 4, lambda x, y: (200, 40 * y, 255 - 30 * x))
            texture = Styler.image(path, width=8, shades='#', color=True)
        flat = Styler.rotate(texture, xrotation=0)
        wall = Styler.rotate(texture, yrotation=90)
        slant = Styler.rotate(texture, yrotation=45)
        self.assertIsInstance(wall, sprite_mod.sprite)
        t = make_object()
        merged = t.merge(flat, wall, slant)
        self.assertIsInstance(merged, sprite_mod.sprite)
        self.assertEqual(merged.axes, wall.axes)
        self.assertGreaterEqual(len(merged), len(wall))
        self.assertGreaterEqual(merged.size[2], wall.size[2])
        self.assertTrue(all(cell[1] for cell in merged.cells.values()))

    def test_sprites_are_centred_on_every_axis(self):
        a = sprite_mod.sprite(('###', '###', '###'))
        b = sprite_mod.sprite(('#', '#', '#', '#', '#'))
        merged = make_object().merge(a, b)
        self.assertEqual(merged.size[2], 5)
        z = {k for (c, r, k) in merged.cells}
        self.assertEqual(z, {0, 1, 2, 3, 4})
        self.assertEqual({k for (c, r, k) in merged.cells if (c, r) == (1, 0)}, {0, 1, 2, 3, 4})
        self.assertEqual({k for (c, r, k) in merged.cells if (c, r) == (0, 0)}, {1, 2, 3})

    def test_center_false_keeps_origins(self):
        a = sprite_mod.sprite(('#', '#', '#'))
        b = sprite_mod.sprite(('@@', '@@'))
        merged = make_object().merge(a, b, center=False)
        self.assertEqual(merged.cells[(0, 0, 0)][0], '@')
        self.assertEqual(merged.cells[(0, 0, 2)][0], '#')
        self.assertEqual(merged.cells[(1, 0, 1)][0], '@')
        self.assertNotIn((1, 0, 2), merged.cells)

    def test_flat_layer_joins_a_sprite_mid_depth(self):
        deep = sprite_mod.sprite(('##', '##', '##', '##', '##'))
        merged = make_object().merge(deep, 'X')
        self.assertEqual(merged.cells[(1, 0, 2)][0], 'X')
        self.assertEqual(merged.cells[(1, 0, 1)][0], '#')

    def test_depth_offsets_on_tuples_and_keywords(self):
        t = make_object()
        by_tuple = t.merge('ab', ('X', 0, 0, 3))
        self.assertEqual(by_tuple.size[2], 4)
        self.assertEqual(by_tuple.cells[(1, 0, 3)][0], 'X')
        by_keyword = t.merge('ab', 'X', dz=3)
        self.assertEqual(by_keyword.cells, by_tuple.cells)

    def test_higher_axes_merge_to_nested_sprites(self):
        a = sprite_mod.sprite((('a', 'b'), ('c', 'd')), axes=('z', 'w'))
        b = sprite_mod.sprite(('x', 'y', 'z'), axes='w')
        merged = make_object().merge(a, b, center=False)
        self.assertEqual(merged.axes, (2, 3))
        self.assertEqual(merged.size, (1, 1, 2, 3))
        self.assertEqual(merged.cells[(0, 0, 0, 0)][0], 'x')
        self.assertEqual(merged.cells[(0, 0, 1, 1)][0], 'd')

    def test_steps_of_the_first_sprite_are_kept(self):
        a = sprite_mod.sprite(('#', '#'), step=2)
        b = sprite_mod.sprite(('@', '@', '@'))
        merged = make_object().merge(a, b, center=False)
        self.assertEqual(merged.steps, (2,))

    def test_single_sprite_merges_into_the_objects_own_sprite(self):
        own = sprite_mod.sprite(('##', '##'))
        t = make_object(sprite=own)
        merged = t.merge(('@', 0, 0, 5), center=False)
        self.assertIsInstance(merged, sprite_mod.sprite)
        self.assertEqual(merged.cells[(0, 0, 5)][0], '@')
        self.assertEqual(merged.cells[(0, 0, 0)][0], '#')

    def test_unknown_keywords_are_rejected(self):
        t = make_object()
        for bad in ({'dq': 1}, {'dx2': 1}, {'z': 1}):
            with self.assertRaises(TypeError):
                t.merge('a', 'b', **bad)

    def test_empty_layers_give_empty_text(self):
        t = make_object()
        self.assertEqual(t.merge(sprite_mod.sprite(''), sprite_mod.sprite('')), '')

    def test_flat_result_collapses_to_text(self):
        a = sprite_mod.sprite(('ab',))
        merged = make_object().merge(a, ('c', 0, 1))
        self.assertIsInstance(merged, str)

    def test_merged_sprite_can_be_assigned(self):
        a = sprite_mod.sprite(('#', '#', '#'))
        t = make_object()
        t.sprite = t.merge(a, sprite_mod.sprite(('@@', '@@')))
        self.assertEqual(t.sprite.rank, 3)


class ShapeTests(unittest.TestCase):
    def test_two_dimensional_shapes_are_unchanged(self):
        self.assertEqual(Shapes.block(4, 3, char='#'), '####\n#  #\n####')
        self.assertEqual(Shapes.block(4, 3, char='#', filled=True), '####\n####\n####')
        self.assertEqual(Shapes.circle(1, 'o', True), ' ooo \nooooo\n ooo ')
        self.assertEqual(Shapes.line(3, '-'), '---')
        self.assertIsInstance(Shapes.ellipse(3, 2), str)
        self.assertEqual(Shapes.ellipse((3, 2)), Shapes.ellipse(3, 2))
        self.assertEqual(Shapes.block((4, 3), char='#'), Shapes.block(4, 3, char='#'))

    def test_block_filled_and_surface(self):
        solid = Shapes.block((6, 4, 4), char='#', filled=True)
        shell = Shapes.block((6, 4, 4), char='#', filled=True, surface=True)
        outline = Shapes.block((6, 4, 4), char='#')
        self.assertEqual((solid.rank, solid.size), (3, (6, 4, 4)))
        self.assertEqual((len(solid), len(shell), len(outline)), (96, 80, 64))
        self.assertLess(set(outline.cells), set(shell.cells))
        self.assertLess(set(shell.cells), set(solid.cells))
        self.assertEqual(layer_cells(shell, 0), layer_cells(solid, 0))
        self.assertEqual(len(layer_cells(shell, 1)), 16)
        self.assertEqual(layer_cells(outline, 0), layer_cells(outline, 1))

    def test_surface_without_filled_changes_nothing(self):
        self.assertEqual(Shapes.block((5, 4, 3), char='#', surface=True).cells,
                         Shapes.block((5, 4, 3), char='#').cells)

    def test_sphere_nesting_and_symmetry(self):
        solid = Shapes.circle(3, 'o', True, dims=3)
        shell = Shapes.circle(3, 'o', True, surface=True, dims=3)
        rings = Shapes.circle(3, 'o', False, dims=3)
        self.assertEqual(solid.size, (13, 7, 7))
        self.assertLess(set(shell.cells), set(solid.cells))
        self.assertLess(set(rings.cells), set(shell.cells))
        self.assertNotIn((6, 3, 3), shell.cells)
        self.assertIn((6, 3, 3), solid.cells)
        for c, r, z in solid.cells:
            self.assertIn((12 - c, 6 - r, 6 - z), solid.cells)
        flat = sprite_mod.sprite(Shapes.circle(3, 'o', True))
        self.assertEqual(layer_cells(solid, 3), {(c, r) for c, r in flat.cells})

    def test_sphere_shell_is_watertight(self):
        solid = Shapes.circle(4, 'o', True, dims=3)
        shell = Shapes.circle(4, 'o', True, surface=True, dims=3)
        inside = set(solid.cells) - set(shell.cells)
        for c, r, z in inside:
            for axis in range(3):
                for gap in (-1, 1):
                    near = [c, r, z]
                    near[axis] += gap
                    self.assertIn(tuple(near), solid.cells)

    def test_thickness_grows_the_shell(self):
        thin = Shapes.block((9, 9, 9), char='#', filled=True, surface=True, thickness=1)
        thick = Shapes.block((9, 9, 9), char='#', filled=True, surface=True, thickness=2)
        self.assertEqual((len(thin), len(thick)), (729 - 343, 729 - 125))
        full = Shapes.block((4, 4, 4), char='#', filled=True, surface=True, thickness=2)
        self.assertEqual(len(full), 64)

    def test_ellipse_with_per_axis_radii(self):
        sp = Shapes.ellipse((6, 5, 4), char='o', filled=True)
        self.assertEqual(sp.size, (13, 11, 9))
        flat = Shapes.ellipse((4, 3, 0), char='o', filled=True)
        self.assertEqual(flat.size, (9, 7, 1))
        self.assertEqual(len(flat), len(sprite_mod.sprite(Shapes.ellipse(4, 3, 'o', True)).cells))

    def test_diamond_is_an_octahedron(self):
        sp = Shapes.diamond(2, filled=True, dims=3)
        self.assertEqual(sp.size, (9, 5, 5))
        self.assertIn((4, 2, 2), sp.cells)
        self.assertIn((0, 2, 2), sp.cells)
        self.assertIn((4, 0, 2), sp.cells)
        self.assertIn((4, 2, 0), sp.cells)
        self.assertNotIn((0, 0, 0), sp.cells)

    def test_pyramid(self):
        sp = Shapes.triangle(4, (7, 5), filled=True)
        self.assertEqual(sp.size, (7, 4, 5))
        self.assertEqual(len([k for k in sp.cells if k[:2] == (3, 0)]), 1)
        self.assertEqual(len(layer_cells(sp, 2)), 1 + 3 + 5 + 7)
        down = Shapes.triangle(4, (7, 5), filled=True, direction='down')
        self.assertEqual({(c, 3 - r, z) for c, r, z in down.cells}, set(sp.cells))
        self.assertEqual(Shapes.triangle(4, dims=3, filled=True).rank, 3)

    def test_four_dimensions(self):
        sp = Shapes.circle(2, 'o', True, surface=True, dims=4)
        self.assertEqual((sp.rank, sp.axes), (4, (2, 3)))
        solid = Shapes.circle(2, 'o', True, dims=4)
        self.assertLess(len(sp), len(solid))
        named = Shapes.block((3, 3, 2, 2), char='#', filled=True, axes=('z', 'a4'))
        self.assertEqual(named.axes, (2, 4))

    def test_steps_scale_default_extents(self):
        a = Shapes.circle(4, 'o', True, dims=3, step=1)
        b = Shapes.circle(4, 'o', True, dims=3, step=2)
        self.assertEqual((a.size[2], b.size[2]), (9, 5))
        self.assertEqual(b.steps, (2,))

    def test_line_along_extra_axes(self):
        sp = Shapes.line(4, '#', 2, axis='z')
        self.assertEqual((sp.size, len(sp)), ((2, 2, 4), 16))
        self.assertEqual(Shapes.line(3, '-', axis='x'), Shapes.line(3, '-'))
        self.assertEqual(Shapes.line(3, '-', axis='y'), Shapes.line(3, '-', vertical=True))
        self.assertEqual(Shapes.line(2, axis='w').axes, (3,))

    def test_invalid_arguments(self):
        for bad in (lambda: Shapes.ellipse(3), lambda: Shapes.ellipse((3, 4), 4), lambda: Shapes.ellipse((3,)),
                    lambda: Shapes.block((3, 3, 3), 3), lambda: Shapes.block(()), lambda: Shapes.circle(3, dims=1),
                    lambda: Shapes.circle(3, dims=3, step=0), lambda: Shapes.circle(3, dims=4, step=(1, 1, 1)),
                    lambda: Shapes.circle(400, dims=4)):
            with self.assertRaises(ValueError):
                bad()

    def test_shapes_work_through_the_session_styler(self):
        styler = Styler()
        sp = styler.shapes.block((3, 3, 3), char='#', filled=True)
        make_object(sprite=sp)
        self.assertEqual(len(sp), 27)

    def test_shape_merges_with_a_rotated_texture(self):
        box = Shapes.block((5, 3, 3), char='#', filled=True)
        wall = Styler.rotate('@@@@\n@@@@', yrotation=90)
        merged = make_object().merge(box, wall)
        self.assertIsInstance(merged, sprite_mod.sprite)
        self.assertGreaterEqual(len(merged), len(box))


class ScaleTests(unittest.TestCase):
    def test_two_dimensional_sprites_scale_like_text(self):
        text = '\x1b[31mab#\x1b[0m\n c  d\n#e#\x1b[32mf\x1b[0m'
        for x in (0.3, 0.5, 0.75, 1, 1.5, 2, 3):
            for y in (0.4, 1, 2.5):
                self.assertEqual(Styler.scale(sprite_mod.sprite(text), x, y).cells,
                                 sprite_mod.sprite(Styler.scale(text, x, y)).cells)

    def test_every_axis_follows_the_first_factor_by_default(self):
        sp = sprite_mod.sprite(('ab\ncd', 'ef\ngh'))
        big = Styler.scale(sp, 2)
        self.assertIsInstance(big, sprite_mod.sprite)
        self.assertEqual((big.size, len(big), big.axes, big.steps), ((4, 4, 4), 64, sp.axes, sp.steps))
        self.assertEqual(big.cells[(0, 0, 0)][0], 'a')
        self.assertEqual(big.cells[(3, 3, 3)][0], 'h')

    def test_depth_factors_by_position_and_name(self):
        sp = sprite_mod.sprite(('ab\ncd', 'ef\ngh'))
        self.assertEqual(Styler.scale(sp, 1, 1, 3).size, (2, 2, 6))
        self.assertEqual(Styler.scale(sp, 1, 1, z=3).cells, Styler.scale(sp, 1, 1, 3).cells)
        self.assertEqual(Styler.scale(sp, 2, 2, z=0.5).size, (4, 4, 1))

    def test_shrinking_keeps_visible_cells_and_styles(self):
        text = '\x1b[31m#\x1b[0m'
        sp = Styler.scale(sprite_mod.sprite((text,) * 4), 1, 1, 0.5)
        self.assertEqual(sp.size[2], 2)
        self.assertTrue(all(cell == ('#', '\x1b[31m') for cell in sp.cells.values()))

    def test_higher_axes(self):
        sp = sprite_mod.sprite((('a', 'b'), ('c', 'd')), axes=('z', 'w'))
        big = Styler.scale(sp, 1, 1, 2, 3)
        self.assertEqual((big.size, big.axes), ((1, 1, 4, 6), (2, 3)))
        self.assertEqual(Styler.scale(sp, 1, 1, w=2).size, (1, 1, 2, 4))

    def test_scaled_sprite_roundtrips(self):
        sp = Shapes.block((4, 3, 2), char='#', filled=True)
        back = Styler.scale(Styler.scale(sp, 2), 0.5)
        self.assertEqual(back.cells, sp.cells)

    def test_invalid_factors(self):
        sp = sprite_mod.sprite(('a', 'b'))
        for bad in (lambda: Styler.scale(sp, 1, 1, 0), lambda: Styler.scale(sp, 1, 1, 2, 2),
                    lambda: Styler.scale(sp, 1, 1, w=2), lambda: Styler.scale(sp, 1, 1, q=2),
                    lambda: Styler.scale(sp, 1, 1, float('inf')), lambda: Styler.scale('a', 1, 1, 2),
                    lambda: Styler.scale(sp, 1000, 1000, 1000)):
            with self.assertRaises(ValueError):
                bad()


if __name__ == '__main__':
    unittest.main()
