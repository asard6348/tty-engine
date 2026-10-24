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


class VsyncTests(unittest.TestCase):
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
        comp = compositor.Compositor(vsync=True, refresh=50)
        comp.vblank()
        stamps = []
        for _ in range(6):
            time.sleep(0.003)
            comp.vblank()
            stamps.append(time.perf_counter())
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        for gap in gaps:
            self.assertAlmostEqual(gap, 0.02, delta=0.006)

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


if __name__ == "__main__":
    unittest.main()
