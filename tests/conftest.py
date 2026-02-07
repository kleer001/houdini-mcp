"""Shared fixtures for HoudiniMCP tests."""
import json
import socket
import threading

import pytest


class MockHoudiniServer:
    """Minimal TCP server that mimics Houdini's command protocol.

    Accepts a JSON command, looks up a canned response by command type,
    and sends it back.  Falls back to a generic success response.
    """

    def __init__(self, host="localhost", port=0):
        self.host = host
        self.port = port
        self.responses = {}  # type str -> dict
        self._server_sock = None
        self._thread = None
        self._running = False

    def set_response(self, cmd_type, response_dict):
        self.responses[cmd_type] = response_dict

    def start(self):
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(1)
        self._server_sock.settimeout(2.0)
        # Get the actual port assigned by the OS
        self.port = self._server_sock.getsockname()[1]
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while self._running:
            try:
                client, _ = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                client.settimeout(5.0)
                data = b""
                while True:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                    try:
                        command = json.loads(data.decode("utf-8"))
                        break
                    except json.JSONDecodeError:
                        continue

                cmd_type = command.get("type", "")
                response = self.responses.get(cmd_type, {
                    "status": "success",
                    "result": {"echo": cmd_type},
                })
                client.sendall(json.dumps(response).encode("utf-8"))
            except Exception:
                pass
            finally:
                client.close()

    def stop(self):
        self._running = False
        if self._server_sock:
            self._server_sock.close()
        if self._thread:
            self._thread.join(timeout=5)


@pytest.fixture
def mock_houdini_server():
    """Yield a started MockHoudiniServer, stop it on teardown."""
    server = MockHoudiniServer()
    server.start()
    yield server
    server.stop()
