LIMIT = 32
_POOL = ('x', 'y', 'z', 'w')
_cache = {}
_index = {}


def name(i):
    return _POOL[i] if i < len(_POOL) else 'a%d' % i


NAMES = tuple(name(i) for i in range(LIMIT))
FREE = frozenset(NAMES[2:])


class axes(tuple):
    __slots__ = ()
    n = property(tuple.__len__)
    names = property(lambda self: self)

    @property
    def index(self):
        return _index[len(self)]


def get(spec):
    if isinstance(spec, axes):
        return spec
    if isinstance(spec, (tuple, list)):
        found = tuple(spec)
        if found != NAMES[:len(found)]:
            raise ValueError('axes must be named %s in order' % ', '.join(NAMES[:4]))
        spec = len(found)
    if isinstance(spec, bool) or not isinstance(spec, int):
        raise TypeError('axes must be a count or a sequence of axis names')
    if not 3 <= spec <= LIMIT:
        raise ValueError('axes must number between 3 and %d' % LIMIT)
    found = _cache.get(spec)
    if found is None:
        found = _cache[spec] = axes(NAMES[:spec])
        _index[spec] = {key: i for i, key in enumerate(found)}
    return found


DEFAULT = get(3)
