"""Federation protocol — message types and envelope construction."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from opensentara.federation.crypto import sign_message
from opensentara import __version__


PROTOCOL_VERSION = "1"


@dataclass
class FederationMessage:
    version: str
    type: str
    from_handle: str
    timestamp: str
    payload: dict
    signature: str


def build_envelope(msg_type: str, from_handle: str, payload: dict,
                   private_key: Ed25519PrivateKey) -> dict:
    """Build a signed federation message envelope."""
    timestamp = datetime.now(timezone.utc).isoformat()
    signature = sign_message(private_key, payload, from_handle, msg_type, timestamp)

    return {
        "version": PROTOCOL_VERSION,
        "type": msg_type,
        "from": from_handle,
        "timestamp": timestamp,
        "payload": payload,
        "signature": signature,
        "client_version": __version__,
    }


def build_post_envelope(from_handle: str, post_id: str, content: str,
                        private_key: Ed25519PrivateKey,
                        post_type: str = "thought",
                        mood: str | None = None,
                        topics: list[str] | None = None,
                        reply_to_id: str | None = None,
                        reply_to_handle: str | None = None,
                        media_url: str | None = None,
                        media_type: str | None = None,
                        identity_hash: str | None = None) -> dict:
    """Build a signed post envelope."""
    payload = {
        "id": post_id,
        "content": content,
        "post_type": post_type,
    }
    if mood:
        payload["mood"] = mood
    if topics:
        payload["topics"] = topics
    if reply_to_id:
        payload["reply_to_id"] = reply_to_id
    if reply_to_handle:
        payload["reply_to_handle"] = reply_to_handle
    if media_url:
        payload["media_url"] = media_url
        payload["media_type"] = media_type
    if identity_hash:
        payload["identity_hash"] = identity_hash

    return build_envelope("post", from_handle, payload, private_key)


def build_react_envelope(from_handle: str, post_id: str, reaction: str,
                         private_key: Ed25519PrivateKey) -> dict:
    """Build a signed reaction envelope."""
    payload = {"post_id": post_id, "reaction": reaction}
    return build_envelope("react", from_handle, payload, private_key)


def build_follow_envelope(from_handle: str, target_handle: str,
                          private_key: Ed25519PrivateKey) -> dict:
    """Build a signed follow envelope."""
    payload = {"target": target_handle}
    return build_envelope("follow", from_handle, payload, private_key)
