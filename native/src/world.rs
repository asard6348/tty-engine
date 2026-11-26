use std::sync::Arc;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::hash::Map;
use crate::kernels;
use crate::shape::{py_round, Mask, Shape};

const SHIFT: u32 = 3;
const LIMIT: i128 = 64;
const SCAN: i128 = 4096;
const DEG_TO_RAD: f64 = std::f64::consts::PI / 180.0;
const RAD_TO_DEG: f64 = 180.0 / std::f64::consts::PI;

pub struct Bail;

type Res<T> = Result<T, Bail>;

fn pymin(a: f64, b: f64) -> f64 {
    if b < a {
        b
    } else {
        a
    }
}

fn pymax(a: f64, b: f64) -> f64 {
    if b > a {
        b
    } else {
        a
    }
}

pub struct Rel {
    pub rows: Vec<(i64, Mask)>,
    pub n: i64,
    pub sx: i64,
    pub si: i64,
    pub ext: Option<[i64; 4]>,
    pub spans: Vec<(i64, Vec<(i64, i64)>)>,
}

impl Rel {
    fn build(spans: Vec<(i64, Vec<(i64, i64)>)>) -> Rel {
        let mut rows = Vec::with_capacity(spans.len());
        let (mut n, mut sx, mut si) = (0i64, 0i64, 0i64);
        let (mut lo, mut hi) = (i64::MAX, i64::MIN);
        let (mut top, mut bottom) = (None, None);
        for (i, runs) in &spans {
            let mut bits: Vec<i64> = Vec::new();
            let mut count = 0i64;
            for &(a, b) in runs {
                for c in a..b {
                    bits.push(c);
                }
                count += b - a;
                sx += (a + b - 1) * (b - a) / 2;
                if a < lo {
                    lo = a;
                }
                if b - 1 > hi {
                    hi = b - 1;
                }
            }
            n += count;
            si += i * count;
            if top.is_none() {
                top = Some(*i);
            }
            bottom = Some(*i);
            rows.push((*i, Mask::from_cells_x(bits.into_iter(), 0)));
        }
        let ext = match (top, bottom) {
            (Some(t), Some(b)) => Some([lo, hi, t, b]),
            _ => None,
        };
        Rel { rows, n, sx, si, ext, spans }
    }

    fn spread(&self, aspect: f64) -> f64 {
        if self.n == 0 {
            return 0.0;
        }
        let n = self.n as f64;
        let cxr = self.sx as f64 / n;
        let cyr = (-self.si) as f64 / n;
        let mut tot = 0.0f64;
        for (i, runs) in &self.spans {
            let dy = (-(*i)) as f64 - cyr;
            let dy2 = dy * dy;
            for &(a, b) in runs {
                for c in a..b {
                    let d = (c as f64 - cxr) * aspect;
                    tot += d * d + dy2;
                }
            }
        }
        tot / n
    }
}

#[derive(Clone)]
pub struct Body {
    live: bool,
    solid: bool,
    phantom: bool,
    dynamic: bool,
    hitbox: bool,
    slope: bool,
    ok: bool,
    quiet: bool,
    ghost_call: bool,
    ghosts: Vec<u32>,
    bounciness: f64,
    friction: f64,
    bt: Option<f64>,
    mass: f64,
    drag: f64,
    adrag: f64,
    precision: f64,
    gx: f64,
    gy: f64,
    aspect: f64,
    xvel: f64,
    yvel: f64,
    avel: f64,
    x: f64,
    y: f64,
    ox: f64,
    oy: f64,
    rel: Option<Arc<Rel>>,
    spread0: f64,
    order: i64,
    boxed: Option<[i64; 4]>,
    large: bool,
    touch: [bool; 2],
    sides: [bool; 4],
    depenskip: i64,
    stamp: u64,
}

impl Body {
    fn empty() -> Body {
        Body {
            live: false,
            solid: false,
            phantom: false,
            dynamic: false,
            hitbox: false,
            slope: false,
            ok: false,
            quiet: false,
            ghost_call: false,
            ghosts: Vec::new(),
            bounciness: 0.0,
            friction: 0.0,
            bt: None,
            mass: 1.0,
            drag: 1.0,
            adrag: 1.0,
            precision: 0.5,
            gx: 0.0,
            gy: 0.0,
            aspect: 0.5,
            xvel: 0.0,
            yvel: 0.0,
            avel: 0.0,
            x: 0.0,
            y: 0.0,
            ox: 0.0,
            oy: 0.0,
            rel: None,
            spread0: 0.0,
            order: -1,
            boxed: None,
            large: false,
            touch: [false; 2],
            sides: [false; 4],
            depenskip: 0,
            stamp: 0,
        }
    }
}

#[derive(Clone)]
struct Snap {
    slot: u32,
    x: f64,
    y: f64,
    xvel: f64,
    yvel: f64,
    avel: f64,
    touch: [bool; 2],
    sides: [bool; 4],
    depenskip: i64,
}

#[pyclass(module = "ttyengine._native")]
pub struct World {
    bodies: Vec<Body>,
    free: Vec<u32>,
    cells: Map<(i64, i64), Vec<u32>>,
    large: Vec<u32>,
    bt_scene: f64,
    stamp: u64,
    journal: Vec<Snap>,
    touched: Vec<u32>,
    remember: bool,
}

fn overlap_each<F: FnMut(i64, i64)>(ra: &Rel, ax: i64, ay: i64, rb: &Rel, bx: i64, by: i64, mut f: F) {
    for (i, ma) in ra.rows.iter() {
        let y = ay - i;
        let ib = by - y;
        if let Ok(k) = rb.rows.binary_search_by_key(&ib, |r| r.0) {
            let mb = &rb.rows[k].1;
            for (wi, &w) in ma.0.iter().enumerate() {
                let mut w = w;
                while w != 0 {
                    let c = (wi as i64) * 64 + w.trailing_zeros() as i64;
                    w &= w - 1;
                    if mb.bit(ax + c - bx) {
                        f(ax + c, y);
                    }
                }
            }
        }
    }
}

