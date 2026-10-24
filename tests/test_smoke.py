import os
import unittest

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

import ttyengine
import contextlib
import io

from ttyengine import ansi, region
from ttyengine.figlet import figlet_format
from ttyengine.launcher import Session


def make_session(**kwargs):
    return Session(sound=False, inp=False, **kwargs)


class VersionTests(unittest.TestCase):
    def test_version_is_set(self):
        self.assertNotEqual(ttyengine.__version__, "0+unknown")


class TransformTests(unittest.TestCase):
    def setUp(self):
        self.world = make_session().World()
        self.t = self.world.scene.obj().create("abcd", 10, -5).transform

    def test_center_includes_position_by_default(self):
        self.assertEqual(self.t.center(), (12.0, -5.5))

    def test_center_local_excludes_position(self):
        self.assertEqual(self.t.center(local=True), (2.0, -0.5))

    def test_extent_local_keeps_half_sizes(self):
        self.assertEqual(self.t.extent(local=True), (2.0, -0.5, 2.0, 0.5))


class SessionSizeTests(unittest.TestCase):
    def test_world_has_terminal_size_on_creation(self):
        sc = make_session().World().scene
        self.assertEqual((sc.termx, sc.termy, sc.dimx, sc.dimy), (100, 40, 100, 40))

    def test_handle_start_sees_real_size(self):
        seen = []

        class Handle:
            def start(self, scene):
                seen.append((scene.termx, scene.termy, scene.dimx, scene.dimy))

        make_session().World().launch(Handle)
        self.assertEqual(seen, [(100, 40, 100, 40)])

    def test_region_width_is_respected(self):
        sc = make_session(termwidth=50).World().scene
        self.assertEqual((sc.termx, sc.dimx), (50, 50))

    def test_autodim_off_keeps_default_dim(self):
        sc = make_session().World(autodim=False).scene
        self.assertEqual((sc.termx, sc.dimx), (100, 120))

    def test_stop_clears_running(self):
        session = make_session()
        session.running = True
        session.stop()
        self.assertFalse(session.running)


class SceneCallbackTests(unittest.TestCase):
    def test_ondim_fires_only_on_change(self):
        sc = make_session().World().scene
        calls = []
        sc.ondim(lambda att, old: calls.append((att, old)))
        sc.dimx = sc.dimx
        self.assertEqual(calls, [])
        sc.dimx = sc.dimx + 3
        self.assertEqual(calls, [("x", 100)])

    def test_oncam_fires_only_on_change(self):
        sc = make_session().World().scene
        calls = []
        sc.oncam(lambda att, old: calls.append(att))
        sc.camx = 0
        self.assertEqual(calls, [])
        sc.camx = 5
        self.assertEqual(calls, ["x"])


class RenderTests(unittest.TestCase):
    def test_render_contains_text(self):
        world = make_session().World()
        world.scene.obj().create("hello", 2, -2)
        self.assertIn("hello", ansi.strip_color(world.scene.render(full=True)))


class AnsiTests(unittest.TestCase):
    def test_strip_color_removes_colors_keeps_bold(self):
        text = ansi.sgr(1, 31) + "x" + ansi.RESET
        self.assertEqual(ansi.strip_color(text), ansi.sgr(1) + "x" + ansi.RESET)


class FigletTests(unittest.TestCase):
    def test_bundled_font_renders(self):
        self.assertGreater(len(figlet_format("hi").splitlines()), 1)


