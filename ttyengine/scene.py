import inspect
import math
import weakref
_ARGS = {}
def _argslen(cb):
    try:
        found = _ARGS.get(cb)
    except TypeError:
        return len(inspect.signature(cb).parameters)
    if found is None:
        if len(_ARGS) >= 256:
            _ARGS.clear()
        found = _ARGS[cb] = len(inspect.signature(cb).parameters)
    return found
def get_components(module):
    return [
        cls for _, cls in inspect.getmembers(module, inspect.isclass)
        if cls.__module__ == module.__name__ or cls.__module__.startswith(module.__name__ + '.')
    ]
def wrap_property(component_attr: str, prop: property) -> property:
    def fget(self):
        return prop.fget(getattr(self, component_attr))
    def fset(self, value):
        prop.fset(getattr(self, component_attr), value)
    return property(fget, fset if prop.fset else None)

from . import ansi
from . import axes as _ax
from . import sprite as _sprite
from . import region as _regions
from . import components as _components
from .ascii_styler import Styler
from .compositor import Compositor
from .broadphase import Broadphase
from .components.physics import _nat_begin, _nat_end
_comps = []
_attrs = {}
_temps = []
_allcomps = {}
_defls = []
for _cls in get_components(_components):
    defls = hasattr(_cls, '_owned')
    reqrs = hasattr(_cls, '_required')
    defl = hasattr(_cls, '_default')
    _allcomps[_cls] = _argslen(_cls)
    if defls or reqrs or defl:
        _comps.append(_cls)
        if defls:
            for _attr in _cls._owned:
                _attrs[_attr] = _cls
        if defl:
            if _cls._default: _defls.append(_cls)
    else:
        _temps.append(_cls)


def _findcomp(name):
    for comp, params in _allcomps.items():
        if comp.__name__ == name:
            return comp, params
    raise KeyError(f'Unknown component: {name!r}')

def _scopes():
    found = {}
    for cls in _comps:
        names = getattr(cls, '_settings', None)
        owned = getattr(cls, '_owned', None)
        if not names or not owned:
            continue
        aliases = getattr(cls, '_aliases', {})
        mapping = {name: aliases.get(name, name) for name in names}
        if all(flat in owned for flat in mapping.values()):
            found[cls.__name__] = (cls, mapping)
    return found
_scoped = _scopes()
_TURNS = frozenset(('xrotation', 'yrotation', 'zrotation', 'turns'))

def _expand(kwargs):
    if not any(name in kwargs for name in _scoped):
        return kwargs, ()
    flat = {}
    scoped = {}
    forced = []
    for key, value in kwargs.items():
        scope = _scoped.get(key)
        if scope is None or not (isinstance(value, dict) or (value is True and key not in scope[0]._owned)):
            flat[key] = value
            continue
        cls, mapping = scope
        forced.append(cls)
        if isinstance(value, dict):
            for name, val in value.items():
                if name not in mapping:
                    raise TypeError(f'unknown {key} setting: {name}')
                scoped[mapping[name]] = val
    flat.update(scoped)
    return flat, forced

def _comname(c):
    if isinstance(c, str):
        return c
    return c.__name__ if inspect.isclass(c) else type(c).__name__

_names = frozenset(_cls.__name__ for _cls in _allcomps)


def _note(com, key, value):
    changed = getattr(com, '_changed', None)
    if not changed:
        changed = com._changed = {key: value}
    else:
        changed[key] = value
    return changed

_versions = [0]


class _ObjList(list):
    rev = 0


def _tracked(name):
    base = getattr(list, name)
    def method(self, *args, **kwargs):
        self.rev += 1
        return base(self, *args, **kwargs)
    method.__name__ = name
    return method


for _name in ('append', 'extend', 'insert', 'remove', 'pop', 'clear', 'sort', 'reverse',
              '__setitem__', '__delitem__', '__iadd__', '__imul__'):
    setattr(_ObjList, _name, _tracked(_name))