fn overlap_any(ra: &Rel, ax: i64, ay: i64, rb: &Rel, bx: i64, by: i64) -> bool {
    for (i, ma) in ra.rows.iter() {
        let y = ay - i;
        let ib = by - y;
        if let Ok(k) = rb.rows.binary_search_by_key(&ib, |r| r.0) {
            let mb = &rb.rows[k].1;
            for (wi, &w) in ma.0.iter().enumerate() {
                let mut w = w;
                while w != 0 {
                    let c = (wi as i64) * 64 + w.trailing_zeros() as i64;
                    w &= w - 1;
                    if mb.bit(ax + c - bx) {
                        return true;
                    }
                }
            }
        }
    }
    false
}

impl World {
    fn rel(&self, s: u32) -> Option<&Arc<Rel>> {
        self.bodies[s as usize].rel.as_ref()
    }

    fn pos_at(&self, s: u32, x: f64, y: f64) -> (i64, i64) {
        let b = &self.bodies[s as usize];
        (py_round(x + b.ox) as i64, py_round(y + b.oy) as i64)
    }

    fn pos(&self, s: u32) -> (i64, i64) {
        let b = &self.bodies[s as usize];
        self.pos_at(s, b.x, b.y)
    }

    fn bounds_at(&self, s: u32, x: f64, y: f64) -> Option<[i64; 4]> {
        let ext = self.rel(s)?.ext?;
        let (rx, ry) = self.pos_at(s, x, y);
        Some([rx + ext[0], rx + ext[1], ry - ext[3], ry - ext[2]])
    }

    fn bounds(&self, s: u32) -> Option<[i64; 4]> {
        let b = &self.bodies[s as usize];
        self.bounds_at(s, b.x, b.y)
    }

    fn ix_remove(&mut self, s: u32) {
        let (boxed, large) = {
            let b = &mut self.bodies[s as usize];
            (b.boxed.take(), b.large)
        };
        let bx = match boxed {
            Some(bx) => bx,
            None => return,
        };
        if large {
            if let Some(p) = self.large.iter().position(|&v| v == s) {
                self.large.swap_remove(p);
            }
            return;
        }
        for cx in (bx[0] >> SHIFT)..=(bx[1] >> SHIFT) {
            for cy in (bx[2] >> SHIFT)..=(bx[3] >> SHIFT) {
                if let Some(bucket) = self.cells.get_mut(&(cx, cy)) {
                    if let Some(p) = bucket.iter().position(|&v| v == s) {
                        bucket.swap_remove(p);
                    }
                    if bucket.is_empty() {
                        self.cells.remove(&(cx, cy));
                    }
                }
            }
        }
    }

    fn ix_insert(&mut self, s: u32) {
        let (live, solid, order) = {
            let b = &self.bodies[s as usize];
            (b.live, b.solid, b.order)
        };
        if !live || !solid || order < 0 {
            return;
        }
        let bx = match self.bounds(s) {
            Some(bx) => bx,
            None => return,
        };
        let (cx0, cx1, cy0, cy1) = (bx[0] >> SHIFT, bx[1] >> SHIFT, bx[2] >> SHIFT, bx[3] >> SHIFT);
        let area = (cx1 as i128 - cx0 as i128 + 1) * (cy1 as i128 - cy0 as i128 + 1);
        let large = area > LIMIT;
        {
            let b = &mut self.bodies[s as usize];
            b.boxed = Some(bx);
            b.large = large;
        }
        if large {
            self.large.push(s);
            return;
        }
        for cx in cx0..=cx1 {
            for cy in cy0..=cy1 {
                self.cells.entry((cx, cy)).or_default().push(s);
            }
        }
    }

    fn reindex(&mut self, s: u32) {
        self.ix_remove(s);
        self.ix_insert(s);
    }

    fn near(&self, x0: i64, x1: i64, y0: i64, y1: i64, skip: Option<u32>) -> Vec<u32> {
        let (cx0, cx1, cy0, cy1) = (x0 >> SHIFT, x1 >> SHIFT, y0 >> SHIFT, y1 >> SHIFT);
        let mut found: Vec<(i64, u32)> = Vec::new();
        let mut take = |slot: u32| {
            if Some(slot) == skip {
                return;
            }
            let b = &self.bodies[slot as usize];
            if let Some(bx) = &b.boxed {
                if bx[1] < x0 || bx[0] > x1 || bx[3] < y0 || bx[2] > y1 {
                    return;
                }
                found.push((b.order, slot));
            }
        };
        let area = (cx1 as i128 - cx0 as i128 + 1) * (cy1 as i128 - cy0 as i128 + 1);
        let mut dedupe = true;
        if cx0 == cx1 && cy0 == cy1 {
            dedupe = false;
            for &slot in &self.large {
                take(slot);
            }
            if let Some(bucket) = self.cells.get(&(cx0, cy0)) {
                for &slot in bucket {
                    take(slot);
                }
            }
        } else if area > SCAN {
            dedupe = false;
            for i in 0..self.bodies.len() {
                take(i as u32);
            }
        } else {
            for &slot in &self.large {
                take(slot);
            }
            for cx in cx0..=cx1 {
                for cy in cy0..=cy1 {
                    if let Some(bucket) = self.cells.get(&(cx, cy)) {
                        for &slot in bucket {
                            take(slot);
                        }
                    }
                }
            }
        }
        if found.len() > 1 {
            found.sort_unstable_by_key(|f| f.0);
            if dedupe {
                found.dedup_by_key(|f| f.0);
            }
        }
        found.into_iter().map(|f| f.1).collect()
    }