class RegionSettingTests(unittest.TestCase):
    def test_region_setting_resolves_against_the_terminal(self):
        session = make_session(region=region.bottom(2))
        self.assertEqual(session.resolved_region, (0, 38, 100, 2))
        sc = session.World().scene
        self.assertEqual((sc.termx, sc.termy, sc.dimx, sc.dimy), (100, 2, 100, 2))

    def test_legacy_names_read_and_write_the_region(self):
        session = make_session(termxoffset=5, termyoffset=2, termwidth=30, termheight=4)
        self.assertEqual(session.region, (5, 2, 30, 4))
        self.assertEqual(session.resolved_region, (5, 2, 30, 4))
        session.termwidth = "50%"
        self.assertEqual(session.resolved_region, (5, 2, 50, 4))
        session.region = region.line(-1)
        self.assertEqual((session.termxoffset, session.termyoffset, session.termwidth, session.termheight), (0, -1, None, 1))

    def test_region_can_be_changed_with_dicts_and_none(self):
        session = make_session()
        session.region = {"top": 1, "bottom": 1}
        self.assertEqual(session.resolved_region, (0, 1, 100, 38))
        session.region = None
        self.assertEqual(session.resolved_region, (0, 0, 100, 40))

    def test_bad_region_is_rejected(self):
        with self.assertRaises(ValueError):
            make_session(region=(1, 2, 3))

    def test_unknown_settings_are_still_rejected(self):
        with self.assertRaises(TypeError):
            make_session(regio=region.line())


class WorldRegionTests(unittest.TestCase):
    def test_world_region_sets_the_scene_view(self):
        session = make_session()
        bar = session.World(region=region.top(1)).scene
        side = session.World(region=region.right(10)).scene
        self.assertEqual((bar.canvas, bar.view), ((100, 40), (0, 0, 100, 1)))
        self.assertEqual((side.canvas, side.view), ((100, 40), (90, 0, 10, 40)))

    def test_world_region_resolves_inside_the_session_region(self):
        session = make_session(region=region.bottom(10))
        sc = session.World(region={"left": 2, "right": 2}).scene
        self.assertEqual((sc.canvas, sc.view), ((100, 10), (2, 0, 96, 10)))

    def test_world_region_follows_changes(self):
        session = make_session()
        world = session.World(region=region.top(1))
        world.region = region.box(10, 10, "50%", 3)
        session._fit(world.scene, world)
        self.assertEqual(world.scene.view, (10, 10, 50, 3))
        world.region = None
        session._fit(world.scene, world)
        self.assertEqual(world.scene.view, (0, 0, 100, 40))

    def test_autodim_off_leaves_the_view_alone(self):
        session = make_session()
        sc = session.World(region=region.top(1), autodim=False).scene
        self.assertEqual(sc.view, (0, 0, 120, 30))

    def test_footprint_covers_every_world_view(self):
        session = make_session()
        session.World(region=region.box(0, 0, 20, 2))
        session.World(region=region.box(10, 5, 30, 3))
        self.assertEqual(session._footprint(session.resolved_region), (0, 0, 40, 8))

    def test_world_region_is_validated(self):
        with self.assertRaises(ValueError):
            make_session().World(region="nope")


class InlineRegionTests(unittest.TestCase):
    def anchor(self, cursors, **kwargs):
        session = make_session(region=region.inline(3), **kwargs)
        replies = iter(cursors)
        session.term.get_cursor = lambda *a, **k: next(replies)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            session._anchor()
        return session, out.getvalue()

    def test_region_starts_below_the_cursor_line(self):
        session, out = self.anchor([(10, 0), (13, 0)])
        self.assertEqual(out, "\n\n\n")
        self.assertEqual(session.resolved_region, (0, 10, 100, 3))

    def test_a_partly_written_line_is_left_alone(self):
        session, out = self.anchor([(10, 8), (14, 0)])
        self.assertEqual(out, "\r\n\n\n\n")
        self.assertEqual(session.resolved_region, (0, 11, 100, 3))

    def test_region_scrolls_into_view_at_the_bottom(self):
        session, _ = self.anchor([(39, 0), (39, 0)])
        self.assertEqual(session.resolved_region, (0, 36, 100, 3))

    def test_without_a_terminal_the_region_goes_to_the_bottom(self):
        session, _ = self.anchor([None, None])
        self.assertEqual(session.resolved_region, (0, 37, 100, 3))

    def test_other_regions_never_anchor(self):
        session = make_session(region=region.line(-1))
        session._anchor()
        self.assertIsNone(session._anchor_row)
        self.assertEqual(session.resolved_region, (0, 39, 100, 1))

    def test_inline_regions_use_the_normal_screen(self):
        session = make_session(region=region.inline(2))
        self.assertTrue(session._partial())


if __name__ == "__main__":
    unittest.main()
