import inspect
def _argslen(cb):
    params = inspect.signature(cb).parameters
    return len(params)
def get_components(module):
    return [
        cls for _, cls in inspect.getmembers(module, inspect.isclass)
        if cls.__module__ == module.__name__
    ]
def wrap_property(component_attr: str, prop: property) -> property:
    def fget(self):
        return prop.fget(getattr(self, component_attr))
    def fset(self, value):
        prop.fset(getattr(self, component_attr), value)
    return property(fget, fset if prop.fset else None)

from . import ansi
from . import region as _regions
from . import components as _components
from .ascii_styler import Styler
from .compositor import Compositor
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


class obj:
    __iter__ = None

    def __init__(self, scene):
        self.scene = scene
        self._ondiscardcb = []
        self._ghosts = []

    def _owner(self, key):
        if not isinstance(key, str):
            raise TypeError('object settings are looked up by name, not by %s' % type(key).__name__)
        comp = _attrs.get(key)
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
                setattr(self, k, v)

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
                    setattr(self, k, v)

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
                setattr(self, k, kwargs[k])

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
        self.gravity = (0, 0)
        self.drag = 1
        self.precision = 0.5
        self.bouncethreshold = 0.25
        self.aspect = 0.5
        self.lights = []
        self.ambient = 1.0
        self._camx = 0
        self._camy = 0
        self._camrotation = 0.0
        self._bgcolor = (0, 0, 0)
        self._fade = None
        self._ticks = 0
        self._compositor = None
        self.fgcolor = (204, 204, 204)
        self.styler = Styler(self)
        self.recomp = ansi.SEQUENCE
        self._lastz = 0
        self._firstz = 0

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
        if physics:
            for o in list(self.objs):
                phy = getattr(o, 'physics', None)
                if phy is not None and phy.dynamic:
                    phy.physics()
        self._ticks += 1
        self._tickfade()
        for o in list(self.objs):
            tf = getattr(o, 'transform', None)
            if tf is not None:
                tf._tick()
        for o in list(self.objs):
            jnt = getattr(o, 'joint', None)
            if physics and jnt is not None:
                jnt.step()
            lgt = getattr(o, 'light', None)
            if lgt is not None:
                lgt.step()

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
    def camrotation(self):
        return self._camrotation
    @camrotation.setter
    def camrotation(self, value):
        old = self._camrotation
        self._camrotation = float(value) % 360.0
        if self._camrotation != old:
            self._fire(self._oncamcb, 'rotation', old)

    def focus(self, target):
        t = getattr(target, 'transform', target)
        pivot = getattr(t, 'pivot', None)
        if pivot is None:
            return target[0], target[1]
        return pivot()

    def follow(self, target=None, y=None, smooth=1, offset=(0, 0)):
        if target is None or isinstance(target, (int, float)):
            px, py = target, y
        else:
            px, py = self.focus(target)
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
