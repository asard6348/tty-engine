import os
import random
import unittest

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

from array import array

from ttyengine import scene as scene_mod
from ttyengine.components import shared
from ttyengine.sound import Mixer, Sound, Voice


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


if __name__ == "__main__":
    unittest.main()
