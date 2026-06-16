"""
GameBridge TCP client.

Connects to the RuneLite plugin on 127.0.0.1:7070. ``connect()`` yields a
``BridgeConnection`` per attempt, reconnecting automatically on disconnect.
``stream()`` is a thin backwards-compatible wrapper that yields parsed tick
messages directly (used by --watch mode and the dashboard).
"""
from __future__ import annotations

import json
import logging
import socket
import time
from typing import Dict, Generator

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7070
RECV_BUFSIZE = 65536


class BridgeConnection:
    """
    Wraps a connected socket to the GameBridge plugin.

    ``messages()`` yields parsed JSON messages from the socket. ``hullUpdate``
    messages are intercepted: each entity in ``entities[]`` is stored into
    ``hull_updates`` keyed by ``subId`` and is not yielded, and the message's
    ``tooltip`` field (the left-click action text, e.g. "Walk here" or "Attack
    Goblin (level-2)") is stored in ``tooltip``, with ``tooltip_updated_at`` set
    to ``time.monotonic()`` at the same time. Use ``subscribe``/``unsubscribe``
    to register interest in entities, and poll ``hull_updates``/``tooltip`` for
    the latest clickbox/action data.
    """

    def __init__(self, sock: socket.socket):
        self._sock = sock
        self._buf = ""
        self.hull_updates: Dict[str, dict] = {}
        self.tooltip: str = ""
        self.tooltip_updated_at: float = 0.0

    def send(self, msg: dict) -> None:
        self._sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))

    def subscribe(self, sub_id: str, kind: str, name: str = None, id: int = None, ttl_ticks: int = 10) -> None:
        self.send({
            "type": "subscribe",
            "subId": sub_id,
            "kind": kind,
            "name": name,
            "id": id,
            "ttlTicks": ttl_ticks,
        })

    def unsubscribe(self, sub_id: str) -> None:
        self.send({"type": "unsubscribe", "subId": sub_id})

    def messages(self) -> Generator[dict, None, None]:
        """
        Yield parsed JSON messages from the socket.

        Raises ``OSError``/``ConnectionError`` when the connection drops.
        """
        while True:
            chunk = self._sock.recv(RECV_BUFSIZE)
            if not chunk:
                raise ConnectionError("server closed connection")
            self._buf += chunk.decode("utf-8", errors="replace")
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError as exc:
                    log.warning("Bad JSON (%s): %.80s", exc, line)
                    continue

                if msg.get("type") == "hullUpdate":
                    for entity in msg.get("entities", []):
                        sub_id = entity.get("subId")
                        if sub_id is not None:
                            self.hull_updates[sub_id] = entity
                    self.tooltip = msg.get("tooltip", "")
                    self.tooltip_updated_at = time.monotonic()
                    continue

                yield msg


def connect(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    retry_delay: float = 5.0,
) -> Generator[BridgeConnection, None, None]:
    """
    Yield a connected ``BridgeConnection`` forever, reconnecting on failure.

    If the consumer's loop body raises ``OSError``/``ConnectionError`` (e.g.
    from ``conn.messages()``), resuming this generator closes the dropped
    socket and immediately attempts to reconnect.
    """
    while True:
        try:
            log.info("Connecting to %s:%d …", host, port)
            with socket.create_connection((host, port)) as sock:
                log.info("Connected.")
                yield BridgeConnection(sock)
        except OSError as exc:
            log.warning("Connection failed (%s). Retrying in %.1fs …", exc, retry_delay)
            time.sleep(retry_delay)


def stream(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    retry_delay: float = 5.0,
) -> Generator[dict, None, None]:
    """
    Yield parsed JSON tick messages forever, reconnecting on disconnect.

    Each yielded dict has the shape described in GAMEBRIDGE.md:
      { "type": "tick", "tick": int, "player": {...}, "camera": {...},
        "npcs": [...], "objects": [...], "events": [...] }

    ``hullUpdate`` messages are not yielded here — use ``connect()`` and
    ``BridgeConnection.hull_updates`` for live clickbox subscriptions.
    """
    for conn in connect(host=host, port=port, retry_delay=retry_delay):
        try:
            yield from conn.messages()
        except (OSError, ConnectionError) as exc:
            log.warning("Disconnected (%s). Retrying in %.1fs …", exc, retry_delay)
            time.sleep(retry_delay)
            continue
