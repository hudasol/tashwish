"""Run the API: `python -m tashwish.api --release-dir release/ [--host 0.0.0.0] [--port 8000]`."""

from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tashwish.api", description=__doc__)
    ap.add_argument("--release-dir", default=os.environ.get("TASHWISH_RELEASE_DIR"), help="release directory")
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    a = ap.parse_args(argv)
    if not a.release_dir:
        ap.error("--release-dir or TASHWISH_RELEASE_DIR is required")
    try:
        import uvicorn

        from .app import create_app
        from .release import ReleaseError
    except ImportError:
        print("The API needs the optional extra: pip install '.[api]'", file=sys.stderr)
        return 2
    try:
        app = create_app(a.release_dir)
    except ReleaseError as e:
        print(f"refusing to start: {e}", file=sys.stderr)
        return 1
    uvicorn.run(app, host=a.host, port=a.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
