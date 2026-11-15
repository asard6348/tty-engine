import base64
import functools
import hashlib
import inspect
import os
import random
import struct
import unittest
import zlib

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

from array import array

from ttyengine import ansi, image_reader, input_handler
from ttyengine import scene as scene_mod
from ttyengine.components import shared
from ttyengine.sound import Mixer, Sound, Voice


JPEGS = {
    'color420': ('6d9d4390946f8a79c733dd87ec70d5e0', '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIfIiEmKzcvJik0KSEiMEExNDk7Pj4+JS5ESUM8SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozv/wAARCAATABoDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDh4dLOcBSAeevTmte10cEA7QBW7aaTkhTH6fStu00raFbAU99w4rmoSVUwwGaW6nMw6K+1isWcL8q5xu9q5m50RlupRK5aQO24qcAnPOK9Ylsytu/kRMzBTgDv14H6DiuUOnW7Es0U+Tyds2B+A2mt8PicLGUlCLlbta33tnVneZc0aac7b73/AEX6/IY+rX0WparEkwCWu3yhsU7c20rntz8yKefStfxtqV7pUVn9huZIftSMkuDnIAGMZ6H5jyMHp6DBRV0IRVGFlvH/ANtPLyalTeLw6cVZx10392/56nQ+Hrue60a4uJpMyxxIysAF58iN+3X5mJ/HHSvJ9X8Va1BrV9FHeYSO4kVQYkPAYgckc0UV6XClClL2ilFPboi8xpU543llFNcu1j//2Q=='),
    'color444': ('bf4eca9d6423ecb28cd315995e7420f8', '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCAATABoDAREAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDxCx8ONu2rGQDhiSeFyevTrx6+tebHEqV0npt/Xp5fqYZbmvLaSe/4+XXrY6zSfCqsgPlhVwBwPfoff/P12p0nNcr2/r8O/Rbb3Pv8uziUbc2uv9f1sdLY+EZgjvFah9qExpuChyAeDnI55+lEcopylyW1vvZu2u/W/TTqvM+0pZ7UpUpTpx5pqLajoru10rvRXfXVdzzPVfCEiapdrdTO84ncStG4CltxyQMcDNfdYfIqjpRdOKUbK17Xt0P5zzPPK0MbWjiJJ1FKXM1s5Xd306+S9EexaJ4Y3OsbW5PQ8jI6+/A4PevyPA4nnj723rbZf526/I+Qwea6Jx3X9f13O20bw2UWNwgjbqS4IA7/AE45r6/COCp+0k+WMdW+1t7v+tux9tgM1XxXvsv+G7/h2Nm70p47CY2NtLLIsbhVTjdweFI5znAyPUY6CvnMz40UajwmVtX5o/vLJqyu5NJ6O2lm7ppy6JM+3p5lOnhKtSacmoytFNqTstEnHVSfRrVNq2p5Q2gafIxkktL4Ox3MEvNq5PXAMZIHsSfqa9WWOz2o3N42euv2l+EZJfckuySPwtZ7k/XDyT8pxt8r0pO3a8pO27b1ILjxPrdt4j8VWsN4qw6aYhaL5EZ8vdpt1MeSuW/eRRtzn7uOmRUcMZThK+Hw9WpC8prXV62qwj3t8La/HfU6uHsswtbBYSrOPvTvfVq/76nDZOy92TWne++p1/x+1/WfDdro/wDYmpXFl/aUMkN1sbO5VUYxnOw/vG+ZcE8c/KuPZqU41MqqSkr2qxj6xlGaaa2a0Wjuk9VZ6n6N4WZVg8xlVeKpqXs1CUfVt3va117q0d1vpq7+hfDHVL/UfBuo6hd3Be6htoJUkVQhDfYbeYk7QM/vHc4ORzjpxX5vgMtwtHFU6cIJJzlH5c842+5L7r7nRxlSjgMLUlhrxcYTktXvCpUUd30UIprZpap3d/lDxt8SvGtn4z1y0t9ZCwwajcRxhrSFiFWRgMkoSeB1PNf1plvC2UTwdGToK7jHv2XmfmOX8OZdjMJSxNeDlOcYyk3KV22k2373V6n/2Q=='),
    'progressive': ('e4cff2d124597f40c597e17df3bff23c', '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA0JCgsKCA0LCgsODg0PEyAVExISEyccHhcgLikxMC4pLSwzOko+MzZGNywtQFdBRkxOUlNSMj5aYVpQYEpRUk//2wBDAQ4ODhMREyYVFSZPNS01T09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT0//wgARCAATABoDASIAAhEBAxEB/8QAGAABAQEBAQAAAAAAAAAAAAAABAAFBgL/xAAWAQEBAQAAAAAAAAAAAAAAAAADAQL/2gAMAwEAAhADEAAAAclK1ngAOiz9p5TVBvO09//EABoQAAMBAQEBAAAAAAAAAAAAAAECAwASIQT/2gAIAQEAAQUCCYTwnjP1Z5UxXzgbtg/1OyCLEzpegp//xAAdEQABBAIDAAAAAAAAAAAAAAABAAIDBBETIUHw/9oACAEDAQE/AYbCtT5A5VVo2M90pmgyYK//xAAcEQACAgIDAAAAAAAAAAAAAAABAgASBSERMXH/2gAIAQIBAT8BQ2iOg63EAqPJj0U86n//xAAgEAABAwMFAQAAAAAAAAAAAAABABExAhASAyFBUZHh/9oACAEBAAY/ArQi99lB9WoHiPCqcSzyiTPxVDLnpf/EACAQAAICAQMFAAAAAAAAAAAAAAABESExEEGBUWFxwfD/2gAIAQEAAT8h0Zu3gPuXNnY0YHg2yXIGsKRwxd6Jk4WvnI56iTngxVqJ1h1P/9oADAMBAAIAAwAAABCvrzz/xAAaEQADAQADAAAAAAAAAAAAAAAAARExQVHR/9oACAEDAQE/EIcki43vwZQ1qEqJqH//xAAaEQEAAwADAAAAAAAAAAAAAAABABFBMXHB/9oACAECAQE/EIFkD0qCqOfEqKMyf//EAB8QAQEAAgEEAwAAAAAAAAAAAAERACExQVFhcYGRsf/aAAgBAQABPxBrAg79YaDIZMtIaWXDEiVQ6W5ZBzEGA+cWDAwOvrFFpdsg/MMkaSOXab2H4zgm4PIHS8O2zf0ZTiOAG+28q5H2KqaF4z//2Q=='),
    'gray': ('9b78c78564218aac43baec571361bd49', '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAATABoBAREA/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oACAEBAAA/APOoNIOcBSAec56c/wA627TQwVB2gDA7e9a8GgSBWZIQcL8i5xu68VyF3oDLeTiaRmlEjBypwCc849q72y0XcwUxnt15FdFZ6PtCttCt33DAq/NYsltIbeJ3cK2FXjPXgH16DiuJOl2zks0NwGPJ2z4GfYFT/Oo5Nav4dV1qGOcCO02eSPLU7c2s0h7c/Minn09K3fH+q3+jw2H9n3UkH2tHjm2nOQAMYz90/MeRg9PQY6nwxe3F3oN1czSZmjijdXACnP2eKTt1+ZmPPrjpxXiWt+Mdet9f1GGO+AjjupUUGGMkAMQOSuTX/9k='),
}


