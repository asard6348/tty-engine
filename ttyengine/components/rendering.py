from .inherit import _lerpable
from .transform import transform
from .light import light

class rendering(_lerpable):
    _owned = ['show', 'renderspaces', 'z']
    _required = [transform]
    _default = True
    _settings = ('show', 'spaces', 'z')
    _aliases = {'spaces': 'renderspaces'}

    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.t = obj.transform
        self.scene = obj.scene
        self._litkey = None
        self._lit = ''
        self.show = kwargs.get('show', True)
        self.renderspaces = kwargs.get('renderspaces', False)
        self.z = kwargs.get('z', 0)

    @property
    def z(self):
        return self._z

    @z.setter
    def z(self, value):
        self._z = value
        if self._z > self.scene._lastz: self.scene._lastz = self._z
        if self._z < self.scene._firstz: self.scene._firstz = self._z

    @property
    def spaces(self):
        return self.renderspaces
    @spaces.setter
    def spaces(self, value):
        self.renderspaces = value

    def _shown(self):
        self.t._stylecheck()
        text = self.t.vtext
        sc = self.scene
        if not text or (not sc.lights and sc.ambient >= 1):
            return text
        lights = tuple((id(l), l._version) for l in sc.lights if l.on and l._affects(self.obj))
        key = (text, self.t._origin(), sc.ambient, sc.bgcolor, sc.fgcolor, lights)
        if self._litkey != key:
            self._litkey = key
            self._lit = light.shade(sc, self.obj, text)
        return self._lit

    def state(self, camx, camy, xoff, yoff):
        if not self.show:
            return (0, 0, '', 0, 0)
        t = self.t
        return (
            int((t.x + t.vx - camx + 0.5) // 1),
            -int((t.y + t.vy - camy + 0.5) // 1),
            self._shown(),
            xoff,
            yoff,
        )

    def front(self):
        self.z = self.scene._lastz +1

    def back(self):
        self.z = self.scene._firstz -1
