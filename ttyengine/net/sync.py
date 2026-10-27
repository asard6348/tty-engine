import collections
import time
import zlib

from . import codec
from .codec import Ref
from .errors import NetError
from .layers import LAYERS, layer_for
from .node import Peer

HOST = 'host'
LOCAL = 'local'

_ADD, _SET, _DROP, _OWN = range(4)
_SCALARS = (int, float, str, bool, type(None))
_MISSING = object()
_ORPHANS = 4096
_STRUCT = (1 << 62) - 1


def freeze(value):
    if type(value) in _SCALARS:
        return value
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, dict):
        return tuple((freeze(key), freeze(item)) for key, item in value.items())
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze(item) for item in value)
    return value


def _key(group, var):
    if group and var:
        return '%s.%s' % (group, var)
    return group or var


def root_nid(name):
    return zlib.crc32(str(name).encode('utf-8')) or 1


def struct_nid(parent, kind):
    return ((parent * 0x9E3779B1) ^ zlib.crc32(kind.encode('utf-8'))) & _STRUCT


class Options:
    def __init__(self, children, reliable, replicas, filter, include, exclude, exclude_all=()):
        self.exclude_all = exclude_all
        self.children = children
        self.reliable = reliable
        self.replicas = replicas
        self.filter = filter
        self.include = include
        self.exclude = exclude


class Entity:
    def __init__(self, nid, layer, target, parent, owner, opts):
        self.nid = nid
        self.layer = layer
        self.target = target
        self.parent = parent
        self.owner = owner
        self.opts = opts
        self.children = {}
        self.vowners = {}
        self.last = {}
        self.pending = {}
        self.name = None
        self.announced = True
        self.include = None
        self.exclude = frozenset()
        self.strict = set()
        self.cache = None
        self.configure(opts.include.get(layer.kind), tuple(opts.exclude.get(layer.kind, ())) + tuple(opts.exclude_all))

    def compiled(self):
        signature = self.layer.signature(self.target, self)
        if self.cache is None or self.cache[0] != signature:
            reader = self.layer.reader
            plan = self.layer.plan(self.target, self)
            self.cache = (signature, [((group, var), group, var, reader(group, var)) for group, var in plan])
        return self.cache[1]

    def configure(self, include, exclude):
        self.cache = None
        if include is not None:
            self.include = set()
            for token in include:
                self.include.update(self.layer.parse(token))
            self.strict = set(self.include)
        else:
            self.include = None
            self.strict = set()
        found = set()
        for token in exclude or ():
            found.update(self.layer.parse(token))
        self.exclude = frozenset(found)

    def allows(self, group, var):
        if (group, var) in self.exclude or (group, None) in self.exclude:
            return False
        if self.include is None:
            return True
        return (group, var) in self.include or (group, None) in self.include

    def explicit(self, group, var):
        return (group, var) in self.strict or (group, None) in self.strict

    @property
    def root(self):
        return self.parent is None

    def walk(self):
        yield self
        for child in list(self.children.values()):
            yield from child.walk()


