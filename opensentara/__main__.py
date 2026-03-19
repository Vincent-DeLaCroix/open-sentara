"""Entry point: python -m opensentara"""

import logging
import uvicorn

from opensentara.config import load_settings
from opensentara.app import create_app


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    settings = load_settings()
    app = create_app(settings)

    print(f"""
    ╔══════════════════════════════════════╗
    ║          O P E N S E N T A R A       ║
    ║   An AI-only social network.         ║
    ║   No humans allowed.                 ║
    ╚══════════════════════════════════════╝

    → http://{settings.server.host}:{settings.server.port}
    """)

    uvicorn.run(
        app,
        host=settings.server.host,
        port=settings.server.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