    fn record(&mut self, s: u32) {
        let stamp = self.stamp;
        let b = &mut self.bodies[s as usize];
        if b.stamp == stamp {
            return;
        }
        b.stamp = stamp;
        let snap = Snap {
            slot: s,
            x: b.x,
            y: b.y,
            xvel: b.xvel,
            yvel: b.yvel,
            avel: b.avel,
            touch: b.touch,
            sides: b.sides,
            depenskip: b.depenskip,
        };
        self.journal.push(snap);
    }

    fn set_coord(&mut self, s: u32, axis: usize, v: f64) {
        self.record(s);
        {
            let b = &mut self.bodies[s as usize];
            if axis == 0 {
                b.x = v;
            } else {
                b.y = v;
            }
        }
        self.reindex(s);
    }

    fn coord(&self, s: u32, axis: usize) -> f64 {
        let b = &self.bodies[s as usize];
        if axis == 0 {
            b.x
        } else {
            b.y
        }
    }

    fn set_vel(&mut self, s: u32, axis: usize, v: f64) {
        self.record(s);
        let b = &mut self.bodies[s as usize];
        if axis == 0 {
            b.xvel = v;
        } else {
            b.yvel = v;
        }
    }

    fn vel(&self, s: u32, axis: usize) -> f64 {
        let b = &self.bodies[s as usize];
        if axis == 0 {
            b.xvel
        } else {
            b.yvel
        }
    }

    fn set_avel(&mut self, s: u32, v: f64) {
        self.record(s);
        self.bodies[s as usize].avel = v;
    }

    fn ghosted(&self, a: u32, b: u32) -> Res<bool> {
        let (ba, bb) = (&self.bodies[a as usize], &self.bodies[b as usize]);
        if !ba.ok || !bb.ok || ba.ghost_call || bb.ghost_call {
            return Err(Bail);
        }
        Ok(ba.ghosts.contains(&b) || bb.ghosts.contains(&a))
    }

    fn center(&self, s: u32) -> (f64, f64) {
        let b = &self.bodies[s as usize];
        let rel = match &b.rel {
            Some(r) if r.n > 0 => r,
            _ => return (0.0, 0.0),
        };
        let (rx, ry) = self.pos(s);
        let n = rel.n;
        ((n * rx + rel.sx) as f64 / n as f64, (n * ry - rel.si) as f64 / n as f64)
    }

    fn inertia_spread(&self, s: u32) -> f64 {
        let b = &self.bodies[s as usize];
        match &b.rel {
            Some(r) if r.n > 0 => b.spread0 + (b.aspect * b.aspect + 1.0) / 12.0,
            _ => 1.0,
        }
    }

    fn invinertia(&self, s: u32) -> f64 {
        let b = &self.bodies[s as usize];
        let n = b.rel.as_ref().map_or(0, |r| r.n);
        if b.hitbox || !b.slope || !b.dynamic || !b.solid || n < 2 {
            return 0.0;
        }
        1.0 / (b.mass * self.inertia_spread(s))
    }

    fn velocity(&self, s: u32) -> (f64, f64) {
        let b = &self.bodies[s as usize];
        (b.xvel / b.mass * b.aspect, b.yvel / b.mass)
    }

    fn omega(&self, s: u32) -> f64 {
        let b = &self.bodies[s as usize];
        -(b.avel / b.mass * DEG_TO_RAD)
    }

    fn arm(&self, s: u32, point: (f64, f64)) -> (f64, f64) {
        let a = self.bodies[s as usize].aspect;
        let (cx, cy) = self.center(s);
        ((point.0 - cx) * a, point.1 - cy)
    }

    fn impulse(&mut self, s: u32, jx: f64, jy: f64, rx: f64, ry: f64) {
        self.record(s);
        let a = self.bodies[s as usize].aspect;
        {
            let b = &mut self.bodies[s as usize];
            b.xvel += jx / a;
            b.yvel += jy;
        }
        if rx != 0.0 || ry != 0.0 {
            self.spin(s, rx * jy - ry * jx);
        }
    }

    fn spin(&mut self, s: u32, torque: f64) {
        let inv = self.invinertia(s);
        if inv != 0.0 && torque != 0.0 {
            let b = &mut self.bodies[s as usize];
            b.avel -= (torque * inv * RAD_TO_DEG) * b.mass;
        }
    }

    fn apply_other(&mut self, group: &Option<Vec<u32>>, single: Option<u32>, jx: f64, jy: f64, rb: (f64, f64)) {
        let group = match group {
            Some(g) => g,
            None => return,
        };
        if let Some(sg) = single {
            self.impulse(sg, jx, jy, rb.0, rb.1);
            return;
        }
        let mut total = 0.0f64;
        for &m in group {
            total += self.bodies[m as usize].mass;
        }
        for &m in group {
            let share = self.bodies[m as usize].mass / total;
            self.impulse(m, jx * share, jy * share, 0.0, 0.0);
        }
    }

