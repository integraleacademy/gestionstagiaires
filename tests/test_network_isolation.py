import socket

import pytest


def test_external_network_is_disabled_during_tests():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="External network disabled during tests"):
            sock.connect(("192.0.2.1", 443))
    finally:
        sock.close()
