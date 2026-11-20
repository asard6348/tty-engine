import hashlib
import math
import os
import random
import re
import threading
import unittest

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

from ttyengine import ansi
from ttyengine import scene as scene_mod
from ttyengine.compositor import Compositor
from ttyengine.components import shared
import sys
transform_mod = sys.modules['ttyengine.components.transform']


def make_scene(gravity=(0, 0)):
    sc = scene_mod.Scene()
    sc.termx, sc.termy, sc.dimx, sc.dimy = 60, 20, 60, 20
    sc.camx, sc.camy = -30, 10
    sc.gravity = gravity
    return sc


def reference_gradient(pixels, center, sign, aspect):
    reach = shared._REACH
    cx, cy = center
    window = []
    total = 0
    for x in range(math.ceil(cx - reach / aspect), math.floor(cx + reach / aspect) + 1):
        for y in range(math.ceil(cy - reach), math.floor(cy + reach) + 1):
            if math.hypot((x - cx) * aspect, y - cy) > reach:
                continue
            total += 1
            if (x, y) in pixels:
                window.append((x, y))
    sx = sy = 0.0
    for x, y in window:
        sx += (x - cx) * aspect
        sy += y - cy
    length = math.hypot(sx, sy)
    if not window or length < 1e-9:
        return None
    gx, gy = sign * sx / length, sign * sy / length
    edge = [p for p in window if any((p[0] + a, p[1] + b) not in pixels for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
    if len(edge) >= 3:
        mx = sum(p[0] for p in edge) * aspect / len(edge)
        my = sum(p[1] for p in edge) / len(edge)
        sxx = sum((p[0] * aspect - mx) ** 2 for p in edge)
        syy = sum((p[1] - my) ** 2 for p in edge)
        sxy = sum((p[0] * aspect - mx) * (p[1] - my) for p in edge)
        half = math.hypot((sxx - syy) / 2, sxy)
        major = (sxx + syy) / 2 + half
        minor = (sxx + syy) / 2 - half
        if major > 3 * max(minor, 1e-9):
            angle = 0.5 * math.atan2(2 * sxy, sxx - syy)
            nx, ny = -math.sin(angle), math.cos(angle)
            if nx * gx + ny * gy < 0:
                nx, ny = -nx, -ny
            gx, gy = nx, ny
    return gx, gy, len(window) / total


class NormalFitTests(unittest.TestCase):
    def shapes(self, rng):
        for _ in range(120):
            kind = rng.randint(0, 3)
            if kind == 0:
                w, h = rng.randint(1, 30), rng.randint(1, 10)
                x0, y0 = rng.randint(-40, 40), rng.randint(-15, 15)
                yield {(x, y) for x in range(x0, x0 + w) for y in range(y0, y0 + h)}
            elif kind == 1:
                yield {(rng.randint(0, 25), rng.randint(0, 10)) for _ in range(rng.randint(4, 120))}
            elif kind == 2:
                a = math.radians(rng.uniform(0, 360))
                yield {(round(i * 0.5 * math.cos(a)) + rng.randint(-1, 1), round(i * 0.5 * math.sin(a))) for i in range(rng.randint(4, 60))}
            else:
                r = rng.randint(1, 8)
                yield {(x, y) for x in range(-2 * r, 2 * r + 1) for y in range(-r, r + 1) if math.hypot(x * 0.5, y) <= r}

    def test_agrees_with_cell_by_cell_fit(self):
        rng = random.Random(7)
        cases = differing = 0
        for pixels in self.shapes(rng):
            cells = list(pixels)
            for _ in range(40):
                cell = rng.choice(cells)
                center = (cell[0] + rng.choice([0, 0.5, -0.5]), cell[1] + rng.choice([0, 0.5, -0.5]))
                aspect = rng.choice([0.5, 0.5, 0.45, 0.35, 0.25, 0.7, 1.0])
                sign = rng.choice([1, -1])
                want = reference_gradient(pixels, center, sign, aspect)
                got = shared._gradient_cells(pixels, center, sign, aspect)
                cases += 1
                if (want is None) != (got is None) or (want is not None and max(abs(a - b) for a, b in zip(want, got)) > 1e-9):
                    differing += 1
        self.assertGreater(cases, 4000)
        self.assertLessEqual(differing, cases // 500)

    def test_cached_result_is_stable(self):
        pixels = {(x, y) for x in range(10) for y in range(4)}
        first = shared._gradient_cells(pixels, (4.5, 3.5), 1, 0.5)
        second = shared._gradient_cells(pixels, (4.5, 3.5), 1, 0.5)
        self.assertEqual(first, second)
        shifted = {(x + 100, y - 7) for x, y in pixels}
        moved = shared._gradient_cells(shifted, (104.5, -3.5), 1, 0.5)
        self.assertEqual(first, moved)


class ColorStepTests(unittest.TestCase):
    def state_after(self, text, state):
        fg, bg = state
        for match in re.finditer(r'\x1b\[([0-9;]*)m', text):
            params = match.group(1).split(';')
            i = 0
            while i < len(params):
                p = params[i]
                if p in ('0', ''):
                    fg = bg = None
                elif p == '39':
                    fg = None
                elif p == '49':
                    bg = None
                elif p in ('38', '48'):
                    if params[i + 1] == '2':
                        value = ';'.join(params[i:i + 5])
                        i += 4
                    else:
                        value = ';'.join(params[i:i + 3])
                        i += 2
                    if p == '38':
                        fg = value
                    else:
                        bg = value
                elif 30 <= int(p) <= 37 or 90 <= int(p) <= 97:
                    fg = p
                elif 40 <= int(p) <= 47 or 100 <= int(p) <= 107:
                    bg = p
                i += 1
        return fg, bg

    def test_steps_reach_the_same_colors_as_full_emission(self):
        rng = random.Random(3)
        comp = Compositor()
        pool = ['', ansi.fg(10, 20, 30), ansi.bg(1, 2, 3), ansi.bg(1, 2, 3) + ansi.fg(200, 100, 50),
                ansi.fg(10, 20, 30) + ansi.bg(9, 9, 9), '\x1b[31m', '\x1b[41m\x1b[32m', ansi.bg(0, 0, 0)]
        for plain in (False, True):
            for _ in range(400):
                old, new = rng.choice(pool), rng.choice(pool)
                full = self.state_after(comp.emit(new, plain), (None, None))
                before = self.state_after(comp.emit(old, plain), (None, None))
                stepped = self.state_after(comp.step(old, new, plain), before)
                self.assertEqual(full, stepped)

    def test_other_attributes_fall_back_to_full_emission(self):
        comp = Compositor()
        bold = '\x1b[1m' + ansi.fg(1, 2, 3)
        self.assertEqual(comp.step(ansi.fg(5, 5, 5), bold, False), comp.emit(bold, False))
        self.assertEqual(comp.step(bold, ansi.fg(5, 5, 5), False), comp.emit(ansi.fg(5, 5, 5), False))

    def test_color_step_is_never_longer_than_full_emission(self):
        comp = Compositor()
        for old in ('', ansi.fg(1, 2, 3), ansi.bg(4, 5, 6)):
            for new in ('', ansi.fg(1, 2, 3) + ansi.bg(4, 5, 6), ansi.bg(7, 8, 9)):
                self.assertLessEqual(len(comp.step(old, new, False)), len(comp.emit(new, False)))


class TrackingTests(unittest.TestCase):
    def test_object_list_counts_every_mutation(self):
        sc = make_scene()
        objs = sc.objs
        marks = [objs.rev]
        a = sc.obj().create('a', 0, 0)
        b = sc.obj().create('b', 1, 0)
        marks.append(objs.rev)
        objs.remove(b)
        marks.append(objs.rev)
        objs.insert(0, b)
        marks.append(objs.rev)
        objs.sort(key=id)
        marks.append(objs.rev)
        objs.reverse()
        marks.append(objs.rev)
        objs.pop()
        marks.append(objs.rev)
        objs.extend([a])
        marks.append(objs.rev)
        objs[0] = a
        marks.append(objs.rev)
        del objs[0]
        marks.append(objs.rev)
        objs.clear()
        marks.append(objs.rev)
        self.assertEqual(marks, sorted(set(marks)))

    def test_component_changes_bump_the_version(self):
        sc = make_scene()
        o = sc.obj().create('a', 0, 0, dynamic=False, solid=False)
        before = scene_mod._versions[0]
        o.add('light', radius=5)
        self.assertGreater(scene_mod._versions[0], before)
        before = scene_mod._versions[0]
        o.discard()
        self.assertGreater(scene_mod._versions[0], before)

    def test_discard_during_tick_stops_the_discarded_object_ticking(self):
        sc = make_scene()
        a = sc.obj().create('a', 0, 0, dynamic=False, solid=False)
        b = sc.obj().create('b', 3, 0, dynamic=False, solid=False)
        fired = []
        a.transform.fade(alpha=0.5, time=0.001, callback=lambda: (fired.append('a'), b.discard()))
        b.transform.fade(alpha=0.5, time=0.001, callback=lambda: fired.append('b'))
        for _ in range(3):
            sc.tick(True)
        self.assertEqual(fired, ['a'])
        self.assertNotIn(b, sc.objs)

    def test_objects_created_during_a_tick_join_the_next_one(self):
        sc = make_scene()
        made = []
        a = sc.obj().create('a', 0, 0, dynamic=False, solid=False)
        a.transform.fade(alpha=0.5, time=0.001, callback=lambda: made.append(sc.obj().create('n', 5, 5, dynamic=False, solid=False)))
        sc.tick(True)
        sc.tick(True)
        self.assertEqual(len(made), 1)
        self.assertIn(made[0], sc.objs)
        self.assertIn(made[0].transform, sc._roster()[5])


class CacheInvariantTests(unittest.TestCase):
    def fresh_front(self, sc):
        comp = Compositor()
        comp.compose([sc], [sc], (0, 0, sc.termx, sc.termy), (sc.termx, sc.termy), None, True)
        return comp.front

    def test_incremental_rendering_matches_a_fresh_compositor(self):
        for seed in (11, 12, 13):
            self.run_program(seed)

    def run_program(self, seed):
        rng = random.Random(seed)
        sc = make_scene()
        objs = []
        texts = ['@', '##\n##', '<=>', 'o', '[==]\n[==]', 'ab\ncd\nef', ' x \nxxx']
        colors = ['red', 'cyan', (200, 100, 50), None]

        def make():
            kw = dict(dynamic=False, solid=rng.random() < 0.3, z=rng.randint(0, 4))
            color = rng.choice(colors)
            if color is not None:
                kw['fg'] = color
            if rng.random() < 0.15:
                kw['light'] = {'radius': rng.randint(5, 12), 'color': (255, 220, 160), 'glow': rng.random() < 0.5}
            objs.append(sc.obj().create(rng.choice(texts), rng.randint(-8, 8), rng.randint(-4, 4), **kw))

        for _ in range(8):
            make()
        for step in range(160):
            for _ in range(rng.randint(0, 3)):
                k = rng.randint(0, 12)
                o = rng.choice(objs) if objs else None
                if k <= 1 or o is None:
                    make()
                elif k == 2:
                    o.transform.x = o.transform.x + rng.uniform(-3, 3)
                elif k == 3:
                    o.transform.rotation = rng.uniform(0, 360)
                elif k == 4:
                    o.transform.rtext = rng.choice(texts)
                elif k == 5:
                    o.transform.show = not o.transform.show
                elif k == 6:
                    o.transform.z = rng.randint(-2, 6)
                elif k == 7:
                    o.transform.fg = rng.choice(colors)
                elif k == 8 and len(objs) > 2:
                    o.discard()
                    objs.remove(o)
                elif k == 9:
                    sc.ambient = rng.choice([1, 0.4, 0.7])
                elif k == 10:
                    sc.bgcolor = rng.choice([(0, 0, 0), (30, 0, 40)])
                elif k == 11:
                    sc.camx = sc.camx + rng.choice([-1, 0, 1])
                else:
                    o.transform.alpha = rng.choice([None, 0.4, 0.8])
            sc.tick(True)
            sc.render()
            incremental = sc.compositor.front
            self.assertEqual(incremental, self.fresh_front(sc), 'seed %d step %d' % (seed, step))


class RotationMemoTests(unittest.TestCase):
    def test_equal_shapes_share_results_across_objects(self):
        sc = make_scene()
        a = sc.obj().create('##\n##', 0, 0, dynamic=False, solid=False)
        b = sc.obj().create('##\n##', 10, 0, dynamic=False, solid=False)
        a.transform.rotation = 33.3
        b.transform.rotation = 33.3
        self.assertEqual(a.transform.vtext, b.transform.vtext)
        self.assertEqual(a.transform._ptext, b.transform._ptext)
        self.assertEqual(a.transform.worldcells(), {(x - 10, y) for x, y in b.transform.worldcells()})

    def test_memory_stays_inside_the_budget(self):
        sc = make_scene()
        o = sc.obj().create('\n'.join(['#' * 20] * 6), 0, 0, dynamic=False, solid=False)
        saved = transform_mod._ROTATION_BUDGET
        transform_mod._ROTATION_BUDGET = 4000
        try:
            for angle in range(0, 360, 3):
                o.transform.rotation = angle
                self.assertLessEqual(transform_mod._rotation_cost[0], 4000)
        finally:
            transform_mod._ROTATION_BUDGET = saved

class RotationRasterTests(unittest.TestCase):
    @staticmethod
    def fingerprints():
        rng = random.Random(4242)
        out = []
        texts = []
        for _ in range(36):
            k = rng.randint(0, 6)
            w, h = rng.randint(2, 22), rng.randint(2, 9)
            if k == 0:
                texts.append("\n".join(["#" * w] * h))
            elif k == 1:
                texts.append("\n".join("".join(rng.choice("#@ .") for _ in range(w)) for _ in range(h)).replace("\n ", "\n#"))
            elif k == 2:
                texts.append("\n".join("#" * (i + 1) for i in range(h)))
            elif k == 3:
                texts.append("\n".join([" " * i + "##" for i in range(h)]))
            elif k == 4:
                texts.append("\n".join(["#" * w] + ["#" + " " * max(0, w - 2) + "#"] * max(0, h - 2) + ["#" * w]))
            elif k == 5:
                texts.append("\n".join(" " * rng.randint(0, 9) + "".join(rng.choice("xyz") for _ in range(rng.randint(1, 8))) for _ in range(h)))
            else:
                texts.append("#" * w)
        for text in texts:
            if not text.strip():
                continue
            sc = make_scene()
            o = sc.obj().create(text, 0, 0, dynamic=False, solid=False)
            t = o.transform
            t.aspect = rng.choice([0.5, 0.5, 0.45, 1.0, 0.7])
            if rng.random() < 0.3:
                t.flip = rng.uniform(0, 180)
            for _ in range(2):
                t.rotation = rng.uniform(-400, 400)
                record = [t.vtext, t._text, t._ptext, t.vx, t.vy, repr(t._rotmap)]
                record.append(repr(sorted((repr(a), repr(b)) for a, b in t._rotsrc.items())))
                record.append(repr(t._rotcells))
                out.append(hashlib.md5(repr(record).encode()).hexdigest()[:12])
        return out

    ORIGINAL = ['eb0e477e6926', 'e5a76a87f380', '8dac4af66411', 'af9daaba3768', '69161f214f38', 'afabdec219c5', 'e8098e42971f', '5dd17febfee4', 'eb631a133733', '11d8ee9e7642', 'e655fe1f73da', 'a7c08ea6d350', '65221fe3a4ec', 'b0cb10ce5feb', '85e213bb2b7b', '4c3c816cd1ad', '96735f47724b', '1545c8d4b3d1', 'f1f1a11f0b81', '5fde65bd3c2f', '0f410b018fd7', '1291b8f1775c', '322aec372fd5', '4300d46ae9ac', 'ffadc79c8090', '99ce2c658945', 'e331e00755a7', '88368537d364', '063da2975a88', '363b80fa5afe', '11890687b98b', '24320d72f90b', 'cf51f6e588ec', 'a170bb955918', '0f1cc730097b', 'deeb055a5165', '7a89cd743bbd', '4b076201a07e', '5ac7cad2b356', 'f7dd9d84db41', 'd2a13512bc75', '169dbdd724df', 'aed0c1441533', 'a2eed47ace03', 'e2b14c6ed413', 'ac9f7fbe5fff', '4179b63e3b71', '40a40f4c7bce', '9a490528f95c', '55788faa7f61', 'aef35e72e58e', '5deec36d864d', '5608e288dde8', '460f45577ea8', '9f468d6ecee3', 'cd0cb99ec7ab', '6adc24aa817d', '2c519daae3e3', '955ca61e0176', '84ebe3c31dea', 'dd5d9edd72b9', 'a859adde5ba9', '4cc63ce8ddcc', '1c436cf2bf40', '5f1106daf488', '6a45de74f61c', '5a9cf48452bc', '7fd1d203513a', '36b0abceef3a', 'a320bbfd35f8', 'cb81b849001c', '17078fc1654a']
    CURRENT = ['eb0e477e6926', 'e5a76a87f380', '992bedcb2feb', 'af9daaba3768', '69161f214f38', 'afabdec219c5', 'e8098e42971f', '711657edaa4b', 'eb631a133733', '11d8ee9e7642', 'e655fe1f73da', 'a7c08ea6d350', '65221fe3a4ec', 'b0cb10ce5feb', '85e213bb2b7b', '4c3c816cd1ad', '96735f47724b', '1545c8d4b3d1', 'f1f1a11f0b81', '5fde65bd3c2f', '0f410b018fd7', '1291b8f1775c', '322aec372fd5', '4300d46ae9ac', 'ffadc79c8090', '99ce2c658945', 'e331e00755a7', '88368537d364', '063da2975a88', '363b80fa5afe', '11890687b98b', '24320d72f90b', 'cf51f6e588ec', 'a170bb955918', '0f1cc730097b', 'deeb055a5165', '7a89cd743bbd', '4b076201a07e', '5ac7cad2b356', 'f7dd9d84db41', 'd2a13512bc75', '169dbdd724df', 'aed0c1441533', 'a2eed47ace03', 'e2b14c6ed413', 'ac9f7fbe5fff', '4179b63e3b71', '40a40f4c7bce', '9a490528f95c', '55788faa7f61', 'aef35e72e58e', '5deec36d864d', '5608e288dde8', '460f45577ea8', '9f468d6ecee3', 'cd0cb99ec7ab', '6adc24aa817d', '2c519daae3e3', '955ca61e0176', '84ebe3c31dea', 'dd5d9edd72b9', 'a859adde5ba9', '4cc63ce8ddcc', '1c436cf2bf40', '5f1106daf488', '6a45de74f61c', '5a9cf48452bc', '7fd1d203513a', '36b0abceef3a', 'a320bbfd35f8', 'cb81b849001c', '17078fc1654a']
    CHANGED = [2, 7]

    def test_rasterization_is_stable(self):
        self.assertEqual(self.fingerprints(), self.CURRENT)

    def test_only_far_displaced_glyphs_differ_from_the_original_algorithm(self):
        same = [i for i in range(len(self.ORIGINAL)) if self.ORIGINAL[i] == self.CURRENT[i]]
        self.assertEqual(sorted(set(range(len(self.ORIGINAL))) - set(same)), self.CHANGED)
        self.assertGreater(len(same), len(self.ORIGINAL) * 0.9)

    @staticmethod
    def displacement(transform, rotation):
        transform.rotation = rotation
        m = transform._rotmap
        aspect = transform.aspect
        a = math.radians(transform.rotation)
        c, s = math.cos(a), math.sin(a)
        worst = 0.0
        for (ci, ri), cells in transform._rotsrc.items():
            u, v = (ci - m[0]) * aspect, ri - m[1]
            fx = m[0] + (u * c - v * s) / aspect
            fy = m[1] + (u * s + v * c)
            for g in cells:
                worst = max(worst, math.hypot((g[0] - fx) * aspect, g[1] - fy))
        return worst

    def test_dense_images_never_scatter_glyphs(self):
        text = "\n".join("".join("#@%&"[(x * 7 + y * 3) % 4] for x in range(44)) for y in range(20))
        for aspect in (0.3, 0.5, 1.0):
            sc = make_scene()
            o = sc.obj().create(text, 0, 0, dynamic=False, solid=False)
            o.transform.aspect = aspect
            for k in range(0, 360, 5):
                self.assertLess(self.displacement(o.transform, k + 0.7), 2.5, 'aspect %s angle %s' % (aspect, k))

    def test_the_relocation_limit_is_the_documented_constant(self):
        self.assertEqual(sys.modules['ttyengine.components.transform']._SHIFT, 1.5)

    def test_coloured_images_keep_every_glyph_near_its_place(self):
        rng = random.Random(5)
        chars = " .:-=+*#%@\u2591\u2592\u2593\u2588\u2580\u2584"
        rows = []
        for _ in range(20):
            rows.append("".join("\x1b[38;2;%d;%d;%dm%s" % (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255), rng.choice(chars[1:])) for _ in range(40)) + "\x1b[0m")
        sc = make_scene()
        o = sc.obj().create("\n".join(rows), 0, 0, dynamic=False, solid=False)
        for k in range(1, 360, 4):
            self.assertLess(self.displacement(o.transform, k + 0.3), 2.5)

    def test_solid_blocks_keep_their_footprint_while_turning(self):
        for w, h in ((24, 8), (14, 6), (10, 10)):
            sc = make_scene()
            o = sc.obj().create("\n".join(["#" * w] * h), 0, 0, dynamic=False, solid=False)
            for k in range(0, 3600, 25):
                o.transform.rotation = k / 10.0 + 0.037
                self.assertGreaterEqual(len(o.transform._rotcells), w * h - 3)

    def test_sparse_text_keeps_every_glyph(self):
        sc = make_scene()
        o = sc.obj().create("Hello, World!\nrotating text", 0, 0, dynamic=False, solid=False)
        glyphs = {(x, y) for y, row in enumerate("Hello, World!\nrotating text".split("\n")) for x, ch in enumerate(row) if ch != " "}
        for k in range(0, 360, 7):
            o.transform.rotation = k + 0.4
            self.assertEqual({src for src, cells in o.transform._rotsrc.items() if cells}, glyphs)

    def test_single_glyph_coefficients_follow_the_current_angle(self):
        sc = make_scene()
        a = sc.obj().create('#', 0, 0, dynamic=False, solid=False)
        b = sc.obj().create('#', 5, 0, dynamic=False, solid=False)
        a.transform.rotation = 30
        a.transform.rotation = 100
        b.transform.rotation = 100
        self.assertEqual(a.transform._rotmap[5:], b.transform._rotmap[5:])
        self.assertAlmostEqual(math.degrees(math.atan2(a.transform._rotmap[6], a.transform._rotmap[5])), 100, places=6)
        fresh = sc.obj().create('#', 9, 0, dynamic=False, solid=False)
        fresh.transform.rotation = 250
        a.transform.rotation = 250
        self.assertEqual(a.transform._rotmap[5:], fresh.transform._rotmap[5:])


class TurnTests(unittest.TestCase):
    def sprite(self, rng):
        kind = rng.randint(0, 5)
        w, h = rng.randint(1, 24), rng.randint(1, 9)
        if kind == 0:
            return "\n".join(["#" * w] * h)
        if kind == 1:
            return "\n".join("#" * (i + 1) for i in range(h))
        if kind == 2:
            return "#" * w
        if kind == 3:
            return "\n".join(" " * i + "##" for i in range(h))
        if kind == 4:
            return "\n".join(["#" * w] + ["#" + " " * max(0, w - 2) + "#"] * max(0, h - 2) + ["#" * w])
        return "\n".join("".join(rng.choice("## ") for _ in range(w)) for _ in range(h)).replace("\n ", "\n#") or "#"

    def test_clear_turns_never_hit_when_taken_piece_by_piece(self):
        rng = random.Random(21)
        clear = 0
        for _ in range(260):
            sc = make_scene()
            o = sc.obj().create(self.sprite(rng), rng.randint(-8, 8) + rng.choice([0, 0.5]), rng.randint(-4, 4), dynamic=True, solid=True)
            p = o.physics
            for _ in range(rng.randint(1, 4)):
                w, h = rng.randint(1, 10), rng.randint(1, 5)
                sc.obj().create("\n".join(["#" * w] * h), rng.randint(-26, 26), rng.randint(-12, 12), dynamic=False, solid=True)
            if p.overlaps() or not p._turn_clear():
                continue
            clear += 1
            degrees = rng.uniform(-180, 180)
            pieces = max(1, int(math.ceil(abs(degrees) / 3)))
            for _ in range(pieces):
                o.transform.rotation = o.transform.rotation + degrees / pieces
                self.assertFalse(p.overlaps())
        self.assertGreater(clear, 40)

    def test_rotated_cells_stay_inside_the_swept_disc(self):
        rng = random.Random(8)
        for _ in range(160):
            sc = make_scene()
            o = sc.obj().create(self.sprite(rng), 0, 0, dynamic=True, solid=True)
            p = o.physics
            o.transform.rotation = rng.choice([0, rng.uniform(0, 360)])
            pivot = p._pivot()
            if pivot is None:
                continue
            cx, cy, far = pivot[:3]
            aspect = o.transform.aspect
            for _ in range(6):
                o.transform.rotation = rng.uniform(-720, 720)
                ox, rows = p.rowmask()[:2]
                for y, mask in rows.items():
                    k = 0
                    while mask:
                        if mask & 1:
                            self.assertLessEqual(math.hypot((ox + k - cx) * aspect, y - cy), far + 2.8)
                        mask >>= 1
                        k += 1

    def test_nearby_solids_keep_the_careful_path(self):
        sc = make_scene()
        o = sc.obj().create("####\n####", 0, 0, dynamic=True, solid=True)
        self.assertTrue(o.physics._turn_clear())
        sc.obj().create("#" * 30, -15, -3, dynamic=False, solid=True)
        self.assertFalse(o.physics._turn_clear())
        far = make_scene()
        p = far.obj().create("####\n####", 0, 0, dynamic=True, solid=True).physics
        far.obj().create("#" * 30, -15, -30, dynamic=False, solid=True)
        self.assertTrue(p._turn_clear())

    def test_rotation_step_defaults_to_the_arc_and_can_be_pinned(self):
        sc = make_scene()
        small = sc.obj().create("##\n##", 0, 0, dynamic=True, solid=True).physics
        large = sc.obj().create("#" * 40, -30, 6, dynamic=True, solid=True).physics
        self.assertEqual(small.rprecision, 3)
        self.assertGreater(small._turn_step(), 3)
        self.assertEqual(large._turn_step(), 3)
        small.rprecision = 3
        self.assertEqual(small._turn_step(), 3)
        small.rprecision = None
        self.assertGreater(small._turn_step(), 3)
        small.rprecision = 10
        self.assertEqual(small._turn_step(), 10)
        with self.assertRaises(ValueError):
            small.rprecision = 0
        pinned = sc.obj().create("##\n##", 20, 0, dynamic=True, solid=True, rprecision=3).physics
        self.assertEqual(pinned._turn_step(), 3)

    def test_granted_jumps_never_skip_a_hit(self):
        rng = random.Random(33)
        granted = 0
        for _ in range(420):
            sc = make_scene()
            w, h = rng.randint(10, 36), rng.randint(3, 10)
            text = "\n".join(["#" * w] * h) if rng.random() < 0.6 else "\n".join("#" * (i * w // h + 1) for i in range(h))
            o = sc.obj().create(text, rng.randint(-8, 8) + rng.choice([0, 0.5]), rng.randint(-4, 4), dynamic=True, solid=True)
            p = o.physics
            o.transform.rotation = rng.uniform(0, 360)
            pivot = p._pivot()
            if pivot is None or pivot[3] < 40:
                continue
            cx, cy, far = pivot[:3]
            for _ in range(rng.randint(1, 6)):
                direction = rng.uniform(0, 2 * math.pi)
                distance = rng.uniform(far * 0.5, far + 14)
                w2, h2 = rng.choice([(1, 1), (3, 1), (1, 4), (6, 2), (12, 1), (2, 6)])
                sc.obj().create("\n".join(["#" * w2] * h2), round(cx + distance * math.cos(direction) / 0.5), round(cy + distance * math.sin(direction)), dynamic=False, solid=True)
            if p.overlaps():
                continue
            da = rng.choice([-1, 1]) * rng.uniform(1, 8)
            jump = p._turn_free(da, rng.randint(2, 20))
            if jump < 2:
                continue
            granted += 1
            for _ in range(jump):
                o.transform.rotation = o.transform.rotation + da
                self.assertFalse(p.overlaps())
        self.assertGreater(granted, 20)

    def test_jumps_need_room_and_enough_cells(self):
        sc = make_scene()
        big = sc.obj().create("\n".join(["#" * 24] * 8), -12, 0, dynamic=True, solid=True).physics
        self.assertGreaterEqual(big._turn_free(3, 10), 2)
        sc.obj().create("#" * 40, -20, -5, dynamic=False, solid=True)
        self.assertLess(big._turn_free(3, 20), 20)
        tiny = sc.obj().create("##\n##", 40, 0, dynamic=True, solid=True).physics
        self.assertEqual(tiny._turn_free(3, 10), 0)

    def test_automatic_step_still_stops_a_spinning_body_at_a_post(self):
        for mode in ('auto', 3):
            sc = make_scene()
            o = sc.obj().create("\n".join(["#" * 15] * 4), -7, 2, dynamic=True, solid=True, friction=0.0, bounciness=0.0)
            sc.obj().create("#", 0, 3, dynamic=False, solid=True)
            p = o.physics
            if mode != 'auto':
                p.rprecision = mode
            p.avel = 170 * p.mass
            sc.tick(True)
            self.assertLess(abs((o.transform.rotation + 180) % 360 - 180), 120)
            self.assertFalse(p.overlaps())


class BoundTests(unittest.TestCase):
    def test_rotation_memo_survives_concurrent_sessions(self):
        errors = []

        def spin(seed):
            try:
                rng = random.Random(seed)
                sc = make_scene()
                o = sc.obj().create('\n'.join(['#' * 8] * 3), 0, 0, dynamic=False, solid=False)
                for _ in range(300):
                    o.transform.rotation = rng.randint(0, 719) / 2.0
            except Exception as exc:
                errors.append(exc)

        saved = transform_mod._ROTATION_BUDGET
        transform_mod._ROTATION_BUDGET = 20000
        try:
            threads = [threading.Thread(target=spin, args=(n,)) for n in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        finally:
            transform_mod._ROTATION_BUDGET = saved
        self.assertEqual(errors, [])
        total = sum(entry[0] for entry in transform_mod._ROTATIONS.values())
        self.assertEqual(total, transform_mod._rotation_cost[0])

    def test_normal_memo_stays_inside_its_budget(self):
        rng = random.Random(5)
        saved = shared._NORMAL_BUDGET
        shared._NORMAL_BUDGET = 600
        try:
            for _ in range(400):
                pixels = {(rng.randint(0, 20), rng.randint(0, 8)) for _ in range(40)}
                shared._gradient_cells(pixels, (rng.randint(0, 20) + 0.5, rng.randint(0, 8) + 0.5), 1, 0.5)
                self.assertLessEqual(shared._NORMAL_COST[0], 600)
        finally:
            shared._NORMAL_BUDGET = saved

    def test_oversized_shapes_skip_the_memo(self):
        tall = {(0, y) for y in range(700)}
        before = len(shared._NORMALS)
        shared._gradient_cells(tall, (0.5, 300.5), 1, 0.5)
        self.assertEqual(len(shared._NORMALS), before)


if __name__ == '__main__':
    unittest.main()
