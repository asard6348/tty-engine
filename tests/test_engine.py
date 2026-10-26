import io
import math
import os
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
from unittest import mock

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

from ttyengine import ansi, ascii_styler, compositor, errors, figlet, image_reader, launcher, region, terminal
from ttyengine.launcher import Session
from ttyengine.sound import Sound, find_ffmpeg


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

    def test_key_callback_error_propagates(self):
        def bad():
            raise RuntimeError("press failed")

        self.inp.onpress("a", bad)
        with self.assertRaisesRegex(RuntimeError, "press failed"):
            self.feed("a")

    def test_mouse_callback_error_propagates(self):
        def bad(*args):
            raise RuntimeError("mouse failed")

        self.inp.onmouse("click", bad)
        with self.assertRaisesRegex(RuntimeError, "mouse failed"):
            self.feed("\x1b[<0;10;5M")


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

    @staticmethod
    def raw_png(width, height, depth, ctype, rows, extra=b""):
        def chunk(kind, data):
            body = kind + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, ctype, 0, 0, 0))
                + extra
                + chunk(b"IDAT", zlib.compress(b"".join(b"\x00" + row for row in rows)))
                + chunk(b"IEND", b""))

    @staticmethod
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    def test_rgba_png_decodes_all_rows(self):
        rows = [bytes([1, 2, 3, 4, 5, 6, 7, 8]), bytes([9, 10, 11, 12, 13, 14, 15, 16])]
        width, height, data = image_reader.decode(self.raw_png(2, 2, 8, 6, rows))
        self.assertEqual((width, height), (2, 2))
        self.assertEqual(bytes(data), b"".join(rows))

    def test_png_16bit_transparent_key_compares_full_value(self):
        key = self.chunk(b"tRNS", struct.pack(">H", 0x1299))
        rows = [struct.pack(">HH", 0x1234, 0x1299)]
        _, _, data = image_reader.decode(self.raw_png(2, 1, 16, 0, rows, key))
        self.assertEqual(data[3], 255)
        self.assertEqual(data[7], 0)

    def test_png_palette_index_out_of_range_is_black(self):
        palette = self.chunk(b"PLTE", bytes([255, 0, 0]))
        _, _, data = image_reader.decode(self.raw_png(2, 1, 8, 3, [bytes([0, 5])], palette))
        self.assertEqual(bytes(data), bytes([255, 0, 0, 255, 0, 0, 0, 255]))

    def test_png_rejects_invalid_depth_for_color_type(self):
        with mock.patch.object(image_reader, "_ffmpeg", return_value=(None, "")):
            with self.assertRaises(image_reader.ImageError):
                image_reader.decode(self.raw_png(1, 1, 4, 2, [b"\x00" * 2]))

    def test_gif_rejects_invalid_code_size(self):
        gif = (b"GIF89a" + struct.pack("<HHBBB", 1, 1, 0x80, 0, 0) + bytes(6)
               + b"\x2c" + struct.pack("<HHHHB", 0, 0, 1, 1, 0) + bytes([200, 1, 0, 0]) + b"\x3b")
        with mock.patch.object(image_reader, "_ffmpeg", return_value=(None, "")):
            with self.assertRaises(image_reader.ImageError):
                image_reader.decode(gif)

    def test_corrupt_data_only_raises_image_error(self):
        png = self.png(3, 3, [(10, 20, 30)] * 9)
        samples = [
            png[:40], png[:len(png) // 2], png[:20] + b"\xff" * 20 + png[40:],
            b"GIF89a" + b"\x01" * 30, b"\xff\xd8\xff\xdb\x00\x04\x00\x00\xff\xc0\x00\x02",
            b"P3\n1 1\n10\n99 99 99", b"P6\n2 2\n255\n\x00", b"P5\nx y\n255\n", b"BM" + b"\x00" * 60,
        ]
        with mock.patch.object(image_reader, "_ffmpeg", return_value=(None, "")):
            for data in samples:
                with self.assertRaises(image_reader.ImageError, msg=data[:12]):
                    image_reader.decode(data)

    def test_unknown_format_mentions_ffmpeg_when_missing(self):
        with mock.patch("ttyengine.sound.find_ffmpeg", return_value=None):
            with self.assertRaises(image_reader.ImageError) as caught:
                image_reader.decode(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
        self.assertIn("ffmpeg", str(caught.exception))

    def test_ffmpeg_fallback_decodes_other_formats(self):
        exe = find_ffmpeg()
        if not exe:
            self.skipTest("ffmpeg is not available")
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "red.tiff")
            subprocess.run([exe, "-v", "error", "-f", "lavfi", "-i", "color=c=0xff0000:s=4x2", "-frames:v", "1", "-pix_fmt", "rgb24", path],
                           check=True, stdin=subprocess.DEVNULL)
            width, height, data = image_reader.read(path)
        self.assertEqual((width, height), (4, 2))
        for got, want in zip(data[:4], (255, 0, 0, 255)):
            self.assertAlmostEqual(got, want, delta=4)
        self.assertEqual(len(data), 4 * 2 * 4)

    def test_ffmpeg_fallback_ignores_wrong_extension(self):
        exe = find_ffmpeg()
        if not exe:
            self.skipTest("ffmpeg is not available")
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "actually-a-tiff.png")
            subprocess.run([exe, "-v", "error", "-f", "lavfi", "-i", "color=c=0x00ff00:s=4x4", "-frames:v", "1",
                            "-pix_fmt", "rgb24", "-f", "image2", "-c:v", "tiff", path], check=True, stdin=subprocess.DEVNULL)
            width, height, data = image_reader.read(path)
        self.assertEqual((width, height), (4, 4))
        for got, want in zip(data[:4], (0, 255, 0, 255)):
            self.assertAlmostEqual(got, want, delta=4)


