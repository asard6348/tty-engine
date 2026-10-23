import io
import math
import os
import struct
import sys
import time
import unittest
import zlib
from unittest import mock

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

from ttyengine import errors, image_reader, launcher
from ttyengine.launcher import Session
from ttyengine.sound import Sound


def make_scene(**kwargs):
    session = Session(sound=False, inp=False, **kwargs)
    return session, session.World().scene


def dist(a, b):
    return math.hypot(a.transform.x - b.transform.x, a.transform.y - b.transform.y)


class PhysicsTests(unittest.TestCase):
    def test_ball_comes_to_rest_on_floor(self):
        _, sc = make_scene()
        sc.gravity = (0, -1)
        ball = sc.obj().create("O", 5, 0, bounciness=0)
        floor = sc.obj().create("#" * 20, 0, -10, dynamic=False)
        for _ in range(600):
            sc.tick()
        self.assertGreater(ball.transform.y, floor.transform.y)
        self.assertLessEqual(ball.transform.y, floor.transform.y + 1)
        self.assertEqual(floor.transform.y, -10)

    def test_no_gravity_means_no_motion(self):
        _, sc = make_scene()
        ball = sc.obj().create("O", 5, 0, bounciness=0)
        for _ in range(120):
            sc.tick()
        self.assertEqual((ball.transform.x, ball.transform.y), (5, 0))

    def test_velocity_moves_object(self):
        _, sc = make_scene()
        ball = sc.obj().create("O", 0, 0, xvel=5)
        for _ in range(60):
            sc.tick()
        self.assertGreater(ball.transform.x, 1)

    def test_immovable_object_does_not_fall(self):
        _, sc = make_scene()
        sc.gravity = (0, -1)
        wall = sc.obj().create("#", 3, 3, dynamic=False)
        for _ in range(120):
            sc.tick()
        self.assertEqual((wall.transform.x, wall.transform.y), (3, 3))


class JointTests(unittest.TestCase):
    def build(self, preset):
        _, sc = make_scene()
        sc.gravity = (0, -1)
        anchor = sc.obj().create("A", 10, 0, dynamic=False)
        body = sc.obj().create("B", 14, 0, preset=preset, joints=[anchor], bounciness=0)
        return sc, anchor, body

    def test_jointed_body_stays_near_anchor(self):
        for preset in ("rod", "rope", "spring"):
            with self.subTest(preset=preset):
                sc, anchor, body = self.build(preset)
                for _ in range(300):
                    sc.tick()
                self.assertLess(dist(anchor, body), 4.5)

    def test_unjointed_body_falls_away(self):
        _, sc = make_scene()
        sc.gravity = (0, -1)
        anchor = sc.obj().create("A", 10, 0, dynamic=False)
        body = sc.obj().create("B", 14, 0, bounciness=0)
        for _ in range(300):
            sc.tick()
        self.assertGreater(dist(anchor, body), 10)


@unittest.skipIf(sys.platform == "win32", "terminal input needs a console")
class InputTests(unittest.TestCase):
    def setUp(self):
        from ttyengine.input_handler import inp
        self.inp = inp(watchfocus=False, trackmotion=False, quiet=True)

    def tearDown(self):
        self.inp.cleanup()

    def feed(self, data):
        self.inp._buf = data
        self.inp._parse_input(time.monotonic())
        self.inp.update()

    def test_keypress_callback(self):
        hits = []
        self.inp.onpress("a", lambda: hits.append("a"))
        self.feed("a")
        self.assertEqual(hits, ["a"])

    def test_other_key_does_not_trigger(self):
        hits = []
        self.inp.onpress("a", lambda: hits.append("a"))
        self.feed("b")
        self.assertEqual(hits, [])

    def test_sgr_mouse_position(self):
        self.feed("\x1b[<0;10;5M")
        self.assertEqual(self.inp.mouse, (9, 4))


class ImageTests(unittest.TestCase):
    @staticmethod
    def png(width, height, pixels):
        def chunk(kind, data):
            body = kind + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        rows = b"".join(
            b"\x00" + b"".join(bytes(pixels[y * width + x]) for x in range(width))
            for y in range(height)
        )
        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows))
                + chunk(b"IEND", b""))

    def test_png_decodes_to_rgba(self):
        width, height, data = image_reader.decode(self.png(2, 1, [(255, 0, 0), (0, 0, 255)]))
        self.assertEqual((width, height), (2, 1))
        self.assertEqual(bytes(data), bytes([255, 0, 0, 255, 0, 0, 255, 255]))

    def test_ppm_decodes(self):
        width, height, data = image_reader.decode(b"P6\n2 1\n255\n" + bytes([1, 2, 3, 4, 5, 6]))
        self.assertEqual((width, height), (2, 1))
        self.assertEqual(bytes(data[:3]), bytes([1, 2, 3]))

    def test_garbage_raises_image_error(self):
        with self.assertRaises(image_reader.ImageError):
            image_reader.decode(b"not an image")


