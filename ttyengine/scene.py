import re, inspect
def _argslen(cb):
    params = inspect.signature(cb).parameters
    l = len(params) - (1 if hasattr(cb, '__self__') else 0)
    return l
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

from . import components as _components
from .ascii_styler import Styler
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


class obj:
    def __init__(self, scene):
        self.scene = scene
        self._ondiscardcb = []

    def __getitem__(self, key):
        return getattr(getattr(self, _attrs[key].__name__), key)

    def __setitem__(self, key, value):
        setattr(getattr(self, _attrs[key].__name__), key, value)

    def add(self, com, **kwargs):
        if isinstance(com, str):
            comp, params = {co: pars for co, pars in _allcomps.items() if co.__name__ == com}.items()[0]
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
        com = comn if isinstance(comn, (tuple, list)) else [comn]
        for c in com:
            c = getattr(self, c) if isinstance(c, str) else getattr(self, c.__name__) if inspect.isclass(c) else c
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

    def kwargs(self):
        result = {}
        for at, cl in _attrs.items():
            com = getattr(self, cl.__name__, None)
            if at in result or not com or not hasattr(com, '_changed'): continue
            result.update({k: getattr(com, k) for k in com._changed})
        return result

    def clone(self, **overrides):
        kwargs = self.kwargs()
        kwargs.update(overrides)
        return self.scene.obj().create(**kwargs)

    def create(self, text=None, x=None, y=None, **kwargs):
        kwargs.update({k: v for k, v in {'text': text, 'x': x, 'y': y}.items() if v is not None})
        processed = set()

        for com in _defls:
            if com not in processed:
                if not hasattr(self, com.__name__):
                    if hasattr(com, '_required'):
                        for rcom in com._required:
                            if rcom not in processed:
                                if not hasattr(self, rcom.__name__):
                                    self.add(rcom, **kwargs)
                                else:
                                    self.set(rcom, **kwargs)
                                processed.add(rcom)
                    self.add(com, **kwargs)
                else: 
                    self.set(com, **kwargs)
                processed.add(com)

        for k in list(kwargs.keys()):
            comp = _attrs.get(k)
            if comp:
                if comp not in processed:
                    if not hasattr(self, comp.__name__):
                        if hasattr(comp, '_required'):
                            for rcomp in comp._required:
                                if rcomp not in processed:
                                    if not hasattr(self, rcomp.__name__):
                                        self.add(rcomp, **kwargs)
                                    else: 
                                        self.set(rcomp, **kwargs)
                                    processed.add(rcomp)
                        self.add(comp, **kwargs)
                    else: 
                        self.set(comp, **kwargs)
                    processed.add(comp)
            else:
                setattr(self, k, kwargs[k])

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
        self.discards = []
        self.dirtyrects = []
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
        self.gravity = (0, -0.05)
        self.drag = 0.97
        self.precision = 0.1
        self._camx = 0
        self._camy = 0
        self._bgcolor = (0, 0, 0)
        self.fgcolor = (204, 204, 204)
        self.styler = Styler(self)
        self.recomp =re.compile(r'(\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07?|\x1b[()]?[A-Za-z0-9])')
        self._lastz = 0
        self._firstz = 0

    @property
    def dimx(self):
        return self._dimx
    @dimx.setter
    def dimx(self, value):
        old = self._dimx
        self._dimx = self.iround(value)
        self._fire(self._ondimcb, 'x', old)

    @property
    def dimy(self):
        return self._dimy
    @dimy.setter
    def dimy(self, value):
        old = self._dimy
        self._dimy = self.iround(value)
        self._fire(self._ondimcb, 'y', old)

    @property
    def dimxoffset(self):
        return self._dimxoffset
    @dimxoffset.setter
    def dimxoffset(self, value):
        old = self._dimxoffset
        self._dimxoffset = self.iround(value)
        self._fire(self._ondimoffsetcb, 'x', old)

    @property
    def dimyoffset(self):
        return self._dimyoffset
    @dimyoffset.setter
    def dimyoffset(self, value):
        old = self._dimyoffset
        self._dimyoffset = self.iround(value)
        self._fire(self._ondimoffsetcb, 'y', old)

    @property
    def framerate(self):
        return self._framerate
    @framerate.setter
    def framerate(self, value):
        self._framerate = min(self._maxframerate, value)

    @property
    def maxframerate(self):
        return self._maxframerate
    @maxframerate.setter
    def maxframerate(self, value):
        self._maxframerate = value
        self._framerate = min(value, self._framerate)

    @property
    def bgcolor(self):
        return self._bgcolor
    @bgcolor.setter
    def bgcolor(self, value):
        self._bgcolor = (int(value),int(value),int(value)) if isinstance(value, (int,float)) else value
        self._getlast(True)

    @property
    def camx(self):
        return self._camx
    @camx.setter
    def camx(self, value):
        old = self._camx
        self._camx = value
        self._fire(self._oncamcb, 'x', old)

    @property
    def camy(self):
        return self._camy
    @camy.setter
    def camy(self, value):
        old = self._camy
        self._camy = value
        self._fire(self._oncamcb, 'y', old)

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
        store[wrapped] = 3
        return wrapped

    def oncam(self, callback):
        self._oncamcb[callback] = _argslen(callback)
        return callback

    def offcam(self, callback):
        self._oncamcb = {cb: pars for cb, pars in self._oncamcb.items() if cb is not callback}

    def ondim(self, callback):
        self._ondimcb[callback] = _argslen(callback)
        return callback

    def offdim(self, callback):
        self._ondimcb = {cb: pars for cb, pars in self._ondimcb.items() if cb is not callback}

    def ondimoffset(self, callback):
        self._ondimoffsetcb[callback] = _argslen(callback)
        return callback

    def offdimoffset(self, callback):
        self._ondimoffsetcb = {cb: pars for cb, pars in self._ondimoffsetcb.items() if cb is not callback}

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
