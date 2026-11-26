use crate::shape::{py_round, spread, Shape};

const REACH: f64 = 3.5;

pub struct Window {
    pub span: i64,
    pub rows: [u128; 9],
}

pub fn window(fx: f64, fy: f64, aspect: f64) -> Option<Window> {
    let span = (REACH / aspect) as i64 + 2;
    if 2 * span + 1 > 120 {
        return None;
    }
    let mut rows = [0u128; 9];
    for yrel in -4i64..=4 {
        let dy = yrel as f64 - fy;
        let mut bits = 0u128;
        for j in 0..(2 * span + 1) {
            let u = ((j - span) as f64 - fx) * aspect;
            if (u * u + dy * dy).sqrt() <= REACH {
                bits |= 1u128 << j;
            }
        }
        rows[(yrel + 4) as usize] = bits;
    }
    Some(Window { span, rows })
}

pub fn fit_rows(
    shape: &Shape<'_>,
    center: (f64, f64),
    sign: i64,
    aspect: f64,
) -> Result<Option<(f64, f64, f64)>, ()> {
    let (cx, cy) = center;
    let ix = cx.floor() as i64;
    let iy = cy.floor() as i64;
    let win = window(cx - ix as f64, cy - iy as f64, aspect).ok_or(())?;
    let span = win.span;
    let base = ix - span;
    let xlo = (cx - REACH / aspect).ceil() as i64;
    let xhi = (cx + REACH / aspect).floor() as i64;
    let ylo = (cy - REACH).ceil() as i64;
    let yhi = (cy + REACH).floor() as i64;
    let width = (xhi - xlo + 1) as u32;
    if width >= 120 {
        return Err(());
    }
    let keep: u128 = ((1u128 << width) - 1) << (xlo - base);
    let edge_base = base - 1;
    let origin = shape.origin;
    let (mut total, mut filled) = (0i64, 0i64);
    let (mut sum_x, mut sum_y) = (0i128, 0i128);
    let (mut n, mut ex, mut ey, mut exx, mut eyy, mut exy) = (0i128, 0i128, 0i128, 0i128, 0i128, 0i128);
    let wbits = (2 * span + 1) as u32;
    for y in ylo..=yhi {
        let yrel = y - iy;
        if !(-4..=4).contains(&yrel) {
            continue;
        }
        let mut window = win.rows[(yrel + 4) as usize];
        if window == 0 {
            continue;
        }
        window &= keep;
        if window == 0 {
            continue;
        }
        total += spread(window).0;
        let row = match shape.get(y) {
            Some(r) if !r.is_zero() => r,
            _ => continue,
        };
        let here = row.window(base - origin, wbits);
        let hit = here & window;
        if hit == 0 {
            continue;
        }
        let (count, offset, _) = spread(hit);
        filled += count;
        sum_x += (count * base + offset) as i128;
        sum_y += (count * y) as i128;
        let above = shape.get(y + 1);
        let below = shape.get(y - 1);
        let cw = wbits + 2;
        let centre = row.window(edge_base - origin, cw);
        let up = above.map_or(0, |m| m.window(edge_base - origin, cw));
        let down = below.map_or(0, |m| m.window(edge_base - origin, cw));
        let rim = centre & (window << 1) & !(centre & (centre << 1) & (centre >> 1) & up & down);
        if rim != 0 {
            let (count, offset, square) = spread(rim);
            let cells_x = (count * edge_base + offset) as i128;
            let c = count as i128;
            let eb = edge_base as i128;
            n += c;
            ex += cells_x;
            ey += (count * y) as i128;
            exx += c * eb * eb + 2 * eb * offset as i128 + square as i128;
            eyy += c * y as i128 * y as i128;
            exy += y as i128 * cells_x;
        }
    }
    if filled == 0 {
        return Ok(None);
    }
    let sx = (sum_x as f64 - filled as f64 * cx) * aspect;
    let sy = sum_y as f64 - filled as f64 * cy;
    let length = (sx * sx + sy * sy).sqrt();
    if length < 1e-9 {
        return Ok(None);
    }
    let s = sign as f64;
    let (mut gx, mut gy) = (s * sx / length, s * sy / length);
    if n >= 3 {
        let nf = n as f64;
        let sxx = (n * exx - ex * ex) as f64 * aspect * aspect / nf;
        let syy = (n * eyy - ey * ey) as f64 / nf;
        let sxy = (n * exy - ex * ey) as f64 * aspect / nf;
        let hd = (sxx - syy) / 2.0;
        let half = (hd * hd + sxy * sxy).sqrt();
        let major = (sxx + syy) / 2.0 + half;
        let minor = (sxx + syy) / 2.0 - half;
        let floor = if minor > 1e-9 { minor } else { 1e-9 };
        if major > 3.0 * floor {
            let angle = 0.5 * (2.0 * sxy).atan2(sxx - syy);
            let (mut nx, mut ny) = (-angle.sin(), angle.cos());
            if nx * gx + ny * gy < 0.0 {
                nx = -nx;
                ny = -ny;
            }
            gx = nx;
            gy = ny;
        }
    }
    Ok(Some((gx, gy, filled as f64 / total as f64)))
}