def make_scene(gravity=(0, 0)):
    sc = scene_mod.Scene()
    sc.termx, sc.termy, sc.dimx, sc.dimy = 120, 40, 120, 40
    sc.camx, sc.camy = -60, 20
    sc.gravity = gravity
    return sc


def frame(sc):
    sc.tick(True)
    return sc.render()


class BroadphaseTests(unittest.TestCase):
    def test_near_matches_brute_force_while_objects_move(self):
        rng = random.Random(7)
        sc = make_scene()
        for _ in range(60):
            sc.obj().create(rng.choice(["O", "##\n##", "@@@"]), rng.randint(-50, 50), rng.randint(-15, 15), dynamic=False, solid=True)
        wall = "\n".join("#" * 90 for _ in range(12))
        sc.obj().create(wall, -45, 10, dynamic=False, solid=True)
        broad = sc._broad
        for step in range(5):
            for obj in rng.sample(list(sc.solids), 20):
                obj.transform.x += rng.randint(-9, 9)
                obj.transform.y += rng.randint(-5, 5)
            for _ in range(25):
                x0 = rng.randint(-60, 50)
                y0 = rng.randint(-20, 15)
                x1 = x0 + rng.randint(0, 25)
                y1 = y0 + rng.randint(0, 12)
                expected = []
                for obj in sc.solids:
                    box = obj.physics.bounds()
                    if box is not None and not (box[1] < x0 or box[0] > x1 or box[3] < y0 or box[2] > y1):
                        expected.append(obj)
                self.assertEqual(broad.near(x0, x1, y0, y1), expected)

    def test_new_and_removed_solids_are_tracked(self):
        sc = make_scene()
        a = sc.obj().create("#", 0, 0, dynamic=False, solid=True)
        self.assertEqual(sc._broad.near(-1, 1, -1, 1), [a])
        b = sc.obj().create("#", 1, 0, dynamic=False, solid=True)
        self.assertEqual(sc._broad.near(-1, 2, -1, 1), [a, b])
        sc.solids.remove(a)
        self.assertEqual(sc._broad.near(-1, 2, -1, 1), [b])


