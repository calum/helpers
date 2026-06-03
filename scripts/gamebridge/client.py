"""
GameBridge TCP client.

Connects to the RuneLite plugin on 127.0.0.1:7070 and yields one parsed
dict per game tick (~600 ms).  Reconnects automatically on disconnect.
"""
from __future__ import annotations

import json
import logging
import socket
import time
from typing import Generator

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7070
RECV_BUFSIZE = 65536


def stream(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    retry_delay: float = 5.0,
) -> Generator[dict, None, None]:
    """
    Yield parsed JSON tick messages forever, reconnecting on disconnect.

    Each yielded dict has the shape described in GAMEBRIDGE.md:
      { "tick": int, "player": {...}, "camera": {...},
        "npcs": [...], "objects": [...], "events": [...] }
    """
    while True:
        try:
            log.info("Connecting to %s:%d …", host, port)
            with socket.create_connection((host, port)) as sock:
                log.info("Connected.")
                buf = ""
                while True:
                    chunk = sock.recv(RECV_BUFSIZE)
                    if not chunk:
                        raise ConnectionError("server closed connection")
                    buf += chunk.decode("utf-8", errors="replace")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if line:
                            try:
                                yield json.loads(line)
                            except json.JSONDecodeError as exc:
                                log.warning("Bad JSON (%s): %.80s", exc, line)
        except (OSError, ConnectionError) as exc:
            log.warning("Disconnected (%s). Retrying in %.1fs …", exc, retry_delay)
            time.sleep(retry_delay)