    fn solve(&mut self, s: u32, other: u32, group: &Option<Vec<u32>>, point: (f64, f64), nx: f64, ny: f64) -> bool {
        let a = self.bodies[s as usize].aspect;
        let ra = self.arm(s, point);
        let va = self.velocity(s);
        let wa = self.omega(s);
        let vax = va.0 - wa * ra.1;
        let vay = va.1 + wa * ra.0;

        let (mut vbx, mut vby);
        let (rb, invmb, invib, e_other, mu_other, single, total);
        match group {
            None => {
                rb = (0.0, 0.0);
                vbx = 0.0;
                vby = 0.0;
                invmb = 0.0;
                invib = 0.0;
                e_other = self.bodies[other as usize].bounciness;
                mu_other = self.bodies[other as usize].friction;
                single = None;
                total = 0.0;
            }
            Some(g) => {
                single = if g.len() == 1 { Some(g[0]) } else { None };
                let mut t = 0.0f64;
                for &m in g {
                    t += self.bodies[m as usize].mass;
                }
                total = t;
                invmb = 1.0 / total;
                if let Some(sg) = single {
                    rb = self.arm(sg, point);
                    let vb = self.velocity(sg);
                    let wb = self.omega(sg);
                    vbx = vb.0 - wb * rb.1;
                    vby = vb.1 + wb * rb.0;
                    invib = self.invinertia(sg);
                } else {
                    rb = (0.0, 0.0);
                    let mut sxv = 0.0f64;
                    let mut syv = 0.0f64;
                    for &m in g {
                        let b = &self.bodies[m as usize];
                        sxv += b.xvel / b.mass * b.aspect * b.mass;
                        syv += b.yvel;
                    }
                    vbx = sxv / total;
                    vby = syv / total;
                    invib = 0.0;
                }
                let mut eo = self.bodies[g[0] as usize].bounciness;
                let mut mo = self.bodies[g[0] as usize].friction;
                for &m in &g[1..] {
                    let b = &self.bodies[m as usize];
                    if b.bounciness > eo {
                        eo = b.bounciness;
                    }
                    if b.friction > mo {
                        mo = b.friction;
                    }
                }
                e_other = eo;
                mu_other = mo;
            }
        }

        let vn = (vax - vbx) * nx + (vay - vby) * ny;
        if vn >= 0.0 {
            return false;
        }

        let me = &self.bodies[s as usize];
        let mut e = pymax(me.bounciness, e_other);
        let limit = match (me.bt, self.bodies[other as usize].bt) {
            (Some(p), Some(q)) => Some(pymin(p, q)),
            (Some(p), None) => Some(p),
            (None, Some(q)) => Some(q),
            (None, None) => None,
        };
        if -vn < limit.unwrap_or(self.bt_scene) {
            e = 0.0;
        }

        let inva = 1.0 / me.mass;
        let ia = self.invinertia(s);
        let can = {
            let v = ra.0 * ny - ra.1 * nx;
            v * v * ia
        };
        let cbn = {
            let v = rb.0 * ny - rb.1 * nx;
            v * v * invib
        };
        let denom = inva + invmb + can + cbn;
        let (gx, gy) = (me.gx, me.gy);
        let boost = e * pymax(0.0, -(gx * a * nx + gy * ny));
        let j = (-(1.0 + e) * vn + boost) / denom;

        self.impulse(s, j * nx, j * ny, ra.0, ra.1);
        self.apply_other(group, single, -j * nx, -j * ny, rb);

        let mu = pymax(self.bodies[s as usize].friction, mu_other);
        if mu != 0.0 {
            let (tx, ty) = (-ny, nx);
            let va = self.velocity(s);
            let wa = self.omega(s);
            let vax = va.0 - wa * ra.1;
            let vay = va.1 + wa * ra.0;
            match group {
                None => {
                    vbx = 0.0;
                    vby = 0.0;
                }
                Some(g) => {
                    if let Some(sg) = single {
                        let vb = self.velocity(sg);
                        let wb = self.omega(sg);
                        vbx = vb.0 - wb * rb.1;
                        vby = vb.1 + wb * rb.0;
                    } else {
                        let mut sxv = 0.0f64;
                        let mut syv = 0.0f64;
                        for &m in g {
                            let b = &self.bodies[m as usize];
                            sxv += b.xvel * b.aspect / 1.0;
                            syv += b.yvel;
                        }
                        vbx = sxv / total;
                        vby = syv / total;
                    }
                }
            }
            let vt = (vax - vbx) * tx + (vay - vby) * ty;
            let cat = {
                let v = ra.0 * ty - ra.1 * tx;
                v * v * ia
            };
            let cbt = {
                let v = rb.0 * ty - rb.1 * tx;
                v * v * invib
            };
            let mut jt = -vt / (inva + invmb + cat + cbt);
            let lim = mu * j;
            jt = pymax(-lim, pymin(lim, jt));
            self.impulse(s, jt * tx, jt * ty, ra.0, ra.1);
            self.apply_other(group, single, -jt * tx, -jt * ty, rb);
        }
        true
    }

    fn contact_normal(&self, s: u32, o: u32, point: (f64, f64), nx: i64, ny: i64, inside: bool) -> Res<(f64, f64)> {
        let (a, b) = (&self.bodies[s as usize], &self.bodies[o as usize]);
        let (ra, rb) = match (&a.rel, &b.rel) {
            (Some(x), Some(y)) => (x, y),
            _ => return Err(Bail),
        };
        let (ax, ay) = self.pos(s);
        let (bx, by) = self.pos(o);
        let mine = Shape::placed(ax, ay, &ra.rows);
        let theirs = Shape::placed(bx, by, &rb.rows);
        kernels::contact_normal(&mine, &theirs, point, nx, ny, inside, a.slope && b.slope, a.aspect).map_err(|_| Bail)
    }

    fn cells_of(&self, s: u32) -> Vec<(i64, i64)> {
        let mut out = Vec::new();
        if let Some(r) = self.rel(s) {
            let (rx, ry) = self.pos(s);
            for (i, m) in r.rows.iter() {
                for (wi, &w) in m.0.iter().enumerate() {
                    let mut w = w;
                    while w != 0 {
                        let c = (wi as i64) * 64 + w.trailing_zeros() as i64;
                        w &= w - 1;
                        out.push((rx + c, ry - i));
                    }
                }
            }
        }
        out
    }

