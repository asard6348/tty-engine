import re, inspect
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
_comps = []
_attrs = {}
_temps = []
_allcomps = []
_defls = []
for _cls in get_components(_components):
    defls = hasattr(_cls, '_owned')
    reqrs = hasattr(_cls, '_required')
    defl = hasattr(_cls, '_default')
    _allcomps.append(_cls)
    if defls or reqrs or defl:
        _comps.append(_cls)
        if defls:
            for _attr in _cls._owned:
                _attrs[_attr] = _cls
        if defl:
            if _cls._default: _defls.append(_cls)
    else:
        _temps.append(_cls)


#OBJ CLASS
class obj:
    def __init__(self, scene):
        self.scene = scene

    def __getitem__(self, key):
        return getattr(getattr(self, _attrs[key].__name__), key)

    def __setitem__(self, key, value):
        setattr(getattr(self, _attrs[key].__name__), key, value)

    def add(self, com, **kwargs):
        if isinstance(com, str):
            comp = [co for co in _allcomps if co.__name__ == com][0]
        else:
            comp = com
        if hasattr(comp, '__init__'):
            params = len(inspect.signature(comp.__init__).parameters)
        else:
            params = 0
        if params > 2:
            compins = comp(self, **kwargs)
        elif params > 1:
            compins = comp(self)
        else:
            compins = comp()
        compinsattr = comp.__name__
        setattr(self, compinsattr, compins)
        return compins

    def set(self, comn, **kwargs):
        com = [getattr(self, comn)] if isinstance(comn, str) else [getattr(self, comn.__name__)] if inspect.isclass(comn) else comn
        for c in com:
            for k,v in kwargs.items():
                if (hasattr(c, '_owned') and k in c._owned) or (not hasattr(c, '_owned') and hasattr(c, k)): 
                    setattr(c, k, v)

    def kwargs(self):
        result = {}
        for com_name in vars(self):
            com = getattr(self, com_name)
            if not hasattr(com, '_owned') or com.__class__.__name__ == 'transform':
                continue
            for k in com._owned:
                if hasattr(com, k):
                    result[k] = getattr(com, k)
        return result

    def clone(self, **overrides):
        kwargs = self.kwargs()
        kwargs.update(overrides)
        return self.scene.obj().create(**kwargs)

    def create(self, text=None, x=None, y=None, **kwargs):
        kwargs.update({k: v for k,v in {'text': text, 'x': x, 'y': y}.items() if v is not None})
        
        for com in _defls:
            if not hasattr(self, com.__name__):
                if hasattr(com, '_required'):
                    for rcom in com._required:
                        if not hasattr(self, rcom.__name__):
                            self.add(rcom, **kwargs)
                        else: self.set(rcom, **kwargs)
                self.add(com, **kwargs)
            else: self.set(com, **kwargs)
        for k in kwargs:
            comp = _attrs.get(k)
            if not hasattr(self, comp.__name__):
                if hasattr(comp, '_required'):
                    for rcomp in comp._required:
                        if not hasattr(self, rcomp.__name__):
                            self.add(rcomp, **kwargs)
                        else: self.set(rcomp, **kwargs)
                self.add(comp, **kwargs)
            else: self.set(comp, **kwargs)

        if not self in self.scene.objs:
            self.scene.objs.append(self)
        return self

    def discard(self, clean=True):
        owned = [(n, getattr(self, n)) for n in list(vars(self))
                 if hasattr(getattr(self, n), '_owned')]
        for _, com in owned:
            if hasattr(com, 'on_discard'):
                com.on_discard()
        if self in self.scene.objs:
            self.scene.objs.remove(self)
        for name, _ in owned:
            delattr(self, name)
        self.scene._getlast(True)


#SCENE CLASS
class Scene:
    def __init__(self):
        self.objs = []
        self.dinfo = []
        self.pending = []
        self._maxframerate = 60
        self.framerate = 60
        # resolution
        self.termx = 120
        self.termy = 30
        self.dimx = self.termx
        self.dimy = self.termy
        self.dimxoffset = 0
        self.dimyoffset = 0
        self._last = {}
        self._getlast(True)
        # physics
        self.solids = []
        self.gravity = (0, -0.05)
        self.drag = 0.97
        self.precision = 0.1
        # rendering
        self.camx = 0
        self.camy = 0
        self._bgcolor = (0, 0, 0)
        self.recomp = re.compile(r'(\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07?|\x1b[()]?[A-Za-z0-9])')

    @property
    def dimx(self):
        return self._dimx
    @dimx.setter
    def dimx(self, value):
        self._dimx = self.iround(value)

    @property
    def dimy(self):
        return self._dimy
    @dimy.setter
    def dimy(self, value):
        self._dimy = self.iround(value)

    @property
    def dimxoffset(self):
        return self._dimxoffset
    @dimxoffset.setter
    def dimxoffset(self, value):
        self._dimxoffset = self.iround(value)

    @property
    def dimyoffset(self):
        return self._dimyoffset
    @dimyoffset.setter
    def dimyoffset(self, value):
        self._dimyoffset = self.iround(value)

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
