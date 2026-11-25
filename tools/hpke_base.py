"""HPKE base mode (RFC 9180) for the onboarding seal, reference for tools/validate.py.

Suite: DHKEM(X25519, HKDF-SHA256) / HKDF-SHA256 / ChaCha20Poly1305 (kem 0x0020, kdf 0x0001,
aead 0x0003), single-shot (sequence number 0). The hub has its own copy
(services/onboard_crypto.py); the apps use CryptoKit HPKE (Curve25519_SHA256_ChachaPoly).
"""

from __future__ import annotations

import hashlib
import hmac

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

KEM_ID, KDF_ID, AEAD_ID = 0x0020, 0x0001, 0x0003
KEM_SUITE = b"KEM" + KEM_ID.to_bytes(2, "big")
HPKE_SUITE = b"HPKE" + KEM_ID.to_bytes(2, "big") + KDF_ID.to_bytes(2, "big") + AEAD_ID.to_bytes(2, "big")
NK, NN, NH = 32, 12, 32
MODE_BASE = 0


def _extract(salt: bytes, ikm: bytes) -> bytes:
    return hmac.new(salt or bytes(NH), ikm, hashlib.sha256).digest()


def _expand(prk: bytes, info: bytes, length: int) -> bytes:
    out, block, counter = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def _labeled_extract(suite: bytes, salt: bytes, label: bytes, ikm: bytes) -> bytes:
    return _extract(salt, b"HPKE-v1" + suite + label + ikm)


def _labeled_expand(suite: bytes, prk: bytes, label: bytes, info: bytes, length: int) -> bytes:
    return _expand(prk, length.to_bytes(2, "big") + b"HPKE-v1" + suite + label + info, length)


def _raw(public: X25519PublicKey) -> bytes:
    return public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _shared_secret(dh: bytes, enc: bytes, pk_r: bytes) -> bytes:
    eae_prk = _labeled_extract(KEM_SUITE, b"", b"eae_prk", dh)
    return _labeled_expand(KEM_SUITE, eae_prk, b"shared_secret", enc + pk_r, NH)


def key_schedule(shared_secret: bytes, info: bytes) -> tuple[bytes, bytes]:
    psk_id_hash = _labeled_extract(HPKE_SUITE, b"", b"psk_id_hash", b"")
    info_hash = _labeled_extract(HPKE_SUITE, b"", b"info_hash", info)
    context = bytes([MODE_BASE]) + psk_id_hash + info_hash
    secret = _labeled_extract(HPKE_SUITE, shared_secret, b"secret", b"")
    key = _labeled_expand(HPKE_SUITE, secret, b"key", context, NK)
    nonce = _labeled_expand(HPKE_SUITE, secret, b"base_nonce", context, NN)
    return key, nonce


def seal(pk_r: bytes, info: bytes, aad: bytes, plaintext: bytes, sk_e: bytes | None = None) -> tuple[bytes, bytes]:
    """(enc, ciphertext). ``sk_e`` only for known-answer tests (fresh key otherwise)."""
    eph = X25519PrivateKey.from_private_bytes(sk_e) if sk_e else X25519PrivateKey.generate()
    enc = _raw(eph.public_key())
    dh = eph.exchange(X25519PublicKey.from_public_bytes(pk_r))
    key, nonce = key_schedule(_shared_secret(dh, enc, pk_r), info)
    return enc, ChaCha20Poly1305(key).encrypt(nonce, plaintext, aad)


def open_(sk_r: bytes, enc: bytes, info: bytes, aad: bytes, ciphertext: bytes) -> bytes:
    priv = X25519PrivateKey.from_private_bytes(sk_r)
    dh = priv.exchange(X25519PublicKey.from_public_bytes(enc))
    key, nonce = key_schedule(_shared_secret(dh, enc, _raw(priv.public_key())), info)
    return ChaCha20Poly1305(key).decrypt(nonce, ciphertext, aad)


def public_key(sk: bytes) -> bytes:
    return _raw(X25519PrivateKey.from_private_bytes(sk).public_key())
