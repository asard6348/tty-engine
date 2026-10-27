import collections
import os
import random
import secrets
import select
import socket
import struct
import time

from .errors import NetError

MAX_FRAME = 1 << 26
_LENGTH = struct.Struct('>I')
_READS = 64
_DATAGRAMS = 8192


def split_address(address):
    if isinstance(address, str):
        host, _, port = address.rpartition(':')
        if not port.isdigit():
            raise NetError('invalid address %r: use (host, port) or "host:port"' % (address,))
        return host.strip('[]'), int(port)
    try:
        host, port = address[0], address[1]
        return str(host), int(port)
    except (TypeError, IndexError, ValueError):
        raise NetError('invalid address %r: use (host, port) or "host:port"' % (address,)) from None


def family_of(host):
    return socket.AF_INET6 if host and ':' in host else socket.AF_INET


def resolve(address, kind):
    host, port = split_address(address)
    try:
        found = socket.getaddrinfo(host or '127.0.0.1', port, 0, kind)
    except socket.gaierror as exc:
        raise NetError('cannot resolve %s: %s' % (host, exc)) from None
    if not found:
        raise NetError('cannot resolve %s' % host)
    fam, _, _, _, sockaddr = found[0]
    return fam, sockaddr


def _reserve(sock, fam, host):
    if os.name == 'nt':
        option = getattr(socket, 'SO_EXCLUSIVEADDRUSE', None)
        if option is not None:
            sock.setsockopt(socket.SOL_SOCKET, option, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if fam == socket.AF_INET6 and host in ('', '::'):
        try:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (OSError, AttributeError):
            pass


def _settled(sock):
    if hasattr(select, 'poll'):
        poller = select.poll()
        poller.register(sock.fileno(), select.POLLOUT)
        return bool(poller.poll(0))
    _, writable, failed = select.select([], [sock], [sock], 0)
    return bool(writable or failed)


class Link:
    protocol = ''

    def __init__(self, address):
        self.address = address
        self.alive = True
        self.opened = False
        self.reason = None
        self.rtt = None
        self.peer = None
        self.initiator = False
        self.born = time.monotonic()
        self.heard = self.born
        self.bytes_in = 0
        self.bytes_out = 0
        self.inbox = collections.deque()

    @property
    def mtu(self):
        return None

    def send(self, data, reliable=True):
        raise NotImplementedError

    def update(self, now):
        raise NotImplementedError

    def recv(self):
        found = list(self.inbox)
        self.inbox.clear()
        return found

    def close(self, reason=None):
        raise NotImplementedError

    def _die(self, reason):
        if self.alive:
            self.alive = False
            self.reason = reason


class TcpLink(Link):
    protocol = 'tcp'

    def __init__(self, sock, address, connecting=False):
        super().__init__(address)
        self.sock = sock
        self.connecting = connecting
        self.opened = not connecting
        self._out = bytearray()
        self._in = bytearray()
        sock.setblocking(False)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

    @classmethod
    def dial(cls, address):
        fam, sockaddr = resolve(address, socket.SOCK_STREAM)
        sock = socket.socket(fam, socket.SOCK_STREAM)
        sock.setblocking(False)
        try:
            sock.connect(sockaddr)
        except (BlockingIOError, InterruptedError):
            pass
        except OSError as exc:
            sock.close()
            raise NetError('cannot connect to %s: %s' % (address, exc)) from None
        return cls(sock, sockaddr[:2], connecting=True)

    def send(self, data, reliable=True):
        if not self.alive:
            return False
        if len(data) > MAX_FRAME:
            raise NetError('message of %d bytes is larger than the %d byte limit' % (len(data), MAX_FRAME))
        self._out += _LENGTH.pack(len(data))
        self._out += data
        if self.opened:
            self._flush()
        return True

    def _flush(self):
        while self._out and self.alive:
            try:
                sent = self.sock.send(self._out)
            except (BlockingIOError, InterruptedError):
                return
            except OSError as exc:
                self._die(str(exc) or 'connection lost')
                return
            if not sent:
                return
            self.bytes_out += sent
            del self._out[:sent]

    def update(self, now):
        if not self.alive:
            return
        if self.connecting:
            try:
                if not _settled(self.sock):
                    return
                error = self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            except (OSError, ValueError) as exc:
                self._die(str(exc))
                return
            if error:
                self._die(os.strerror(error) or 'connection failed')
                return
            self.connecting = False
            self.opened = True
        self._flush()
        gone = None
        for _ in range(_READS):
            if not self.alive:
                break
            try:
                chunk = self.sock.recv(65536)
            except (BlockingIOError, InterruptedError):
                break
            except OSError as exc:
                gone = str(exc) or 'connection lost'
                break
            if not chunk:
                gone = 'closed by peer'
                break
            self.bytes_in += len(chunk)
            self._in += chunk
        buffer = self._in
        total = len(buffer)
        pos = 0
        while total - pos >= 4:
            size = _LENGTH.unpack_from(buffer, pos)[0]
            if size > MAX_FRAME:
                gone = 'frame is too large'
                buffer.clear()
                total = pos = 0
                break
            end = pos + 4 + size
            if total < end:
                break
            self.inbox.append(bytes(buffer[pos + 4:end]))
            pos = end
        if pos:
            del buffer[:pos]
        if gone is not None:
            self._die(gone)
        if self.alive:
            self.heard = now

    def _die(self, reason):
        if self.alive:
            super()._die(reason)
            try:
                self.sock.close()
            except OSError:
                pass

    def close(self, reason=None):
        if self.alive and self.opened:
            self._flush()
        if self.alive:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self._die(reason or 'closed')


class TcpListener:
    def __init__(self, host='', port=0, backlog=64):
        fam = family_of(host)
        self.sock = socket.socket(fam, socket.SOCK_STREAM)
        try:
            _reserve(self.sock, fam, host)
            self.sock.bind((host or ('::' if fam == socket.AF_INET6 else ''), port))
            self.sock.listen(backlog)
        except OSError as exc:
            self.sock.close()
            raise NetError('cannot listen on tcp %s:%s: %s' % (host or '*', port, exc)) from None
        self.sock.setblocking(False)
        self.address = self.sock.getsockname()[:2]

    @property
    def port(self):
        return self.address[1]

    def accept(self):
        found = []
        while True:
            try:
                conn, addr = self.sock.accept()
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                break
            found.append(TcpLink(conn, addr[:2]))
        return found

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


_SYN, _SYNACK, _DATA, _UNREL, _ACK, _FIN, _PING, _PONG = range(1, 9)
_HEAD = struct.Struct('>BIQQI')
_STAMP = struct.Struct('>d')


class UdpLink(Link):
    protocol = 'udp'
    CHUNK = 1000
    WINDOW = 128
    SPAN = 1024
    TIMEOUT = 10.0

    def __init__(self, endpoint, sockaddr, token, client):
        super().__init__(sockaddr[:2])
        self.endpoint = endpoint
        self.sockaddr = sockaddr
        self.token = token
        self.client = client
        self.opened = not client
        self.sent = self.born
        self.timeout = self.TIMEOUT
        self._syn = 0.0
        self._next = 1
        self._unacked = collections.OrderedDict()
        self._queue = collections.deque()
        self._expect = 1
        self._held = {}
        self._asm = bytearray()
        self._owe = False
        self._useq = 0
        self._ureceived = 0
        self._rto = 0.25
        self._pinged = 0.0

    @property
    def mtu(self):
        return self.CHUNK

    def _emit(self, kind, seq=0, payload=b''):
        sack = 0
        if self._held:
            for bit in range(32):
                if self._expect + 1 + bit in self._held:
                    sack |= 1 << bit
        data = _HEAD.pack(kind, self.token, seq, self._expect - 1, sack) + payload
        self.endpoint._send(data, self.sockaddr)
        self.bytes_out += len(data)
        self.sent = time.monotonic()
        if kind in (_DATA, _UNREL, _ACK, _PING, _PONG):
            self._owe = False

    def send(self, data, reliable=True):
        if not self.alive:
            return False
        if not reliable and self.opened and len(data) <= self.CHUNK:
            self._useq += 1
            self._emit(_UNREL, self._useq, bytes(data))
            return True
        if len(data) > MAX_FRAME:
            raise NetError('message of %d bytes is larger than the %d byte limit' % (len(data), MAX_FRAME))
        view = bytes(data)
        total = len(view)
        offset = 0
        while True:
            part = view[offset:offset + self.CHUNK]
            offset += self.CHUNK
            self._queue.append((b'\x01' if offset < total else b'\x00') + part)
            if offset >= total:
                break
        self._pump()
        return True

    def _pump(self):
        while self._queue and self.opened and len(self._unacked) < self.WINDOW and self.alive:
            payload = self._queue.popleft()
            seq = self._next
            self._next += 1
            now = time.monotonic()
            self._unacked[seq] = [payload, now, now, 1]
            self._emit(_DATA, seq, payload)

    def _settle(self, ack, sack, now):
        done = [seq for seq in self._unacked if seq <= ack]
        if sack:
            for bit in range(32):
                if sack >> bit & 1:
                    seq = ack + 2 + bit
                    if seq in self._unacked:
                        done.append(seq)
        for seq in done:
            entry = self._unacked.pop(seq, None)
            if entry is not None and entry[3] == 1:
                sample = now - entry[1]
                self.rtt = sample if self.rtt is None else self.rtt * 0.875 + sample * 0.125
                self._rto = min(1.0, max(0.05, self.rtt * 1.5 + 0.03))

    def _handle(self, kind, seq, ack, sack, payload, now):
        self.heard = now
        if kind == _SYNACK:
            self.opened = True
            return
        if kind == _SYN:
            self.endpoint._reply(self)
            return
        if kind == _FIN:
            self._die('closed by peer')
            return
        self._settle(ack, sack, now)
        if kind == _DATA:
            self._owe = True
            if seq >= self._expect and seq not in self._held and seq < self._expect + self.SPAN:
                self._held[seq] = payload
                while self._expect in self._held:
                    part = self._held.pop(self._expect)
                    self._expect += 1
                    self._asm += part[1:]
                    if not part[0]:
                        self.inbox.append(bytes(self._asm))
                        self._asm.clear()
        elif kind == _UNREL:
            if seq > self._ureceived:
                self._ureceived = seq
                self.inbox.append(payload)
        elif kind == _PING:
            self._emit(_PONG, 0, payload)
        elif kind == _PONG and len(payload) == _STAMP.size:
            sample = now - _STAMP.unpack(payload)[0]
            if sample >= 0:
                self.rtt = sample if self.rtt is None else self.rtt * 0.875 + sample * 0.125

    def update(self, now):
        if not self.alive:
            return
        if not self.opened:
            if now - self._syn >= 0.2:
                self._syn = now
                self._emit(_SYN)
            return
        self._pump()
        for seq, entry in self._unacked.items():
            wait = self._rto * (1 << min(entry[3] - 1, 4))
            if now - entry[2] >= wait:
                entry[2] = now
                entry[3] += 1
                if entry[3] > 40:
                    self._die('timed out')
                    return
                self._emit(_DATA, seq, entry[0])
        if self._owe:
            self._emit(_ACK)
        if now - self.sent >= 1.0 or (self.rtt is None and now - self._pinged >= 0.5):
            self._pinged = now
            self._emit(_PING, 0, _STAMP.pack(now))
        if now - self.heard > self.timeout:
            self._die('timed out')

    def close(self, reason=None):
        if self.alive and self.opened:
            self._emit(_FIN)
            self._emit(_FIN)
        self._die(reason or 'closed')


class UdpEndpoint:
    def __init__(self, host='', port=0, fam=None, accept=False):
        fam = fam or family_of(host)
        self.sock = socket.socket(fam, socket.SOCK_DGRAM)
        try:
            if accept:
                _reserve(self.sock, fam, host)
            elif fam == socket.AF_INET6:
                try:
                    self.sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                except (OSError, AttributeError):
                    pass
            self.sock.bind((host or ('::' if fam == socket.AF_INET6 else ''), port))
        except OSError as exc:
            self.sock.close()
            raise NetError('cannot bind udp %s:%s: %s' % (host or '*', port, exc)) from None
        self.sock.setblocking(False)
        for option in (socket.SO_RCVBUF, socket.SO_SNDBUF):
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, option, 1 << 20)
            except OSError:
                pass
        self.family = fam
        self.accepting = accept
        self.address = self.sock.getsockname()[:2]
        self.links = {}
        self.loss = 0.0

    @property
    def port(self):
        return self.address[1]

    def _send(self, data, sockaddr):
        if self.loss and random.random() < self.loss:
            return
        try:
            self.sock.sendto(data, sockaddr)
        except (BlockingIOError, InterruptedError):
            pass
        except OSError:
            pass

    def _reply(self, link):
        self._send(_HEAD.pack(_SYNACK, link.token, 0, 0, 0), link.sockaddr)

    def connect(self, sockaddr):
        token = secrets.randbits(32) or 1
        link = UdpLink(self, sockaddr, token, True)
        old = self.links.get(sockaddr[:2])
        if old is not None:
            old.close('replaced')
        self.links[sockaddr[:2]] = link
        return link

    def _route(self, data, addr, now, fresh):
        if len(data) < _HEAD.size:
            return
        kind, token, seq, ack, sack = _HEAD.unpack_from(data)
        key = addr[:2]
        link = self.links.get(key)
        if kind == _SYN:
            if link is not None and link.token == token:
                link._handle(kind, seq, ack, sack, b'', now)
            elif self.accepting:
                if link is not None:
                    link.close('replaced')
                link = UdpLink(self, addr, token, False)
                link.opened = True
                self.links[key] = link
                fresh.append(link)
                self._reply(link)
            return
        if link is None or link.token != token:
            return
        link.bytes_in += len(data)
        link._handle(kind, seq, ack, sack, data[_HEAD.size:], now)

    def update(self, now):
        fresh = []
        for _ in range(_DATAGRAMS):
            try:
                data, addr = self.sock.recvfrom(2048)
            except (BlockingIOError, InterruptedError):
                break
            except ConnectionResetError:
                continue
            except OSError:
                break
            self._route(data, addr, now, fresh)
        for key, link in list(self.links.items()):
            link.update(now)
            if not link.alive:
                if self.links.get(key) is link:
                    del self.links[key]
        return fresh

    def close(self):
        for link in list(self.links.values()):
            link.close()
        self.links.clear()
        try:
            self.sock.close()
        except OSError:
            pass