class MotionTests(unittest.TestCase):
    def test_fast_body_does_not_tunnel(self):
        sc = make_scene()
        wall = "\n".join("#" for _ in range(30))
        sc.obj().create(wall, 40, 15, dynamic=False, solid=True)
        ball = sc.obj().create("O", 0, 0, xvel=5000, bounciness=0.0)
        for _ in range(20):
            frame(sc)
        self.assertLess(ball.transform.x, 40)

    def test_huge_fast_body_stays_inside_walls(self):
        sc = make_scene()
        top = "#" * 100
        side = "\n".join("#" for _ in range(30))
        sc.obj().create(top, -50, 15, dynamic=False, solid=True)
        sc.obj().create(top, -50, -15, dynamic=False, solid=True)
        sc.obj().create(side, -50, 15, dynamic=False, solid=True)
        sc.obj().create(side, 50, 15, dynamic=False, solid=True)
        block = "\n".join("#" * 20 for _ in range(6))
        body = sc.obj().create(block, -10, 5, xvel=9000, yvel=4000, bounciness=0.8)
        for _ in range(40):
            frame(sc)
            self.assertTrue(-50 < body.transform.x < 50)
            self.assertTrue(-15 < body.transform.y < 15)

    def test_rotation_result_is_stable_after_cache(self):
        sc = make_scene()
        obj = sc.obj().create("###\n###", 0, 0)
        t = obj.transform
        t.rotation = 37
        first = (t.text, t.vx, t.vy)
        t.rotation = 90
        t.rotation = 37
        self.assertEqual((t.text, t.vx, t.vy), first)


class MaskedPenetrationTests(unittest.TestCase):
    def reference(self, mine, other, aspect):
        best = None
        for dx, dy, cost in ((1, 0, aspect), (-1, 0, aspect), (0, 1, 1.0), (0, -1, 1.0)):
            for k in range(1, 64):
                moved = {(x + dx * k, y + dy * k) for x, y in mine}
                if not moved & other:
                    score = k * cost - (0.01 if dy == 1 else 0)
                    if best is None or score < best[0]:
                        best = (score, dx, dy, k)
                    break
        return best

    def test_matches_set_based_search(self):
        rng = random.Random(3)
        for _ in range(200):
            mine = {(rng.randint(0, 9), rng.randint(0, 6)) for _ in range(rng.randint(1, 30))}
            other = {(rng.randint(-3, 12), rng.randint(-3, 9)) for _ in range(rng.randint(1, 40))}
            self.assertEqual(shared._mtv_cells(mine, other, 2.0), self.reference(mine, other, 2.0))


