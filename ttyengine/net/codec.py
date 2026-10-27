import struct

from .errors import NetError, ProtocolError

_NONE, _FALSE, _TRUE, _INT, _FLOAT, _STR, _BYTES, _LIST, _TUPLE, _DICT, _REF, _SET = range(12)
_DOUBLE = struct.Struct('>d')
_DEPTH = 64


class Ref:
    __slots__ = ('nid',)

    def __init__(self, nid):
        self.nid = nid

    def __eq__(self, other):
        return isinstance(other, Ref) and other.nid == self.nid

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(('ttyengine.net.Ref', self.nid))

    def __repr__(self):
        return 'Ref(%d)' % self.nid


def _varint(out, number):
    while number > 0x7F:
        out.append((number & 0x7F) | 0x80)
        number >>= 7
    out.append(number)


def _put_none(out, value, ref, depth):
    out.append(_NONE)


def _put_bool(out, value, ref, depth):
    out.append(_TRUE if value else _FALSE)


def _put_int(out, value, ref, depth):
    out.append(_INT)
    number = value * 2 if value >= 0 else -value * 2 - 1
    if number < 0x80:
        out.append(number)
    else:
        _varint(out, number)


def _put_float(out, value, ref, depth):
    out.append(_FLOAT)
    out += _DOUBLE.pack(value)


def _put_str(out, value, ref, depth):
    data = value.encode('utf-8', 'surrogatepass')
    out.append(_STR)
    _varint(out, len(data))
    out += data


def _put_bytes(out, value, ref, depth):
    out.append(_BYTES)
    _varint(out, len(value))
    out += value


def _put_list(out, value, ref, depth):
    if depth > _DEPTH:
        raise NetError('value is nested too deeply to be shared')
    out.append(_LIST)
    _varint(out, len(value))
    depth += 1
    for item in value:
        _ENCODERS.get(type(item), _put_other)(out, item, ref, depth)


def _put_tuple(out, value, ref, depth):
    if depth > _DEPTH:
        raise NetError('value is nested too deeply to be shared')
    out.append(_TUPLE)
    _varint(out, len(value))
    depth += 1
    for item in value:
        _ENCODERS.get(type(item), _put_other)(out, item, ref, depth)


def _put_dict(out, value, ref, depth):
    if depth > _DEPTH:
        raise NetError('value is nested too deeply to be shared')
    out.append(_DICT)
    _varint(out, len(value))
    depth += 1
    for key, item in value.items():
        _ENCODERS.get(type(key), _put_other)(out, key, ref, depth)
        _ENCODERS.get(type(item), _put_other)(out, item, ref, depth)


def _put_set(out, value, ref, depth):
    if depth > _DEPTH:
        raise NetError('value is nested too deeply to be shared')
    out.append(_SET)
    _varint(out, len(value))
    depth += 1
    for item in value:
        _ENCODERS.get(type(item), _put_other)(out, item, ref, depth)


_ENCODERS = {
    type(None): _put_none,
    bool: _put_bool,
    int: _put_int,
    float: _put_float,
    str: _put_str,
    bytes: _put_bytes,
    bytearray: _put_bytes,
    list: _put_list,
    tuple: _put_tuple,
    dict: _put_dict,
    set: _put_set,
    frozenset: _put_set,
}


def _put(out, value, ref, depth):
    _ENCODERS.get(type(value), _put_other)(out, value, ref, depth)


def _put_other(out, value, ref, depth):
    nid = ref(value) if ref is not None else None
    if nid is not None:
        out.append(_REF)
        _varint(out, nid)
    elif isinstance(value, bool):
        _put_bool(out, value, ref, depth)
    elif isinstance(value, int):
        _put_int(out, int(value), ref, depth)
    elif isinstance(value, float):
        _put_float(out, float(value), ref, depth)
    elif isinstance(value, str):
        _put_str(out, str(value), ref, depth)
    elif isinstance(value, (bytes, bytearray)):
        _put_bytes(out, bytes(value), ref, depth)
    elif isinstance(value, tuple):
        _put_tuple(out, tuple(value), ref, depth)
    elif isinstance(value, list):
        _put_list(out, list(value), ref, depth)
    elif isinstance(value, dict):
        _put_dict(out, dict(value), ref, depth)
    elif isinstance(value, (set, frozenset)):
        _put_set(out, set(value), ref, depth)
    else:
        raise NetError('cannot share a value of type %s' % type(value).__name__)


