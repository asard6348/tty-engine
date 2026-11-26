#[derive(Clone, Default)]
pub struct Mask(pub Vec<u64>);

impl Mask {
    pub fn from_bytes(bytes: &[u8]) -> Mask {
        let mut words = vec![0u64; (bytes.len() + 7) / 8];
        for (i, b) in bytes.iter().enumerate() {
            words[i / 8] |= (*b as u64) << (8 * (i % 8));
        }
        while words.last() == Some(&0) {
            words.pop();
        }
        Mask(words)
    }

    #[inline]
    pub fn is_zero(&self) -> bool {
        self.0.is_empty()
    }

    #[inline]
    pub fn bit(&self, i: i64) -> bool {
        if i < 0 {
            return false;
        }
        let w = (i >> 6) as usize;
        w < self.0.len() && (self.0[w] >> (i & 63)) & 1 == 1
    }

    pub fn window(&self, start: i64, width: u32) -> u128 {
        let mut out = 0u128;
        for i in 0..width as i64 {
            if self.bit(start + i) {
                out |= 1u128 << i;
            }
        }
        out
    }

    pub fn from_cells_x(xs: impl Iterator<Item = i64>, origin: i64) -> Mask {
        let mut words: Vec<u64> = Vec::new();
        for x in xs {
            let i = (x - origin) as usize;
            let w = i >> 6;
            if words.len() <= w {
                words.resize(w + 1, 0);
            }
            words[w] |= 1u64 << (i & 63);
        }
        Mask(words)
    }

    pub fn and_nonzero_shifted(&self, other: &Mask, shift: i64) -> bool {
        for (wi, &word) in self.0.iter().enumerate() {
            if word == 0 {
                continue;
            }
            let mut w = word;
            while w != 0 {
                let k = w.trailing_zeros() as i64;
                w &= w - 1;
                if other.bit((wi as i64) * 64 + k + shift) {
                    return true;
                }
            }
        }
        false
    }
}

#[derive(Clone)]
pub struct Shape<'a> {
    pub origin: i64,
    pub ry: i64,
    pub rows: std::borrow::Cow<'a, [(i64, Mask)]>,
}

impl<'a> Shape<'a> {
    pub fn new(origin: i64, rows_by_y: Vec<(i64, Mask)>) -> Shape<'static> {
        let mut rows: Vec<(i64, Mask)> = rows_by_y.into_iter().map(|(y, m)| (-y, m)).collect();
        rows.sort_by_key(|r| r.0);
        Shape { origin, ry: 0, rows: std::borrow::Cow::Owned(rows) }
    }

    pub fn placed(origin: i64, ry: i64, rows: &'a [(i64, Mask)]) -> Shape<'a> {
        Shape { origin, ry, rows: std::borrow::Cow::Borrowed(rows) }
    }

    pub fn get(&self, y: i64) -> Option<&Mask> {
        let i = self.ry - y;
        match self.rows.binary_search_by_key(&i, |r| r.0) {
            Ok(k) => Some(&self.rows[k].1),
            Err(_) => None,
        }
    }
}

pub fn spread(mut bits: u128) -> (i64, i64, i64) {
    let mut count = 0i64;
    let mut total = 0i64;
    let mut square = 0i64;
    while bits != 0 {
        let k = bits.trailing_zeros() as i64;
        bits &= bits - 1;
        count += 1;
        total += k;
        square += k * k;
    }
    (count, total, square)
}

pub fn py_round(x: f64) -> f64 {
    let f = x.floor();
    let d = x - f;
    if d < 0.5 {
        f
    } else if d > 0.5 {
        f + 1.0
    } else if (f % 2.0) == 0.0 {
        f
    } else {
        f + 1.0
    }
}
