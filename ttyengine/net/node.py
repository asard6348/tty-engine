import hashlib
import hmac
import os
import random
import socket
import struct
import time
import zlib

from . import codec
from .errors import ConnectError, NetError, ProtocolError
from .transport import MAX_FRAME, TcpLink, TcpListener, UdpEndpoint, resolve, split_address

VERSION = 2

_HELLO, _WELCOME, _DATA, _JOIN, _LEAVE, _BYE, _REJECT = range(1, 8)
_HEADER = struct.Struct('>BIIB')
_RELAY = 1
_ZLIB = 2
_RELIABLE = 4
_COMPRESS_FROM = 256

PROTOCOLS = ('tcp', 'udp')
_MAX_ID = (1 << 32) - 1
_NONCE = 16


def _inflate(payload):
    inflater = zlib.decompressobj()
    try:
        out = inflater.decompress(payload, MAX_FRAME)
    except zlib.error:
        raise ProtocolError('bad compressed payload') from None
    if inflater.unconsumed_tail or not inflater.eof:
        raise ProtocolError('compressed payload is incomplete or too large')
    return out


def _valid_listen(listen):
    if not isinstance(listen, dict):
        return False
    for key, port in listen.items():
        if key not in PROTOCOLS or type(port) is not int or not 0 < port < 65536:
            return False
    return True


def _valid_entry(ident, name, listen):
    return type(ident) is int and 0 < ident <= _MAX_ID and isinstance(name, str) and _valid_listen(listen)


class Peer:
    def __init__(self, node, ident, name, link=None, listen=None, host=None):
        self.node = node
        self.id = ident
        self.name = name
        self.link = link
        self.listen = dict(listen or {})
        self.host = host
        self.data = {}

    @property
    def direct(self):
        return self.link is not None and self.link.alive

    @property
    def protocol(self):
        return self.link.protocol if self.link is not None else None

    @property
    def rtt(self):
        return self.link.rtt if self.link is not None else None

    @property
    def address(self):
        return self.link.address if self.link is not None else None

    def send(self, channel, data, reliable=True):
        return self.node.send(channel, data, to=self.id, reliable=reliable)

    def __repr__(self):
        return 'Peer(%s, id=%d, %s)' % (self.name, self.id, self.protocol or 'relayed')