class obj:
    __iter__ = None

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        if name in _names:
            _versions[0] += 1

    def __delattr__(self, name):
        object.__delattr__(self, name)
        if name in _names:
            _versions[0] += 1

    def __init__(self, scene):
        self.scene = scene
        self._ondiscardcb = []
        self._ghosts = []
        self._remote = False

    def _owner(self, key):
        if not isinstance(key, str):
            raise TypeError('object settings are looked up by name, not by %s' % type(key).__name__)
        comp = _attrs.get(key)
        if comp is None:
            comp = self._extra(key)
            if comp is None:
                raise KeyError(key)
        found = getattr(self, comp.__name__, None)
        if found is None:
            raise KeyError('%s belongs to the %s component, which this object does not have' % (key, comp.__name__))
        return found

    def __getitem__(self, key):
        return getattr(self._owner(key), key)

    def __setitem__(self, key, value):
        setattr(self._owner(key), key, value)

    def __contains__(self, key):
        try:
            self._owner(key)
        except KeyError:
            return False
        return True

    def _extra(self, key, value=None):
        if key in _TURNS:
            if value is None:
                return _attrs['x']
            ok = isinstance(value, dict) if key == 'turns' else isinstance(value, (int, float)) and not isinstance(value, bool)
            return _attrs['x'] if ok else None
        if key == 'sprite':
            return _attrs['x'] if isinstance(value, _sprite.sprite) else None
        if key == 'projected':
            return _attrs['x'] if isinstance(value, bool) else None
        index = self.scene._axes.index
        if key in index:
            return None if key in _attrs else _attrs['x']
        if key.endswith('vel') and key[:-3] in index:
            return None if key in _attrs else _attrs['xvel']
        return None

    def add(self, com, **kwargs):
        kwargs, _ = _expand(kwargs)
        if isinstance(com, str):
            comp, params = _findcomp(com)
        else:
            comp = com
            params = _argslen(com)
        if params > 1:
            compins = comp(self, **kwargs)
        elif params > 0:
            compins = comp(self)
        else:
            compins = comp()
        ow = getattr(compins, '_owned', None)
        ch = getattr(compins, '_changed', None)

        for k, v in kwargs.items():
            if ow and k in ow:
                val = getattr(compins, k, None)
                if val == v:
                    if not ch:
                        compins._changed = {k: v}
                        ch = compins._changed
                    else:
                        ch.update({k: v})
            elif k not in _attrs:
                own = self._extra(k, v)
                if own is None:
                    setattr(self, k, v)
                elif own is comp:
                    ch = _note(compins, k, v)

        compinsattr = comp.__name__
        setattr(self, compinsattr, compins)
        return compins

    def set(self, comn, **kwargs):
        kwargs, _ = _expand(kwargs)
        com = comn if isinstance(comn, (tuple, list)) else [comn]
        for c in com:
            if isinstance(c, str):
                c, _ = _findcomp(c)
            if inspect.isclass(c):
                if not hasattr(self, c.__name__):
                    for rcom in getattr(c, '_required', ()):
                        if not hasattr(self, rcom.__name__):
                            self.add(rcom, **kwargs)
                    self.add(c, **kwargs)
                c = getattr(self, c.__name__)
            ow = getattr(c, '_owned', None)
            ch = getattr(c, '_changed', None)
            for k, v in kwargs.items():
                if (ow and k in ow) or (not ow and hasattr(c, k)):
                    setattr(c, k, v)
                    if ow and k in ow:
                        if not ch:
                            c._changed = {k: v}
                            ch = c._changed
                        else:
                            ch.update({k: v})
                elif k not in _attrs:
                    own = self._extra(k, v)
                    if own is None:
                        setattr(self, k, v)
                    elif own is type(c):
                        setattr(c, k, v)
                        ch = _note(c, k, v)

    def kwargs(self, coms=None):
        if coms is None:
            names = None
        else:
            if isinstance(coms, str) or inspect.isclass(coms):
                coms = [coms]
            names = {_comname(c) for c in coms}
        result = {}
        for at, cl in _attrs.items():
            if names is not None and cl.__name__ not in names:
                continue
            com = getattr(self, cl.__name__, None)
            changed = getattr(com, '_changed', None)
            if at in result or not com or not changed: continue
            result.update({k: getattr(com, k) for k in changed})
        return result

    def clone(self, coms=None, **overrides):
        kwargs = self.kwargs(coms)
        kwargs.update(overrides)
        return self.scene.obj().create(**kwargs)

    def _ensure(self, comp, kwargs, processed):
        if comp in processed:
            return
        if not hasattr(self, comp.__name__):
            for rcom in getattr(comp, '_required', ()):
                if rcom not in processed:
                    if not hasattr(self, rcom.__name__):
                        self.add(rcom, **kwargs)
                    else:
                        self.set(rcom, **kwargs)
                    processed.add(rcom)
            self.add(comp, **kwargs)
        else:
            self.set(comp, **kwargs)
        processed.add(comp)

    def create(self, text=None, x=None, y=None, **kwargs):
        kwargs.update({k: v for k, v in {'text': text, 'x': x, 'y': y}.items() if v is not None})
        kwargs, forced = _expand(kwargs)
        processed = set()

        for com in _defls:
            self._ensure(com, kwargs, processed)

        for k in list(kwargs.keys()):
            comp = _attrs.get(k)
            if comp:
                self._ensure(comp, kwargs, processed)
            else:
                own = self._extra(k, kwargs[k])
                if own is None:
                    setattr(self, k, kwargs[k])
                else:
                    self._ensure(own, kwargs, processed)

        for comp in forced:
            self._ensure(comp, kwargs, processed)

        if self not in self.scene.objs:
            self.scene.objs.append(self)
        return self

    def ondiscard(self, callback):
        self._ondiscardcb.append(callback)
        return callback

    def offdiscard(self, callback):
        self._ondiscardcb = [cb for cb in self._ondiscardcb if cb is not callback]

    def discard(self, clean=True):
        for dscb in list(self._ondiscardcb):
            dscb()
        self._ondiscardcb = []
        owned = []
        for co in _allcomps:
            own = getattr(self, co.__name__, None)
            if own is None: continue
            owned.append((co.__name__, own))
        for _, com in owned:
            if hasattr(com, 'on_discard'):
                com.on_discard()
        if self in self.scene.objs:
            self.scene.objs.remove(self)
        for name, _ in owned:
            delattr(self, name)
        self.scene._getlast(True)


