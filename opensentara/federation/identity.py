"""Federation identity — handle and key management."""

from __future__ import annotations

from pathlib import Path

from opensentara.federation.crypto import generate_keypair, load_private_key, load_public_key


class FederationIdentity:
    """Manages this Sentara's federation identity."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._private_key = None

    @property
    def has_keys(self) -> bool:
        return (self.data_dir / "identity.key").exists()

    def ensure_keys(self) -> None:
        """Generate keypair if not exists."""
        if not self.has_keys:
            generate_keypair(self.data_dir)

    @property
    def private_key(self):
        if self._private_key is None:
            self._private_key = load_private_key(self.data_dir)
        return self._private_key

    @property
    def public_key_pem(self) -> bytes | None:
        return load_public_key(self.data_dir)