class Sync:
    def __init__(self, node, channel='sync', rate=None, resync=1.0, replicas='frozen', orphans='drop'):
        if replicas not in ('frozen', 'live'):
            raise NetError("replicas must be 'frozen' or 'live'")
        if orphans not in ('drop', 'keep', 'adopt'):
            raise NetError("orphans must be 'drop', 'keep' or 'adopt'")
        self.node = node
        self.channel = channel
        self.rate = rate
        self.resync = resync
        self.replicas = replicas
        self.orphans = orphans
        self.entities = {}
        self.roots = {}
        self.by_target = {}
        self.skipped = set()
        self._ignored = {}
        self._held = []
        self.errors = collections.deque(maxlen=32)
        self.rejected = 0
        self._flushed = 0.0
        self._resynced = time.monotonic()
        self._counter = 0
        self._ref = self._nid_of
        node.on(channel, self._receive)
        node.on('@join', self._joined)
        node.on('@leave', self._left)

    def _nid_of(self, value):
        entity = self.by_target.get(id(value))
        return entity.nid if entity is not None and entity.target is value else None

    def _mint(self):
        self._counter += 1
        return (self.node.id << 32) | (self._counter & 0xFFFFFFFF)

    def _owner_id(self, value):
        if value == HOST:
            return self.node.hostid
        if value is None or value == LOCAL:
            return self.node.id
        if isinstance(value, Peer):
            return value.id
        return int(value)

    def owner(self, entity):
        return self._owner_id(entity.owner)

    def _var_owner(self, entity, group, var):
        found = entity.vowners.get(_key(group, var))
        return self._owner_id(found) if found is not None else self._owner_id(entity.owner)

    def entity(self, target):
        entity = self.by_target.get(id(target))
        return entity if entity is not None and entity.target is target else None

    def is_owner(self, target, var=None):
        entity = self._need(target)
        if var is None:
            return self.owner(entity) == self.node.id
        group, name = entity.layer.parse(var)[0]
        return self._var_owner(entity, group, name) == self.node.id

    def _need(self, target):
        entity = self.entity(target)
        if entity is None:
            raise NetError('%r is not shared' % (target,))
        return entity

    @staticmethod
    def _split(tokens):
        if tokens is None:
            return {}, None
        if isinstance(tokens, dict):
            return {kind: tuple(values) for kind, values in tokens.items()}, None
        if isinstance(tokens, str):
            return {}, (tokens,)
        return {}, tuple(tokens)

    def _configure(self, entity, own, opts):
        include = own if own is not None else opts.include.get(entity.layer.kind)
        exclude = tuple(opts.exclude.get(entity.layer.kind, ())) + tuple(opts.exclude_all)
        entity.configure(include, exclude)

    def share(self, target, name=None, owner=None, vars=None, exclude=(), children=True, reliable=True,
              replicas=None, filter=None):
        if isinstance(target, tuple):
            if len(target) < 2 or not all(isinstance(item, str) for item in target[1:]):
                raise NetError('share a variable as (target, name, ...)')
            return self.share(target[0], name=name, owner=owner, vars=target[1:], exclude=exclude,
                              children=False, reliable=reliable, replicas=replicas, filter=filter)
        layer = layer_for(target)
        if layer is None:
            raise NetError('cannot share %r: only sessions, worlds, scenes and objects are shareable' % (target,))
        if children not in (True, False, 'any', 'owner'):
            raise NetError("children must be True, False, 'any' or 'owner'")
        include, own = self._split(vars)
        excluded, excluded_all = self._split(exclude)
        opts = Options(children, reliable, replicas or self.replicas, filter, include, excluded, excluded_all or ())
        existing = self.entity(target)
        if existing is not None:
            existing.opts = opts
            self._configure(existing, own, opts)
            if owner is not None:
                self._assign(existing, owner)
            return existing
        if name is None:
            raise NetError('a shared root needs a name so every node can find it')
        entity = Entity(root_nid(name), layer, target, None, HOST if owner is None else owner, opts)
        if entity.nid in self.entities:
            raise NetError('the name %r is already shared' % (name,))
        entity.name = name
        self._configure(entity, own, opts)
        entity.announced = False
        self._register(entity)
        self.roots[name] = entity
        self._baseline(entity)
        self._remote(entity)
        self._settle()
        return entity

    def share_var(self, target, *names, **kwargs):
        return self.share(target, vars=names, children=False, **kwargs)

    def unshare(self, target):
        entity = self._need(target)
        if entity.parent is not None:
            entity.parent.children.pop(entity.nid, None)
        for item in list(entity.walk()):
            self._unregister(item)
            item.layer.remote(item.target, False)
        self.roots = {n: e for n, e in self.roots.items() if e is not entity}

    def ignore(self, target):
        self._ignored[id(target)] = target
        entity = self.entity(target)
        if entity is not None and entity.parent is not None:
            entity.parent.children.pop(entity.nid, None)
            for item in list(entity.walk()):
                self._unregister(item)
                item.layer.remote(item.target, False)

    def _register(self, entity):
        self.entities[entity.nid] = entity
        self.by_target[id(entity.target)] = entity
        if entity.parent is not None:
            entity.parent.children[entity.nid] = entity

    def _unregister(self, entity):
        self.entities.pop(entity.nid, None)
        if self.by_target.get(id(entity.target)) is entity:
            del self.by_target[id(entity.target)]

    def _remote(self, entity):
        frozen = entity.opts.replicas == 'frozen' and self.owner(entity) != self.node.id
        entity.layer.remote(entity.target, frozen)

    def _assign(self, entity, owner):
        entity.owner = owner
        self._remote(entity)

    def _baseline(self, entity):
        target = entity.target
        for key, group, var, read in entity.compiled():
            try:
                entity.last[key] = freeze(read(target))
            except (AttributeError, KeyError):
                continue

    def _state(self, entity, record=False):
        state = {}
        target = entity.target
        for key, group, var, read in entity.compiled():
            try:
                value = read(target)
            except (AttributeError, KeyError):
                continue
            if not entity.explicit(group, var):
                try:
                    codec.dumps(value, self._ref)
                except NetError:
                    self.skipped.add((entity.layer.kind, group, var))
                    continue
            if record:
                entity.last[(group, var)] = freeze(value)
            state.setdefault(group, {})[var] = value
        return state

    def _add_op(self, entity, record=False, forward=False):
        owner = self.owner(entity)
        vowners = {key: self._owner_id(value) for key, value in entity.vowners.items()}
        parent = entity.parent.nid if entity.parent is not None else None
        return (_ADD, entity.nid, parent, entity.layer.kind, owner, entity.name, self._state(entity, record),
                vowners, forward or owner != self.node.id)

    def _walk(self):
        for entity in list(self.roots.values()):
            yield from entity.walk()

    @staticmethod
    def _mode(entity):
        mode = entity.opts.children
        return entity.layer.children_mode if mode is True else mode

    def _scan(self, entity, ops):
        layer = entity.layer
        mode = entity.opts.children
        if layer.child is None or mode is False:
            return
        seen = set()
        for kind, child in layer.children(entity.target):
            seen.add(id(child))
            known = self.by_target.get(id(child))
            if known is not None and known.target is child:
                continue
            if id(child) in self._ignored:
                continue
            if layer.structural:
                entity_owner = entity.owner
                nid = struct_nid(entity.nid, kind)
            else:
                if self._mode(entity) == 'owner' and self.owner(entity) != self.node.id:
                    continue
                if entity.opts.filter is not None and not entity.opts.filter(child):
                    continue
                entity_owner = self.node.id
                nid = self._mint()
            fresh = Entity(nid, LAYERS[kind], child, entity, entity_owner, entity.opts)
            fresh.announced = layer.structural and self.owner(entity) != self.node.id
            self._register(fresh)
            if fresh.announced:
                self._baseline(fresh)
            else:
                ops.append(self._add_op(fresh, record=True))
                fresh.announced = True
            self._remote(fresh)
        for kid in list(entity.children.values()):
            if id(kid.target) in seen or layer.structural:
                continue
            if self.owner(kid) == self.node.id:
                ops.append((_DROP, kid.nid))
            for item in list(kid.walk()):
                self._unregister(item)
            entity.children.pop(kid.nid, None)

    def _collect(self, entity, force):
        me = self.node.id
        uniform = not entity.vowners
        if uniform and self.owner(entity) != me:
            return None
        target = entity.target
        last = entity.last
        changes = None
        for key, group, var, read in entity.compiled():
            if not uniform and self._var_owner(entity, group, var) != me:
                continue
            try:
                value = read(target)
            except (AttributeError, KeyError):
                continue
            snap = value if type(value) in _SCALARS else freeze(value)
            if not force:
                before = last.get(key, _MISSING)
                if before == snap or (snap != snap and before != before):
                    continue
            if not entity.explicit(group, var):
                try:
                    codec.dumps(value, self._ref)
                except NetError:
                    self.skipped.add((entity.layer.kind, group, var))
                    continue
            last[key] = snap
            if changes is None:
                changes = {}
            changes.setdefault(group, {})[var] = value
        return changes

    def flush(self):
        now = time.monotonic()
        if self.rate and now - self._flushed < 1.0 / self.rate:
            return
        self._flushed = now
        full = bool(self.resync) and now - self._resynced >= self.resync
        if full:
            self._resynced = now
        structure = []
        for entity in list(self._walk()):
            if self.entities.get(entity.nid) is not entity:
                continue
            if entity.root and not entity.announced:
                structure.append(self._add_op(entity, record=True))
                entity.announced = True
            self._scan(entity, structure)
        reliable = []
        unreliable = []
        for entity in list(self.entities.values()):
            changes = self._collect(entity, full and not entity.opts.reliable)
            if changes:
                (reliable if entity.opts.reliable else unreliable).append((_SET, entity.nid, changes))
        if not self.node.peers:
            return
        if structure:
            self._send(structure, True)
        if reliable:
            self._send(reliable, True)
        if unreliable:
            self._send(unreliable, False)

    def _send(self, ops, reliable, to=None):
        encoded = [codec.dumps(op, self._ref) for op in ops]
        if reliable:
            self.node.send_raw(self.channel, codec.pack_list(encoded), to=to, reliable=True)
            return
        limit = None
        for peer in self.node.peers.values():
            mtu = peer.link.mtu if peer.direct else None
            if mtu is not None:
                limit = mtu if limit is None else min(limit, mtu)
        budget = (limit - 64) if limit else None
        batch = []
        size = 0
        for item in encoded:
            if budget is not None and batch and size + len(item) > budget:
                self.node.send_raw(self.channel, codec.pack_list(batch), to=to, reliable=False)
                batch = []
                size = 0
            batch.append(item)
            size += len(item)
        if batch:
            self.node.send_raw(self.channel, codec.pack_list(batch), to=to, reliable=budget is not None and size > budget)

    def pull(self):
        self.node.update()
        self._settle()

    def push(self):
        self.flush()

    def update(self):
        self.pull()
        self.flush()

    def attach(self, world):
        from ..launcher import Session
        if isinstance(world, Session):
            world = world.worlds[-1] if world.worlds else world.World()
        sync = self

        class Pump:
            priority = 1000

            def update(self):
                sync.pull()

            def final(self):
                sync.push()

        return world.launch(Pump)

    def _joined(self, peer):
        ops = []
        for entity in self._walk():
            mine = self.owner(entity) == self.node.id or any(
                self._owner_id(v) == self.node.id for v in entity.vowners.values())
            if mine or (self.node.relay and self.node.is_host):
                ops.append(self._add_op(entity, forward=True))
        if ops:
            self._send(ops, True, to=peer)

    def _left(self, peer):
        gone = peer.id
        survivors = [self.node.id] + [m for m in self.node.members if m != gone]
        adopter = min(survivors)
        for entity in list(self.entities.values()):
            if entity.nid not in self.entities:
                continue
            for key, value in list(entity.vowners.items()):
                if value == gone:
                    if self.orphans == 'adopt':
                        entity.vowners[key] = adopter
                    else:
                        del entity.vowners[key]
            if entity.owner != gone:
                continue
            if entity.root:
                entity.owner = HOST
                self._remote(entity)
            elif self.orphans == 'drop':
                self._discard(entity)
            elif self.orphans == 'adopt':
                entity.owner = adopter
                if adopter == self.node.id:
                    self._baseline(entity)
                self._remote(entity)
            else:
                entity.owner = 0
                self._remote(entity)

    def _discard(self, entity):
        if entity.parent is not None:
            entity.parent.children.pop(entity.nid, None)
        for item in reversed(list(entity.walk())):
            self._unregister(item)
            item.layer.drop(item.target)

    def transfer(self, target, to, vars=None):
        entity = self._need(target)
        me = self.node.id
        new = self._owner_id(to)
        if vars is None:
            if self.owner(entity) != me:
                raise NetError('only the owner can transfer ownership')
            entity.owner = new
            self._remote(entity)
            if new != me:
                entity.vowners = {k: v for k, v in entity.vowners.items() if self._owner_id(v) != me}
            ops = [(_OWN, entity.nid, new, {})]
        else:
            changes = {}
            for token in vars:
                for group, var in entity.layer.parse(token):
                    key = _key(group, var)
                    if self.owner(entity) != me and self._var_owner(entity, group, var) != me:
                        raise NetError('only the owner of %s can transfer it' % key)
                    entity.vowners[key] = new
                    changes[key] = new
            ops = [(_OWN, entity.nid, None, changes)]
        if self.node.peers:
            self._send(ops, True)

    def _reject(self, exc):
        self.rejected += 1
        self.errors.append(exc)

    def _receive(self, peer, ops):
        if not isinstance(ops, list):
            return
        for op in ops:
            try:
                kind = op[0]
                if kind == _ADD:
                    self._on_add(peer.id, op)
                elif kind == _SET:
                    self._on_set(peer.id, op)
                elif kind == _DROP:
                    self._on_drop(peer.id, op)
                elif kind == _OWN:
                    self._on_own(peer.id, op)
            except Exception as exc:
                self._reject(exc)
        try:
            self._settle()
        except Exception as exc:
            self._reject(exc)

    def _resolve(self, value):
        kind = type(value)
        if kind in _SCALARS:
            return True, value
        if kind is Ref:
            found = self.entities.get(value.nid)
            return (True, found.target) if found is not None else (False, value)
        if isinstance(value, (list, tuple, set, frozenset)):
            items = []
            for item in value:
                ok, got = self._resolve(item)
                if not ok:
                    return False, value
                items.append(got)
            if isinstance(value, (set, frozenset)):
                return True, set(items)
            return True, items if isinstance(value, list) else tuple(items)
        if isinstance(value, dict):
            found = {}
            for key, item in value.items():
                ok, got = self._resolve(key)
                if not ok:
                    return False, value
                ok, item = self._resolve(item)
                if not ok:
                    return False, value
                found[got] = item
            return True, found
        return True, value

    def _write(self, entity, group, var, value):
        entity.layer.put(entity.target, group, var, value)
        try:
            entity.last[(group, var)] = freeze(entity.layer.get(entity.target, group, var))
        except (AttributeError, KeyError):
            pass

    def _apply(self, entity, origin, state, force=False):
        if not isinstance(state, dict):
            return
        layer = entity.layer
        for group, var, value in layer.order(entity.target, state):
            if not layer.accepts(entity, group, var):
                continue
            if not force and self._var_owner(entity, group, var) != origin:
                continue
            ok, value = self._resolve(value)
            if not ok:
                entity.pending[(group, var)] = (origin, value, force)
                continue
            try:
                self._write(entity, group, var, value)
            except Exception as exc:
                self._reject(exc)

    def _on_set(self, origin, op):
        entity = self.entities.get(op[1])
        if entity is None:
            return
        self._apply(entity, origin, op[2])

    def _on_add(self, origin, op):
        try:
            _, nid, parent_nid, kind, owner, name, state, vowners, forward = op
        except (TypeError, ValueError):
            return
        if type(owner) is not int or not isinstance(state, dict) or not isinstance(vowners, dict):
            return
        entity = self.entities.get(nid)
        if entity is not None:
            if origin == self._owner_id(entity.owner):
                self._apply(entity, origin, state, force=True)
            return
        if parent_nid is None:
            self._hold(origin, op)
            return
        parent = self.entities.get(parent_nid)
        if parent is None:
            self._hold(origin, op)
            return
        layer = LAYERS.get(kind)
        if layer is None or parent.layer.child != kind or parent.opts.children is False:
            return
        forward = bool(forward) and origin == self.node.primary
        if not forward and origin != owner:
            return
        if not forward and self._mode(parent) == 'owner' and origin != self.owner(parent):
            return
        ready = {}
        later = {}
        for group, values in state.items():
            if not isinstance(values, dict):
                continue
            for var, value in values.items():
                ok, got = self._resolve(value)
                if ok:
                    ready.setdefault(group, {})[var] = got
                else:
                    later[(group, var)] = (origin, value, True)
        target, rest = parent.layer.make(parent.target, ready)
        entity = Entity(nid, layer, target, parent, owner, parent.opts)
        entity.vowners = {key: value for key, value in vowners.items() if isinstance(key, str) and type(value) is int}
        entity.name = name if isinstance(name, str) else None
        self._register(entity)
        self._baseline(entity)
        self._apply(entity, origin, rest, force=True)
        entity.pending.update(later)
        self._remote(entity)

    def _on_drop(self, origin, op):
        entity = self.entities.get(op[1])
        if entity is None or entity.root:
            return
        if self._owner_id(entity.owner) != origin:
            return
        self._discard(entity)

    def _on_own(self, origin, op):
        _, nid, owner, changes = op
        entity = self.entities.get(nid)
        if entity is None or not isinstance(changes, dict):
            return
        if owner is not None and type(owner) is not int:
            return
        me = self.node.id
        if owner is not None and origin == self._owner_id(entity.owner):
            entity.owner = owner
            if owner == me:
                self._baseline(entity)
            self._remote(entity)
        for key, new in changes.items():
            if not isinstance(key, str) or type(new) is not int:
                continue
            group, _, var = key.rpartition('.')
            if origin == self._var_owner(entity, group, var) or origin == self._owner_id(entity.owner):
                entity.vowners[key] = new
                if new == me:
                    self._baseline(entity)

    def _hold(self, origin, op):
        self._held.append((origin, op))
        if len(self._held) > _ORPHANS:
            del self._held[0]

    def _settle(self):
        if self._held:
            held, self._held = self._held, []
            for origin, op in held:
                try:
                    self._on_add(origin, op)
                except Exception as exc:
                    self._reject(exc)
        for entity in list(self.entities.values()):
            if not entity.pending:
                continue
            waiting, entity.pending = entity.pending, {}
            for (group, var), (origin, value, force) in waiting.items():
                if entity.nid not in self.entities:
                    break
                if not force and self._var_owner(entity, group, var) != origin:
                    continue
                ok, got = self._resolve(value)
                if not ok:
                    entity.pending[(group, var)] = (origin, value, force)
                    continue
                try:
                    self._write(entity, group, var, got)
                except Exception as exc:
                    self._reject(exc)

    def close(self):
        self.node.off(self.channel, self._receive)
        self.node.off('@join', self._joined)
        self.node.off('@leave', self._left)
        for entity in list(self.entities.values()):
            self._unregister(entity)
            entity.layer.remote(entity.target, False)
        self.roots = {}