class Node:
    def __init__(self, name=None, ident=None, mesh=False, relay=None, timeout=10.0, compress=True, password=None):
        if ident is not None and (type(ident) is not int or not 0 < ident <= _MAX_ID):
            raise NetError('ident must be an integer between 1 and %d' % _MAX_ID)
        self.id = ident if ident is not None else random.SystemRandom().randrange(1 << 8, 1 << 32)
        self.name = name if name is not None else 'node-%08x' % self.id
        self.mesh = mesh
        self.relay = (not mesh) if relay is None else relay
        self.timeout = timeout
        self.compress = compress
        self.password = password
        self.peers = {}
        self.members = {}
        self.primary = None
        self.listen = {}
        self.addresses = {}
        self._tcp = []
        self._udp = {}
        self._links = []
        self._handlers = {}
        self._closed = False
        self.handshake = 5.0

    @property
    def is_host(self):
        return bool(self._tcp) or any(ep.accepting for ep in self._udp.values())

    @property
    def hostid(self):
        if self.primary is not None and self.primary in self.members:
            return self.primary
        return self.id

    def on(self, channel, callback):
        self._handlers.setdefault(channel, []).append(callback)
        return callback

    def off(self, channel, callback):
        handlers = self._handlers.get(channel)
        if handlers and callback in handlers:
            handlers.remove(callback)

    def _fire(self, channel, *args):
        for callback in list(self._handlers.get(channel, ())):
            callback(*args)

    def host(self, port=0, address='', protocol='both'):
        if protocol not in ('tcp', 'udp', 'both'):
            raise NetError("protocol must be 'tcp', 'udp' or 'both'")
        wanted = PROTOCOLS if protocol == 'both' else (protocol,)
        listener = TcpListener(address, port) if 'tcp' in wanted else None
        if listener is not None and port == 0:
            port = listener.port
        endpoint = None
        if 'udp' in wanted:
            try:
                endpoint = UdpEndpoint(address, port, accept=True)
            except NetError:
                if listener is None or port == 0:
                    raise
                try:
                    endpoint = UdpEndpoint(address, 0, accept=True)
                except NetError:
                    listener.close()
                    raise
        found = {}
        if listener is not None:
            self._tcp.append(listener)
            self.listen['tcp'] = listener.port
            found['tcp'] = listener.address
        if endpoint is not None:
            self._udp[('listen', endpoint.family, endpoint.port)] = endpoint
            self.listen['udp'] = endpoint.port
            found['udp'] = endpoint.address
        self.addresses.update(found)
        return found

    def _client_endpoint(self, fam):
        for endpoint in self._udp.values():
            if endpoint.family == fam:
                return endpoint
        endpoint = UdpEndpoint('::' if fam == socket.AF_INET6 else '', 0, fam=fam)
        self._udp[('client', fam, endpoint.port)] = endpoint
        return endpoint

    def _dial(self, address, protocol):
        if protocol == 'tcp':
            return TcpLink.dial(address)
        if protocol == 'udp':
            fam, sockaddr = resolve(address, socket.SOCK_DGRAM)
            return self._client_endpoint(fam).connect(sockaddr)
        raise NetError("protocol must be 'tcp', 'udp' or 'auto'")

    def connect(self, address, protocol='tcp', timeout=5.0, wait=True):
        if protocol not in ('tcp', 'udp', 'auto'):
            raise NetError("protocol must be 'tcp', 'udp' or 'auto'")
        if protocol == 'auto' and not wait:
            raise NetError("protocol 'auto' needs wait=True")
        order = ('tcp', 'udp') if protocol == 'auto' else (protocol,)
        failure = None
        for each in order:
            try:
                return self._connect(address, each, timeout, wait)
            except ConnectError as exc:
                failure = exc
        raise failure

    def _connect(self, address, protocol, timeout, wait):
        try:
            link = self._dial(address, protocol)
        except ConnectError:
            raise
        except NetError as exc:
            raise ConnectError(str(exc)) from None
        link.initiator = True
        link.limit = timeout
        link.nonce = os.urandom(_NONCE)
        self._links.append(link)
        link.send(self._frame(_HELLO, (VERSION, self.id, self.name, dict(self.listen), link.nonce,
                                       self._proof(b'H', link.nonce, self.id))), True)
        if not wait:
            return link
        deadline = time.monotonic() + timeout
        while link.peer is None:
            self.update()
            if not link.alive:
                raise ConnectError('cannot connect to %s over %s: %s' % (split_address(address), protocol, link.reason))
            if time.monotonic() > deadline:
                link.close('timed out')
                self._links = [l for l in self._links if l is not link]
                raise ConnectError('connecting to %s over %s timed out' % (split_address(address), protocol))
            time.sleep(0.001)
        return link.peer

    def _proof(self, tag, nonce, ident):
        if self.password is None:
            return None
        key = str(self.password).encode('utf-8')
        return hmac.new(key, tag + nonce + ident.to_bytes(4, 'big'), hashlib.sha256).digest()

    def _proven(self, proof, tag, nonce, ident):
        expected = self._proof(tag, nonce, ident)
        return expected is not None and isinstance(proof, bytes) and hmac.compare_digest(proof, expected)

    @staticmethod
    def _frame(kind, body):
        return bytes((kind,)) + codec.dumps(body)

    def _roster(self, skip):
        return [(m.id, m.name, m.host, dict(m.listen)) for m in self.members.values() if m.id != skip]

    def update(self):
        if self._closed:
            return
        now = time.monotonic()
        failure = None
        for listener in self._tcp:
            self._links.extend(listener.accept())
        for endpoint in list(self._udp.values()):
            self._links.extend(endpoint.update(now))
        for link in list(self._links):
            if link.protocol == 'tcp':
                link.update(now)
            inbox = link.inbox
            while inbox:
                data = inbox.popleft()
                try:
                    self._receive(link, data)
                except ProtocolError as exc:
                    link.close('protocol error: %s' % exc)
                    inbox.clear()
                except Exception as exc:
                    if failure is None:
                        failure = exc
            if link.peer is None and link.alive:
                limit = getattr(link, 'limit', self.handshake) if link.initiator else self.handshake
                if now - link.born > limit:
                    link.close('handshake timed out')
            if not link.alive:
                self._lost(link)
        if failure is not None:
            raise failure

    def _receive(self, link, data):
        if not data:
            raise ProtocolError('empty frame')
        kind = data[0]
        if kind == _DATA:
            self._data(link, data)
            return
        body = codec.loads(data[1:])
        if kind == _HELLO:
            self._hello(link, body)
        elif kind == _WELCOME:
            self._welcome(link, body)
        elif kind == _BYE:
            link.close('closed by peer')
        elif kind == _REJECT:
            link.close('rejected: %s' % (body,))
        elif kind == _JOIN or kind == _LEAVE:
            if link.peer is None:
                raise ProtocolError('membership change before handshake')
            if kind == _JOIN:
                self._joined(body)
            else:
                self._left(body)
        else:
            raise ProtocolError('unknown frame %d' % kind)

    def _hello(self, link, body):
        if link.initiator or link.peer is not None:
            raise ProtocolError('unexpected hello')
        try:
            version, ident, name, listen, nonce, proof = body
        except (TypeError, ValueError):
            raise ProtocolError('malformed hello') from None
        if version != VERSION:
            link.send(self._frame(_REJECT, 'protocol version %s is not supported' % (version,)))
            link.close('version mismatch')
            return
        if not _valid_entry(ident, name, listen) or not isinstance(nonce, bytes) or len(nonce) != _NONCE:
            raise ProtocolError('malformed hello')
        if self.password is not None and not self._proven(proof, b'H', nonce, ident):
            link.send(self._frame(_REJECT, 'wrong password'))
            link.close('wrong password')
            return
        existing = self.peers.get(ident)
        if ident == self.id or (existing is not None and existing.direct):
            link.send(self._frame(_REJECT, 'duplicate node id'))
            link.close('duplicate node id')
            return
        peer = self._register(link, ident, name, listen, link.address[0])
        link.send(self._frame(_WELCOME, (self.id, self.name, dict(self.listen), self._roster(ident),
                                         self._proof(b'W', nonce, self.id))))
        self._announce(peer)
        self._fire('@join', peer)

    def _welcome(self, link, body):
        if not link.initiator or link.peer is not None:
            raise ProtocolError('unexpected welcome')
        try:
            ident, name, listen, roster, proof = body
        except (TypeError, ValueError):
            raise ProtocolError('malformed welcome') from None
        if not _valid_entry(ident, name, listen) or not isinstance(roster, list):
            raise ProtocolError('malformed welcome')
        if self.password is not None and not self._proven(proof, b'W', link.nonce, ident):
            link.close('wrong password')
            return
        existing = self.peers.get(ident)
        if ident == self.id or (existing is not None and existing.direct):
            link.close('duplicate node id')
            return
        entries = [self._entry(item) for item in roster]
        peer = self._register(link, ident, name, listen, link.address[0])
        if self.primary is None:
            self.primary = peer.id
        for entry in entries:
            self._remember(entry)
        self._fire('@join', peer)
        if self.mesh:
            self._weave(link.protocol, [entry for entry in entries if entry is not None])

    def _register(self, link, ident, name, listen, host):
        peer = self.members.get(ident)
        if peer is None:
            peer = Peer(self, ident, name, link, listen, host)
        else:
            peer.name, peer.link, peer.listen, peer.host = name, link, dict(listen), host
        link.peer = peer
        self.peers[ident] = peer
        self.members[ident] = peer
        return peer

    @staticmethod
    def _entry(entry):
        try:
            ident, name, host, listen = entry
        except (TypeError, ValueError):
            raise ProtocolError('malformed member') from None
        if not _valid_entry(ident, name, listen) or not (host is None or isinstance(host, str)):
            raise ProtocolError('malformed member')
        return ident, name, host, listen

    def _remember(self, entry):
        if entry is None:
            return None
        ident, name, host, listen = entry
        if ident == self.id or ident in self.members:
            return None
        member = Peer(self, ident, name, None, listen, host)
        self.members[ident] = member
        return member

    def _announce(self, peer):
        frame = self._frame(_JOIN, (peer.id, peer.name, peer.host, dict(peer.listen)))
        for other in self.peers.values():
            if other is not peer and other.direct:
                other.link.send(frame)

    def _joined(self, entry):
        self._remember(self._entry(entry))

    def _left(self, ident):
        member = self.members.get(ident) if type(ident) is int else None
        if member is None or member.direct:
            return
        del self.members[ident]
        self._fire('@leave', member)

    def _weave(self, protocol, roster):
        for ident, name, host, listen in roster:
            if ident == self.id or ident in self.peers:
                continue
            for each in (protocol,) + tuple(p for p in PROTOCOLS if p != protocol):
                port = listen.get(each)
                if port and host:
                    try:
                        self._connect((host, port), each, 5.0, False)
                    except NetError:
                        continue
                    break

    def _lost(self, link):
        link.close(link.reason)
        self._links = [l for l in self._links if l is not link]
        peer = link.peer
        if peer is None or peer.link is not link:
            return
        self.peers.pop(peer.id, None)
        self.members.pop(peer.id, None)
        if self.primary == peer.id:
            self.primary = None
        peer.link = None
        frame = self._frame(_LEAVE, peer.id)
        for other in self.peers.values():
            if other.direct:
                other.link.send(frame)
        self._fire('@leave', peer)

    def _data(self, link, data):
        peer = link.peer
        if peer is None:
            return
        if len(data) < _HEADER.size + 1:
            raise ProtocolError('short data frame')
        _, origin, target, flags = _HEADER.unpack_from(data)
        size = data[_HEADER.size]
        start = _HEADER.size + 1
        end = start + size
        if end > len(data):
            raise ProtocolError('short data frame')
        if origin != peer.id:
            known = self.members.get(origin)
            if known is None:
                return
            if known.link is not None:
                raise ProtocolError('spoofed origin')
        mine = not target or target == self.id
        relaying = self.relay and flags & _RELAY
        channel = bytes(data[start:end]).decode('utf-8', 'replace')
        value = None
        if mine and origin != self.id and (relaying or self._handlers.get(channel)):
            try:
                payload = data[end:]
                if flags & _ZLIB:
                    payload = _inflate(payload)
                value = codec.loads(payload)
            except ProtocolError:
                if origin == peer.id:
                    raise
                return
        if relaying:
            reliable = bool(flags & _RELIABLE)
            if target and target != self.id:
                hop = self.peers.get(target)
                if hop is not None and hop.direct and hop.link is not link:
                    hop.link.send(data, reliable)
            elif not target:
                for other in list(self.peers.values()):
                    if other.direct and other.link is not link and other.id != origin:
                        other.link.send(data, reliable)
        if not mine or origin == self.id:
            return
        sender = self.members.get(origin) or peer
        self._fire(channel, sender, value)

    def send(self, channel, data, to=None, reliable=True, ref=None):
        return self.send_raw(channel, codec.dumps(data, ref), to, reliable)

    def send_raw(self, channel, payload, to=None, reliable=True):
        flags = _RELAY
        if reliable:
            flags |= _RELIABLE
        if self.compress and len(payload) >= _COMPRESS_FROM:
            packed = zlib.compress(payload, 1)
            if len(packed) < len(payload):
                payload = packed
                flags |= _ZLIB
        name = channel.encode('utf-8')
        if len(name) > 255:
            raise NetError('channel name is too long')
        target = 0 if to is None else (to.id if isinstance(to, Peer) else int(to))
        frame = _HEADER.pack(_DATA, self.id, target, flags) + bytes((len(name),)) + name + payload
        sent = False
        if target:
            peer = self.peers.get(target)
            if peer is not None and peer.direct:
                return peer.link.send(frame, reliable)
            via = self.peers.get(self.hostid)
            if via is not None and via.direct:
                return via.link.send(frame, reliable)
            return False
        for peer in list(self.peers.values()):
            if peer.direct:
                peer.link.send(frame, reliable)
                sent = True
        return sent

    def disconnect(self, peer):
        target = self.peers.get(peer.id if isinstance(peer, Peer) else peer)
        if target is not None and target.link is not None:
            target.link.send(self._frame(_BYE, None))
            target.link.close('disconnected')
            self.update()

    def serve(self, interval=0.005, until=None):
        while not self._closed and (until is None or not until()):
            self.update()
            time.sleep(interval)

    def close(self):
        if self._closed:
            return
        for peer in list(self.peers.values()):
            if peer.direct:
                peer.link.send(self._frame(_BYE, None))
        for link in list(self._links):
            link.close('closed')
        for listener in self._tcp:
            listener.close()
        for endpoint in self._udp.values():
            endpoint.close()
        self._closed = True
        self.peers.clear()
        self.members.clear()
        self._links = []
