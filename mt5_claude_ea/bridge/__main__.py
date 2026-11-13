"""Run: python -m bridge   (binds loopback only; refuses anything else)."""
from __future__ import annotations

import secrets
import sys


def main() -> int:
    if "--new-token" in sys.argv:
        print(secrets.token_urlsafe(48))
        return 0
    from dotenv import load_dotenv
    import uvicorn

    from .config import ConfigError, load_settings
    from .server import create_app

    load_dotenv()
    try:
        s = load_settings()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    if not s.bridge_token:
        print("BRIDGE_TOKEN is not set: every request will be rejected (401).", file=sys.stderr)
    uvicorn.run(create_app(s), host=s.host, port=s.port, access_log=False, server_header=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