class MixerTests(unittest.TestCase):
    def build(self, speeds):
        rng = random.Random(5)
        mixer = Mixer(backend=lambda *a: None)
        sounds = [mixer.tone(rng.uniform(100, 1500), 0.5, wave, 0.9) for wave in ("sine", "square", "saw")]
        voices = []
        for i, speed in enumerate(speeds):
            voice = Voice(mixer, sounds[i % 3].at_rate(mixer.rate), rng.uniform(0.2, 2.5), rng.uniform(-1, 1), True, None, speed, None, None, None)
            voice._pos = rng.randint(0, 9000)
            mixer._voices.append(voice)
        return mixer, voices

    def scalar(self, mixer, voices, frames):
        left = [0] * frames
        right = [0] * frames
        for v in voices:
            gain = v._volume * mixer._volume * 256.0
            pan = max(-1.0, min(1.0, v._pan))
            gl = int(gain * (1.0 if pan <= 0 else 1.0 - pan))
            gr = int(gain * (1.0 if pan >= 0 else 1.0 + pan))
            total = v._sound.frames
            for n in range(frames):
                i = (v._pos + n) % total
                left[n] += (v._sound.left[i] * gl) >> 8
                right[n] += (v._sound.right[i] * gr) >> 8
        out = array("h", bytes(4 * frames))
        clip = lambda s: 32767 if s > 32767 else -32768 if s < -32768 else s
        out[0::2] = array("h", [clip(s) for s in left])
        out[1::2] = array("h", [clip(s) for s in right])
        return out.tobytes()

    def test_plain_voices_match_scalar_mix(self):
        mixer, voices = self.build([1.0] * 12)
        voices = list(mixer._voices)
        expected = self.scalar(mixer, voices, mixer.block)
        self.assertEqual(mixer._render(), expected)

    def test_overdriven_mix_clips_like_scalar(self):
        mixer, voices = self.build([1.0] * 30)
        voices = list(mixer._voices)
        expected = self.scalar(mixer, voices, mixer.block)
        self.assertEqual(mixer._render(), expected)


def _png(rows, ctype, bpp, kind, palette=None):
    width = len(rows[0]) // bpp
    raw = bytearray()
    prev = bytes(len(rows[0]))
    for y, row in enumerate(rows):
        row = bytes(row)
        ft = kind if kind < 5 else y % 5
        raw.append(ft)
        for i in range(len(row)):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if ft == 0:
                p = 0
            elif ft == 1:
                p = a
            elif ft == 2:
                p = b
            elif ft == 3:
                p = (a + b) >> 1
            else:
                est = a + b - c
                pa, pb, pc = abs(est - a), abs(est - b), abs(est - c)
                p = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
            raw.append((row[i] - p) & 255)
        prev = row

    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data) & 0xffffffff)

    out = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, len(rows), 8, ctype, 0, 0, 0))
    if palette:
        out += chunk(b'PLTE', palette)
    return out + chunk(b'IDAT', zlib.compress(bytes(raw))) + chunk(b'IEND', b'')


class ImageDecodeTests(unittest.TestCase):
    def rows(self, width, height, bpp, seed):
        rng = random.Random(seed)
        smooth = [[(x * 3 + y * 5 + k * 40) & 255 for x in range(width * bpp)] for y in range(height) for k in (0,)]
        noisy = [[rng.randrange(256) for _ in range(width * bpp)] for _ in range(height)]
        return [smooth[y] if y % 2 else noisy[y] for y in range(height)]

    def test_every_png_filter_round_trips(self):
        for ctype, bpp in ((2, 3), (6, 4), (0, 1), (4, 2)):
            for kind in range(6):
                for width in (1, 2, 7, 33):
                    rows = self.rows(width, 9, bpp, ctype * 100 + kind * 10 + width)
                    w, h, data = image_reader.decode(_png(rows, ctype, bpp, kind))
                    self.assertEqual((w, h), (width, 9))
                    for y, row in enumerate(rows):
                        got = bytes(data[y * w * 4:(y + 1) * w * 4])
                        if ctype == 6:
                            want = bytes(row)
                        elif ctype == 2:
                            want = b''.join(bytes(row[i:i + 3]) + b'\xff' for i in range(0, len(row), 3))
                        elif ctype == 0:
                            want = b''.join(bytes((v, v, v, 255)) for v in row)
                        else:
                            want = b''.join(bytes((row[i], row[i], row[i], row[i + 1])) for i in range(0, len(row), 2))
                        self.assertEqual(got, want, (ctype, kind, width, y))

    def test_palette_png_maps_every_index(self):
        palette = bytes(v for i in range(40) for v in (i * 6 % 256, i * 11 % 256, i * 17 % 256))
        rows = [[(x * 7 + y) % 256 for x in range(30)] for y in range(6)]
        w, h, data = image_reader.decode(_png(rows, 3, 1, 5, palette))
        for y, row in enumerate(rows):
            for x, index in enumerate(row):
                got = tuple(data[(y * w + x) * 4:(y * w + x) * 4 + 4])
                want = tuple(palette[index * 3:index * 3 + 3]) + (255,) if index < 40 else (0, 0, 0, 255)
                self.assertEqual(got, want)

    def test_jpeg_decoding_is_unchanged(self):
        for name, (digest, encoded) in JPEGS.items():
            w, h, data = image_reader.decode(base64.b64decode(encoded))
            self.assertEqual((w, h), (26, 19), name)
            self.assertEqual(hashlib.md5(bytes(data)).hexdigest(), digest, name)


