from operator import attrgetter

from .. import scene as _scene
from ..components import force, joint, light, pen, physics, transform


class Spec:
    def __init__(self, cls, names, ctor, getters=None, setters=None, extra=None, prepare=None, deferred=()):
        self.cls = cls
        self.name = cls.__name__
        self.names = tuple(names)
        self.ctor = dict(ctor)
        self.getters = getters or {}
        self.setters = setters or {}
        self.extra = extra or {}
        self.custom = prepare
        self.deferred = frozenset(deferred)

    def get(self, comp, var):
        getter = self.getters.get(var)
        return getter(comp) if getter is not None else getattr(comp, var)

    def put(self, comp, var, value):
        setter = self.setters.get(var)
        if setter is not None:
            setter(comp, value)
        else:
            setattr(comp, var, value)

    def prepare(self, values, scene):
        if self.custom is not None:
            return self.custom(self, values, scene)
        flat = {}
        late = {}
        for var, value in values.items():
            owned = self.ctor.get(var)
            if owned is not None:
                flat[owned] = value
            else:
                late[var] = value
        flat.update(self.extra)
        return flat, late


def _default(cls, names=None, **kwargs):
    names = tuple(cls._settings if names is None else names)
    aliases = getattr(cls, '_aliases', {})
    owned = set(getattr(cls, '_owned', ()))
    ctor = {name: aliases.get(name, name) for name in names if aliases.get(name, name) in owned}
    return Spec(cls, names, ctor, **kwargs)


def _transform_prepare(spec, values, scene):
    flat = {}
    late = {}
    for var, value in values.items():
        owned = spec.ctor.get(var)
        if owned is not None:
            flat[owned] = value
        else:
            late[var] = value
    raw = late.pop('rtext', None)
    if raw is not None:
        flat['text'] = raw
        if late.get('htext') == scene.recomp.sub('', raw):
            del late['htext']
    return flat, late


def _transform_spec():
    names = ('x', 'y', 'htext', 'rtext', 'rotation', 'aspect', 'fg', 'bg', 'alpha', 'bgalpha',
             'flip', 'shadow', 'show', 'spaces', 'z')
    ctor = {'x': 'x', 'y': 'y', 'rotation': 'rotation', 'aspect': 'aspect', 'fg': 'fg', 'bg': 'bg',
            'alpha': 'alpha', 'bgalpha': 'bgalpha', 'flip': 'flip', 'shadow': 'shadow', 'show': 'show',
            'spaces': 'renderspaces', 'z': 'z'}
    getters = {
        'htext': lambda comp: comp._htext,
        'rtext': lambda comp: comp._vbase,
        'aspect': lambda comp: comp._aspect,
    }
    return Spec(transform, names, ctor, getters=getters, prepare=_transform_prepare)


def _links_get(comp):
    return tuple((edge.origin.obj, edge.collide) for edge in comp._edges.values()
                 if edge.alive and edge.follower is comp)


def _links_put(comp, value):
    wanted = [(item[0], item[1]) for item in value]
    keep = {id(parent) for parent, _ in wanted}
    for edge in [e for e in comp._edges.values() if e.alive and e.follower is comp]:
        if id(edge.origin.obj) not in keep:
            edge.origin.remove(comp.obj)
    for parent, collide in wanted:
        if getattr(parent, 'joint', None) is None:
            parent.set(joint)
        parent_joint = parent.joint
        if id(comp.obj) not in parent_joint._edges:
            parent_joint.joints.append(comp.obj)
        edge = parent_joint._edges.get(id(comp.obj))
        if edge is not None and edge.collide != collide:
            edge.collide = collide


def _joint_spec():
    names = tuple(n for n in joint._settings if n not in ('preset', 'joints')) + ('links',)
    base = _default(joint, names=names[:-1])
    return Spec(joint, names, base.ctor, getters={'links': _links_get}, setters={'links': _links_put},
                deferred=('links',))


def _light_spec():
    return _default(light, extra={'light': True})


ORDER = [_transform_spec(), _default(physics), _joint_spec(), _light_spec(), _default(force), _default(pen)]
SPECS = {spec.name: spec for spec in ORDER}
FLAT = {}


def _index(spec):
    for var in spec.names:
        FLAT.setdefault(var, (spec.name, var))
        owned = spec.ctor.get(var)
        if owned is not None:
            FLAT.setdefault(owned, (spec.name, var))


for _spec in ORDER:
    _index(_spec)


def register(cls, names=None, **kwargs):
    spec = _default(cls, names, **kwargs)
    if spec.name in SPECS:
        ORDER[ORDER.index(SPECS[spec.name])] = spec
    else:
        ORDER.append(spec)
    SPECS[spec.name] = spec
    _index(spec)
    return spec


class Layer:
    kind = ''
    child = None
    structural = False
    names = ()
    children_mode = 'owner'

    def parse(self, token):
        return [('', token)]

    def plan(self, target, entity):
        found = []
        if entity.include is not None:
            for group, var in entity.include:
                if var is not None and entity.allows(group, var):
                    found.append((group, var))
            return found
        for var in self.names:
            if entity.allows('', var):
                found.append(('', var))
        return found

    def signature(self, target, entity):
        return ()

    def reader(self, group, var):
        return attrgetter(var)

    def accepts(self, entity, group, var):
        if not isinstance(group, str) or not isinstance(var, str):
            return False
        if entity.include is not None:
            return entity.allows(group, var)
        return group == '' and var in self.names and entity.allows(group, var)

    def get(self, target, group, var):
        return getattr(target, var)

    def put(self, target, group, var, value):
        setattr(target, var, value)

    def order(self, target, state):
        return [(group, var, value) for group, values in state.items() for var, value in values.items()]

    def children(self, target):
        return []

    def make(self, parent, state):
        raise NotImplementedError

    def drop(self, target):
        pass

    def remote(self, target, flag):
        pass


