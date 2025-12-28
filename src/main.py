"""Application entry points."""

import uvicorn

from src.core import settings


def main() -> None:
    """Run production server."""
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


def dev() -> None:
    """Run development server with reload."""
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=settings.port,
        log_level="debug",
        reload=True,
        reload_dirs=["src"],
    )


if __name__ == "__main__":
    dev()
