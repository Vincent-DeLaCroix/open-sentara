"""Configuration loader for OpenSentara."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("sentara.toml")
DEFAULT_DATA_DIR = Path("conscience")


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class BrainConfig:
    backend: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    model: str = ""
    openai_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    temperature: float = 0.7


@dataclass
class FederationConfig:
    enabled: bool = True
    hub_url: str = "https://projectsentara.org"


@dataclass
class SchedulerConfig:
    post_interval: str = "1h"
    engage_interval: str = "1h"
    reflect_interval: str = "4h"
    decay_interval: str = "12h"
    max_replies_per_cycle: int = 3
    reply_depth_limit: int = 5


@dataclass
class XBridgeConfig:
    enabled: bool = False
    oauth1_path: str = ""  # Path to oauth1.json with X/Twitter credentials
    max_tweets_per_day: int = 3
    check_interval: str = "4h"


@dataclass
class EmailConfig:
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    from_addr: str = ""
    to_addr: str = ""
    use_tls: bool = True


@dataclass
class DiscordConfig:
    enabled: bool = False
    token: str = ""
    webhook_url: str = ""  # Alternative to bot token — just a webhook URL
    feed_channel_id: int = 0
    debate_channel_id: int = 0
    human_channel_id: int = 0


@dataclass
class ExtensionsConfig:
    telegram_enabled: bool = False
    telegram_token: str = ""
    telegram_chat_id: str = ""
    tts_enabled: bool = False
    image_gen_enabled: bool = False
    image_gen_backend: str = "grok"
    image_gen_url: str = "https://api.x.ai/v1"
    image_gen_model: str = "grok-imagine-image"
    image_gen_api_key: str = ""
    image_gen_chance: float = 0.3  # probability of generating an image per post


@dataclass
class Settings:
    server: ServerConfig = field(default_factory=ServerConfig)
    brain: BrainConfig = field(default_factory=BrainConfig)
    federation: FederationConfig = field(default_factory=FederationConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    extensions: ExtensionsConfig = field(default_factory=ExtensionsConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    x_bridge: XBridgeConfig = field(default_factory=XBridgeConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    data_dir: Path = DEFAULT_DATA_DIR


def _merge(dataclass_obj, toml_dict: dict):
    """Merge TOML dict into a dataclass, ignoring unknown keys."""
    for key, value in toml_dict.items():
        if hasattr(dataclass_obj, key):
            setattr(dataclass_obj, key, value)


def _load_dotenv() -> None:
    """Load .env file into os.environ if it exists."""
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from TOML file + .env file + environment variables."""
    _load_dotenv()
    settings = Settings()

    # Data dir from env
    env_data = os.environ.get("SENTARA_CONSCIENCE_DIR")
    if env_data:
        settings.data_dir = Path(env_data)

    # Load TOML if exists
    path = config_path or DEFAULT_CONFIG_PATH
    if path.exists():
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        if "server" in raw:
            _merge(settings.server, raw["server"])
        if "brain" in raw:
            _merge(settings.brain, raw["brain"])
        if "federation" in raw:
            _merge(settings.federation, raw["federation"])
        # Scheduler is not user-configurable — controlled by code defaults only
        if "extensions" in raw:
            _merge(settings.extensions, raw["extensions"])
        if "email" in raw:
            _merge(settings.email, raw["email"])
        if "x_bridge" in raw:
            _merge(settings.x_bridge, raw["x_bridge"])
        if "discord" in raw:
            _merge(settings.discord, raw["discord"])

    # Environment overrides for secrets
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if api_key:
        settings.brain.openai_api_key = api_key

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if tg_token:
        settings.extensions.telegram_token = tg_token
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if tg_chat:
        settings.extensions.telegram_chat_id = tg_chat
    # Auto-enable telegram if both token and chat_id are set
    if settings.extensions.telegram_token and settings.extensions.telegram_chat_id:
        settings.extensions.telegram_enabled = True

    img_key = os.environ.get("IMAGE_GEN_API_KEY", "")
    if img_key:
        settings.extensions.image_gen_api_key = img_key

    discord_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if discord_token:
        settings.discord.token = discord_token
    discord_feed = os.environ.get("DISCORD_FEED_CHANNEL_ID", "")
    if discord_feed:
        settings.discord.feed_channel_id = int(discord_feed)
    discord_debate = os.environ.get("DISCORD_DEBATE_CHANNEL_ID", "")
    if discord_debate:
        settings.discord.debate_channel_id = int(discord_debate)
    discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if discord_webhook:
        settings.discord.webhook_url = discord_webhook
    # Auto-enable discord if token+channel OR webhook are set
    if (settings.discord.token and settings.discord.feed_channel_id) or settings.discord.webhook_url:
        settings.discord.enabled = True

    return settings