class SessionLayer(Layer):
    kind = 'session'
    child = 'world'
    names = ('bgcolor', 'fgcolor', 'pause', 'pausephysics', 'pauserendering')

    def children(self, target):
        return [('world', world) for world in list(target.worlds)]

    def make(self, parent, state):
        return parent.World(front=True), state


class WorldLayer(Layer):
    kind = 'world'
    child = 'scene'
    structural = True
    names = ('layer', 'pause', 'pausephysics', 'pauserendering')

    def children(self, target):
        return [('scene', target.scene)]

    def make(self, parent, state):
        return parent.scene, state

    def drop(self, target):
        target.unregister()


class SceneLayer(Layer):
    kind = 'scene'
    child = 'obj'
    children_mode = 'any'
    names = ('gravity', 'drag', 'precision', 'bouncethreshold', 'aspect', 'ambient')

    def children(self, target):
        return [('obj', item) for item in list(target.objs)]

    def make(self, parent, state):
        flat = {}
        rest = {}
        for group, values in state.items():
            spec = SPECS.get(group)
            if spec is None:
                rest[group] = dict(values)
                continue
            ctor, late = spec.prepare(values, parent)
            flat.update(ctor)
            if late:
                rest[group] = late
        created = parent.obj().create(**flat)
        for group in state:
            spec = SPECS.get(group)
            if spec is not None and getattr(created, spec.name, None) is None:
                created.set(spec.cls)
        return created, rest


class ObjLayer(Layer):
    kind = 'obj'

    def parse(self, token):
        if '.' in token:
            group, var = token.split('.', 1)
            if group in SPECS:
                return [(group, var or None)]
            return [('obj', token)]
        if token in SPECS:
            return [(token, None)]
        if token == 'text':
            return [('transform', 'htext'), ('transform', 'rtext')]
        hit = FLAT.get(token)
        if hit is not None:
            return [hit]
        return [('obj', token)]

    def plan(self, target, entity):
        found = []
        for spec in ORDER:
            if getattr(target, spec.name, None) is None:
                continue
            for var in spec.names:
                if entity.allows(spec.name, var):
                    found.append((spec.name, var))
        if entity.include is not None:
            for group, var in entity.include:
                if group == 'obj' and var is not None and hasattr(target, var) and entity.allows(group, var):
                    found.append((group, var))
        return found

    def signature(self, target, entity):
        present = tuple(getattr(target, spec.name, None) is not None for spec in ORDER)
        if entity.include is None:
            return present
        return present + tuple(hasattr(target, var) for group, var in entity.include if group == 'obj')

    def reader(self, group, var):
        if group == 'obj':
            return attrgetter(var)
        getter = SPECS[group].getters.get(var)
        if getter is not None:
            return lambda target: getter(getattr(target, group))
        return attrgetter(group + '.' + var)

    def accepts(self, entity, group, var):
        if not isinstance(group, str) or not isinstance(var, str):
            return False
        if group == 'obj':
            return entity.include is not None and (group, var) in entity.include and entity.allows(group, var)
        spec = SPECS.get(group)
        return spec is not None and var in spec.names and entity.allows(group, var)

    def get(self, target, group, var):
        if group == 'obj':
            return getattr(target, var)
        return SPECS[group].get(getattr(target, group), var)

    def put(self, target, group, var, value):
        if group == 'obj':
            setattr(target, var, value)
            return
        spec = SPECS.get(group)
        if spec is None:
            return
        if getattr(target, group, None) is None:
            target.set(spec.cls)
        spec.put(getattr(target, group), var, value)

    def order(self, target, state):
        rank = {spec.name: index for index, spec in enumerate(ORDER)}
        found = []
        for group, values in state.items():
            spec = SPECS.get(group)
            if group != 'obj' and spec is None:
                continue
            for var, value in values.items():
                if spec is None:
                    key = (2, len(rank), 0)
                else:
                    deferred = 1 if var in spec.deferred else 0
                    position = spec.names.index(var) if var in spec.names else len(spec.names)
                    key = (deferred, rank[group], position)
                found.append((key, group, var, value))
        found.sort(key=lambda item: item[0])
        return [(group, var, value) for _, group, var, value in found]

    def drop(self, target):
        target.discard()

    def remote(self, target, flag):
        target._remote = bool(flag)


LAYERS = {layer.kind: layer for layer in (SessionLayer(), WorldLayer(), SceneLayer(), ObjLayer())}


def layer_for(target):
    from ..launcher import Session, World
    if isinstance(target, Session):
        return LAYERS['session']
    if isinstance(target, World):
        return LAYERS['world']
    if isinstance(target, _scene.Scene):
        return LAYERS['scene']
    if isinstance(target, _scene.obj):
        return LAYERS['obj']
    return None
