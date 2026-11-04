"""Sealing with age (pyrage)."""

from __future__ import annotations

from pyrage import decrypt, encrypt, x25519


class DecryptionError(Exception):
    pass


def seal(key: bytes, plaintext: bytes) -> bytes:
    identity = x25519.Identity.from_str(key.decode())
    return bytes(encrypt(plaintext, [identity.to_public()]))


def open_sealed(key: bytes, ciphertext: bytes) -> bytes:
    identity = x25519.Identity.from_str(key.decode())
    try:
        return bytes(decrypt(ciphertext, [identity]))
    except Exception as exc:  # pyrage raises its own error types
        raise DecryptionError("cannot decrypt with this key") from exc
