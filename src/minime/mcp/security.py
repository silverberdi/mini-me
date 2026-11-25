from __future__ import annotations

import json
import os
import re
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


SECRET_PATTERNS = re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+[^\s,}]+|(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password)\s*[:=]\s*[^,}\s]+)")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): ("[REDACTED]" if any(x in str(k).lower() for x in ("token", "secret", "key", "authorization", "password")) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return SECRET_PATTERNS.sub("[REDACTED]", value)
    return value


class CredentialCipher:
    """Fernet wrapper with an explicit runtime key; no development fallback."""

    def __init__(self, key: str | bytes | None = None):
        raw = key or os.getenv("MINIME_MCP_MASTER_KEY")
        if not raw:
            raise RuntimeError("MCP master key is required")
        try:
            self._fernet = Fernet(raw.encode() if isinstance(raw, str) else raw)
        except Exception as exc:
            raise RuntimeError("Invalid MCP master key") from exc

    def encrypt(self, credentials: dict[str, Any]) -> bytes:
        return self._fernet.encrypt(json.dumps(credentials, sort_keys=True).encode())

    def decrypt(self, ciphertext: bytes) -> dict[str, Any]:
        try:
            value = json.loads(self._fernet.decrypt(ciphertext).decode())
        except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("MCP credential decryption failed") from exc
        if not isinstance(value, dict):
            raise RuntimeError("MCP credentials have invalid shape")
        return value
