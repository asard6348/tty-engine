import os
import unittest

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

import ttyengine
from ttyengine import ansi
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


if __name__ == "__main__":
    unittest.main()