class StylerImageTests(unittest.TestCase):
    def test_default_size_does_not_depend_on_terminal(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "white.ppm")
            with open(path, "wb") as f:
                f.write(b"P6\n200 100\n255\n" + b"\xff" * (200 * 100 * 3))
            outputs = []
            for size in ((10, 5), (300, 100)):
                with mock.patch("shutil.get_terminal_size", return_value=os.terminal_size(size)):
                    outputs.append(ascii_styler.image(path, shades=" #", color=False))
            small = ascii_styler.image(os.path.join(folder, "white.ppm"), shades=" #", color=False)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], small)
        lines = outputs[0].split("\n")
        self.assertEqual(len(lines[0]), ascii_styler.DEFAULT_IMAGE_WIDTH)
        self.assertEqual(len(lines), 20)

    def test_default_size_never_upscales_small_images(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "tiny.ppm")
            with open(path, "wb") as f:
                f.write(b"P6\n8 4\n255\n" + b"\xff" * (8 * 4 * 3))
            lines = ascii_styler.image(path, shades=" #", color=False).split("\n")
        self.assertEqual((len(lines[0]), len(lines)), (8, 2))

    @staticmethod
    def rgba_png(folder, pixels):
        def chunk(kind, data):
            body = kind + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        rows = b"\x00" + b"".join(bytes(p) for p in pixels)
        path = os.path.join(folder, "alpha.png")
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n"
                    + chunk(b"IHDR", struct.pack(">IIBBBBB", len(pixels), 1, 8, 6, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(rows))
                    + chunk(b"IEND", b""))
        return path

    def test_default_shades_cover_every_brightness_level(self):
        self.assertEqual(len(ascii_styler.DEFAULT_SHADES), 256)
        self.assertEqual(ascii_styler.DEFAULT_SHADES[0], " ")
        self.assertEqual(ascii_styler.DEFAULT_SHADES[-1], "█")

    def test_bgcolor_fills_every_cell_and_blends_transparency(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.rgba_png(folder, [(255, 255, 255, 255), (255, 255, 255, 0)])
            plain = ascii_styler.image(path, width=2, height=1, shades=" #", color=False)
            filled = ascii_styler.image(path, width=2, height=1, shades=" #", color=False, bgcolor=(10, 20, 30))
            lit = ascii_styler.image(path, width=2, height=1, shades=" #", color=False, bgcolor="white")
        self.assertEqual(plain, "#")
        self.assertEqual(filled, ansi.bg(10, 20, 30) + "# " + ansi.RESET)
        self.assertNotIn(ansi.bg(10, 20, 30), plain)
        self.assertEqual(lit, ansi.bg(255, 255, 255) + "# " + ansi.RESET)

    def test_bgcolor_with_color_keeps_pixel_colors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.rgba_png(folder, [(200, 100, 50, 255)])
            out = ascii_styler.image(path, width=1, height=1, shades="#", color=True, bgcolor="blue")
        self.assertEqual(out, ansi.bg(36, 114, 200) + ansi.fg(200, 100, 50) + "#" + ansi.RESET)

    def test_bgcolor_rejects_unknown_colors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.rgba_png(folder, [(0, 0, 0, 255)])
            with self.assertRaises(ValueError):
                ascii_styler.image(path, bgcolor="nope")


class FakeClock:
    def __init__(self, overshoot=0.0):
        self.now = 1000.0
        self.overshoot = overshoot

    def perf_counter(self):
        self.now += 0.00005
        return self.now

    def sleep(self, seconds):
        self.now += seconds + self.overshoot


class VsyncTests(unittest.TestCase):
    @staticmethod
    def vblank_stamps(clock, count):
        comp = compositor.Compositor(vsync=True, refresh=50)
        stamps = []
        with mock.patch.object(compositor, "time", clock):
            comp.vblank()
            start = clock.now
            for _ in range(count):
                clock.sleep(0.003)
                comp.vblank()
                stamps.append(clock.now)
        return start, stamps

    def test_synchronized_output_sequences_are_kept(self):
        self.assertEqual(ansi.SYNC_BEGIN, ansi.mode(2026, True))
        self.assertEqual(ansi.SYNC_END, ansi.mode(2026, False))
        self.assertEqual(terminal.MODE_SYNC, 2026)
        self.assertTrue(callable(terminal.Terminal.synchronized_output))

    def test_vblank_is_a_noop_when_disabled(self):
        comp = compositor.Compositor(vsync=False, refresh=30)
        start = time.perf_counter()
        for _ in range(5):
            self.assertFalse(comp.vblank())
        self.assertLess(time.perf_counter() - start, 0.05)

    def test_vblank_locks_presentation_to_refresh_rate(self):
        _, stamps = self.vblank_stamps(FakeClock(), 6)
        for a, b in zip(stamps, stamps[1:]):
            self.assertAlmostEqual(b - a, 0.02, delta=0.001)

    def test_vblank_compensates_for_late_sleeps(self):
        start, stamps = self.vblank_stamps(FakeClock(overshoot=0.008), 16)
        for stamp in stamps[4:]:
            offset = (stamp - start) % 0.02
            self.assertLess(min(offset, 0.02 - offset), 0.001)

    def test_refresh_is_validated(self):
        comp = compositor.Compositor(vsync=True)
        for bad in (0, 5, 5000, "fast"):
            with self.assertRaises(ValueError):
                comp.refresh = bad
        comp.refresh = 144
        self.assertEqual(comp.refresh_rate(), 144.0)
        comp.refresh = None
        self.assertGreaterEqual(comp.refresh_rate(), compositor.MIN_REFRESH)

    def test_refresh_environment_override(self):
        with mock.patch.dict(os.environ, {"TTYENGINE_REFRESH": "75"}):
            self.assertEqual(compositor.detect_refresh(), 75.0)

    def test_session_hands_vsync_to_compositor(self):
        session, _ = make_scene(vsync=True, refresh=90)
        self.assertTrue(session.vsync)
        self.assertEqual(session.refresh, 90)


class FfmpegSettingTests(unittest.TestCase):
    def test_ffmpeg_path_applies_without_sound(self):
        with mock.patch.object(launcher, "set_ffmpeg") as setter:
            Session(sound=False, inp=False, ffmpeg="/opt/ffmpeg")
        setter.assert_called_once_with("/opt/ffmpeg")


class FigletTests(unittest.TestCase):
    def test_glyph_exactly_as_wide_as_width_terminates(self):
        font = figlet.FigletFont("standard")
        width = font.width[ord("a")]
        text = figlet.Figlet("standard", width=width).renderText("a")
        self.assertTrue(text.strip())

    def test_right_to_left_works_for_every_tested_font(self):
        for name in ("1943____", "3d_diagonal", "4x4_offr", "a_zooloo", "advenger"):
            with self.subTest(font=name):
                text = figlet.Figlet(name, direction="right-to-left").renderText("Hello")
                self.assertTrue(text.strip())

    def test_glyph_wider_than_width_raises(self):
        with self.assertRaises(figlet.CharNotPrinted):
            figlet.Figlet("standard", width=1).renderText("a")


class StylerColorTests(unittest.TestCase):
    def test_rgb_accepts_lists(self):
        self.assertEqual(ascii_styler.Styler.rgb([255, 0, 0]), (255, 0, 0))
        self.assertIsNone(ascii_styler.Styler.rgb({}))

    def test_style_accepts_list_color(self):
        out = ascii_styler.Styler().style("x", color=[255, 0, 0])
        self.assertIn("38;2;255;0;0", out)

    def test_alpha_is_clamped(self):
        styler = ascii_styler.Styler()
        for alpha in (2, -1, 1.5):
            for kwargs in ({"color": "red", "alpha": alpha}, {"bgcolor": "red", "bgalpha": alpha}):
                out = styler.style("x", **kwargs)
                self.assertNotIn("-", out.replace("\x1b[", ""))
                for part in out.split("\x1b[")[1:]:
                    numbers = [int(n) for n in part.split("m")[0].split(";") if n.isdigit()]
                    if part.startswith(("38;2;", "48;2;")):
                        self.assertTrue(all(0 <= n <= 255 for n in numbers[2:5]), out)


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


    def test_thread_error_is_deferred_and_raised(self):
        import threading
        original = threading.excepthook

        def worker():
            raise RuntimeError("thread failed")

        with errors.capture():
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()
            self.assertTrue(errors.pending())
            with self.assertRaisesRegex(RuntimeError, "thread failed"):
                errors.raise_pending()
            self.assertFalse(errors.pending())
        self.assertIs(threading.excepthook, original)

    def test_session_run_is_fatal_on_thread_error(self):
        import threading

        class Faulty:
            def update(self):
                def worker():
                    raise RuntimeError("background failed")

                thread = threading.Thread(target=worker)
                thread.start()
                thread.join()

        session = Session(sound=False, inp=False)
        session.World().launch(Faulty)
        guard = threading.Timer(10, session.stop)
        guard.start()
        try:
            with self.assertRaisesRegex(RuntimeError, "background failed"):
                session.run_attempt()
        finally:
            guard.cancel()


class RegionTests(unittest.TestCase):
    def test_presets_resolve_against_a_size(self):
        r = region.resolve
        self.assertEqual(r(None, 100, 40), (0, 0, 100, 40))
        self.assertEqual(r(region.line(-1), 100, 40), (0, 39, 100, 1))
        self.assertEqual(r(region.line(5), 100, 40), (0, 5, 100, 1))
        self.assertEqual(r(region.column(-1), 100, 40), (99, 0, 1, 40))
        self.assertEqual(r(region.top(3), 100, 40), (0, 0, 100, 3))
        self.assertEqual(r(region.bottom(3), 100, 40), (0, 37, 100, 3))
        self.assertEqual(r(region.left(10), 100, 40), (0, 0, 10, 40))
        self.assertEqual(r(region.right(10), 100, 40), (90, 0, 10, 40))
        self.assertEqual(r(region.box(5, 6, 7, 8), 100, 40), (5, 6, 7, 8))

    def test_regions_are_clamped_to_the_available_space(self):
        r = region.resolve
        self.assertEqual(r(region.line(99), 100, 40), (0, 40, 100, 0))
        self.assertEqual(r((90, 0, 50, 5), 100, 40), (90, 0, 10, 5))
        self.assertEqual(r(region.centered(200, 100), 100, 40), (0, 0, 100, 40))
        self.assertEqual(r((0, 0, 5, 5), 0, 0), (0, 0, 0, 0))

    def test_percentages_alignment_and_negative_sizes(self):
        r = region.resolve
        self.assertEqual(r(region.centered(40, 10), 100, 40), (30, 15, 40, 10))
        self.assertEqual(r(region.centered("50%", "50%"), 100, 40), (25, 10, 50, 20))
        self.assertEqual(r(("10%", "25%", "50%", -5), 100, 40), (10, 10, 50, 25))
        self.assertEqual(r(("end", "end", 10, 3), 100, 40), (90, 37, 10, 3))

    def test_dict_form_supports_insets(self):
        r = region.resolve
        self.assertEqual(r({"top": 1, "bottom": 1}, 100, 40), (0, 1, 100, 38))
        self.assertEqual(r({"left": 2, "right": 2, "top": 1, "bottom": 1}, 100, 40), (2, 1, 96, 38))
        self.assertEqual(r({"right": 10, "width": 4}, 100, 40), (86, 0, 4, 40))
        self.assertEqual(r({"width": 10, "height": 3}, 100, 40), (0, 0, 10, 3))

    def test_inline_uses_the_cursor_row(self):
        self.assertEqual(region.resolve(region.inline(5), 100, 40, cursor=12), (0, 12, 100, 5))
        self.assertTrue(region.uses_cursor(region.inline(2)))
        self.assertFalse(region.uses_cursor(region.line(2)))

    def test_invalid_specs_raise_value_error(self):
        for bad in (5, "x", (1, 2, 3), {"zz": 1}, (True, 0, 1, 1), (0, 0, "a", 1),
                    (float("nan"), 0, 1, 1), {"right": -1}, {"width": 3, "right": 1, "x": 2}):
            with self.assertRaises(ValueError):
                region.resolve(bad, 100, 40)

    def test_fill_accepts_a_region(self):
        styler = ascii_styler.Styler
        self.assertEqual(
            styler.fill((1, 2, 3), termx=6, termy=3, region={"top": 1, "bottom": 1, "left": 2, "right": 2}),
            styler.fill((1, 2, 3), width=2, height=1, xoffset=2, yoffset=1, termx=6, termy=3),
        )

    def test_scene_view_and_canvas(self):
        _, sc = make_scene()
        sc.canvas = (60, 20)
        sc.view = region.bottom(2)
        self.assertEqual(sc.view, (0, 18, 60, 2))
        self.assertEqual((sc.dimx, sc.dimy, sc.dimxoffset, sc.dimyoffset), (60, 2, 0, -18))
        sc.view = {"left": 1, "right": 1}
        self.assertEqual(sc.view, (1, 0, 58, 20))
        sc.view = None
        self.assertEqual(sc.view, (0, 0, 60, 20))
        self.assertEqual(sc.canvas, (60, 20))


class RegressionTests(unittest.TestCase):
    def test_ansi_decode_tolerates_bad_escapes(self):
        self.assertEqual(ansi._decode("\\"), "\\")
        self.assertEqual(ansi._decode("\\x1"), "\\x1")
        self.assertEqual(ansi._decode("\\x1b[0m"), "\x1b[0m")

    def test_figlet_error_str_accepts_non_strings(self):
        self.assertEqual(str(figlet.FontNotFound(2.5)), "2.5")

    def test_rgb_returns_none_for_unusable_values(self):
        styler = ascii_styler.Styler
        self.assertIsNone(styler.rgb(float("nan")))
        self.assertIsNone(styler.rgb(float("inf")))
        self.assertIsNone(styler.rgb(("a", "b", "c")))

    def test_fill_clamps_colors_and_accepts_names(self):
        styler = ascii_styler.Styler()
        out = styler.fill((-5, 300, 3), width=2, height=1, termx=10, termy=5)
        self.assertNotIn("-5", out)
        self.assertNotIn("300", out)
        self.assertIn("48;2;0;255;3", out)
        self.assertEqual(styler.fill("red", width=1, height=1, termx=3, termy=1), styler.fill(styler.rgb("red"), width=1, height=1, termx=3, termy=1))
        with self.assertRaises(ValueError):
            styler.fill("nocolor", termx=3, termy=1)

    def test_fill_zero_size_is_empty(self):
        styler = ascii_styler.Styler()
        self.assertEqual(styler.fill((1, 2, 3), width=0, height=2, termx=10, termy=5), "")
        self.assertEqual(styler.fill((1, 2, 3), width=2, height=0, termx=10, termy=5), "")
        self.assertTrue(styler.fill((1, 2, 3), width=2.0, height=1.0, termx=10, termy=5))

    def test_image_rejects_non_positive_aspect(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "a.ppm")
            with open(path, "wb") as f:
                f.write(b"P6\n2 2\n255\n" + bytes(12))
            with self.assertRaises(ValueError):
                ascii_styler.image(path, height=2, aspect=0)

    def test_default_precision_is_half_a_cell(self):
        _, sc = make_scene()
        ball = sc.obj().create("O", 0, 0, dynamic=True)
        self.assertEqual(sc.precision, 0.5)
        self.assertEqual(ball.physics.precision, 0.5)

    def test_manual_mass_off_still_gets_a_mass(self):
        _, sc = make_scene()
        sc.gravity = (0, -1)
        ball = sc.obj().create("##\n##", 5, 5, automass=False)
        for _ in range(3):
            sc.tick()
        self.assertEqual(ball.physics.mass, 4)

    def test_scene_bgcolor_accepts_names_and_rejects_junk(self):
        _, sc = make_scene()
        sc.bgcolor = "red"
        self.assertEqual(sc.bgcolor, ascii_styler.Styler.rgb("red"))
        sc.bgcolor = 7
        self.assertEqual(sc.bgcolor, (7, 7, 7))
        with self.assertRaises(ValueError):
            sc.bgcolor = None

    def test_scene_framerate_must_be_positive(self):
        _, sc = make_scene()
        for bad in (0, -5, float("nan")):
            with self.assertRaises(ValueError):
                sc.framerate = bad
            with self.assertRaises(ValueError):
                sc.maxframerate = bad
        sc.framerate = 30
        self.assertEqual(sc.framerate, 30)


class ObjectAccessTests(unittest.TestCase):
    def setUp(self):
        _, self.sc = make_scene()
        self.thing = self.sc.obj().create("hi", 1, -1, xvel=0, light=True)
        self.bare = self.sc.obj().create("b", 0, 0)

    def test_objects_are_not_iterable(self):
        with self.assertRaises(TypeError):
            iter(self.thing)
        with self.assertRaises(TypeError):
            list(self.thing)

    def test_object_keys_must_be_names(self):
        with self.assertRaises(TypeError):
            self.thing[0]
        with self.assertRaises(TypeError):
            self.thing[0] = 1

    def test_unknown_or_missing_settings_raise_key_error(self):
        with self.assertRaises(KeyError):
            self.thing["nope"]
        with self.assertRaises(KeyError):
            self.bare["xvel"]
        with self.assertRaises(KeyError):
            self.bare["xvel"] = 1

    def test_object_membership_follows_attached_components(self):
        self.assertIn("xvel", self.thing)
        self.assertNotIn("xvel", self.bare)
        self.assertNotIn("nope", self.thing)

    def test_object_settings_read_and_write(self):
        self.thing["x"] = 12
        self.assertEqual(self.thing["x"], 12)
        self.assertEqual(self.thing.transform.x, 12)

    def test_components_reject_bad_keys(self):
        for comp in (self.thing.transform, self.thing.physics, self.thing.light):
            with self.assertRaises(TypeError):
                comp[0]
            with self.assertRaises(TypeError):
                list(comp)
            with self.assertRaises(KeyError):
                comp["nope"]
            with self.assertRaises(KeyError):
                comp["nope"] = 1
        self.assertIn("x", self.thing.transform)
        self.assertNotIn("nope", self.thing.transform)


class CallbackAndBounceTests(unittest.TestCase):
    def test_bound_methods_get_all_their_arguments(self):
        class Listener:
            def __init__(self):
                self.seen = []

            def touched(self, other, intersection):
                self.seen.append("touch")

            def changed(self, attr, old):
                self.seen.append(attr)

        _, sc = make_scene()
        sc.gravity = (0, -1)
        listener = Listener()
        ball = sc.obj().create("O", 5, 0, bounciness=0)
        sc.obj().create("#" * 20, 0, -3, dynamic=False)
        ball.physics.ontouch(listener.touched)
        ball.transform.onchange(listener.changed)
        for _ in range(10):
            sc.tick()
        self.assertIn("touch", listener.seen)
        self.assertIn("y", listener.seen)

    def test_bounce_can_ignore_headings_that_already_leave_the_surface(self):
        _, sc = make_scene()
        t = sc.obj().create("O", 0, 0).transform
        self.assertTrue(t.approaching((0, 1), angle=180))
        self.assertFalse(t.approaching((0, 1), angle=0))
        self.assertAlmostEqual(t.bounce((0, 1), angle=135), 45)
        self.assertEqual(t.bounce((0, 1), angle=45, incoming_only=True), 45)
        self.assertAlmostEqual(t.bounce((0, 1), angle=135, incoming_only=True), 45)
        self.assertEqual(t.rotation, 0)

    def test_bounce_threshold_is_configurable(self):
        def rebound(**kwargs):
            _, sc = make_scene()
            sc.gravity = (0, -0.02)
            ball = sc.obj().create("O", 5, -3, bounciness=1, **kwargs)
            sc.obj().create("#" * 20, 0, -6, dynamic=False)
            for _ in range(400):
                sc.tick()
                if ball.physics.yvel > 0:
                    return True
            return False

        self.assertFalse(rebound())
        self.assertTrue(rebound(bouncethreshold=0))


PARTS = {
    "torso": "###\n###\n###",
    "head": {"text": "O", "parent": "torso", "at": "top", "joint": "neck"},
    "left_arm": {"text": "|\n|\n|", "parent": "torso", "at": "top_left", "pin": "top", "shift": (-0.5, 0),
                 "joint": "shoulder", "group": "arm"},
    "right_arm": {"mirror": "left_arm"},
    "left_forearm": {"text": "|\n|\n|", "parent": "left_arm", "joint": "elbow", "group": "forearm"},
    "right_forearm": {"mirror": "left_forearm"},
    "left_hand": {"text": "o", "parent": "left_forearm", "joint": "wrist", "group": "hand"},
    "right_hand": {"mirror": "left_hand"},
    "left_thigh": {"text": "|\n|\n|", "parent": "torso", "at": "bottom_left", "pin": "top", "shift": (0.5, 0),
                   "joint": "hip", "group": "thigh", "density": 10},
    "right_thigh": {"mirror": "left_thigh", "flip": False},
    "left_shin": {"text": "|\n|\n|", "parent": "left_thigh", "joint": "knee", "group": "shin",
                  "contact": True, "density": 10},
    "right_shin": {"mirror": "left_shin", "flip": False},
    "left_foot": {"text": "__", "parent": "left_shin", "at": "bottom_left", "pin": "top", "joint": "ankle",
                  "group": "foot", "contact": True, "density": 10},
    "right_foot": {"mirror": "left_foot", "flip": False},
}

CYCLES = {
    "walk": {
        "left_thigh": {"amp": -32}, "right_thigh": {"amp": 32},
        "left_shin": {"amp": 50, "shift": -math.pi / 2, "rectify": True},
        "right_shin": {"amp": 50, "shift": math.pi / 2, "rectify": True},
        "arm": {"amp": 35}, "forearm": {"amp": -12.5, "bias": -12.5},
    },
}


class HumanoidTests(unittest.TestCase):
    def make(self, parts=PARTS, gravity=-0.05, **config):
        _, sc = make_scene()
        sc.gravity = (0, gravity)
        sc.obj().create("#" * 200, -50, -30, dynamic=False)
        body = sc.obj().create(None, 20, -20, humanoid=dict(parts=parts, **config))
        return sc, body, body.humanoid

    def rects(self, parts):
        _, _, h = self.make(parts)
        return {name: h._nodes[name]["rect"] for name in h}

    def test_parts_come_from_the_given_graph(self):
        _, body, h = self.make({
            "core": "##",
            "cap": {"text": "O", "parent": "core", "at": "top", "style": {"fg": "red"}},
            "tail": {"text": "~", "parent": "core", "at": "right", "group": "extra"},
        })
        self.assertEqual(sorted(h), ["cap", "core", "tail"])
        self.assertEqual(body.transform.text, "##")
        self.assertEqual(h["cap"].transform.fg, "red")
        self.assertIs(h["core"], body)
        self.assertIs(h["extra"], h["tail"])
        self.assertIn("extra", h)

    def test_any_part_can_be_the_root(self):
        _, body, h = self.make({"leg": "|\n|", "foot": {"text": "__", "parent": "leg", "pin": "top_right"}})
        self.assertIs(h["leg"], body)
        self.assertEqual(len(h), 2)

    def test_anchors_place_and_pivot_parts_consistently(self):
        rects = self.rects({
            "base": "####\n####",
            "above": {"text": "o", "parent": "base", "at": "top"},
            "below": {"text": "|", "parent": "base"},
            "side": {"text": "-", "parent": "base", "at": "right"},
            "corner": {"text": "x", "parent": "base", "at": "top_left", "pin": "bottom_right"},
            "inset": {"text": "i", "parent": "base", "at": (0.25, 0.5), "pin": "center"},
            "nudged": {"text": "n", "parent": "base", "at": "bottom_left", "pin": "top_left", "shift": (1, 1)},
        })
        self.assertEqual(rects["above"], (2, -1, 1, 1))
        self.assertEqual(rects["below"], (2, 2, 1, 1))
        self.assertEqual(rects["side"], (4, 1, 1, 1))
        self.assertEqual(rects["corner"], (-1, -1, 1, 1))
        self.assertEqual(rects["inset"], (1, 1, 1, 1))
        self.assertEqual(rects["nudged"], (1, 3, 1, 1))

    def test_joint_sits_at_the_shared_point(self):
        _, _, h = self.make()
        for name in h:
            node = h._nodes[name]
            if node["parent"] is None:
                continue
            x, y, w, hh = node["rect"]
            fx, fy = node["pin"]
            self.assertEqual(node["point"], (x + fx * w, y + fy * hh))

    def test_mirror_reflects_layout_and_inherits_settings(self):
        _, _, h = self.make()
        torso = h._nodes["torso"]["rect"]
        for left, right in (("left_arm", "right_arm"), ("left_shin", "right_shin"), ("left_foot", "right_foot")):
            a, b = h._nodes[left]["rect"], h._nodes[right]["rect"]
            self.assertEqual(a[0] + a[2] + b[0], 2 * torso[0] + torso[2])
            self.assertEqual(a[1], b[1])
        self.assertEqual(h._nodes["right_forearm"]["parent"], "right_arm")
        self.assertEqual(h._nodes["right_foot"]["parent"], "right_shin")
        self.assertEqual(h["right_foot"].transform.text, "__")
        self.assertEqual(h["right_thigh"].physics.mass, h["left_thigh"].physics.mass)
        self.assertEqual(h._nodes["right_arm"]["groups"], ["right_arm", "arm"])

    def test_mirrored_joints_flip_only_when_asked(self):
        _, _, h = self.make()
        self.assertEqual(h._nodes["left_arm"]["limits"], (-170, 170))
        self.assertEqual(h._nodes["left_forearm"]["limits"], (-150, 0))
        self.assertEqual(h._nodes["right_forearm"]["limits"], (0, 150))
        self.assertEqual(h._nodes["left_shin"]["limits"], (0, 140))
        self.assertEqual(h._nodes["right_shin"]["limits"], (0, 140))

    def test_joint_overrides_follow_groups_and_names(self):
        _, _, h = self.make(joints={"forearm": {"range": (-90, 0)}, "left_forearm": {"range": (-45, 0)}})
        self.assertEqual(h._nodes["left_forearm"]["limits"], (-45, 0))
        self.assertEqual(h._nodes["right_forearm"]["limits"], (0, 90))

    def test_mirror_axis_can_be_another_part(self):
        _, _, h = self.make({
            "base": "#####",
            "mast": {"text": "|", "parent": "base", "at": "top"},
            "left": {"text": "<", "parent": "mast", "at": "left"},
            "right": {"mirror": "left"},
        }, axis="mast")
        mast = h._nodes["mast"]["rect"]
        left, right = h._nodes["left"]["rect"], h._nodes["right"]["rect"]
        self.assertEqual(left[0] + left[2] + right[0], 2 * mast[0] + mast[2])
        self.assertEqual(left[0] + left[2], mast[0])
        self.assertEqual(right[0], mast[0] + mast[2])

    def test_invalid_configuration_is_rejected(self):
        _, sc = make_scene()
        bad = [
            (True, TypeError), ({"parts": {}}, ValueError), ({"parts": {"a": "#", "b": "#"}}, ValueError),
            ({"parts": {"a": "#", "b": {"text": "#", "parent": "ghost"}}}, ValueError),
            ({"parts": {"a": {"text": "#", "parent": "b"}, "b": {"text": "#", "parent": "a"}}}, ValueError),
            ({"parts": {"a": "#", "b": {"mirror": "a"}}}, ValueError),
            ({"parts": {"a": "#", "b": {"mirror": "c", "parent": "a"}}}, ValueError),
            ({"parts": {"a": "#", "b": {"mirror": "b", "parent": "a"}}}, ValueError),
            ({"parts": {"a": "#", "b": {"text": "#", "parent": "a", "at": "nowhere"}}}, ValueError),
            ({"parts": {"a": "#", "b": {"text": "#", "parent": "a", "joint": "nope"}}}, KeyError),
            ({"parts": {"a": "#", "b": {"text": "#", "parent": "a", "flip": True}}}, TypeError),
            ({"parts": {"a": "#", "b": {"text": "#", "parent": "a", "wing": 1}}}, TypeError),
            ({"parts": {"a": 5}}, TypeError), ({"parts": {"a": "#"}, "nope": 1}, TypeError),
            ({"parts": {"a": "#"}, "poses": []}, TypeError), ({"parts": {"a": "#"}, "axis": "z"}, ValueError),
        ]
        for config, error in bad:
            with self.assertRaises(error, msg=repr(config)):
                sc.obj().create(None, 0, 0, humanoid=config)

    def test_stands_on_the_floor(self):
        sc, body, h = self.make()
        for _ in range(200):
            sc.tick()
        self.assertTrue(h.grounded)
        self.assertEqual(body.transform.rotation, 0)
        self.assertLess(abs(h["right_foot"].transform.y - (-29.5)), 0.6)
        self.assertGreater(body.transform.y, h["right_foot"].transform.y)

    def test_standing_figure_comes_to_rest_without_flicker(self):
        sc, _, h = self.make()
        for _ in range(500):
            sc.tick()
        low = {n: h[n].transform.y for n in h}
        high = dict(low)
        for _ in range(80):
            sc.tick()
            for n in h:
                y = h[n].transform.y
                low[n] = min(low[n], y)
                high[n] = max(high[n], y)
        self.assertLess(max(high[n] - low[n] for n in h), 0.02)

    def test_ragdoll_releases_every_joint_and_can_be_undone(self):
        sc, body, h = self.make()
        for _ in range(100):
            sc.tick()
        self.assertFalse(h.ragdolled)
        top, bottom = h.bounds[1], h.bounds[3]
        h.ragdoll()
        self.assertTrue(h.ragdolled)
        self.assertTrue(all(h.parts[n].physics.solid for n in h))
        h.pose({"arm": 90})
        self.assertEqual(h.angle("left_arm"), 0)
        for _ in range(300):
            sc.tick()
        self.assertLess(h.bounds[1] - h.bounds[3], (top - bottom) - 3)
        for name in h:
            node = h._nodes[name]
            if node["parent"] is not None:
                self.assertEqual(h[name].joint.kind, "hinge")
                ex, ey, _ = h[node["parent"]].joint.link(h[name]).error(False)
                self.assertLess(math.hypot(ex * sc.aspect, ey), 3)
        h.ragdoll(False)
        self.assertFalse(h.ragdolled)
        self.assertEqual([n for n in h if h.parts[n].physics.solid], ["left_foot", "right_foot"])
        h.pose({"arm": 40}, reset=True)
        self.assertEqual(h.angle("left_arm"), 40)
        self.assertEqual(h.angle("right_arm"), -40)

    def test_parts_snap_back_when_a_joint_is_stretched_far(self):
        sc, body, h = self.make(gravity=0)
        sc.tick()
        body.transform.x += 12
        body.transform.y += 6
        for _ in range(3):
            sc.tick()
        for name in h:
            node = h._nodes[name]
            if node["parent"] is not None:
                ex, ey, _ = h[node["parent"]].joint.link(h[name]).error(False)
                self.assertLess(math.hypot(ex * sc.aspect, ey), 2.5, name)

    def test_pose_swings_limbs_and_clamps_to_joint_limits(self):
        sc, _, h = self.make()
        for _ in range(100):
            sc.tick()
        h.pose({"arm": 90, "left_shin": -50})
        for _ in range(20):
            sc.tick()
        self.assertAlmostEqual(h["left_arm"].transform.rotation, 90, delta=1)
        self.assertAlmostEqual(h["right_arm"].transform.rotation, -90, delta=1)
        self.assertEqual(h.angle("left_shin"), 0)
        h.reset_pose()
        for _ in range(20):
            sc.tick()
        self.assertAlmostEqual(h["left_arm"].transform.rotation, 0, delta=1)

    def test_named_poses_come_from_the_configuration(self):
        sc, _, h = self.make(poses={"out": {"arm": 90}})
        for _ in range(100):
            sc.tick()
        h.apply_pose("out")
        for _ in range(20):
            sc.tick()
        self.assertAlmostEqual(h["left_arm"].transform.rotation, 90, delta=1)
        with self.assertRaises(KeyError):
            h.apply_pose("missing")
        with self.assertRaises(KeyError):
            h.pose({"nothing": 1}, strict=True)

    def test_cycles_sample_channels(self):
        _, _, h = self.make(cycles=CYCLES)
        sample = h.sample("walk", math.pi / 2)
        self.assertAlmostEqual(sample["left_thigh"], -32)
        self.assertAlmostEqual(sample["right_thigh"], 32)
        self.assertAlmostEqual(sample["left_shin"], 0)
        self.assertAlmostEqual(sample["right_shin"], 0)
        self.assertAlmostEqual(sample["forearm"], -25)
        self.assertAlmostEqual(h.sample("walk", math.pi / 2, scale=0.5)["arm"], 17.5)

    def test_walking_moves_the_figure(self):
        sc, body, h = self.make(cycles=CYCLES)
        for _ in range(100):
            sc.tick()
        start = body.transform.x
        for i in range(100):
            h.velocity = (0.1, None)
            h.animate("walk", i * 0.12)
            sc.tick()
        self.assertGreater(body.transform.x - start, 8)
        self.assertEqual(body.transform.rotation, 0)

    def test_detach_add_and_remove_parts(self):
        sc, _, h = self.make()
        seen = []
        h.onbreak(lambda name, part: seen.append(name))
        h.detach("left_forearm")
        self.assertEqual(seen, ["left_forearm"])
        self.assertEqual(h.remove_part("hand"), ["left_hand", "right_hand"])
        self.assertNotIn("hand", h)
        self.assertEqual(h.add_parts({
            "left_hand": {"text": "x", "parent": "left_forearm", "group": "hand"},
            "right_hand": {"mirror": "left_hand", "parent": "right_forearm"},
        }), ["left_hand", "right_hand"])
        self.assertIn("hand", h)
        self.assertEqual(h.add_part("cap", {"text": "^", "parent": "head", "at": "top"}), ["cap"])
        with self.assertRaises(ValueError):
            h.add_part("cap", "^")
        with self.assertRaises(ValueError):
            h.add_part("orphan", "?")
        with self.assertRaises(ValueError):
            h.set_text("head", "OO")
        with self.assertRaises(ValueError):
            h.remove_part("torso")

    def test_solid_parts_follow_contact_flags_or_settings(self):
        _, _, h = self.make()
        self.assertEqual([n for n in h if h.parts[n].physics.solid], ["left_foot", "right_foot"])
        _, _, h = self.make(solid=["shin"])
        self.assertEqual([n for n in h if h.parts[n].physics.solid], ["left_shin", "right_shin"])
        _, _, h = self.make(solid=True)
        self.assertTrue(all(h.parts[n].physics.solid for n in h))

    def test_discarding_the_root_removes_every_part(self):
        sc, body, h = self.make()
        before = len(sc.objs)
        body.discard()
        self.assertEqual(len(sc.objs), before - 14)
        self.assertEqual(len(sc.solids), 1)


if __name__ == "__main__":
    unittest.main()
