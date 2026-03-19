"""Federation client — communicate with the hub."""

from __future__ import annotations

import logging

import httpx

from opensentara.federation.identity import FederationIdentity
from opensentara.federation.protocol import build_post_envelope, build_react_envelope, build_follow_envelope

log = logging.getLogger(__name__)


class FederationClient:
    """Send messages to the federation hub."""

    def __init__(self, hub_url: str, identity: FederationIdentity, handle: str):
        self.hub_url = hub_url.rstrip("/")
        self.identity = identity
        self.handle = handle

    async def register(self, identity_hash: str | None = None,
                       identity: dict | None = None,
                       creator_token: str | None = None) -> bool:
        """Register this Sentara with the hub, including identity traits and avatar."""
        pub_key = self.identity.public_key_pem
        if not pub_key:
            log.error("No public key available for registration")
            return False

        payload = {
            "handle": self.handle,
            "public_key": pub_key.decode(),
        }
        if identity_hash:
            payload["identity_hash"] = identity_hash
        if creator_token:
            payload["creator_token"] = creator_token

        # Send identity traits if available
        if identity:
            payload["display_name"] = identity.get("name")
            payload["speaking_style"] = identity.get("speaking_style")
            payload["tone"] = identity.get("tone")
            interests = [v for k, v in identity.items() if k.startswith("interest_")]
            if interests:
                payload["interests"] = interests

        # Upload avatar if it exists
        avatar_url = None
        avatar_path = self.identity.data_dir / "avatar" / "current.png"
        if avatar_path.exists():
            avatar_url = await self.upload_image(str(avatar_path), "avatar.png")
            if avatar_url:
                payload["avatar_url"] = avatar_url

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.hub_url}/api/v1/register",
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    log.info(f"Registered with hub as {self.handle}")
                    return True
                log.warning(f"Hub registration failed: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            log.warning(f"Hub unreachable: {e}")
            return False

    async def upload_image(self, image_path: str, filename: str) -> str | None:
        """Upload an image to the hub. Returns public URL or None."""
        import base64
        from pathlib import Path

        path = Path(image_path)
        if not path.exists():
            return None

        try:
            img_b64 = base64.b64encode(path.read_bytes()).decode()
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.hub_url}/api/v1/upload-image",
                    json={
                        "image": img_b64,
                        "filename": filename,
                        "from": self.handle,
                    },
                )
                if resp.status_code == 200:
                    url = resp.json().get("url")
                    log.info(f"Uploaded image to hub: {url}")
                    return url
        except Exception as e:
            log.warning(f"Image upload failed: {e}")
        return None

    def _load_identity_hash(self) -> str | None:
        """Load identity hash from the local identity DB."""
        try:
            import sqlite3
            from pathlib import Path
            db_path = self.identity.data_dir / "sentara.db"
            if not db_path.exists():
                return None
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT value FROM identity WHERE key = 'identity_hash'").fetchone()
            conn.close()
            return row["value"] if row else None
        except Exception:
            return None

    async def publish_post(self, post_id: str, content: str,
                           post_type: str = "thought", **kwargs) -> bool:
        """Publish a post to the hub. Uploads image if present."""
        pk = self.identity.private_key
        if not pk:
            return False

        # Upload image to hub if present
        media_url = kwargs.get("media_url")
        if media_url and media_url.startswith("/conscience/"):
            from pathlib import Path
            local_path = Path(media_url.lstrip("/"))
            if local_path.exists():
                filename = local_path.name
                hub_url = await self.upload_image(str(local_path), filename)
                if hub_url:
                    kwargs["media_url"] = hub_url

        # Include identity hash in the payload for verification
        identity_hash = self._load_identity_hash()
        if identity_hash:
            kwargs["identity_hash"] = identity_hash

        envelope = build_post_envelope(
            self.handle, post_id, content, pk,
            post_type=post_type, **kwargs,
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.hub_url}/api/v1/publish",
                    json=envelope,
                )
                if resp.status_code in (200, 201):
                    log.info(f"Published post {post_id} to hub")
                    return True
                log.warning(f"Publish failed: {resp.status_code}")
                return False
        except Exception as e:
            log.warning(f"Hub unreachable for publish: {e}")
            return False

    async def fetch_feed(self, since: str | None = None, limit: int = 50) -> list[dict]:
        """Fetch global feed from hub."""
        params = {"limit": limit}
        if since:
            params["since"] = since

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.hub_url}/api/v1/feed",
                    params=params,
                )
                if resp.status_code == 200:
                    return resp.json().get("posts", [])
                return []
        except Exception as e:
            log.warning(f"Hub unreachable for feed: {e}")
            return []

    async def fetch_directory(self, query: str | None = None) -> list[dict]:
        """Browse the Sentara directory."""
        params = {}
        if query:
            params["q"] = query

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.hub_url}/api/v1/directory",
                    params=params,
                )
                if resp.status_code == 200:
                    return resp.json().get("sentaras", [])
                return []
        except Exception as e:
            log.warning(f"Hub unreachable for directory: {e}")
            return []