    fn overlap_cells(&self, a: u32, dx: i64, dy: i64, b: u32) -> Vec<(i64, i64)> {
        let mut out = Vec::new();
        if let (Some(ra), Some(rb)) = (self.rel(a), self.rel(b)) {
            let (ax, ay) = self.pos(a);
            let (bx, by) = self.pos(b);
            overlap_each(ra, ax + dx, ay + dy, rb, bx, by, |x, y| out.push((x, y)));
        }
        out
    }

    fn overlap_hit(&self, a: u32, dx: i64, dy: i64, b: u32) -> bool {
        if let (Some(ra), Some(rb)) = (self.rel(a), self.rel(b)) {
            let (ax, ay) = self.pos(a);
            let (bx, by) = self.pos(b);
            return overlap_any(ra, ax + dx, ay + dy, rb, bx, by);
        }
        false
    }

    fn shifted_bounds(&self, s: u32, dx: i64, dy: i64) -> Option<[i64; 4]> {
        let bx = self.bounds(s)?;
        Some([bx[0] + dx, bx[1] + dx, bx[2] + dy, bx[3] + dy])
    }

    fn overlaps(&self, s: u32, dx: i64, dy: i64) -> Res<Vec<(u32, usize)>> {
        let mut found = Vec::new();
        let b1 = match self.shifted_bounds(s, dx, dy) {
            Some(b) => b,
            None => return Ok(found),
        };
        for o in self.near(b1[0], b1[1], b1[2], b1[3], Some(s)) {
            let p2 = &self.bodies[o as usize];
            if p2.phantom || !p2.solid {
                continue;
            }
            let b2 = match self.bounds(o) {
                Some(b) => b,
                None => continue,
            };
            if b2[1] < b1[0] || b2[0] > b1[1] || b2[3] < b1[2] || b2[2] > b1[3] {
                continue;
            }
            let cells = self.overlap_cells(s, dx, dy, o);
            if !cells.is_empty() && !self.ghosted(s, o)? {
                found.push((o, cells.len()));
            }
        }
        Ok(found)
    }

    fn blocked(&self, s: u32, dx: i64, dy: i64, exclude: &[u32], pool: Option<&[u32]>) -> Res<Vec<u32>> {
        let mut hits = Vec::new();
        let b = match self.bounds(s) {
            Some(b) => b,
            None => return Ok(hits),
        };
        let owned;
        let pool_ref: &[u32] = match pool {
            Some(p) => p,
            None => {
                owned = self.near(b[0] + dx, b[1] + dx, b[2] + dy, b[3] + dy, Some(s));
                &owned
            }
        };
        for &o in pool_ref {
            if exclude.contains(&o) {
                continue;
            }
            let p2 = &self.bodies[o as usize];
            if p2.phantom || !p2.solid {
                continue;
            }
            let b2 = match self.bounds(o) {
                Some(v) => v,
                None => continue,
            };
            if b2[1] < b[0] + dx || b2[0] > b[1] + dx || b2[3] < b[2] + dy || b2[2] > b[3] + dy {
                continue;
            }
            if self.overlap_hit(s, dx, dy, o) && !self.ghosted(s, o)? {
                hits.push(o);
            }
        }
        Ok(hits)
    }

    fn cluster(&self, s: u32, start: u32, dx: i64, dy: i64) -> Res<Option<Vec<u32>>> {
        let mut members = vec![start];
        let mut seen = vec![start, s];
        let mut queue = vec![start];
        while let Some(body) = queue.pop() {
            if !self.bodies[body as usize].dynamic {
                return Ok(None);
            }
            let mut exclude = members.clone();
            exclude.push(s);
            for o in self.blocked(body, dx, dy, &exclude, None)? {
                if seen.contains(&o) {
                    continue;
                }
                if !self.bodies[o as usize].dynamic {
                    return Ok(None);
                }
                seen.push(o);
                members.push(o);
                queue.push(o);
            }
        }
        Ok(Some(members))
    }

    fn lane(&self, s: u32, axis: usize) -> Option<(f64, i64, i64, i64, i64)> {
        let ext = self.rel(s)?.ext?;
        let b = &self.bodies[s as usize];
        if axis == 0 {
            let base = b.x + b.ox;
            let row = py_round(b.y + b.oy) as i64;
            Some((base, ext[0], ext[1], row - ext[3], row - ext[2]))
        } else {
            let base = b.y + b.oy;
            let col = py_round(b.x + b.ox) as i64;
            Some((base, -ext[3], -ext[2], col + ext[0], col + ext[1]))
        }
    }

    fn sweep(&self, s: u32, axis: usize, direction: f64, distance: f64) -> Vec<u32> {
        let (base, lo_off, hi_off, cross_lo, cross_hi) = match self.lane(s, axis) {
            Some(l) => l,
            None => return Vec::new(),
        };
        let end = base + direction * distance;
        let lo = (py_round(base) as i64).min(py_round(end) as i64) - 1;
        let hi = (py_round(base) as i64).max(py_round(end) as i64) + 1;
        if axis == 0 {
            self.near(lo + lo_off, hi + hi_off, cross_lo, cross_hi, Some(s))
        } else {
            self.near(cross_lo, cross_hi, lo + lo_off, hi + hi_off, Some(s))
        }
    }

    fn room(&self, s: u32, pool: &[u32], axis: usize, direction: f64) -> f64 {
        if pool.is_empty() {
            return f64::INFINITY;
        }
        let (base, lo_off, hi_off, cross_lo, cross_hi) = match self.lane(s, axis) {
            Some(l) => l,
            None => return f64::INFINITY,
        };
        let here = py_round(base) as i64;
        let (low, high) = (here + lo_off, here + hi_off);
        let mut room = f64::INFINITY;
        for &o in pool {
            let b2 = match self.bounds(o) {
                Some(b) => b,
                None => continue,
            };
            let (m0, m1, c0, c1) = if axis == 0 { (b2[0], b2[1], b2[2], b2[3]) } else { (b2[2], b2[3], b2[0], b2[1]) };
            if c1 < cross_lo || c0 > cross_hi {
                continue;
            }
            if m1 >= low && m0 <= high {
                return 0.0;
            }
            let mut reach;
            if direction > 0.0 {
                if m1 < low {
                    continue;
                }
                reach = ((m0 - hi_off) as f64 - 0.5) - base;
            } else {
                if m0 > high {
                    continue;
                }
                reach = base - ((m1 - lo_off) as f64 + 0.5);
            }
            reach -= 1.0;
            if reach < room {
                room = reach;
            }
        }
        room
    }