def dumps(value, ref=None):
    out = bytearray()
    _put(out, value, ref, 0)
    return bytes(out)


def pack_list(encoded):
    out = bytearray()
    out.append(_LIST)
    _varint(out, len(encoded))
    for item in encoded:
        out += item
    return bytes(out)


def _read_varint(data, pos):
    byte = data[pos]
    if byte < 0x80:
        return byte, pos + 1
    shift = 0
    number = 0
    while True:
        byte = data[pos]
        pos += 1
        number |= (byte & 0x7F) << shift
        if byte < 0x80:
            return number, pos
        shift += 7
        if shift > 140:
            raise ProtocolError('number is too large')


def _get_none(data, pos, depth):
    return None, pos


def _get_false(data, pos, depth):
    return False, pos


def _get_true(data, pos, depth):
    return True, pos


def _get_int(data, pos, depth):
    number, pos = _read_varint(data, pos)
    return (number >> 1 if not number & 1 else -((number + 1) >> 1)), pos


def _get_float(data, pos, depth):
    return _DOUBLE.unpack_from(data, pos)[0], pos + 8


def _get_chunk(data, pos):
    size, pos = _read_varint(data, pos)
    end = pos + size
    if end > len(data):
        raise ProtocolError('truncated value')
    return bytes(data[pos:end]), end


def _get_str(data, pos, depth):
    chunk, pos = _get_chunk(data, pos)
    return chunk.decode('utf-8', 'surrogatepass'), pos


def _get_bytes(data, pos, depth):
    return _get_chunk(data, pos)


def _get_ref(data, pos, depth):
    nid, pos = _read_varint(data, pos)
    return Ref(nid), pos


def _get_items(data, pos, depth):
    if depth > _DEPTH:
        raise ProtocolError('value is nested too deeply')
    size, pos = _read_varint(data, pos)
    items = []
    depth += 1
    for _ in range(size):
        tag = data[pos]
        if tag >= _KINDS:
            raise ProtocolError('unknown value tag %d' % tag)
        item, pos = _DECODERS[tag](data, pos + 1, depth)
        items.append(item)
    return items, pos


def _get_list(data, pos, depth):
    return _get_items(data, pos, depth)


def _get_tuple(data, pos, depth):
    items, pos = _get_items(data, pos, depth)
    return tuple(items), pos


def _get_set(data, pos, depth):
    items, pos = _get_items(data, pos, depth)
    return set(items), pos


def _get_dict(data, pos, depth):
    if depth > _DEPTH:
        raise ProtocolError('value is nested too deeply')
    size, pos = _read_varint(data, pos)
    found = {}
    depth += 1
    for _ in range(size):
        tag = data[pos]
        if tag >= _KINDS:
            raise ProtocolError('unknown value tag %d' % tag)
        key, pos = _DECODERS[tag](data, pos + 1, depth)
        tag = data[pos]
        if tag >= _KINDS:
            raise ProtocolError('unknown value tag %d' % tag)
        item, pos = _DECODERS[tag](data, pos + 1, depth)
        found[key] = item
    return found, pos


_DECODERS = (_get_none, _get_false, _get_true, _get_int, _get_float, _get_str, _get_bytes, _get_list,
             _get_tuple, _get_dict, _get_ref, _get_set)
_KINDS = len(_DECODERS)


def _get(data, pos, depth):
    tag = data[pos]
    if tag >= _KINDS:
        raise ProtocolError('unknown value tag %d' % tag)
    return _DECODERS[tag](data, pos + 1, depth)


def loads(data):
    try:
        value, pos = _get(data, 0, 0)
    except (IndexError, struct.error, UnicodeDecodeError, TypeError) as exc:
        raise ProtocolError('malformed data: %s' % exc) from None
    if pos != len(data):
        raise ProtocolError('trailing bytes after value')
    return value
