"""All behavior tests reject external socket connections."""
import ipaddress
import socket
import pytest


@pytest.fixture(autouse=True)
def block_external_connections(monkeypatch):
    connect = socket.socket.connect

    def checked(sock, address):
        try:
            allowed = ipaddress.ip_address(address[0]).is_loopback
        except ValueError:
            allowed = address[0] == "localhost"
        if not allowed:
            raise AssertionError("External network connection attempted")
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", checked)
