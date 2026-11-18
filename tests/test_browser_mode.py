import socket

from ozbargain.core.monitor import _cdp_reachable


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_cdp_unreachable_when_port_closed():
    port = _free_port()
    assert _cdp_reachable(f"http://127.0.0.1:{port}", timeout=0.3) is False


def test_cdp_reachable_when_listening():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert _cdp_reachable(f"http://127.0.0.1:{port}", timeout=0.5) is True
    finally:
        server.close()