class ColorCollapseTests(unittest.TestCase):
    def test_keeps_only_the_last_color_of_each_kind(self):
        c = ansi.CSI
        style = c + '48;2;0;0;0m' + c + '38;2;1;2;3m' + c + '1m' + c + '38;2;4;5;6m' + c + '48;2;9;9;9m'
        self.assertEqual(ansi.collapse_color(style), c + '1m' + c + '38;2;4;5;6m' + c + '48;2;9;9;9m')

    def test_mixed_color_forms_collapse_by_kind(self):
        c = ansi.CSI
        self.assertEqual(ansi.collapse_color(c + '31m' + c + '38;5;9m' + c + '4m' + c + '92m'), c + '4m' + c + '92m')

    def test_other_styles_are_untouched(self):
        c = ansi.CSI
        for style in ('', c + '31m', c + '1m' + c + '31m', c + '1m' + c + '4m' + c + '3m', 'text' + c + '31m' + c + '32m' + c + '33m',
                      c + '1;31m' + c + '32m' + c + '4m'):
            self.assertEqual(ansi.collapse_color(style), style)

    def test_stacked_colors_render_the_same_screen_with_less_output(self):
        sc = make_scene()
        c = ansi.CSI
        row = ''.join(c + '38;2;%d;10;10m%s' % (i * 9, 'ab'[i % 2]) for i in range(20))
        sc.obj().create(row + c + '0m', -10, 0)
        frame_text = sc.render(full=True)
        self.assertEqual(frame_text.count('38;2;'), 20)
        for i in range(20):
            self.assertIn(c + '38;2;%d;10;10m%s' % (i * 9, 'ab'[i % 2]), frame_text)


class CallbackShapeTests(unittest.TestCase):
    def callbacks(self):
        class Holder:
            def method(self, a, b):
                pass

            def __call__(self, a):
                pass

        class Unhashable:
            __hash__ = None

            def __call__(self, a, b, c):
                pass

        def plain(a, b=1, *rest, key=None, **extra):
            pass

        return [plain, lambda: None, lambda a: a, Holder().method, Holder(), functools.partial(plain, 1), Unhashable(), len]

    def test_argument_counts_match_inspect_and_stay_stable(self):
        for cb in self.callbacks():
            expected = len(inspect.signature(cb).parameters)
            for _ in range(3):
                self.assertEqual(shared._argslen(cb), expected)
                self.assertEqual(scene_mod._argslen(cb), expected)

    def test_input_shapes_match_inspect(self):
        for cb in self.callbacks():
            params = list(inspect.signature(cb).parameters.values())
            var = any(p.kind == p.VAR_POSITIONAL for p in params)
            count = sum(1 for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
            for _ in range(2):
                self.assertEqual(input_handler._accepts_arg(cb), var or count >= 1)
                self.assertEqual(input_handler._positional_count(cb), None if var else count)


class LightCullTests(unittest.TestCase):
    def build(self, lx):
        sc = make_scene()
        sc.ambient = 0.4
        sc.obj().create("\n".join("#" * 12 for _ in range(4)), -5, 2, dynamic=False)
        sc.obj().create("*", lx, 0, dynamic=False, light={"radius": 8, "color": "yellow"})
        return sc

    def test_far_light_matches_scene_without_it(self):
        far = self.build(300).render(full=True)
        sc = make_scene()
        sc.ambient = 0.4
        sc.obj().create("\n".join("#" * 12 for _ in range(4)), -5, 2, dynamic=False)
        self.assertEqual(far, sc.render(full=True))

    def test_near_light_changes_the_object(self):
        self.assertNotEqual(self.build(0).render(full=True), self.build(300).render(full=True))


if __name__ == "__main__":
    unittest.main()
