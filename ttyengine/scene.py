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
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

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

    def create(self, text='', x=0, y=0, **kwargs):
        kwargs.update({'text': text, 'x': x, 'y': y})
        
        instance_cls = type(self.__class__.__name__, (self.__class__,), {})
        self.__class__ = instance_cls
        for com in _defls:
            if not hasattr(self, com.__name__):
                if hasattr(com, '_required'):
                    for rcom in com._required:
                        if not hasattr(self, rcom.__name__):
                            self.add(rcom, **kwargs)
                self.add(com, **kwargs)
        for k in kwargs:
            comp = _attrs.get(k)
            if comp and not hasattr(self, comp.__name__):
                if hasattr(comp, '_required'):
                    for rcomp in comp._required:
                        if not hasattr(self, rcomp.__name__):
                            self.add(rcomp, **kwargs)
                self.add(comp, **kwargs)

        self.scene.objs.append(self)
        return self


#SCENE CLASS
class Scene:
    def __init__(self):
        self.objs = []
        self.solids = []
        self.dinfo = []
        self.framerate = 60
        self.gravity = (0, -0.05)
        self.drag = 0.97
        self.precision = 0.1
        self.camx = 0
        self.camy = 0
        self.dimx = 120
        self.dimy = 30
        self.bgcolor = (0, 0, 0)
        self.recomp = re.compile(r'(\x1b\[[0-9;]*[a-zA-Z])')

    def obj(self):
        return obj(self)
