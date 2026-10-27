from .codec import Ref, dumps, loads
from .layers import register
from .errors import ConnectError, NetError, ProtocolError
from .node import Node, Peer
from .sync import HOST, LOCAL, Entity, Sync
from .transport import Link, TcpLink, TcpListener, UdpEndpoint, UdpLink


def host(port=0, address='', protocol='both', **kwargs):
    node = Node(**kwargs)
    node.host(port, address, protocol)
    return node


def join(address, protocol='tcp', timeout=5.0, mesh=False, **kwargs):
    node = Node(mesh=mesh, **kwargs)
    node.connect(address, protocol, timeout)
    return node
