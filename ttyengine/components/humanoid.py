import math
from .shared import _wrap
from .transform import transform
from .physics import physics
from .joint import joint

def _clockwise(vector, degrees):
    r = math.radians(degrees)
    u, v = vector
    return (u * math.cos(r) + v * math.sin(r), -u * math.sin(r) + v * math.cos(r))

def _extent_of(scene, text):
    lines = scene.recomp.sub('', text).split('\n')
    return max(len(line) for line in lines), len(lines)

class humanoid:
    _owned = ['humanoid']
    _required = [transform, physics]
    _keys = ('parts', 'solid', 'physics', 'style', 'joints', 'rig')
    _sides = ('left', 'right')
    rig = {
        'torso': {'parent': None},
        'head': {'parent': 'torso', 'preset': 'neck', 'place': 'above'},
        'upper_arm': {'parent': 'torso', 'preset': 'shoulder', 'place': 'beside', 'paired': True, 'flip': True},
        'forearm': {'parent': 'upper_arm', 'preset': 'elbow', 'place': 'below', 'paired': True, 'flip': True},
        'hand': {'parent': 'forearm', 'preset': 'wrist', 'place': 'below', 'paired': True, 'flip': True},
        'thigh': {'parent': 'torso', 'preset': 'hip', 'place': 'under', 'paired': True, 'mass': 10},
        'shin': {'parent': 'thigh', 'preset': 'knee', 'place': 'below', 'paired': True, 'contact': True, 'mass': 10},
        'foot': {'parent': 'shin', 'preset': 'ankle', 'place': 'outward', 'paired': True, 'contact': True, 'mass': 10},
    }
    poses = {
        'stand': {},
        'arms_out': {'upper_arm': 90},
        'arms_up': {'upper_arm': 170},
        'guard': {'upper_arm': 35, 'forearm': -110},
        'wave': {'upper_arm': 150, 'forearm': -40},
        'crouch': {'thigh': -60, 'shin': 100},
        'sit': {'thigh': -90, 'shin': 90},
    }

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
            raise TypeError("humanoid needs a dict of part texts: humanoid={'parts': {'torso': ..., ...}}")
        unknown = [key for key in config if key not in self._keys]
        if unknown:
            raise TypeError('unknown humanoid setting: ' + ', '.join(map(str, unknown)))
        self.obj = obj
        self.scene = obj.scene
        self.t = obj.transform
        self._config = config
        self.rig = dict(type(self).rig)
        self.rig.update(config.get('rig', {}))
        self.parts = {}
        self._nodes = {}
        self._order = []
        self._by_id = {}
        self._detached = set()
        self._watched = set()
        self._breaks = []
        self._solid = config.get('solid')
        self._physics = dict(config.get('physics', {}))
        self._style = dict(config.get('style', {}))
        self._joints = dict(config.get('joints', {}))
        roots = [name for name, spec in self.rig.items() if spec.get('parent') is None]
        if len(roots) != 1:
            raise ValueError('the humanoid rig needs exactly one part without a parent')
        self._root = roots[0]
        entries = self._entries(config['parts'])
        if not any(name == self._root for name, _, _ in entries):
            raise ValueError("humanoid parts need a '%s' text" % self._root)
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

    def pose(self, targets, weight=1.0, reset=False, strict=False):
        goals = {name: 0.0 for name in self._order if name != self._root} if reset else {}
        for key, value in targets.items():
            resolved = self._resolve(key)
            if not resolved and strict:
                raise KeyError(key)
            for name, sign in resolved:
                goals[name] = value * sign
        for name, goal in goals.items():
            node = self._nodes[name]
            if name in self._detached:
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

    @staticmethod
    def walk_cycle(phase, stride=32.0, bend=50.0, swing=35.0, elbow=25.0):
        s = math.sin(phase)
        c = math.cos(phase)
        return {
            'left_thigh': -stride * s,
            'right_thigh': stride * s,
            'left_shin': bend * max(0.0, -c),
            'right_shin': bend * max(0.0, c),
            'upper_arm': swing * s,
            'forearm': -elbow * (0.5 + 0.5 * s),
        }

    def walk(self, phase, weight=1.0, **kwargs):
        return self.pose(self.walk_cycle(phase, **kwargs), weight)

    def add_part(self, name, value):
        entries = self._entries({name: value}, require_root=False)
        if not entries:
            raise KeyError(name)
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

    def _names(self, key):
        if key in self._nodes:
            return [key]
        return [name for name in ('left_' + key, 'right_' + key) if name in self._nodes]

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
        found = []
        for side in self._sides:
            name = side + '_' + key
            if name in self._nodes:
                flip = self._nodes[name]['flip'] and side == 'right'
                found.append((name, -1.0 if flip else 1.0))
        return found

    def _entries(self, texts, require_root=True):
        known = set()
        for name, spec in self.rig.items():
            known.add(name)
            if spec.get('paired'):
                known.update(side + '_' + name for side in self._sides)
        unknown = [key for key in texts if key not in known]
        if unknown:
            raise ValueError('unknown humanoid part: ' + ', '.join(map(str, unknown)))
        entries = []
        for name, spec in self.rig.items():
            if spec.get('paired'):
                for side in self._sides:
                    key = side + '_' + name
                    value = texts.get(key, texts.get(name))
                    if value is not None:
                        entries.append((key, name, side, value))
            elif name in texts:
                entries.append((name, name, None, texts[name]))
        return [(key, (base, side), self._spec(key, value)) for key, base, side, value in entries]

    @staticmethod
    def _spec(name, value):
        if isinstance(value, str):
            return {'text': value}
        if isinstance(value, dict) and isinstance(value.get('text'), str):
            unknown = [key for key in value if key not in ('text', 'solid', 'z', 'physics', 'style', 'joint')]
            if unknown:
                raise TypeError("unknown setting for humanoid part '%s': %s" % (name, ', '.join(map(str, unknown))))
            return dict(value)
        raise TypeError("humanoid part '%s' needs a text or a dict with a 'text'" % name)

    def _layout(self, node):
        base, side = node['base'], node['side']
        rule = self.rig[base].get('place')
        if node['parent'] is None:
            node['rect'] = (0, 0) + node['size']
            node['pivot'] = None
            return
        px, py, pw, ph = self._nodes[node['parent']]['rect']
        w, h = node['size']
        left = side == 'left'
        if rule == 'above':
            x, y = px + (pw - w) // 2, py - h
            pivot = (x + w / 2, y + h)
        elif rule == 'beside':
            x, y = (px - w if left else px + pw), py
            pivot = (x + w / 2, y)
        elif rule == 'under':
            x, y = (px + pw // 2 - w if left else px + (pw + 1) // 2), py + ph
            pivot = (x + w / 2, y)
        elif rule == 'below':
            x, y = px + (pw - w) // 2, py + ph
            pivot = (x + w / 2, y)
        elif rule == 'outward':
            x, y = (px + pw - w if left else px), py + ph
            pivot = (x + w / 2, y)
        else:
            raise ValueError("unknown placement '%s' for humanoid part '%s'" % (rule, base))
        node['rect'] = (x, y, w, h)
        node['pivot'] = pivot

    def _install(self, entries):
        fresh = []
        for name, (base, side), spec in entries:
            if name in self._nodes:
                raise ValueError("duplicate humanoid part '%s'" % name)
            parent = self.rig[base].get('parent')
            if parent is not None and self.rig[parent].get('paired'):
                parent = (side or 'right') + '_' + parent
            if parent is not None and parent not in self._nodes and not any(e[0] == parent for e in entries):
                raise ValueError("humanoid part '%s' needs '%s'" % (name, parent))
            fresh.append({
                'name': name, 'base': base, 'side': side, 'parent': parent, 'spec': spec,
                'size': _extent_of(self.scene, spec['text']), 'angle': 0.0, 'limits': None, 'pose': None,
                'flip': bool(self.rig[base].get('flip')),
            })
        pending = list(fresh)
        ordered = []
        while pending:
            ready = [n for n in pending if n['parent'] is None or n['parent'] in self._nodes
                     or any(o['name'] == n['parent'] for o in ordered)]
            if not ready:
                raise ValueError('humanoid parts are missing a parent')
            ordered.extend(ready)
            pending = [n for n in pending if n not in ready]
        created = []
        for node in ordered:
            self._nodes[node['name']] = node
            self._order.append(node['name'])
            self._layout(node)
            self._spawn(node)
            created.append(node)
        self._isolate([self.parts[n['name']] for n in created])
        for node in created:
            if node['parent'] is not None:
                self._link(node)
        self._resolidify()
        return [n['name'] for n in created]

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
            if 'mass' not in settings and self.rig[node['base']].get('mass'):
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
            if 'mass' not in kwargs and self.rig[node['base']].get('mass'):
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
        return self.rig[node['base']]['mass'] * sum(1 for c in text if c not in ' \n')

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

    def _link(self, node):
        parent = self.parts[node['parent']]
        child = self.parts[node['name']]
        pnode = self._nodes[node['parent']]
        preset = self.rig[node['base']].get('preset')
        shape = {}
        if preset is not None:
            shape = dict(joint.presets[preset]) if isinstance(preset, str) else dict(preset)
            if node['flip'] and node['side'] == 'right':
                shape = joint.mirrored(shape)
        shape.update(self._joints.get(node['base'], {}))
        shape.update(self._joints.get(node['name'], {}))
        shape.update(node['spec'].get('joint', {}))
        if shape.get('range') is not None:
            values = [float(v) for v in shape['range']]
            node['limits'] = (min(values), max(values))
        settings = {key: value for key, value in shape.items() if key not in ('kind', 'range', 'rest', 'radius')}
        settings['kind'] = 'fixed'
        px, py = node['pivot']
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
        if not self.rig[node['base']].get('contact'):
            return False
        return not any(
            self._nodes[n]['parent'] == name and self.rig[self._nodes[n]['base']].get('contact')
            for n in self._order
        )

    def _resolidify(self):
        for name in self._order:
            node = self._nodes[name]
            if 'solid' in node['spec']:
                solid = bool(node['spec']['solid'])
            elif self._solid is None:
                solid = self._contact(name)
            elif isinstance(self._solid, bool):
                solid = self._solid
            else:
                solid = name in self._solid or node['base'] in self._solid
            self.parts[name].physics.solid = solid
