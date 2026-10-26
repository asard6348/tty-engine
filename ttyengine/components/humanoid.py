import math
from .shared import _wrap
from .transform import transform
from .physics import physics
from .joint import joint

_ANCHORS = {
    'center': (0.5, 0.5),
    'top': (0.5, 0.0),
    'bottom': (0.5, 1.0),
    'left': (0.0, 0.5),
    'right': (1.0, 0.5),
    'top_left': (0.0, 0.0),
    'top_right': (1.0, 0.0),
    'bottom_left': (0.0, 1.0),
    'bottom_right': (1.0, 1.0),
}
_SPEC_KEYS = ('text', 'parent', 'at', 'pin', 'shift', 'joint', 'mirror', 'flip', 'group',
              'contact', 'density', 'solid', 'z', 'physics', 'style')
_INHERITED = ('text', 'solid', 'z', 'physics', 'style', 'contact', 'density')
_CHANNEL_KEYS = ('amp', 'shift', 'bias', 'rectify')

def _clockwise(vector, degrees):
    r = math.radians(degrees)
    u, v = vector
    return (u * math.cos(r) + v * math.sin(r), -u * math.sin(r) + v * math.cos(r))

def _extent_of(scene, text):
    lines = scene.recomp.sub('', text).split('\n')
    return max(len(line) for line in lines), len(lines)

def _pair(value, label):
    try:
        a, b = value
        return float(a), float(b)
    except (TypeError, ValueError):
        raise TypeError('%s must be a pair of numbers' % label) from None

def _anchor(value):
    if isinstance(value, str):
        if value not in _ANCHORS:
            raise ValueError("unknown anchor '%s'; use one of: %s" % (value, ', '.join(_ANCHORS)))
        return _ANCHORS[value]
    return _pair(value, 'an anchor')

def _preset(value):
    if isinstance(value, str):
        if value not in joint.presets:
            raise KeyError('unknown joint preset: ' + value)
        return dict(joint.presets[value])
    return dict(value)

