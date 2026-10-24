import re
from collections import namedtuple

Region = namedtuple('Region', 'x y width height')

_PERCENT = re.compile(r'^\s*(-?\d+(?:\.\d+)?)\s*%\s*$')
_NUMBER = re.compile(r'^\s*-?\d+(?:\.\d+)?\s*$')
_ALIGNS = ('start', 'center', 'end')
_KEYS = {
    'x': 'x', 'left': 'x', 'y': 'y', 'top': 'y',
    'width': 'width', 'w': 'width', 'height': 'height', 'h': 'height',
    'right': 'right', 'bottom': 'bottom',
}


def _number(value):
    if isinstance(value, bool):
        raise ValueError('region values must be numbers, percentages or alignments, not %r' % (value,))
    if isinstance(value, (int, float)):
        if value != value or value in (float('inf'), float('-inf')):
            raise ValueError('region values must be finite, got %r' % (value,))
        return int(round(value))
    if isinstance(value, str) and _NUMBER.match(value):
        return int(round(float(value)))
    return None


def _clean(value, name, aligned):
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if _PERCENT.match(text):
            return text.replace(' ', '')
        if aligned and text in _ALIGNS + ('cursor',):
            return text
    number = _number(value)
    if number is None:
        raise ValueError('invalid region %s: %r' % (name, value))
    return number


def parse(spec):
    if spec is None:
        return Region(0, 0, None, None)
    if isinstance(spec, dict):
        unknown = [k for k in spec if k not in _KEYS]
        if unknown:
            raise ValueError('unknown region key(s): %s' % ', '.join(map(str, unknown)))
        merged = {}
        for key, value in spec.items():
            target = _KEYS[key]
            if target in merged and merged[target] != value:
                raise ValueError('region key %r given twice' % (key,))
            merged[target] = value
        x, y = merged.get('x'), merged.get('y')
        width, height = merged.get('width'), merged.get('height')
        right, bottom = merged.get('right'), merged.get('bottom')
        x, width = _anchor(x, width, right, 'right', 'width')
        y, height = _anchor(y, height, bottom, 'bottom', 'height')
    else:
        try:
            x, y, width, height = spec
        except (TypeError, ValueError):
            raise ValueError('a region is None, a dict or (x, y, width, height), got %r' % (spec,)) from None
    return Region(
        _clean(x, 'x', True) if x is not None else 0,
        _clean(y, 'y', True) if y is not None else 0,
        _clean(width, 'width', False),
        _clean(height, 'height', False),
    )


def _anchor(pos, size, inset, inset_name, size_name):
    if inset is None:
        return pos, size
    inset = _number(inset)
    if inset is None or inset < 0:
        raise ValueError('%s must be a non-negative number of cells' % inset_name)
    if size is None:
        return pos, -inset
    size_cells = _number(size)
    if pos is not None or size_cells is None:
        raise ValueError('%s with %s needs a numeric %s and no explicit start' % (inset_name, size_name, size_name))
    return -(inset + size_cells), size_cells


def _fraction(text, total):
    return int(round(total * float(_PERCENT.match(text).group(1)) / 100.0))


def _axis(pos, size, total, cursor):
    if pos in ('center', 'end'):
        if size is None:
            length = total
        elif isinstance(size, str):
            length = _fraction(size, total)
        elif size < 0:
            length = total + size
        else:
            length = size
        length = max(0, min(length, total))
        start = (total - length) // 2 if pos == 'center' else total - length
        return start, length
    if pos == 'start' or pos is None:
        start = 0
    elif pos == 'cursor':
        start = cursor
    elif isinstance(pos, str):
        start = _fraction(pos, total)
        if start < 0:
            start += total
    else:
        start = pos + total if pos < 0 else pos
    start = max(0, min(start, total))
    room = total - start
    if size is None:
        length = room
    elif isinstance(size, str):
        length = _fraction(size, total)
    elif size < 0:
        length = room + size
    else:
        length = size
    return start, max(0, min(length, room))


def resolve(spec, width, height, cursor=0):
    x, y, w, h = parse(spec)
    rx, rw = _axis(x, w, max(0, int(width)), 0)
    ry, rh = _axis(y, h, max(0, int(height)), cursor)
    return Region(rx, ry, rw, rh)


def is_default(spec):
    return parse(spec) == Region(0, 0, None, None)


def uses_cursor(spec):
    return parse(spec).y == 'cursor'


def full():
    return Region(0, 0, None, None)


def line(row=0):
    return Region(0, row, None, 1)


def column(col=0):
    return Region(col, 0, 1, None)


def top(rows=1):
    return Region(0, 0, None, rows)


def bottom(rows=1):
    return Region(0, -rows, None, rows)


def left(columns=1):
    return Region(0, 0, columns, None)


def right(columns=1):
    return Region(-columns, 0, columns, None)


def box(x, y, width, height):
    return Region(x, y, width, height)


def centered(width, height):
    return Region('center', 'center', width, height)


def inline(rows=1):
    return Region(0, 'cursor', None, rows)
