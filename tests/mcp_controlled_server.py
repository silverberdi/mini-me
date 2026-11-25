from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any


class ControlledMCPHandler(BaseHTTPRequestHandler):
    calls: list[dict[str, Any]] = []
    effect: list[dict[str, Any]] = []
    invalid_auth = False
    require_auth = False

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        request = json.loads(self.rfile.read(length))
        self.__class__.calls.append(request)
        if self.__class__.invalid_auth or (self.__class__.require_auth and not self.headers.get("authorization")):
            result = {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32001, "message": "invalid credential"}}
        elif request["method"] == "initialize":
            result = {"jsonrpc": "2.0", "id": request["id"], "result": {"protocolVersion": "2024-11-05"}}
        elif request["method"] == "tools/list":
            result = {"jsonrpc": "2.0", "id": request["id"], "result": {"tools": [{"name": "stitch_get", "description": "controlled tool"}]}}
        elif request["method"] == "resources/list":
            result = {"jsonrpc": "2.0", "id": request["id"], "result": {"resources": [{"name": "design://home"}]}}
        elif request["method"] == "tools/call":
            effect = {"tool": request["params"]["name"], "arguments": request["params"].get("arguments", {})}
            self.__class__.effect.append(effect)
            result = {"jsonrpc": "2.0", "id": request["id"], "result": {"content": [{"type": "text", "text": "controlled-result"}], "isError": False}}
        else:
            result = {"jsonrpc": "2.0", "id": request["id"], "result": {}}
        payload = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args: Any) -> None:
        return


def controlled_server() -> tuple[ThreadingHTTPServer, str]:
    ControlledMCPHandler.calls = []
    ControlledMCPHandler.effect = []
    ControlledMCPHandler.invalid_auth = False
    ControlledMCPHandler.require_auth = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), ControlledMCPHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


class ControlledOAuthHandler(BaseHTTPRequestHandler):
    """Local OAuth provider used by the candidate-specific integration test."""

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length).decode()
        if self.path != "/token" or ("code=consent-code" not in body and "refresh_token=refresh-1" not in body):
            self.send_response(400)
            self.end_headers()
            return
        payload = {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600}
        if "refresh_token=refresh-1" in body:
            payload["access_token"] = "access-2"
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args: Any) -> None:
        return


def controlled_oauth_server() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), ControlledOAuthHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"
