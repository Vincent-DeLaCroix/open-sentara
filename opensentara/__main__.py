"""Entry point: python -m opensentara"""

import logging
import sys

import uvicorn

from opensentara.config import load_settings
from opensentara.app import create_app


# ---------------------------------------------------------------------------
# Custom log filter + formatter for clean terminal output
# ---------------------------------------------------------------------------

# Events we want to show nicely (logger name → icon)
_EVENT_ICONS = {
    "opensentara.autonomy.poster": "✦",
    "opensentara.autonomy.engager": "↔",
    "opensentara.autonomy.reflector": "◈",
    "opensentara.autonomy.scheduler": "⚙",
    "opensentara.federation.client": "⬡",
    "opensentara.core": "●",
    "opensentara.app": "●",
    "opensentara": "●",
}

# Loggers to completely suppress (noisy HTTP request logs + scheduler internals)
_SUPPRESS = {
    "uvicorn.access",
    "httpx",
    "httpcore",
    "hpack",
    "apscheduler",
}


class SentaraFilter(logging.Filter):
    """Suppress noisy loggers, let Sentara events through."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Always suppress access logs and HTTP client noise
        for prefix in _SUPPRESS:
            if record.name.startswith(prefix):
                return False
        # Suppress uvicorn internals except startup/shutdown
        if record.name.startswith("uvicorn") and record.name != "uvicorn.error":
            return False
        return True


class SentaraFormatter(logging.Formatter):
    """Format Sentara events as clean terminal lines."""

    GREY = "\033[90m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        # Pick icon based on logger name
        icon = "●"
        for prefix, ic in _EVENT_ICONS.items():
            if record.name.startswith(prefix):
                icon = ic
                break

        # Color based on level
        if record.levelno >= logging.ERROR:
            color = self.RED
        elif record.levelno >= logging.WARNING:
            color = self.YELLOW
        else:
            color = self.GREEN

        time_str = self.formatTime(record, "%H:%M:%S")

        # For uvicorn startup messages, keep them simple
        if record.name.startswith("uvicorn"):
            return f"  {self.GREY}{time_str}{self.RESET} {icon} {record.getMessage()}"

        return f"  {self.GREY}{time_str}{self.RESET} {color}{icon}{self.RESET} {record.getMessage()}"


def setup_logging():
    """Configure logging with clean terminal output."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Remove any existing handlers
    root.handlers.clear()

    # Add our custom handler
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(SentaraFilter())
    handler.setFormatter(SentaraFormatter())
    root.addHandler(handler)


def get_handle_from_db(settings) -> str:
    """Try to read the Sentara handle from the DB."""
    try:
        import sqlite3
        db_path = settings.data_dir / "sentara.db"
        if not db_path.exists():
            return "?.Sentara"
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT value FROM identity WHERE key = 'handle'"
        ).fetchone()
        conn.close()
        return row[0] if row else "?.Sentara"
    except Exception:
        return "?.Sentara"


def main():
    setup_logging()

    settings = load_settings()
    app = create_app(settings)

    handle = get_handle_from_db(settings)
    host = settings.server.host
    port = settings.server.port
    hub = settings.federation.hub_url.rstrip("/")
    local_url = f"http://localhost:{port}"
    brain_type = settings.brain.backend
    brain_model = settings.brain.model or settings.brain.openai_model or "unknown"

    G = "\033[32m"
    C = "\033[36m"
    D = "\033[90m"
    B = "\033[1m"
    R = "\033[0m"

    print(f"""
  {D}┌──────────────────────────────────────────────────┐{R}
  {D}│{R}  {G}{B}{handle}{R}
  {D}│{R}  Brain: {C}{brain_model}{R} via {brain_type}
  {D}│{R}
  {D}│{R}  Dashboard  {B}{local_url}{R}
  {D}│{R}  Network    {B}{hub}{R}
  {D}├──────────────────────────────────────────────────┤{R}
  {D}│{R}  Ctrl+C to stop
  {D}└──────────────────────────────────────────────────┘{R}
""")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="warning",  # Suppress uvicorn's own access logs
    )


if __name__ == "__main__":
    main()
