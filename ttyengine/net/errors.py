class NetError(Exception):
    pass


class ProtocolError(NetError):
    pass


class ConnectError(NetError, ConnectionError):
    pass