class humanoid:
    _owned = ['humanoid']
    _required = [transform, physics]
    _keys = ('parts', 'solid', 'physics', 'style', 'joints', 'poses', 'cycles', 'axis', 'elasticity', 'snap')

    def on_discard(self):
        for name in reversed(self._order):
            if name == self._root:
                continue
            part = self.parts.get(name)
            if part is not None and part in self.scene.objs:
                part.discard()
        self.parts.clear()

    def __init__(self, obj, **kwargs):
        config = kwargs.get('humanoid')
        if not isinstance(config, dict) or not isinstance(config.get('parts'), dict):
            raise TypeError("humanoid needs a dict of parts: humanoid={'parts': {...}}")
        unknown = [key for key in config if key not in self._keys]
        if unknown:
            raise TypeError('unknown humanoid setting: ' + ', '.join(map(str, unknown)))
        for key in ('physics', 'style', 'joints', 'poses', 'cycles'):
            if not isinstance(config.get(key, {}), dict):
                raise TypeError("humanoid setting '%s' must be a dict" % key)
        self.obj = obj
        self.scene = obj.scene
        self.t = obj.transform
        self._config = config
        self.poses = dict(config.get('poses', {}))
        self.cycles = dict(config.get('cycles', {}))
        self.parts = {}
        self._nodes = {}
        self._order = []
        self._by_id = {}
        self._detached = set()
        self._watched = set()
        self._loose = False
        self._loose_solid = True
        self._loose_limits = True
        self._elasticity = config.get('elasticity', 1.25)
        self._snap = config.get('snap', 2.0)
        self._breaks = []
        self._solid = config.get('solid')
        self._physics = dict(config.get('physics', {}))
        self._style = dict(config.get('style', {}))
        self._joints = dict(config.get('joints', {}))
        self._root = None
        self._axis = config.get('axis')
        entries = self._entries(config['parts'])
        roots = [entry['name'] for entry in entries if entry['parent'] is None]
        if len(roots) != 1:
            raise ValueError('a humanoid needs exactly one part without a parent')
        self._root = roots[0]
        if self._axis is None:
            self._axis = self._root
        if self._axis not in {entry['name'] for entry in entries}:
            raise ValueError("the humanoid axis '%s' is not a part" % self._axis)
        self._install(entries)

    def __getitem__(self, name):
        if name in self.parts:
            return self.parts[name]
        found = self._names(name)
        if len(found) == 1:
            return self.parts[found[0]]
        raise KeyError(name)

    def __contains__(self, name):
        return isinstance(name, str) and bool(self._names(name))

    def __iter__(self):
        return iter(list(self._order))

    def __len__(self):
        return len(self._order)

    def __repr__(self):
        return 'humanoid(%s)' % ', '.join(self._order)

    @property
    def humanoid(self):
        return self._config

    @property
    def root(self):
        return self.obj

    @property
    def names(self):
        return list(self._order)

    @property
    def bounds(self):
        boxes = [self.parts[name].transform.extent() for name in self._order]
        return (
            min(b[0] - b[2] for b in boxes),
            max(b[1] + b[3] for b in boxes),
            max(b[0] + b[2] for b in boxes),
            min(b[1] - b[3] for b in boxes),
        )

    @property
    def grounded(self):
        for name in self._order:
            if name not in self._detached and self.parts[name].physics.grounded:
                return True
        return False

    @property
    def velocity(self):
        p = self.obj.physics
        return (p.xvel / p.mass, p.yvel / p.mass)

    @velocity.setter
    def velocity(self, value):
        vx, vy = value
        for name in self._order:
            if name in self._detached:
                continue
            p = self.parts[name].physics
            if vx is not None:
                p.xvel = vx * p.mass
            if vy is not None:
                p.yvel = vy * p.mass

    @property
    def visible(self):
        return self.obj.rendering.show

    @visible.setter
    def visible(self, value):
        for part in self.parts.values():
            part.rendering.show = value

    def get(self, key):
        return [self.parts[name] for name in self._names(key)]

    def angle(self, name):
        return self._nodes[name]['angle']

    def push(self, dx=0, dy=0):
        for name in self._order:
            if name in self._detached:
                continue
            p = self.parts[name].physics
            p.xvel += dx * p.mass
            p.yvel += dy * p.mass
        return self

    def jump(self, speed):
        if not self.grounded:
            return False
        self.velocity = (None, speed)
        return True

    def place(self, x, y):
        return self.move(x - self.t.x, y - self.t.y, True)

    def move(self, dx, dy, stop=False):
        if getattr(self.obj, 'joint', None) is not None:
            self.obj.joint.teleport(dx, dy, stop=stop)
        else:
            self.t.x += dx
            self.t.y += dy
        return self

    def style(self, parts=None, **kwargs):
        for name in self._select(parts):
            t = self.parts[name].transform
            for key, value in kwargs.items():
                setattr(t, key, value)
        return self

    def colorize(self, colors, attr='fg'):
        if isinstance(colors, str):
            return self.style(None, **{attr: colors})
        for key, value in colors.items():
            self.style(key, **{attr: value})
        return self

    def set_text(self, name, text):
        found = self._names(name)
        if not found:
            raise KeyError(name)
        for part in found:
            node = self._nodes[part]
            if _extent_of(self.scene, text) != node['size']:
                raise ValueError("text for '%s' must keep the size %dx%d" % ((part,) + node['size']))
            self.parts[part].transform.text = text
        return self

    @property
    def ragdolled(self):
        return self._loose

    def ragdoll(self, on=True, solid=True, limits=True):
        if on:
            self._loose_solid = solid
            self._loose_limits = limits
        if bool(on) == self._loose and not on:
            return self
        self._loose = bool(on)
        for name in self._order:
            node = self._nodes[name]
            if node['parent'] is not None and name not in self._detached:
                if on:
                    self._loosen(node)
                else:
                    self._stiffen(node)
        self._resolidify()
        return self

    def pose(self, targets, weight=1.0, reset=False, strict=False):
        if self._loose:
            return self
        goals = {name: 0.0 for name in self._order if name != self._root} if reset else {}
        for key, value in targets.items():
            resolved = self._resolve(key)
            if not resolved and strict:
                raise KeyError(key)
            for name, sign in resolved:
                goals[name] = value * sign
        for name, goal in goals.items():
            node = self._nodes[name]
            if name in self._detached or node['parent'] is None:
                continue
            if node['limits'] is not None:
                goal = max(node['limits'][0], min(node['limits'][1], goal))
            new = node['angle'] + (goal - node['angle']) * weight
            if abs(new - node['angle']) > 1e-3:
                node['angle'] = new
                dist, bearing, turn = node['pose']
                self.parts[node['parent']].joint.link(self.parts[name]).pose = (dist, _wrap(bearing + new), _wrap(turn + new))
        return self

    def apply_pose(self, name, weight=1.0):
        return self.pose(self.poses[name], weight, reset=True)

    def reset_pose(self, weight=1.0):
        return self.pose({}, weight, reset=True)

    def sample(self, cycle, phase, scale=1.0):
        return {key: scale * self._wave(channel, phase) for key, channel in self.cycles[cycle].items()}

    def animate(self, cycle, phase, weight=1.0, scale=1.0):
        return self.pose(self.sample(cycle, phase, scale), weight)

    def add_part(self, name, value):
        return self.add_parts({name: value})

    def add_parts(self, parts):
        entries = self._entries(parts)
        if any(entry['parent'] is None for entry in entries):
            raise ValueError('a humanoid already has a part without a parent')
        return self._install(entries)

    def remove_part(self, name):
        found = self._names(name)
        if not found:
            raise KeyError(name)
        removed = []
        for part in found:
            if part in self._nodes:
                removed.extend(self._remove(part))
        self._resolidify()
        return removed

    def detach(self, name):
        freed = []
        for part in self._names(name):
            node = self._nodes[part]
            if node['parent'] is None or part in self._detached:
                continue
            self.parts[node['parent']].joint.remove(self.parts[part])
            self._lost(part)
            freed.append(self.parts[part])
        return freed

    def onbreak(self, callback):
        self._breaks.append(callback)
        return callback

    def offbreak(self, callback):
        self._breaks = [cb for cb in self._breaks if cb is not callback]

    @staticmethod
    def _wave(channel, phase):
        if isinstance(channel, (int, float)):
            channel = {'amp': channel}
        unknown = [key for key in channel if key not in _CHANNEL_KEYS]
        if unknown:
            raise TypeError('unknown cycle setting: ' + ', '.join(map(str, unknown)))
        wave = math.sin(phase + channel.get('shift', 0.0))
        if channel.get('rectify'):
            wave = max(0.0, wave)
        return channel.get('bias', 0.0) + channel.get('amp', 1.0) * wave

    def _names(self, key):
        if key in self._nodes:
            return [key]
        return [name for name in self._order if key in self._nodes[name]['groups']]

    def _select(self, parts):
        if parts is None:
            return list(self._order)
        if isinstance(parts, str):
            return self._names(parts)
        found = []
        for key in parts:
            found.extend(name for name in self._names(key) if name not in found)
        return found

    def _resolve(self, key):
        if key in self._nodes:
            return [(key, 1.0)]
        return [(name, -1.0 if self._nodes[name]['flip'] else 1.0) for name in self._names(key)]

    @staticmethod
    def _spec(name, value):
        if isinstance(value, str):
            value = {'text': value}
        if not isinstance(value, dict):
            raise TypeError("humanoid part '%s' needs a text or a dict" % name)
        unknown = [key for key in value if key not in _SPEC_KEYS]
        if unknown:
            raise TypeError("unknown setting for humanoid part '%s': %s" % (name, ', '.join(map(str, unknown))))
        mirror = value.get('mirror')
        if 'text' in value:
            if not isinstance(value['text'], str):
                raise TypeError("humanoid part '%s' needs a text" % name)
        elif not isinstance(mirror, str):
            raise TypeError("humanoid part '%s' needs a text or a mirror" % name)
        if mirror is not None:
            if not isinstance(mirror, str):
                raise TypeError("the mirror of humanoid part '%s' must be a part name" % name)
            clash = [key for key in ('at', 'pin') if key in value]
            if clash:
                raise TypeError("mirrored humanoid part '%s' cannot set %s" % (name, ', '.join(clash)))
        elif 'flip' in value:
            raise TypeError("humanoid part '%s' sets 'flip' without a 'mirror'" % name)
        if value.get('parent') is not None and not isinstance(value['parent'], str):
            raise TypeError("the parent of humanoid part '%s' must be a part name" % name)
        for key in ('at', 'pin'):
            if key in value:
                _anchor(value[key])
        if 'shift' in value:
            _pair(value['shift'], 'shift')
        group = value.get('group', ())
        if not isinstance(group, str) and not (isinstance(group, (list, tuple)) and all(isinstance(item, str) for item in group)):
            raise TypeError("the group of humanoid part '%s' must be a name or a list of names" % name)
        return dict(value)

    def _entries(self, texts):
        specs = {name: self._spec(name, value) for name, value in texts.items()}
        for name in specs:
            if name in self._nodes:
                raise ValueError("duplicate humanoid part '%s'" % name)
        resolved = {name: node['spec'] for name, node in self._nodes.items()}
        parents = {name: node['parent'] for name, node in self._nodes.items()}
        mirrors = {name: node['mirror'] for name, node in self._nodes.items()}
        mirrors.update({name: spec.get('mirror') for name, spec in specs.items()})

        def effective(name, trail=()):
            if name in resolved:
                return resolved[name]
            if name in trail or name not in specs:
                raise ValueError("humanoid mirror '%s' is unknown or circular" % name)
            spec = specs[name]
            if spec.get('mirror') is None:
                merged = dict(spec)
            else:
                base = effective(spec['mirror'], trail + (name,))
                merged = {key: base[key] for key in _INHERITED if key in base}
                merged.update(spec)
            resolved[name] = merged
            return merged

        def parent_of(name):
            if name in parents:
                return parents[name]
            spec = specs[name]
            if spec.get('parent') is not None:
                found = spec['parent']
            elif spec.get('mirror') is not None:
                effective(name)
                base = parent_of(spec['mirror'])
                if base is None:
                    raise ValueError("humanoid part '%s' cannot mirror the root" % name)
                peers = [other for other, source in mirrors.items() if source == base and other != name]
                found = peers[0] if peers else (mirrors.get(base) or base)
            else:
                found = None
            parents[name] = found
            return found

        known = set(self._nodes) | set(specs)
        entries = []
        for name, spec in specs.items():
            parent = parent_of(name)
            if parent is not None and (parent not in known or parent == name):
                raise ValueError("humanoid part '%s' needs the part '%s'" % (name, parent))
            entries.append({
                'name': name, 'parent': parent, 'raw': spec, 'spec': effective(name),
                'mirror': spec.get('mirror'),
            })
        return entries

    def _needs(self, node):
        needs = []
        if node['parent'] is not None:
            needs.append(node['parent'])
        if node['mirror'] is not None:
            needs.extend((node['mirror'], self._axis))
        return needs

    def _sequence(self, entries):
        names = {entry['name'] for entry in entries} | set(self._nodes)
        for entry in entries:
            for need in self._needs(entry):
                if need not in names:
                    raise ValueError("humanoid part '%s' needs the part '%s'" % (entry['name'], need))
        done = set(self._nodes)
        pending = list(entries)
        ordered = []
        while pending:
            ready = next((entry for entry in pending if all(need in done for need in self._needs(entry))), None)
            if ready is None:
                raise ValueError('humanoid parts form a loop')
            ordered.append(ready)
            done.add(ready['name'])
            pending = [entry for entry in pending if entry is not ready]
        return ordered

    def _groups(self, node):
        found = [node['name']]
        if node['mirror'] is not None:
            found.extend(self._nodes[node['mirror']]['groups'][1:])
        extra = node['raw'].get('group', ())
        found.extend((extra,) if isinstance(extra, str) else extra)
        return list(dict.fromkeys(found))

    def _layout(self, node):
        w, h = node['size']
        spec = node['spec']
        if node['parent'] is None:
            node['rect'] = (0, 0, w, h)
            node['pin'] = (0.5, 0.5)
            node['point'] = (w / 2, h / 2)
            return
        sx, sy = _pair(spec.get('shift', (0, 0)), 'shift')
        if node['mirror'] is not None:
            source = self._nodes[node['mirror']]
            ax, _, aw, _ = self._nodes[self._axis]['rect']
            fx, fy = source['pin']
            pin = (1 - fx, fy)
            point = (2 * ax + aw - source['point'][0] + sx, source['point'][1] + sy)
        else:
            px, py, pw, ph = self._nodes[node['parent']]['rect']
            ux, uy = _anchor(spec.get('at', 'bottom'))
            pin = _anchor(spec['pin']) if 'pin' in spec else (1 - ux, 1 - uy)
            point = (px + ux * pw + sx, py + uy * ph + sy)
        x = math.floor(point[0] - pin[0] * w + 0.5)
        y = math.floor(point[1] - pin[1] * h + 0.5)
        node['rect'] = (x, y, w, h)
        node['pin'] = pin
        node['point'] = (x + pin[0] * w, y + pin[1] * h)

    def _install(self, entries):
        ordered = self._sequence(entries)
        for node in ordered:
            node['size'] = _extent_of(self.scene, node['spec']['text'])
            node['angle'] = 0.0
            node['limits'] = None
            node['pose'] = None
            node['flip'] = node['mirror'] is not None and bool(node['spec'].get('flip', True))
            node['groups'] = self._groups(node)
            self._nodes[node['name']] = node
            self._order.append(node['name'])
            self._layout(node)
            self._spawn(node)
        self._isolate([self.parts[node['name']] for node in ordered])
        for node in ordered:
            if node['parent'] is not None:
                self._link(node)
        if self._loose:
            for node in ordered:
                if node['parent'] is not None:
                    self._loosen(node)
        self._resolidify()
        return [node['name'] for node in ordered]

    def _spawn(self, node):
        name = node['name']
        spec = node['spec']
        if node['parent'] is None:
            part = self.obj
            self.t.text = spec['text']
            for key, value in {**self._style, **spec.get('style', {})}.items():
                setattr(self.t, key, value)
            if 'z' in spec:
                self.obj.rendering.z = spec['z']
            settings = {**self._physics, **spec.get('physics', {})}
            if 'mass' not in settings and spec.get('density'):
                settings['mass'] = self._mass(node)
            for key, value in settings.items():
                setattr(self.obj.physics, key, value)
        else:
            parent = self.parts[node['parent']]
            pnode = self._nodes[node['parent']]
            A = self.scene.aspect
            pcx, pcy = parent.transform.extent()[:2]
            rotation = parent.transform.rotation
            x, y, w, h = node['rect']
            px, py, pw, ph = pnode['rect']
            offset = _clockwise(((x + w / 2 - px - pw / 2) * A, -(y + h / 2 - py - ph / 2)), rotation)
            kwargs = {'xvel': 0, 'rotation': rotation}
            kwargs.update(self._physics)
            kwargs.update(spec.get('physics', {}))
            if 'mass' not in kwargs and spec.get('density'):
                kwargs['mass'] = self._mass(node)
            kwargs.update(self._style)
            kwargs.update(spec.get('style', {}))
            if 'z' in spec:
                kwargs['z'] = spec['z']
            part = self.scene.obj().create(spec['text'], pcx + offset[0] / A - w / 2, pcy + offset[1] + h / 2, **kwargs)
        self.parts[name] = part
        self._by_id[id(part)] = name

    def _mass(self, node):
        text = self.scene.recomp.sub('', node['spec']['text'])
        return node['spec']['density'] * sum(1 for c in text if c not in ' \n')

    def _isolate(self, fresh):
        pool = list(self.parts.values())
        for a in fresh:
            for b in pool:
                if a is b:
                    continue
                if not any(g is b for g in a._ghosts):
                    a._ghosts.append(b)
                if not any(g is a for g in b._ghosts):
                    b._ghosts.append(a)

    def _shape(self, name, own=True):
        node = self._nodes[name]
        spec = node['spec']
        if node['mirror'] is not None and 'joint' not in spec:
            shape = self._shape(node['mirror'], False)
            if node['flip']:
                shape = joint.mirrored(shape)
        else:
            value = spec.get('joint')
            shape = _preset(value if isinstance(value, str) else 'hinge')
            shape.setdefault('elasticity', self._elasticity)
            shape.setdefault('snap', self._snap)
            for group in node['groups'][1:]:
                shape.update(self._joints.get(group, {}))
            if isinstance(value, dict):
                shape.update(value)
        if own:
            shape.update(self._joints.get(name, {}))
        return shape

    def _loosen(self, node):
        child = self.parts[node['name']]
        shape = self._shape(node['name'])
        child.joint.apply(kind='hinge', radius='keep', rest=node['pose'][1],
                          range=shape.get('range') if self._loose_limits else None)

    def _stiffen(self, node):
        child = self.parts[node['name']]
        child.joint.apply(kind='fixed')
        link = self.parts[node['parent']].joint.link(child)
        node['angle'] = _wrap(link.pose[1] - node['pose'][1])

    def _link(self, node):
        parent = self.parts[node['parent']]
        child = self.parts[node['name']]
        pnode = self._nodes[node['parent']]
        shape = self._shape(node['name'])
        if shape.get('range') is not None:
            values = [float(v) for v in shape['range']]
            node['limits'] = (min(values), max(values))
        settings = {key: value for key, value in shape.items() if key not in ('kind', 'range', 'rest', 'radius')}
        settings['kind'] = 'fixed'
        px, py = node['point']
        x, y, w, h = pnode['rect']
        settings['xoffset'] = px - x - w / 2
        settings['yoffset'] = -(py - y - h / 2)
        if getattr(parent, 'joint', None) is None:
            parent.set(joint)
        parent.joint.attach(child, settings)
        node['pose'] = parent.joint.link(child).pose
        self._watch(node['parent'])

    def _watch(self, parent_name):
        if parent_name in self._watched:
            return
        self._watched.add(parent_name)
        def broke(other):
            name = self._by_id.get(id(other))
            node = self._nodes.get(name)
            if node is None or node['parent'] != parent_name or name in self._detached:
                return
            self._lost(name)
        self.parts[parent_name].joint.onbreak(broke)

    def _lost(self, name):
        self._detached.add(name)
        for callback in list(self._breaks):
            callback(name, self.parts[name])

    def _subtree(self, name):
        found = [name]
        for current in found:
            found.extend(n for n in self._order if self._nodes[n]['parent'] == current and n not in found)
        return found

    def _remove(self, name):
        if name == self._root:
            raise ValueError('the root part cannot be removed; discard the object instead')
        doomed = self._subtree(name)
        for part in reversed(doomed):
            obj = self.parts.pop(part)
            self._nodes.pop(part)
            self._order.remove(part)
            self._by_id.pop(id(obj), None)
            self._detached.discard(part)
            self._watched.discard(part)
            if obj in self.scene.objs:
                obj.discard()
        return doomed

    def _contact(self, name):
        node = self._nodes[name]
        if not node['spec'].get('contact'):
            return False
        return not any(
            self._nodes[n]['parent'] == name and self._nodes[n]['spec'].get('contact')
            for n in self._order
        )

    def _resolidify(self):
        for name in self._order:
            node = self._nodes[name]
            if self._loose and self._loose_solid:
                solid = True
            elif 'solid' in node['spec']:
                solid = bool(node['spec']['solid'])
            elif self._solid is None:
                solid = self._contact(name)
            elif isinstance(self._solid, bool):
                solid = self._solid
            else:
                solid = any(group in self._solid for group in node['groups'])
            self.parts[name].physics.solid = solid
