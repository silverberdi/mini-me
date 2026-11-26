from __future__ import annotations

import json
import socket
import sys
from typing import TextIO


def _request(path: str, line: str) -> str | None:
    payload = json.loads(line)
    if isinstance(payload, dict) and payload.get("method", "").startswith("notifications/"):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(path)
            client.sendall(line.encode("utf-8") + b"\n")
        return None
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(30)
        client.connect(path)
        client.sendall(line.encode("utf-8") + b"\n")
        chunks = bytearray()
        while not chunks.endswith(b"\n"):
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.extend(chunk)
            if len(chunks) > 1_048_576:
                raise ValueError("MCP relay response exceeds limit")
    if not chunks:
        raise ConnectionError("MCP relay returned no response")
    return chunks.decode("utf-8").strip()


def serve(path: str, source: TextIO = sys.stdin, sink: TextIO = sys.stdout) -> int:
    for line in source:
        if not line.strip():
            continue
        try:
            response = _request(path, line.rstrip("\r\n"))
            if response is not None:
                sink.write(response + "\n")
                sink.flush()
        except Exception:
            request = {}
            try:
                request = json.loads(line)
            except ValueError:
                pass
            if request.get("id") is not None:
                sink.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32000, "message": "MCP bridge unavailable"}}) + "\n")
                sink.flush()
            return 1
    return 0


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1]:
        return 2
    return serve(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