class Scene:
    @property
    def objs(self):
        return self._objs

    @objs.setter
    def objs(self, value):
        self._objs = value if isinstance(value, _ObjList) else _ObjList(value)
        self._roster_cache = None

    def _roster(self):
        key = (self._objs.rev, _versions[0])
        found = self._roster_cache
        if found is None or found[0] != key:
            snap = tuple(self._objs)
            phys = []
            trans = []
            joints = []
            tfs = []
            for i, o in enumerate(snap):
                if getattr(o, 'physics', None) is not None:
                    phys.append(i)
                tf = getattr(o, 'transform', None)
                if tf is not None:
                    trans.append(i)
                    tfs.append(tf)
                if getattr(o, 'joint', None) is not None or getattr(o, 'light', None) is not None:
                    joints.append(i)
            found = self._roster_cache = (key, snap, phys, trans, joints, tfs)
        return found

    def __init__(self):
        self.objs = []
        self.dinfo = []
        self.pending = []
        self._maxframerate = 60
        self.framerate = 60
        self._oncamcb = {}
        self._ondimcb = {}
        self._ondimoffsetcb = {}
        self._firing = False
        self.termx = 120
        self.termy = 30
        self._dimx = self.termx
        self._dimy = self.termy
        self._dimxoffset = 0
        self._dimyoffset = 0
        self._last = {}
        self._getlast(True)
        self.solids = []
        self._broad = Broadphase(self)
        self.gravity = (0, 0)
        self.drag = 1
        self.precision = 0.5
        self.bouncethreshold = 0.25
        self.aspect = 0.5
        self.lights = []
        self.ambient = 1.0
        self._axes = _ax.DEFAULT
        self._camx = 0
        self._camy = 0
        self._camext = [0]
        self._camrotation = 0.0
        self._camturn = {}
        self._perspective = 0.0
        self._renderdistance = 0.0
        self._fog = 0.0
        self._fogstart = 0.0
        self._fogcolor = None
        self._spun = weakref.WeakSet()
        self._bgcolor = (0, 0, 0)
        self._fade = None
        self._ticks = 0
        self._compositor = None
        self.fgcolor = (204, 204, 204)
        self.styler = Styler(self)
        self.recomp = ansi.SEQUENCE
        self._lastz = 0
        self._firstz = 0
        self._solidaxes = ()

    @property
    def dimx(self):
        return self._dimx
    @dimx.setter
    def dimx(self, value):
        old = self._dimx
        self._dimx = self.iround(value)
        if self._dimx != old:
            self._fire(self._ondimcb, 'x', old)

    @property
    def dimy(self):
        return self._dimy
    @dimy.setter
    def dimy(self, value):
        old = self._dimy
        self._dimy = self.iround(value)
        if self._dimy != old:
            self._fire(self._ondimcb, 'y', old)

    @property
    def dimxoffset(self):
        return self._dimxoffset
    @dimxoffset.setter
    def dimxoffset(self, value):
        old = self._dimxoffset
        self._dimxoffset = self.iround(value)
        if self._dimxoffset != old:
            self._fire(self._ondimoffsetcb, 'x', old)

    @property
    def dimyoffset(self):
        return self._dimyoffset
    @dimyoffset.setter
    def dimyoffset(self, value):
        old = self._dimyoffset
        self._dimyoffset = self.iround(value)
        if self._dimyoffset != old:
            self._fire(self._ondimoffsetcb, 'y', old)

    @property
    def canvas(self):
        return (self.termx, self.termy)
    @canvas.setter
    def canvas(self, value):
        self.termx, self.termy = (max(0, self.iround(v)) for v in value)

    @property
    def view(self):
        return _regions.Region(self._dimxoffset, -self._dimyoffset, self._dimx, self._dimy)
    @view.setter
    def view(self, value):
        x, y, w, h = _regions.resolve(value, self.termx, self.termy)
        self.dimxoffset = x
        self.dimyoffset = -y
        self.dimx = w
        self.dimy = h

    @property
    def framerate(self):
        return self._framerate
    @framerate.setter
    def framerate(self, value):
        if not value > 0:
            raise ValueError('framerate must be positive')
        self._framerate = min(self._maxframerate, value)

    @property
    def maxframerate(self):
        return self._maxframerate
    @maxframerate.setter
    def maxframerate(self, value):
        if not value > 0:
            raise ValueError('maxframerate must be positive')
        self._maxframerate = value
        self._framerate = min(value, self._framerate)

    @property
    def bgcolor(self):
        return self._bgcolor
    @bgcolor.setter
    def bgcolor(self, value):
        self._bgcolor = self._color(value)
        self._getlast(True)

    @property
    def fading(self):
        return self._fade is not None

    def _color(self, value):
        if isinstance(value, (int, float)):
            value = int(value)
            return (value, value, value)
        color = Styler.rgb(tuple(value) if isinstance(value, list) else value)
        if color is None:
            raise ValueError('unknown color: %r' % (value,))
        return color

    def fade(self, color, time=1, delay=0, start=None, callback=None, ease='linear'):
        if time < 0 or delay < 0:
            raise ValueError('time and delay must not be negative')
        curve = _components._easing(ease)
        target = self._color(color)
        origin = self._color(self._bgcolor if start is None else start)
        if start is not None:
            self._fade = None
            self.bgcolor = origin
        self._fade = {'from': origin, 'to': target, 'time': time, 'delay': delay,
                      'elapsed': 0.0, 'cb': callback, 'ease': curve}
        if time <= 0 and delay <= 0:
            self._finishfade()
        return self

    def unfade(self, finish=False):
        f = self._fade
        self._fade = None
        if f is not None and finish:
            self.bgcolor = f['to']
        return self

    def _finishfade(self):
        f = self._fade
        self._fade = None
        self.bgcolor = f['to']
        cb = f['cb']
        if callable(cb):
            if _argslen(cb):
                cb(self)
            else:
                cb()

    def tick(self, physics=True):
        objs = self._objs
        if physics:
            key, snap, phys = self._roster()[:3]
            _nat_begin(self)
            try:
                for n, i in enumerate(phys):
                    o = snap[i]
                    phy = getattr(o, 'physics', None)
                    if phy is not None and phy.dynamic and not o._remote:
                        phy.physics()
                        if (objs.rev, _versions[0]) != key:
                            for o in snap[i + 1:]:
                                phy = getattr(o, 'physics', None)
                                if phy is not None and phy.dynamic and not o._remote:
                                    phy.physics()
                            break
            finally:
                _nat_end(self)
        self._ticks += 1
        self._tickfade()
        key, snap, _, trans, _, tfs = self._roster()
        for n, i in enumerate(trans):
            tf = tfs[n]
            if tf._fade is None and tf._anim is None:
                continue
            tf = getattr(snap[i], 'transform', None)
            if tf is not None:
                tf._tick()
                if (objs.rev, _versions[0]) != key:
                    for o in snap[i + 1:]:
                        tf = getattr(o, 'transform', None)
                        if tf is not None:
                            tf._tick()
                    break
        key, snap, _, _, joints, _ = self._roster()
        for i in joints:
            o = snap[i]
            jnt = getattr(o, 'joint', None)
            if physics and jnt is not None and not o._remote:
                jnt.step()
            lgt = getattr(o, 'light', None)
            if lgt is not None:
                lgt.step()
            if (objs.rev, _versions[0]) != key:
                for o in snap[i + 1:]:
                    jnt = getattr(o, 'joint', None)
                    if physics and jnt is not None and not o._remote:
                        jnt.step()
                    lgt = getattr(o, 'light', None)
                    if lgt is not None:
                        lgt.step()
                break

    @property
    def compositor(self):
        if self._compositor is None:
            self._compositor = Compositor()
        return self._compositor

    def render(self, region=None, outer=None, autobg=True, full=False):
        comp = self.compositor
        if full:
            comp.invalidate()
        x, y, w, h = region if region is not None else (0, 0, self.termx, self.termy)
        return comp.compose([self], [self], (x, y, w, h), (x + w, y + h), outer, autobg)

    def _tickfade(self):
        f = self._fade
        if f is None:
            return
        dt = 1 / self.framerate
        if f['delay'] > 0:
            f['delay'] -= dt
            if f['delay'] > 0:
                return
            dt = -f['delay']
            f['delay'] = 0
        f['elapsed'] += dt
        if f['elapsed'] >= f['time']:
            self._finishfade()
            return
        p = f['ease'](f['elapsed'] / f['time'])
        self.bgcolor = tuple(max(0, min(255, int(a + (b - a) * p))) for a, b in zip(f['from'], f['to']))

    @property
    def camx(self):
        return self._camx
    @camx.setter
    def camx(self, value):
        old = self._camx
        self._camx = value
        if value != old:
            self._fire(self._oncamcb, 'x', old)

    @property
    def camy(self):
        return self._camy
    @camy.setter
    def camy(self, value):
        old = self._camy
        self._camy = value
        if value != old:
            self._fire(self._oncamcb, 'y', old)

    @property
    def cam(self):
        return (self._camx, self._camy) + tuple(self._camext)
    @cam.setter
    def cam(self, value):
        value = list(value)
        names = self._axes.names
        if not 2 <= len(value) <= len(names):
            raise ValueError('cam takes between 2 and %d values, got %d' % (len(names), len(value)))
        self.camx = value[0]
        self.camy = value[1]
        ext = self._camext
        for i, val in enumerate(value[2:]):
            old = ext[i]
            ext[i] = val
            if val != old:
                self._fire(self._oncamcb, names[i + 2], old)

    @property
    def axes(self):
        return self._axes
    @axes.setter
    def axes(self, value):
        new = _ax.get(value)
        if new is self._axes:
            return
        self._axes = new
        n = new.n
        ext = self._camext
        if len(ext) < n - 2:
            ext.extend([0] * (n - 2 - len(ext)))
        else:
            del ext[n - 2:]
        self._solidaxes = tuple([i for i in self._solidaxes if i < n])
        for plane in [k for k in self._camturn if max(k) >= n]:
            del self._camturn[plane]
        for o in self.objs:
            for name in ('transform', 'physics'):
                com = getattr(o, name, None)
                if com is not None:
                    com._fit(n)

    @property
    def solidaxes(self):
        return tuple([_ax.NAMES[i] for i in self._solidaxes])
    @solidaxes.setter
    def solidaxes(self, value):
        if value is None:
            value = ()
        elif isinstance(value, (str, int)):
            value = (value,)
        found = []
        for name in value:
            i = _ax.NAMES.index(name) if isinstance(name, str) and name in _ax.NAMES else name
            if isinstance(i, bool) or not isinstance(i, int) or not 2 <= i < self._axes.n:
                raise ValueError('solid axes must be axes of the scene beyond x and y, got %r' % (name,))
            if i not in found:
                found.append(i)
        self._solidaxes = tuple(sorted(found))

    @property
    def camrotation(self):
        return self._camrotation
    @camrotation.setter
    def camrotation(self, value):
        old = self._camrotation
        self._camrotation = float(value) % 360.0
        if self._camrotation != old:
            self._fire(self._oncamcb, 'rotation', old)

    def _turn(self, plane, value, name):
        old = self._camturn.get(plane, 0.0)
        value = float(value) % 360.0
        if value:
            self._camturn[plane] = value
        else:
            self._camturn.pop(plane, None)
        if value != old:
            self._fire(self._oncamcb, name, old)

    @property
    def camxrotation(self):
        return self._camturn.get((1, 2), 0.0)
    @camxrotation.setter
    def camxrotation(self, value):
        self._turn((1, 2), value, 'xrotation')

    @property
    def camyrotation(self):
        return self._camturn.get((2, 0), 0.0)
    @camyrotation.setter
    def camyrotation(self, value):
        self._turn((2, 0), value, 'yrotation')

    @property
    def camzrotation(self):
        return self.camrotation
    @camzrotation.setter
    def camzrotation(self, value):
        self.camrotation = value

    @property
    def camturns(self):
        return {','.join([_ax.NAMES[i] for i in plane]): angle for plane, angle in self._camturn.items()}
    @camturns.setter
    def camturns(self, value):
        want = {}
        for key, angle in dict(value or {}).items():
            first, second = key.split(',')
            want[(_ax.NAMES.index(first), _ax.NAMES.index(second))] = angle
        for plane in [k for k in self._camturn if k not in want]:
            self.camturn(plane[0], plane[1], 0)
        for plane, angle in want.items():
            self.camturn(plane[0], plane[1], angle)

    def camturn(self, a, b, value=None):
        i = _ax.NAMES.index(a) if isinstance(a, str) else a
        j = _ax.NAMES.index(b) if isinstance(b, str) else b
        if i == j or not (0 <= i < self._axes.n and 0 <= j < self._axes.n):
            raise ValueError('a camera rotation needs two different axes of the scene')
        if (i, j) == (0, 1):
            if value is None:
                return self.camrotation
            self.camrotation = value
            return None
        if value is None:
            return self._camturn.get((i, j), 0.0)
        self._turn((i, j), value, _ax.NAMES[i] + _ax.NAMES[j] + 'rotation')
        return None

    @property
    def perspective(self):
        return self._perspective
    @perspective.setter
    def perspective(self, value):
        value = float(value or 0.0)
        if value < 0:
            raise ValueError('perspective is a focal distance and cannot be negative')
        old = self._perspective
        self._perspective = value
        if value != old:
            self._fire(self._oncamcb, 'perspective', old)

    def _distance(self, name, value):
        value = float(value or 0.0)
        if not value >= 0 or value == float('inf'):
            raise ValueError('%s is a distance and cannot be negative or infinite' % name)
        old = getattr(self, '_' + name)
        setattr(self, '_' + name, value)
        if value != old:
            self._fire(self._oncamcb, name, old)

    @property
    def renderdistance(self):
        return self._renderdistance
    @renderdistance.setter
    def renderdistance(self, value):
        self._distance('renderdistance', value)

    @property
    def fog(self):
        return self._fog
    @fog.setter
    def fog(self, value):
        self._distance('fog', value)

    @property
    def fogstart(self):
        return self._fogstart
    @fogstart.setter
    def fogstart(self, value):
        self._distance('fogstart', value)

    @property
    def fogcolor(self):
        return self._fogcolor
    @fogcolor.setter
    def fogcolor(self, value):
        value = None if value is None else tuple(value)
        if value is not None and (len(value) != 3 or not all(isinstance(v, (int, float)) and 0 <= v <= 255 for v in value)):
            raise ValueError('fogcolor is None or three numbers between 0 and 255')
        old = self._fogcolor
        self._fogcolor = value
        if value != old:
            self._fire(self._oncamcb, 'fogcolor', old)

    def projected(self):
        return bool(self._perspective or self._camturn or self._renderdistance or self._fog or any([t._turns for t in self._spun]))

    def _planes(self):
        found = [(0, 1, math.cos(math.radians(self._camrotation)), math.sin(math.radians(self._camrotation)))] if self._camrotation else []
        for (i, j), angle in sorted(self._camturn.items()):
            rad = math.radians(angle)
            found.append((i, j, math.cos(rad), math.sin(rad)))
        return found

    def focus(self, target):
        t = getattr(target, 'transform', target)
        if getattr(t, '_sprite', None) is not None:
            return t.center()
        pivot = getattr(t, 'pivot', None)
        if pivot is None:
            return target[0], target[1]
        return pivot()

    def _depthfocus(self, target):
        found = getattr(getattr(target, 'transform', target), 'centre', None)
        if found is not None:
            return found()[2:]
        return tuple(target[2:]) if isinstance(target, (tuple, list)) else ()

    def follow(self, target=None, y=None, smooth=1, offset=(0, 0), depth=None):
        deep = ()
        if target is None or isinstance(target, (int, float)):
            px, py = target, y
        else:
            px, py = self.focus(target)
            if self.projected() if depth is None else depth:
                deep = self._depthfocus(target)
        dx = dy = 0
        if px is not None:
            goal = px + offset[0] - self._dimx / 2
            dx = goal - self._camx
            dx = dx / smooth if smooth > 1 and abs(dx) > 0.01 else dx
        if py is not None:
            goal = py + offset[1] + self._dimy / 2
            dy = goal - self._camy
            dy = dy / smooth if smooth > 1 and abs(dy) > 0.01 else dy
        if dx:
            self.camx = self._camx + dx
        if dy:
            self.camy = self._camy + dy
        if deep:
            ext = self._camext
            goal = list(ext)
            for k in range(min(len(deep), len(ext))):
                step = deep[k] + (offset[k + 2] if len(offset) > k + 2 else 0) - ext[k]
                goal[k] = ext[k] + (step / smooth if smooth > 1 and abs(step) > 0.01 else step)
            self.cam = (self._camx, self._camy) + tuple(goal)
        return dx, dy

    def _fire(self, callbacks, att='', old=None):
        internal = self._firing
        self._firing = True
        try:
            for cb, params in list(callbacks.items()):
                if params > 2:
                    cb(att, old, internal)
                elif params > 1:
                    cb(att, old)
                elif params > 0:
                    cb(att)
                else:
                    cb()
        finally:
            self._firing = internal

    def _register_once(self, cb, store, once):
        match_att = once if isinstance(once, str) else None
        l = _argslen(cb)
        fired = [False]
        orig = cb
        def wrapped(att=None, old=None, internal=False):
            if fired[0]: return
            if match_att is not None and att != match_att: return
            fired[0] = True
            if wrapped in store:
                del store[wrapped]
            if l > 2: orig(att, old, internal)
            elif l > 1: orig(att, old)
            elif l > 0: orig(att)
            else: orig()
        wrapped.__wrapped__ = orig
        store[wrapped] = 3
        return wrapped

    def _register(self, callback, store, once):
        if once:
            self._register_once(callback, store, once)
        else:
            store[callback] = _argslen(callback)
        return callback

    @staticmethod
    def _unregister(store, callback):
        return {cb: pars for cb, pars in store.items()
                if cb is not callback and getattr(cb, '__wrapped__', None) is not callback}

    def oncam(self, callback, once=False):
        return self._register(callback, self._oncamcb, once)

    def offcam(self, callback):
        self._oncamcb = self._unregister(self._oncamcb, callback)

    def ondim(self, callback, once=False):
        return self._register(callback, self._ondimcb, once)

    def offdim(self, callback):
        self._ondimcb = self._unregister(self._ondimcb, callback)

    def ondimoffset(self, callback, once=False):
        return self._register(callback, self._ondimoffsetcb, once)

    def offdimoffset(self, callback):
        self._ondimoffsetcb = self._unregister(self._ondimoffsetcb, callback)

    def iround(self, x):
        return int((x + 0.5) // 1)

    def obj(self):
        return obj(self)

    def flush(self):
        for func in self.pending:
            func()
        self.pending = []

    def _getlast(self, none=False):
        for k,v in vars(self).items():
            if k.startswith('term') or k.startswith('_dim'):
                self._last[k] = v if not none else None

    def checkres(self, reg=True):
        changed = False
        for k,v in self._last.items():
            val = getattr(self, k)
            if val != v:
                changed = True
                if reg: self._last[k] = val
        return changed
