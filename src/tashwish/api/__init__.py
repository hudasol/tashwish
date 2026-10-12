"""Read only HTTP API over a Tashwish release directory (optional extra: `pip install '.[api]'`).

Research and monitoring tool, not for navigation or safety of life, no attribution to any actor.

FastAPI is imported lazily, so `import tashwish.api` works on a base install without the `api` extra.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["create_app"]


def create_app(release_dir: str | Path, **kwargs: Any):
    """Build the FastAPI application for a release directory. Imports FastAPI on first use."""
    from .app import create_app as _create_app

    return _create_app(release_dir, **kwargs)
