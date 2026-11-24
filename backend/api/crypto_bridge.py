"""AES-256-GCM envelope helpers for a FastAPI/Flask service.

Install: pip install cryptography
Keep PORTAL_AES256_KEY_B64 in a secret manager. It must decode to exactly
32 bytes. Never commit the production key or expose it to unauthenticated users.
"""
from __future__ import annotations

import base64
import json
import secrets
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def encrypt_json(value: Any, key: bytes, associated_data: bytes = b"") -> dict[str, Any]:
    """Return a transport envelope; AESGCM appends the 128-bit tag to ciphertext."""
    if len(key) != 32:
        raise ValueError("AES-256 requires a 32-byte key")
    iv = secrets.token_bytes(12)
    plaintext = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ciphertext_and_tag = AESGCM(key).encrypt(iv, plaintext, associated_data or None)
    return {
        "version": 1,
        "algorithm": "AES-256-GCM",
        "iv": base64.b64encode(iv).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext_and_tag).decode("ascii"),
    }


def decrypt_json(envelope: dict[str, Any], key: bytes, associated_data: bytes = b"") -> Any:
    """Authenticate before parsing. Invalid IVs, tags, or ciphertext raise ValueError."""
    if len(key) != 32:
        raise ValueError("AES-256 requires a 32-byte key")
    if envelope.get("version") != 1 or envelope.get("algorithm") != "AES-256-GCM":
        raise ValueError("Unsupported encrypted payload")
    iv = base64.b64decode(envelope["iv"], validate=True)
    if len(iv) != 12:
        raise ValueError("AES-GCM IV must be 12 bytes")
    ciphertext_and_tag = base64.b64decode(envelope["ciphertext"], validate=True)
    plaintext = AESGCM(key).decrypt(iv, ciphertext_and_tag, associated_data or None)
    return json.loads(plaintext)
