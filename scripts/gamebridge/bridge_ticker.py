"""BridgeTicker — background QThread that reads the GameBridge TCP stream."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from .client import stream as tcp_stream


class BridgeTicker(QThread):
    """Reads the GameBridge stream and emits one signal per tick."""
    tick_received: pyqtSignal = pyqtSignal(dict)

    def __init__(self, host: str = "127.0.0.1", port: int = 7070):
        super().__init__()
        self.host = host
        self.port = port

    def run(self) -> None:
        for msg in tcp_stream(host=self.host, port=self.port):
            self.tick_received.emit(dict(msg))