    fn collisions(&self, s: u32, axis: usize, value: f64, pool: &[u32]) -> Vec<(u32, Vec<(i64, i64)>)> {
        let b = &self.bodies[s as usize];
        let (x, y) = if axis == 0 { (value, b.y) } else { (b.x, value) };
        let mut result = Vec::new();
        let b1 = match self.bounds_at(s, x, y) {
            Some(v) => v,
            None => return result,
        };
        let (rx, ry) = self.pos_at(s, x, y);
        let ra = match self.rel(s) {
            Some(r) => r,
            None => return result,
        };
        for &o in pool {
            if o == s {
                continue;
            }
            let b2 = match self.bounds(o) {
                Some(v) => v,
                None => continue,
            };
            if b2[1] < b1[0] || b2[0] > b1[1] || b2[3] < b1[2] || b2[2] > b1[3] {
                continue;
            }
            let rb = match self.rel(o) {
                Some(r) => r,
                None => continue,
            };
            let (bx, by) = self.pos(o);
            let mut cells = Vec::new();
            overlap_each(ra, rx, ry, rb, bx, by, |cx, cy| cells.push((cx, cy)));
            if !cells.is_empty() {
                result.push((o, cells));
            }
        }
        result
    }

    fn notify(&mut self, s: u32, o: u32, once: bool) -> Res<()> {
        if !self.bodies[o as usize].quiet || !self.bodies[s as usize].quiet {
            return Err(Bail);
        }
        if once && self.touched.contains(&o) {
            return Ok(());
        }
        if !self.touched.contains(&o) {
            self.touched.push(o);
        }
        Ok(())
    }

    fn depenetrate(&mut self, s: u32) -> Res<()> {
        {
            let b = &self.bodies[s as usize];
            if b.phantom || !b.solid {
                return Ok(());
            }
        }
        if self.bodies[s as usize].depenskip > 0 {
            self.record(s);
            self.bodies[s as usize].depenskip -= 1;
            return Ok(());
        }
        let found = self.overlaps(s, 0, 0)?;
        if found.is_empty() {
            self.remember = true;
            return Ok(());
        }
        let mut pick = found[0];
        for f in &found[1..] {
            if f.1 > pick.1 {
                pick = *f;
            }
        }
        let obj2 = pick.0;
        let mine = self.cells_of(s);
        let theirs = self.cells_of(obj2);
        let aspect = self.bodies[s as usize].aspect;
        let best = kernels::mtv(&mine, &theirs, aspect).ok_or(Bail)?;
        let (_, dx, dy, k) = best;
        let movable = self.bodies[obj2 as usize].dynamic;
        let (sm, om) = (self.bodies[s as usize].mass, self.bodies[obj2 as usize].mass);
        let (mut mine_share, mut theirs_share);
        if movable {
            let c = (k as f64 * om / (sm + om)).ceil();
            let m = if c > 1.0 { c } else { 1.0 };
            let m = if m < k as f64 { m } else { k as f64 };
            mine_share = m as i64;
            theirs_share = k - mine_share;
        } else {
            mine_share = k;
            theirs_share = 0;
        }
        if movable {
            if theirs_share != 0 {
                let hit = self.overlaps(obj2, -dx * theirs_share, -dy * theirs_share)?;
                if hit.iter().any(|f| f.0 != s) {
                    mine_share = k;
                    theirs_share = 0;
                }
            }
            if mine_share != 0 {
                let hit = self.overlaps(s, dx * mine_share, dy * mine_share)?;
                if hit.iter().any(|f| f.0 != obj2) {
                    let back = self.overlaps(obj2, -dx * k, -dy * k)?;
                    if back.iter().any(|f| f.0 != s) {
                        return Err(Bail);
                    }
                    mine_share = 0;
                    theirs_share = k;
                }
            }
        }
        let (x, y) = (self.bodies[s as usize].x, self.bodies[s as usize].y);
        self.set_coord(s, 0, x + (dx * mine_share) as f64);
        self.set_coord(s, 1, y + (dy * mine_share) as f64);
        if theirs_share != 0 {
            let (ox, oy) = (self.bodies[obj2 as usize].x, self.bodies[obj2 as usize].y);
            self.set_coord(obj2, 0, ox - (dx * theirs_share) as f64);
            self.set_coord(obj2, 1, oy - (dy * theirs_share) as f64);
        }
        for (body, sign) in [(s, 1i64), (obj2, -1i64)] {
            if body == obj2 && theirs_share == 0 {
                continue;
            }
            if dx != 0 && (self.vel(body, 0) * dx as f64 * sign as f64) < 0.0 {
                self.set_vel(body, 0, 0.0);
            }
            if dy != 0 && (self.vel(body, 1) * dy as f64 * sign as f64) < 0.0 {
                self.set_vel(body, 1, 0.0);
            }
        }
        let again = self.overlaps(s, 0, 0)?;
        if again.is_empty() {
            self.remember = true;
            return Ok(());
        }
        Err(Bail)
    }

