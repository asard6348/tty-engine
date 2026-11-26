use pyo3::prelude::*;
use pyo3::types::PyList;
use pyo3::exceptions::PyValueError;
use pyo3::{PyTraverseError, PyVisit};

mod hash;
mod kernels;
mod shape;
mod world;

use hash::Map;

use shape::{Mask, Shape};

type RawRows = Vec<(i64, Vec<u8>)>;

fn shape_of(origin: i64, rows: RawRows) -> Shape<'static> {
    Shape::new(origin, rows.into_iter().map(|(y, b)| (y, Mask::from_bytes(&b))).collect())
}

#[pyfunction]
fn fit_rows(origin: i64, rows: RawRows, center: (f64, f64), sign: i64, aspect: f64) -> PyResult<Option<(f64, f64, f64)>> {
    kernels::fit_rows(&shape_of(origin, rows), center, sign, aspect).map_err(|_| PyValueError::new_err("unsupported aspect"))
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn contact_normal(
    mine: (i64, RawRows),
    theirs: (i64, RawRows),
    point: (f64, f64),
    nx: i64,
    ny: i64,
    inside: bool,
    slope: bool,
    aspect: f64,
) -> PyResult<(f64, f64)> {
    let a = shape_of(mine.0, mine.1);
    let b = shape_of(theirs.0, theirs.1);
    kernels::contact_normal(&a, &b, point, nx, ny, inside, slope, aspect).map_err(|_| PyValueError::new_err("unsupported aspect"))
}

#[pyfunction]
fn mtv(mine: Vec<(i64, i64)>, other: Vec<(i64, i64)>, aspect: f64) -> Option<(f64, i64, i64, i64)> {
    kernels::mtv(&mine, &other, aspect)
}

#[pyfunction]
#[pyo3(signature = (cells, nx, ny, center))]
fn contact_point(cells: Vec<(i64, i64)>, nx: Option<i64>, ny: i64, center: (f64, f64)) -> (f64, f64) {
    kernels::contact_point(&cells, nx, ny, center)
}

const SHIFT: u32 = 3;
const LIMIT: i128 = 64;
const SCAN: i128 = 4096;

struct Entry {
    obj: Py<PyAny>,
    order: u64,
    bounds: [i64; 4],
    large: bool,
}

#[pyclass(module = "ttyengine._native")]
struct Grid {
    slots: Vec<Option<Entry>>,
    free: Vec<u32>,
    by_ptr: Map<usize, u32>,
    cells: Map<(i64, i64), Vec<u32>>,
    large: Vec<u32>,
}

impl Grid {
    fn reset(&mut self) {
        self.slots.clear();
        self.free.clear();
        self.by_ptr.clear();
        self.cells.clear();
        self.large.clear();
    }

    fn span(b: &[i64; 4]) -> (i64, i64, i64, i64) {
        (b[0] >> SHIFT, b[1] >> SHIFT, b[2] >> SHIFT, b[3] >> SHIFT)
    }

    fn remove_from(bucket: &mut Vec<u32>, slot: u32) {
        if let Some(pos) = bucket.iter().position(|&s| s == slot) {
            bucket.swap_remove(pos);
        }
    }
}

#[pymethods]
impl Grid {
    #[new]
    fn new() -> Self {
        Grid {
            slots: Vec::new(),
            free: Vec::new(),
            by_ptr: Map::default(),
            cells: Map::default(),
            large: Vec::new(),
        }
    }

    fn clear(&mut self) {
        self.reset();
    }

    fn __len__(&self) -> usize {
        self.by_ptr.len()
    }

    fn place(&mut self, obj: Bound<'_, PyAny>, order: u64, bounds: (i64, i64, i64, i64)) {
        let key = obj.as_ptr() as usize;
        if self.by_ptr.contains_key(&key) {
            self.lift(&obj);
        }
        let b = [bounds.0, bounds.1, bounds.2, bounds.3];
        let (cx0, cx1, cy0, cy1) = Self::span(&b);
        let area = (cx1 as i128 - cx0 as i128 + 1) * (cy1 as i128 - cy0 as i128 + 1);
        let large = area > LIMIT;
        let entry = Entry {
            obj: obj.unbind(),
            order,
            bounds: b,
            large,
        };
        let slot = match self.free.pop() {
            Some(slot) => {
                self.slots[slot as usize] = Some(entry);
                slot
            }
            None => {
                self.slots.push(Some(entry));
                (self.slots.len() - 1) as u32
            }
        };
        self.by_ptr.insert(key, slot);
        if large {
            self.large.push(slot);
            return;
        }
        for cx in cx0..=cx1 {
            for cy in cy0..=cy1 {
                self.cells.entry((cx, cy)).or_default().push(slot);
            }
        }
    }

    fn lift(&mut self, obj: &Bound<'_, PyAny>) -> bool {
        let key = obj.as_ptr() as usize;
        let slot = match self.by_ptr.remove(&key) {
            Some(slot) => slot,
            None => return false,
        };
        let entry = match self.slots[slot as usize].take() {
            Some(entry) => entry,
            None => return false,
        };
        if entry.large {
            Self::remove_from(&mut self.large, slot);
        } else {
            let (cx0, cx1, cy0, cy1) = Self::span(&entry.bounds);
            for cx in cx0..=cx1 {
                for cy in cy0..=cy1 {
                    if let Some(bucket) = self.cells.get_mut(&(cx, cy)) {
                        Self::remove_from(bucket, slot);
                        if bucket.is_empty() {
                            self.cells.remove(&(cx, cy));
                        }
                    }
                }
            }
        }
        self.free.push(slot);
        true
    }

    #[pyo3(signature = (x0, x1, y0, y1, skip=None))]
    fn query<'py>(
        &self,
        py: Python<'py>,
        x0: i64,
        x1: i64,
        y0: i64,
        y1: i64,
        skip: Option<&Bound<'py, PyAny>>,
    ) -> Bound<'py, PyList> {
        if self.by_ptr.is_empty() {
            return PyList::empty_bound(py);
        }
        let skip_ptr = skip.map(|s| s.as_ptr() as usize);
        let (cx0, cx1, cy0, cy1) = (x0 >> SHIFT, x1 >> SHIFT, y0 >> SHIFT, y1 >> SHIFT);
        let mut found: Vec<(u64, u32)> = Vec::new();

        let mut take = |slot: u32| {
            if let Some(entry) = &self.slots[slot as usize] {
                let b = &entry.bounds;
                if b[1] < x0 || b[0] > x1 || b[3] < y0 || b[2] > y1 {
                    return;
                }
                if Some(entry.obj.as_ptr() as usize) == skip_ptr {
                    return;
                }
                found.push((entry.order, slot));
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
            for (i, entry) in self.slots.iter().enumerate() {
                if entry.is_some() {
                    take(i as u32);
                }
            }
            dedupe = false;
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
        let items: Vec<Py<PyAny>> = found
            .iter()
            .filter_map(|&(_, slot)| {
                self.slots[slot as usize]
                    .as_ref()
                    .map(|entry| entry.obj.clone_ref(py))
            })
            .collect();
        PyList::new_bound(py, items)
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        for entry in self.slots.iter().flatten() {
            visit.call(&entry.obj)?;
        }
        Ok(())
    }

    fn __clear__(&mut self) {
        self.reset();
    }
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Grid>()?;
    m.add_class::<world::World>()?;
    m.add_function(wrap_pyfunction!(fit_rows, m)?)?;
    m.add_function(wrap_pyfunction!(contact_normal, m)?)?;
    m.add_function(wrap_pyfunction!(mtv, m)?)?;
    m.add_function(wrap_pyfunction!(contact_point, m)?)?;
    Ok(())
}
