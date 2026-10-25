from .shared import _HOLD, _argslen, _closure_refs

class _metainit(type):
    def __new__(mcs, name, bases, attrs, **kwargs):
        init_val = kwargs.pop('init', None)
        cls = super().__new__(mcs, name, bases, attrs, **kwargs)
        if init_val:
            cls._target_init = init_val
        return cls
    def __call__(cls, *args, **kwargs):
        inst = super().__call__(*args, **kwargs)
        initfunc = getattr(cls, '_target_init', '_init')
        instinit = getattr(inst, initfunc, None)
        if instinit:
            instinit()
        return inst

class _change_callback(metaclass=_metainit, init='_chinit'):
    def _chinit(self):
        self._onchangecb = {}
        self._changing = False
        def cln():
            discarded = self.obj
            for other in self.obj.scene.objs:
                com = getattr(other, self.__class__.__name__, None)
                if other is discarded or not com or not hasattr(com, '_onchangecb'):
                    continue
                com._onchangecb = {
                    cb:par for cb,par in com._onchangecb.items()
                    if not _closure_refs(cb, discarded)
                }
        if not hasattr(self, 'on_discard'):
            self.on_discard = cln
        else:
            old_func = self.on_discard
            def cln_():
                try:
                    old_func(self) 
                except TypeError:
                    old_func()
                cln()
            self.on_discard = cln_

    def onchange(self, cb, once=False):
        if once:
            match_attr = once if isinstance(once, str) else None
            l = _argslen(cb)
            fired = [False]
            orig = cb
            def wrapped(attr=None, old=None, internal=False):
                if fired[0]: return
                if match_attr is not None and attr != match_attr: return
                fired[0] = True
                if wrapped in self._onchangecb:
                    del self._onchangecb[wrapped]
                if l > 2: orig(attr, old, internal)
                elif l > 1: orig(attr, old)
                elif l > 0: orig(attr)
                else: orig()
            cb = wrapped
            self._onchangecb[cb] = 3
        else:
            self._onchangecb[cb] = _argslen(cb)
        return cb

    def offchange(self, cb):
        self._onchangecb = {f:par for f,par in self._onchangecb.items() if f is not cb}

    def _change(self, attr, old):
        internal = self._changing
        self._changing = True
        try:
            for cb, l in list(self._onchangecb.items()):
                if l > 2:
                    cb(attr, old, internal)
                elif l > 1:
                    cb(attr, old)
                elif l > 0:
                    cb(attr)
                else:
                    cb()
        finally:
            self._changing = internal


class _lerpable:
    _angles = frozenset()
    _colors = frozenset()

    def _lerpbase(self, key):
        return None

    def _lerpkeep(self, key, value):
        return value

    @staticmethod
    def _lerpturn(current, target):
        return (target - current + 540) % 360 - 180

    def _lerpcolor(self, value):
        if isinstance(value, list):
            value = tuple(value)
        return self.scene.styler.rgb(value)

    def _lerpvalue(self, key, current, target, alpha):
        if key in self._colors:
            goal = self._lerpcolor(target)
            if goal is None:
                raise ValueError('unknown color: ' + repr(target))
            start = self._lerpbase(key) if current is None else self._lerpcolor(current)
            if start is None:
                return target if alpha >= 1 else _HOLD
            return tuple(int(round(a + (b - a) * alpha)) for a, b in zip(start, goal))
        if current is None:
            current = self._lerpbase(key)
        if (isinstance(current, (tuple, list)) and isinstance(target, (tuple, list))
                and len(current) == len(target)):
            parts = [self._lerpvalue(key, a, b, alpha) for a, b in zip(current, target)]
            if any(part is _HOLD for part in parts):
                return target if alpha >= 1 else _HOLD
            return type(current)(parts)
        numeric = (int, float)
        if (isinstance(current, numeric) and isinstance(target, numeric)
                and not isinstance(current, bool) and not isinstance(target, bool)):
            if key in self._angles:
                return current + self._lerpturn(current, target) * alpha
            return current + (target - current) * alpha
        return target if alpha >= 1 else _HOLD

    def lerp(self, weight=1, **kwargs):
        for key, target in kwargs.items():
            if not hasattr(self, key):
                raise AttributeError('%s has no attribute %r' % (type(self).__name__, key))
            if weight == 1:
                value = target
            else:
                value = self._lerpvalue(key, getattr(self, key), target, weight)
                if value is _HOLD:
                    continue
            setattr(self, key, self._lerpkeep(key, value))
        return self


class _keyed:
    __iter__ = None

    def _setting(self, key):
        if not isinstance(key, str):
            raise TypeError('%s settings are looked up by name, not by %s' % (type(self).__name__, type(key).__name__))
        if not hasattr(self, key):
            raise KeyError(key)
        return key

    def __getitem__(self, key):
        return getattr(self, self._setting(key))

    def __setitem__(self, key, value):
        setattr(self, self._setting(key), value)

    def __contains__(self, key):
        return isinstance(key, str) and hasattr(self, key)