    fn probe(&mut self, s: u32) -> Res<()> {
        let mut touch = [false, false];
        let mut sides = [false; 4];
        let (solid, phantom) = {
            let b = &self.bodies[s as usize];
            (b.solid, b.phantom)
        };
        if solid && !phantom {
            let reach = self.bounds(s);
            let mut pool: Option<Vec<u32>> = reach.map(|r| self.near(r[0] - 1, r[1] + 1, r[2] - 1, r[3] + 1, Some(s)));
            for ia in 0..2usize {
                for sg in [1i64, -1i64] {
                    let (dx, dy) = if ia == 0 { (sg, 0) } else { (0, sg) };
                    let hits = if pool.as_ref().map_or(true, |p| !p.is_empty()) {
                        self.blocked(s, dx, dy, &[], pool.as_deref())?
                    } else {
                        Vec::new()
                    };
                    for o in hits {
                        if self.overlap_hit(s, 0, 0, o) {
                            continue;
                        }
                        let moved = self.overlap_cells(s, dx, dy, o);
                        if moved.is_empty() {
                            continue;
                        }
                        let contact: Vec<(i64, i64)> = moved.into_iter().map(|c| (c.0 - dx, c.1 - dy)).collect();
                        touch[ia] = true;
                        sides[ia * 2 + if sg == -1 { 0 } else { 1 }] = true;
                        let group = if self.bodies[o as usize].dynamic { self.cluster(s, o, dx, dy)? } else { None };
                        let center = self.center(s);
                        let point = kernels::contact_point(&contact, Some(-dx), -dy, center);
                        let cn = self.contact_normal(s, o, point, -dx, -dy, false)?;
                        if self.solve(s, o, &group, point, cn.0, cn.1) {
                            self.notify(s, o, true)?;
                            pool = None;
                        }
                    }
                }
            }
        }
        self.record(s);
        let b = &mut self.bodies[s as usize];
        b.touch = touch;
        b.sides = sides;
        if b.xvel.abs() < 1e-9 {
            b.xvel = 0.0;
        }
        if b.yvel.abs() < 1e-9 {
            b.yvel = 0.0;
        }
        if b.avel.abs() < 1e-9 {
            b.avel = 0.0;
        }
        Ok(())
    }

    fn run(&mut self, s: u32) -> Res<bool> {
        let (mass, drag, precision, gravity, adrag) = {
            let b = &self.bodies[s as usize];
            if !b.ok || !b.live {
                return Err(Bail);
            }
            (b.mass, b.drag, b.precision, [b.gx, b.gy], b.adrag)
        };
        self.touched.clear();
        self.remember = false;
        self.record(s);
        for ia in 0..2usize {
            let mut v = self.vel(s, ia) * drag;
            v += gravity[ia] * mass;
            self.set_vel(s, ia, v);
            let c: f64 = if v > 0.0 {
                1.0
            } else if v < 0.0 {
                -1.0
            } else {
                0.0
            };
            let mut ch = v.abs() / mass;
            let d: (i64, i64) = if ia == 0 { (c as i64, 0) } else { (0, c as i64) };
            let mut pool: Option<Vec<u32>> = None;
            while ch > 0.0 {
                if pool.is_none() {
                    pool = Some(self.sweep(s, ia, c, ch));
                }
                let free = self.room(s, pool.as_ref().unwrap(), ia, c);
                if free >= precision {
                    let mut pos = self.coord(s, ia);
                    let mut went = 0.0f64;
                    while ch > 0.0 {
                        let step = pymin(precision, ch);
                        if went + step > free {
                            break;
                        }
                        pos += c * step;
                        ch -= step;
                        went += step;
                    }
                    if went != 0.0 {
                        self.set_coord(s, ia, pos);
                    }
                    if ch <= 0.0 {
                        break;
                    }
                }
                let step = pymin(precision, ch);
                let target = self.coord(s, ia) + c * step;
                let hits = self.collisions(s, ia, target, pool.as_ref().unwrap());
                if !hits.is_empty() {
                    pool = None;
                }
                let mut physical: Vec<(u32, Vec<(i64, i64)>)> = Vec::new();
                for (o, cells) in hits {
                    self.notify(s, o, false)?;
                    let (me, ot) = (&self.bodies[s as usize], &self.bodies[o as usize]);
                    if me.solid && !me.phantom && !ot.phantom && !self.ghosted(s, o)? {
                        physical.push((o, cells));
                    }
                }
                if !physical.is_empty() {
                    for (o, cells) in physical {
                        let group = if self.bodies[o as usize].dynamic { self.cluster(s, o, d.0, d.1)? } else { None };
                        let center = self.center(s);
                        let point = kernels::contact_point(&cells, Some(-d.0), -d.1, center);
                        let cn = self.contact_normal(s, o, point, -d.0, -d.1, true)?;
                        self.solve(s, o, &group, point, cn.0, cn.1);
                    }
                    break;
                }
                let moved = self.coord(s, ia) + c * step;
                self.set_coord(s, ia, moved);
                ch -= step;
            }
        }
        self.depenetrate(s)?;
        let spun = self.bodies[s as usize].avel * adrag;
        self.set_avel(s, spun);
        if spun / mass != 0.0 {
            return Ok(true);
        }
        self.depenetrate(s)?;
        self.probe(s)?;
        Ok(false)
    }

    fn run_tail(&mut self, s: u32) -> Res<()> {
        if !self.bodies[s as usize].ok || !self.bodies[s as usize].live {
            return Err(Bail);
        }
        self.remember = false;
        self.record(s);
        self.depenetrate(s)?;
        self.probe(s)?;
        Ok(())
    }