pub fn contact_normal(
    mine: &Shape<'_>,
    theirs: &Shape<'_>,
    point: (f64, f64),
    nx: i64,
    ny: i64,
    inside: bool,
    slope: bool,
    aspect: f64,
) -> Result<(f64, f64), ()> {
    if !slope {
        return Ok((nx as f64, ny as f64));
    }
    let shift = if inside { 0.5 } else { -0.5 };
    let (mut cx, mut cy) = point;
    if nx.abs() > ny.abs() {
        cx += shift * if nx > 0 { 1.0 } else { -1.0 };
    } else {
        cy += shift * if ny > 0 { 1.0 } else { -1.0 };
    }
    let center = (py_round(cx * 2.0) / 2.0, py_round(cy * 2.0) / 2.0);
    let go = fit_rows(theirs, center, -1, aspect)?;
    let gs = fit_rows(mine, center, 1, aspect)?;
    let (fnx, fny) = (nx as f64, ny as f64);
    let mut faces: Vec<(f64, f64, f64)> = Vec::with_capacity(2);
    for g in [go, gs].into_iter().flatten() {
        if g.0 * fnx + g.1 * fny >= 0.25 {
            faces.push(g);
        }
    }
    if faces.is_empty() {
        return Ok((fnx, fny));
    }
    let mut fullest = faces[0].2;
    for g in &faces {
        if g.2 > fullest {
            fullest = g.2;
        }
    }
    faces.retain(|g| g.2 >= fullest - 0.08);
    let mut best = faces[0];
    let mut bestd = best.0 * fnx + best.1 * fny;
    for g in &faces[1..] {
        let d = g.0 * fnx + g.1 * fny;
        if d > bestd {
            best = *g;
            bestd = d;
        }
    }
    Ok((best.0, best.1))
}

pub fn contact_point(cells: &[(i64, i64)], nx: Option<i64>, ny: i64, center: (f64, f64)) -> (f64, f64) {
    let n = cells.len() as f64;
    let sx: i64 = cells.iter().map(|c| c.0).sum();
    let sy: i64 = cells.iter().map(|c| c.1).sum();
    let mx = sx as f64 / n;
    let my = sy as f64 / n;
    if nx.is_none() {
        return (mx, my);
    }
    let (cx, cy) = center;
    if ny != 0 {
        let lo = cells.iter().map(|c| c.0).min().unwrap() as f64;
        let hi = cells.iter().map(|c| c.0).max().unwrap() as f64;
        let inner = if hi + 0.5 < cx { hi + 0.5 } else { cx };
        let outer = if lo - 0.5 > inner { lo - 0.5 } else { inner };
        return (outer, my);
    }
    let lo = cells.iter().map(|c| c.1).min().unwrap() as f64;
    let hi = cells.iter().map(|c| c.1).max().unwrap() as f64;
    let inner = if hi + 0.5 < cy { hi + 0.5 } else { cy };
    let outer = if lo - 0.5 > inner { lo - 0.5 } else { inner };
    (mx, outer)
}

pub fn mtv(mine: &[(i64, i64)], other: &[(i64, i64)], aspect: f64) -> Option<(f64, i64, i64, i64)> {
    const DIRS: [(i64, i64); 4] = [(1, 0), (-1, 0), (0, 1), (0, -1)];
    let cost_of = |dx: i64, _dy: i64| if dx != 0 { aspect } else { 1.0 };
    let adj = |dy: i64| if dy == 1 { 0.01 } else { 0.0 };
    if mine.is_empty() || other.is_empty() {
        let mut best: Option<(f64, i64, i64, i64)> = None;
        for (dx, dy) in DIRS {
            let score = cost_of(dx, dy) - adj(dy);
            if best.map_or(true, |b| score < b.0) {
                best = Some((score, dx, dy, 1));
            }
        }
        return best;
    }
    let origin = mine.iter().chain(other.iter()).map(|c| c.0).min().unwrap();
    let build = |cells: &[(i64, i64)]| -> Shape<'static> {
        let mut ys: Vec<i64> = cells.iter().map(|c| c.1).collect();
        ys.sort_unstable();
        ys.dedup();
        let rows = ys
            .into_iter()
            .map(|y| {
                let m = crate::shape::Mask::from_cells_x(cells.iter().filter(|c| c.1 == y).map(|c| c.0), origin);
                (y, m)
            })
            .collect();
        Shape::new(origin, rows)
    };
    let ms = build(mine);
    let os = build(other);
    let mut best: Option<(f64, i64, i64, i64)> = None;
    for (dx, dy) in DIRS {
        let cost = cost_of(dx, dy);
        for k in 1..64i64 {
            let sx = dx * k;
            let sy = dy * k;
            let mut hit = false;
            for (i, m) in ms.rows.iter() {
                let y = -*i;
                if let Some(o) = os.get(y + sy) {
                    if !o.is_zero() && m.and_nonzero_shifted(o, sx) {
                        hit = true;
                        break;
                    }
                }
            }
            if !hit {
                let score = k as f64 * cost - adj(dy);
                if best.map_or(true, |b| score < b.0) {
                    best = Some((score, dx, dy, k));
                }
                break;
            }
        }
    }
    best
}
