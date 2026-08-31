import ipaddress
import socket

import pytest


def _is_loopback_address(address):
    if not isinstance(address, tuple) or not address:
        return True
    host = str(address[0]).strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    """Keep the test suite from contacting real third-party services."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_connect(sock, address):
        if sock.family != socket.AF_UNIX and not _is_loopback_address(address):
            raise RuntimeError(f"External network disabled during tests: {address!r}")
        return original_connect(sock, address)

    def guarded_connect_ex(sock, address):
        if sock.family != socket.AF_UNIX and not _is_loopback_address(address):
            raise RuntimeError(f"External network disabled during tests: {address!r}")
        return original_connect_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