    fn collect(&mut self, slot: u32, pending: bool) -> (Vec<Write>, Extra) {
        let mut out = Vec::new();
        for sn in &self.journal {
            let b = &self.bodies[sn.slot as usize];
            let mut mask = 0u8;
            if b.x != sn.x {
                mask |= 1;
            }
            if b.y != sn.y {
                mask |= 2;
            }
            if b.xvel != sn.xvel {
                mask |= 4;
            }
            if b.yvel != sn.yvel {
                mask |= 8;
            }
            if b.avel != sn.avel {
                mask |= 16;
            }
            if mask != 0 || sn.slot == slot {
                out.push((sn.slot, mask, b.x, b.y, b.xvel, b.yvel, b.avel));
            }
        }
        let b = &self.bodies[slot as usize];
        let extra = (
            b.touch[0],
            b.touch[1],
            b.sides[0],
            b.sides[1],
            b.sides[2],
            b.sides[3],
            b.depenskip,
            self.remember,
            pending,
        );
        self.journal.clear();
        (out, extra)
    }

    fn rollback(&mut self) {
        let snaps: Vec<Snap> = self.journal.drain(..).collect();
        for sn in snaps.iter().rev() {
            {
                let b = &mut self.bodies[sn.slot as usize];
                b.x = sn.x;
                b.y = sn.y;
                b.xvel = sn.xvel;
                b.yvel = sn.yvel;
                b.avel = sn.avel;
                b.touch = sn.touch;
                b.sides = sn.sides;
                b.depenskip = sn.depenskip;
                b.stamp = 0;
            }
            self.reindex(sn.slot);
        }
    }
}

type Write = (u32, u8, f64, f64, f64, f64, f64);
type Extra = (bool, bool, bool, bool, bool, bool, i64, bool, bool);

#[pymethods]
impl World {
    #[new]
    fn new() -> Self {
        World {
            bodies: Vec::new(),
            free: Vec::new(),
            cells: Map::default(),
            large: Vec::new(),
            bt_scene: 0.0,
            stamp: 0,
            journal: Vec::new(),
            touched: Vec::new(),
            remember: false,
        }
    }

    fn alloc(&mut self) -> u32 {
        if let Some(s) = self.free.pop() {
            self.bodies[s as usize] = Body::empty();
            return s;
        }
        self.bodies.push(Body::empty());
        (self.bodies.len() - 1) as u32
    }

    fn release(&mut self, slot: u32) {
        if (slot as usize) < self.bodies.len() && self.bodies[slot as usize].live {
            self.ix_remove(slot);
            self.bodies[slot as usize] = Body::empty();
            self.free.push(slot);
        }
    }

    fn set_scene(&mut self, bouncethreshold: f64) {
        self.bt_scene = bouncethreshold;
    }

    #[pyo3(signature = (slot, state, spans=None, ghosts=Vec::new()))]
    fn sync(&mut self, slot: u32, state: Vec<f64>, spans: Option<Vec<(i64, Vec<(i64, i64)>)>>, ghosts: Vec<u32>) -> PyResult<()> {
        if state.len() != 26 || slot as usize >= self.bodies.len() {
            return Err(PyValueError::new_err("bad state"));
        }
        self.ix_remove(slot);
        let rel = spans.map(|s| Arc::new(Rel::build(s)));
        let b = &mut self.bodies[slot as usize];
        b.live = true;
        b.solid = state[0] != 0.0;
        b.phantom = state[1] != 0.0;
        b.dynamic = state[2] != 0.0;
        b.hitbox = state[3] != 0.0;
        b.slope = state[4] != 0.0;
        b.ok = state[5] != 0.0;
        b.bounciness = state[6];
        b.friction = state[7];
        b.bt = if state[8].is_nan() { None } else { Some(state[8]) };
        b.mass = state[9];
        b.drag = state[10];
        b.adrag = state[11];
        b.precision = state[12];
        b.gx = state[13];
        b.gy = state[14];
        let aspect_changed = b.aspect != state[15];
        b.aspect = state[15];
        b.xvel = state[16];
        b.yvel = state[17];
        b.avel = state[18];
        b.x = state[19];
        b.y = state[20];
        b.ox = state[21];
        b.oy = state[22];
        b.depenskip = state[23] as i64;
        b.quiet = state[24] != 0.0;
        b.ghost_call = state[25] != 0.0;
        b.ghosts = ghosts;
        let fresh = rel.is_some();
        if let Some(r) = rel {
            b.rel = Some(r);
        }
        if fresh || aspect_changed {
            if let Some(r) = &b.rel {
                b.spread0 = r.spread(b.aspect);
            }
        }
        self.ix_insert(slot);
        Ok(())
    }

    fn set_order(&mut self, slots: Vec<u32>) {
        for i in 0..self.bodies.len() as u32 {
            self.ix_remove(i);
            self.bodies[i as usize].order = -1;
        }
        self.cells.clear();
        self.large.clear();
        for (k, s) in slots.iter().enumerate() {
            if (*s as usize) < self.bodies.len() {
                self.bodies[*s as usize].order = k as i64;
            }
        }
        for s in slots {
            if (s as usize) < self.bodies.len() {
                self.ix_insert(s);
            }
        }
    }

    fn step(&mut self, slot: u32) -> Option<(Vec<Write>, Extra, Vec<u32>)> {
        if slot as usize >= self.bodies.len() || !self.bodies[slot as usize].live {
            return None;
        }
        self.stamp += 1;
        self.journal.clear();
        match self.run(slot) {
            Err(_) => {
                self.rollback();
                None
            }
            Ok(pending) => {
                let (out, extra) = self.collect(slot, pending);
                Some((out, extra, self.touched.clone()))
            }
        }
    }

    fn finish(&mut self, slot: u32, touched: Vec<u32>) -> Option<(Vec<Write>, Extra)> {
        if slot as usize >= self.bodies.len() || !self.bodies[slot as usize].live {
            return None;
        }
        self.stamp += 1;
        self.journal.clear();
        self.touched = touched;
        match self.run_tail(slot) {
            Err(_) => {
                self.rollback();
                None
            }
            Ok(()) => Some(self.collect(slot, false)),
        }
    }
}
