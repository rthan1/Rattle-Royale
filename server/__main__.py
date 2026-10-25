"""Run the phone connection server."""

import logging
import os
import socket
from pathlib import Path

from aiohttp import web

from server.app import HOST, PORT, create_app

TUNNEL_CONFIG = Path(__file__).resolve().parent.parent / "ngrok.yml"


def lan_address() -> str | None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def tunnel_url() -> str | None:
    """Public https address from ngrok.yml, once the placeholder is replaced."""
    if not TUNNEL_CONFIG.exists():
        return None
    for line in TUNNEL_CONFIG.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("url:") or "https://" not in stripped:
            continue
        value = stripped.split(":", 1)[1].strip()
        if "REPLACE_ME" in value:
            return None
        return value
    return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("server")
    log.info("On this laptop: http://127.0.0.1:%s", PORT)
    address = lan_address()
    if address:
        log.info("On this Wi-Fi: http://%s:%s", address, PORT)
    public = tunnel_url()
    if public:
        log.info("On your phone:  %s", public)
    else:
        log.info("On your phone:  put the ngrok url in ngrok.yml")
    app = create_app(public)
    port_name = os.environ.get("RATTLE_PORT", "").strip()
    if port_name:
        app["bridge"].open_port(port_name)
    else:
        log.info("Robot offline (RATTLE_PORT is not set)")
    web.run_app(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
