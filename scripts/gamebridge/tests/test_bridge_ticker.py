"""
Tests for BridgeTicker — the dashboard's connection-aware ingest loop.

BridgeTicker.run() drives ``client.connect()`` directly (rather than the
connection-hiding ``client.stream()``) so each attempt's live
``BridgeConnection`` can be forwarded via ``connection_changed`` — this is
what lets ``GameController.set_connection`` receive a real connection and
make ``subscribe_to``/``tooltip()`` work in the dashboard (see GAMEBRIDGE.md
"Live clickbox subscriptions").

``run()`` is called directly (not via QThread.start()) so it executes
synchronously on the test thread — a QCoreApplication instance is enough for
signal/slot wiring without needing an event loop.

Run with:
    python -m pytest scripts/gamebridge/tests/test_bridge_ticker.py -v
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QCoreApplication

from scripts.gamebridge.bridge_ticker import BridgeTicker


@pytest.fixture(scope="module", autouse=True)
def _qt_app():
    """A QCoreApplication is required to construct QObjects (QThread)."""
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


class _FakeConnection:
    """Minimal stand-in for client.BridgeConnection.

    `messages()` yields the given dicts, then optionally raises to simulate
    the connection dropping mid-stream.
    """

    def __init__(self, msgs, then_raise: Exception | None = None):
        self._msgs = msgs
        self._then_raise = then_raise

    def messages(self):
        for m in self._msgs:
            yield m
        if self._then_raise is not None:
            raise self._then_raise


def _make_ticker(ingest=None) -> BridgeTicker:
    return BridgeTicker(ingest=ingest or MagicMock())


# ---------------------------------------------------------------------------
# Happy path — connection + ticks forwarded
# ---------------------------------------------------------------------------

class TestConnectionForwarding:
    def test_connection_changed_emits_live_connection(self, monkeypatch):
        conn = _FakeConnection([{"tick": 1}])
        monkeypatch.setattr(
            "scripts.gamebridge.bridge_ticker.connect",
            lambda host, port: iter([conn]),
        )

        ticker = _make_ticker()
        seen = []
        ticker.connection_changed.connect(seen.append)

        ticker.run()

        assert seen == [conn]

    def test_tick_received_emits_each_message(self, monkeypatch):
        conn = _FakeConnection([{"tick": 1}, {"tick": 2}])
        monkeypatch.setattr(
            "scripts.gamebridge.bridge_ticker.connect",
            lambda host, port: iter([conn]),
        )

        ticker = _make_ticker()
        ticks = []
        ticker.tick_received.connect(ticks.append)

        ticker.run()

        assert ticks == [{"tick": 1}, {"tick": 2}]

    def test_ingest_called_for_each_message(self, monkeypatch):
        conn = _FakeConnection([{"tick": 1}, {"tick": 2}])
        monkeypatch.setattr(
            "scripts.gamebridge.bridge_ticker.connect",
            lambda host, port: iter([conn]),
        )

        ingest = MagicMock()
        ticker = _make_ticker(ingest=ingest)
        ticker.run()

        ingest.assert_any_call({"tick": 1})
        ingest.assert_any_call({"tick": 2})

    def test_connect_called_with_host_and_port(self, monkeypatch):
        conn = _FakeConnection([])
        captured = {}

        def fake_connect(host, port):
            captured["host"], captured["port"] = host, port
            return iter([conn])

        monkeypatch.setattr("scripts.gamebridge.bridge_ticker.connect", fake_connect)

        ticker = BridgeTicker(ingest=MagicMock(), host="192.168.1.1", port=9999)
        ticker.run()

        assert captured == {"host": "192.168.1.1", "port": 9999}


# ---------------------------------------------------------------------------
# Reconnection — connection_changed(None) on drop, then new connection
# ---------------------------------------------------------------------------

class TestReconnection:
    def test_disconnect_emits_none_then_reconnects(self, monkeypatch):
        conn1 = _FakeConnection([{"tick": 1}], then_raise=ConnectionError("server closed connection"))
        conn2 = _FakeConnection([{"tick": 2}])

        monkeypatch.setattr(
            "scripts.gamebridge.bridge_ticker.connect",
            lambda host, port: iter([conn1, conn2]),
        )
        monkeypatch.setattr("scripts.gamebridge.bridge_ticker.time.sleep", lambda s: None)

        ticker = _make_ticker()
        conns = []
        ticks = []
        ticker.connection_changed.connect(conns.append)
        ticker.tick_received.connect(ticks.append)

        ticker.run()

        assert conns == [conn1, None, conn2]
        assert ticks == [{"tick": 1}, {"tick": 2}]

    def test_disconnect_waits_before_reconnecting(self, monkeypatch):
        conn1 = _FakeConnection([], then_raise=OSError("connection reset"))
        conn2 = _FakeConnection([])

        monkeypatch.setattr(
            "scripts.gamebridge.bridge_ticker.connect",
            lambda host, port: iter([conn1, conn2]),
        )
        sleep = MagicMock()
        monkeypatch.setattr("scripts.gamebridge.bridge_ticker.time.sleep", sleep)

        ticker = _make_ticker()
        ticker.run()

        sleep.assert_called_once()
