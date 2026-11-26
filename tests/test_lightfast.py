import os
import random
import unittest

os.environ.setdefault("COLUMNS", "160")
os.environ.setdefault("LINES", "50")

from ttyengine import scene as scene_mod


def make_scene(seed):
    rng = random.Random(seed)
    sc = scene_mod.Scene()
    sc.termx, sc.termy, sc.dimx, sc.dimy = 160, 50, 160, 50
    objs = []
    for _ in range(rng.randint(5, 90)):
        kw = {"dynamic": False, "solid": rng.random() < 0.9}
        if rng.random() < 0.1:
            kw["phantom"] = True
        objs.append(sc.obj().create(rng.choice(["#", "##", "##\n##", "@@@"]), rng.randint(-70, 70), rng.randint(-22, 22), **kw))
    return sc, objs, rng


class CasterTests(unittest.TestCase):
    def test_fast_casters_match_the_scan(self):
        for seed in range(25):
            sc, objs, rng = make_scene(seed)
            if seed % 5 == 0:
                objs[0].transform.shadow = ["physics", "visual", "hitbox"][seed % 3]
            lights = [
                sc.obj().create("*", rng.randint(-60, 60), rng.randint(-20, 20), dynamic=False,
                                light={"radius": rng.choice([3, 8, 14, 24]), "shadows": True})
                for _ in range(3)
            ]
            for step in range(5):
                for o in rng.sample(objs, min(8, len(objs))):
                    o.transform.x = rng.randint(-70, 70)
                    o.transform.y = rng.randint(-22, 22)
                if step == 3:
                    sc.obj().create("#", 0, 0, dynamic=False, solid=True)
                for lo in lights:
                    lt = lo.light
                    lt._origin = lt.origin()
                    fast = [(id(o), id(t)) for o, t in lt._casters()]
                    scan = [(id(o), id(t)) for o, t in lt._casters_scan()]
                    self.assertEqual(fast, scan)


class LightKeyTests(unittest.TestCase):
    def test_cached_key_matches_the_direct_computation(self):
        for seed in range(15):
            sc, objs, rng = make_scene(seed)
            lights = []
            for _ in range(4):
                cfg = {"radius": rng.choice([4, 9, 14]), "shadows": rng.random() < 0.5}
                if rng.random() < 0.4:
                    cfg["affect"] = "solid"
                lights.append(sc.obj().create("*", rng.randint(-50, 50), rng.randint(-15, 15), dynamic=False, light=cfg))
            for step in range(12):
                action = rng.randint(0, 4)
                lt = rng.choice(lights).light
                if lt is None:
                    continue
                if action == 0:
                    lt.on = not lt.on
                elif action == 1:
                    lt.affect = rng.choice([None, "solid"])
                elif action == 2:
                    lights.append(sc.obj().create("*", rng.randint(-50, 50), 0, dynamic=False, light={"radius": 6}))
                elif action == 3 and len(lights) > 1:
                    victim = lights.pop(rng.randrange(len(lights)))
                    victim.discard()
                else:
                    lt.radius = rng.choice([4, 9, 14])
                for o in rng.sample(objs, min(10, len(objs))):
                    expected = tuple((id(l), l._version) for l in sc.lights if l.on and l._affects(o))
                    self.assertEqual(o.transform._lights_key(), expected)


if __name__ == "__main__":
    unittest.main()