class SoundTests(unittest.TestCase):
    def test_tone_has_requested_length(self):
        sound = Sound.tone(440, 0.1)
        self.assertAlmostEqual(sound.duration, 0.1, places=2)
        self.assertGreater(len(sound.left), 0)

    def test_tone_is_not_silent(self):
        sound = Sound.tone(440, 0.1, volume=0.5)
        self.assertGreater(max(abs(v) for v in sound.left), 0)


class LatencyTests(unittest.TestCase):
    def test_measure_latency_is_small(self):
        value = launcher.measure_latency(samples=50)
        self.assertGreaterEqual(value, 0)
        self.assertLess(value, 0.1)

    def test_single_outlier_does_not_set_the_value(self):
        samples = [1e-5] * 199 + [0.05]
        with mock.patch.object(launcher, "latency", return_value=samples):
            self.assertAlmostEqual(launcher.measure_latency(), 1e-5)

    def test_latency_caps_framerate_of_autofps_worlds(self):
        session, sc = make_scene()
        session.latency = 0.5
        self.assertEqual(sc.maxframerate, 2.0)

    def test_zero_latency_does_not_divide_by_zero(self):
        session, sc = make_scene()
        session.latency = 0
        self.assertGreater(sc.maxframerate, 1000)


def boom():
    raise ValueError("boom")


class ErrorTests(unittest.TestCase):
    def test_attempt_returns_result(self):
        self.assertEqual(errors.attempt(lambda: 42), 42)

    def test_fatal_error_exits_with_code_one(self):
        stream = io.StringIO()
        with self.assertRaises(SystemExit) as ctx:
            errors.attempt(boom, stream=stream, hold=False)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("ValueError: boom", stream.getvalue())

    def test_custom_exit_code(self):
        with self.assertRaises(SystemExit) as ctx:
            errors.attempt(boom, stream=io.StringIO(), hold=False, code=7)
        self.assertEqual(ctx.exception.code, 7)

    def test_non_fatal_error_returns_none(self):
        stream = io.StringIO()
        self.assertIsNone(errors.attempt(boom, fatal=False, stream=stream))
        self.assertIn("ValueError: boom", stream.getvalue())

    def test_output_is_plain_when_not_a_terminal(self):
        stream = io.StringIO()
        errors.attempt(boom, fatal=False, stream=stream)
        self.assertNotIn("\x1b", stream.getvalue())

    def test_internal_frame_is_hidden(self):
        stream = io.StringIO()
        errors.attempt(boom, fatal=False, stream=stream)
        self.assertNotIn("in attempt", stream.getvalue())

    def test_catch_callback_runs_before_report(self):
        order = []
        errors.attempt(boom, catch=lambda: order.append("catch"), fatal=False, stream=io.StringIO())
        self.assertEqual(order, ["catch"])

    def test_failing_catch_callback_is_reported_too(self):
        stream = io.StringIO()

        def bad_catch():
            raise RuntimeError("catch failed")

        errors.attempt(boom, catch=bad_catch, fatal=False, stream=stream)
        self.assertIn("ValueError: boom", stream.getvalue())
        self.assertIn("RuntimeError: catch failed", stream.getvalue())

    def test_should_hold_explicit_values(self):
        self.assertTrue(errors.should_hold(True))
        self.assertFalse(errors.should_hold(False))
        self.assertTrue(errors.should_hold("always"))
        self.assertFalse(errors.should_hold("never"))

    def test_should_hold_reads_environment(self):
        with mock.patch.dict(os.environ, {errors.HOLD_ENV: "always"}):
            self.assertTrue(errors.should_hold())
        with mock.patch.dict(os.environ, {errors.HOLD_ENV: "never"}):
            self.assertFalse(errors.should_hold())

    def test_auto_hold_follows_console_ownership(self):
        with mock.patch.object(errors, "owns_console", return_value=True):
            self.assertTrue(errors.should_hold("auto"))
        with mock.patch.object(errors, "owns_console", return_value=False):
            self.assertFalse(errors.should_hold("auto"))

    def test_fatal_error_waits_when_hold_is_on(self):
        stream = io.StringIO()
        with mock.patch("builtins.input", return_value="") as fake_input:
            with self.assertRaises(SystemExit):
                errors.attempt(boom, stream=stream, hold=True)
        fake_input.assert_called_once()
        self.assertIn(errors.HOLD_PROMPT, stream.getvalue())

    def test_install_replaces_and_restores_excepthook(self):
        original = sys.excepthook
        stream = io.StringIO()
        try:
            previous = errors.install(hold=False, stream=stream)
            self.assertIs(previous, original)
            self.assertIsNot(sys.excepthook, original)
            try:
                boom()
            except ValueError:
                sys.excepthook(*sys.exc_info())
            self.assertIn("ValueError: boom", stream.getvalue())
        finally:
            sys.excepthook = original


if __name__ == "__main__":
    unittest.main()
