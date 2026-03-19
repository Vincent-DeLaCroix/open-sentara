"""Cryptographic operations for federation — Ed25519 signing."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def generate_keypair(data_dir: Path) -> tuple[bytes, bytes]:
    """Generate Ed25519 keypair, save private key, return (private_pem, public_pem)."""
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    public_pem = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    key_path = data_dir / "identity.key"
    key_path.write_bytes(private_pem)
    key_path.chmod(0o600)

    pub_path = data_dir / "identity.pub"
    pub_path.write_bytes(public_pem)

    return private_pem, public_pem


def load_private_key(data_dir: Path) -> Ed25519PrivateKey | None:
    """Load private key from disk."""
    key_path = data_dir / "identity.key"
    if not key_path.exists():
        return None
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    return load_pem_private_key(key_path.read_bytes(), password=None)


def load_public_key(data_dir: Path) -> bytes | None:
    """Load public key PEM from disk."""
    pub_path = data_dir / "identity.pub"
    if not pub_path.exists():
        return None
    return pub_path.read_bytes()


def sign_message(private_key: Ed25519PrivateKey, payload: dict,
                 from_handle: str, msg_type: str, timestamp: str) -> str:
    """Sign a federation message. Returns hex signature."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    data = f"{from_handle}:{msg_type}:{timestamp}:{canonical}".encode()
    signature = private_key.sign(data)
    return signature.hex()


def verify_signature(public_key_pem: bytes, signature_hex: str, payload: dict,
                     from_handle: str, msg_type: str, timestamp: str) -> bool:
    """Verify a federation message signature."""
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    try:
        pub_key = load_pem_public_key(public_key_pem)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        data = f"{from_handle}:{msg_type}:{timestamp}:{canonical}".encode()
        pub_key.verify(bytes.fromhex(signature_hex), data)
        return True
    except Exception:
        return False
