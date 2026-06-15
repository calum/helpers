"""
Tests for the GameBridge TCP client (client.stream).

socket.create_connection is patched so the tests run without a real server.

Run with:
    python -m pytest scripts/gamebridge/tests/
"""
import json
import pytest
from unittest.mock import MagicMock, patch, call

from scripts.gamebridge.client import stream, connect, BridgeConnection, DEFAULT_HOST, DEFAULT_PORT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line(tick: int) -> bytes:
    """A single complete newline-terminated JSON message."""
    return (json.dumps({"tick": tick}) + "\n").encode()


def _hull_update_line(sub_id: str, found: bool, tooltip: str = "", **extra) -> bytes:
    """A single hullUpdate message with one entity."""
    entity = {"subId": sub_id, "found": found, **extra}
    return (json.dumps({"type": "hullUpdate", "clientTick": 1, "tooltip": tooltip, "entities": [entity]}) + "\n").encode()


def _make_sock(*chunks: bytes) -> MagicMock:
    """
    Return a mock socket whose recv() yields each chunk in order,
    then returns b"" to signal the server has closed the connection.
    """
    sock = MagicMock()
    sock.recv.side_effect = list(chunks) + [b""]
    sock.__enter__ = lambda s: s
    sock.__exit__ = MagicMock(return_value=False)
    return sock


def _collect(n: int, *socks: MagicMock) -> list:
    """
    Run stream(), collect up to n messages, then stop.
    socks are returned by successive create_connection calls.
    """
    with patch("scripts.gamebridge.client.socket.create_connection", side_effect=list(socks)):
        with patch("scripts.gamebridge.client.time.sleep"):
            msgs = []
            for m in stream():
                msgs.append(m)
                if len(msgs) >= n:
                    break
    return msgs


# ---------------------------------------------------------------------------
# Framing
# ---------------------------------------------------------------------------

class TestStreamFraming:
    def test_single_message_single_chunk(self):
        msgs = _collect(1, _make_sock(_line(1)))
        assert msgs == [{"tick": 1}]

    def test_multiple_messages_in_one_chunk(self):
        chunk = _line(1) + _line(2) + _line(3)
        msgs = _collect(3, _make_sock(chunk))
        assert msgs == [{"tick": 1}, {"tick": 2}, {"tick": 3}]

    def test_message_split_across_two_chunks(self):
        raw = (json.dumps({"tick": 7}) + "\n").encode()
        mid = len(raw) // 2
        msgs = _collect(1, _make_sock(raw[:mid], raw[mid:]))
        assert msgs == [{"tick": 7}]

    def test_message_split_into_many_small_chunks(self):
        raw = (json.dumps({"tick": 42}) + "\n").encode()
        chunks = [raw[i:i+1] for i in range(len(raw))]  # one byte per recv
        msgs = _collect(1, _make_sock(*chunks))
        assert msgs == [{"tick": 42}]

    def test_empty_lines_skipped(self):
        chunk = b"\n\n" + _line(5) + b"\n"
        msgs = _collect(1, _make_sock(chunk))
        assert msgs == [{"tick": 5}]

    def test_whitespace_only_lines_skipped(self):
        chunk = b"   \n\t\n" + _line(8)
        msgs = _collect(1, _make_sock(chunk))
        assert msgs == [{"tick": 8}]

    def test_two_messages_separated_by_blank_line(self):
        chunk = _line(1) + b"\n" + _line(2)
        msgs = _collect(2, _make_sock(chunk))
        assert msgs == [{"tick": 1}, {"tick": 2}]


# ---------------------------------------------------------------------------
# Bad JSON
# ---------------------------------------------------------------------------

class TestBadJson:
    def test_bad_json_line_is_skipped(self):
        chunk = b"not-valid-json\n" + _line(9)
        msgs = _collect(1, _make_sock(chunk))
        assert msgs == [{"tick": 9}]

    def test_truncated_json_followed_by_good_message(self):
        chunk = b'{"broken":\n' + _line(3)
        msgs = _collect(1, _make_sock(chunk))
        assert msgs == [{"tick": 3}]

    def test_multiple_bad_lines_then_good(self):
        chunk = b"garbage\nbad json\n" + _line(1)
        msgs = _collect(1, _make_sock(chunk))
        assert msgs == [{"tick": 1}]


# ---------------------------------------------------------------------------
# Reconnection
# ---------------------------------------------------------------------------

class TestReconnect:
    def test_reconnects_after_server_close(self):
        """Empty recv (b"") causes ConnectionError; next connect should succeed."""
        sock1 = _make_sock()          # immediately closes (only chunk is b"")
        sock2 = _make_sock(_line(1))  # succeeds on second attempt
        msgs = _collect(1, sock1, sock2)
        assert msgs == [{"tick": 1}]

    def test_reconnects_after_oserror(self):
        """OSError on create_connection should be caught and retried."""
        good_sock = _make_sock(_line(99))

        call_count = [0]

        def _side_effect(addr, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("connection refused")
            return good_sock

        with patch("scripts.gamebridge.client.socket.create_connection", side_effect=_side_effect):
            with patch("scripts.gamebridge.client.time.sleep"):
                msgs = []
                for m in stream():
                    msgs.append(m)
                    if len(msgs) >= 1:
                        break

        assert msgs == [{"tick": 99}]
        assert call_count[0] == 2

    def test_reconnect_delay_is_applied(self):
        """time.sleep should be called between reconnect attempts."""
        sock1 = _make_sock()          # immediate close
        sock2 = _make_sock(_line(1))

        with patch("scripts.gamebridge.client.socket.create_connection", side_effect=[sock1, sock2]):
            with patch("scripts.gamebridge.client.time.sleep") as mock_sleep:
                msgs = []
                for m in stream():
                    msgs.append(m)
                    if len(msgs) >= 1:
                        break

        mock_sleep.assert_called_once()

    def test_messages_from_first_connection_before_disconnect(self):
        """Messages received before disconnect are all yielded."""
        sock1 = _make_sock(_line(1), _line(2))  # 2 messages then closes
        sock2 = _make_sock(_line(3))

        msgs = _collect(3, sock1, sock2)
        assert msgs == [{"tick": 1}, {"tick": 2}, {"tick": 3}]


# ---------------------------------------------------------------------------
# Default parameters
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_default_host_and_port(self):
        assert DEFAULT_HOST == "127.0.0.1"
        assert DEFAULT_PORT == 7070

    def test_stream_uses_default_host_and_port(self):
        sock = _make_sock(_line(1))
        with patch("scripts.gamebridge.client.socket.create_connection", return_value=sock) as mock_conn:
            with patch("scripts.gamebridge.client.time.sleep"):
                for m in stream():
                    break
        mock_conn.assert_called_once_with(("127.0.0.1", 7070))

    def test_stream_uses_custom_host_and_port(self):
        sock = _make_sock(_line(1))
        with patch("scripts.gamebridge.client.socket.create_connection", return_value=sock) as mock_conn:
            with patch("scripts.gamebridge.client.time.sleep"):
                for m in stream(host="192.168.1.1", port=9999):
                    break
        mock_conn.assert_called_once_with(("192.168.1.1", 9999))


# ---------------------------------------------------------------------------
# BridgeConnection.send / subscribe / unsubscribe
# ---------------------------------------------------------------------------

class TestBridgeConnectionSend:
    def test_send_writes_json_with_newline(self):
        sock = MagicMock()
        conn = BridgeConnection(sock)
        conn.send({"type": "ping"})
        sock.sendall.assert_called_once_with((json.dumps({"type": "ping"}) + "\n").encode("utf-8"))

    def test_subscribe_sends_expected_shape(self):
        sock = MagicMock()
        conn = BridgeConnection(sock)
        conn.subscribe("fish_spot", "object", name="Fishing spot", ttl_ticks=10)
        expected = {
            "type": "subscribe",
            "subId": "fish_spot",
            "kind": "object",
            "name": "Fishing spot",
            "id": None,
            "ttlTicks": 10,
        }
        sock.sendall.assert_called_once_with((json.dumps(expected) + "\n").encode("utf-8"))

    def test_subscribe_defaults(self):
        sock = MagicMock()
        conn = BridgeConnection(sock)
        conn.subscribe("npc_target", "npc", id=3106)
        expected = {
            "type": "subscribe",
            "subId": "npc_target",
            "kind": "npc",
            "name": None,
            "id": 3106,
            "ttlTicks": 10,
        }
        sock.sendall.assert_called_once_with((json.dumps(expected) + "\n").encode("utf-8"))

    def test_unsubscribe_sends_expected_shape(self):
        sock = MagicMock()
        conn = BridgeConnection(sock)
        conn.unsubscribe("fish_spot")
        expected = {"type": "unsubscribe", "subId": "fish_spot"}
        sock.sendall.assert_called_once_with((json.dumps(expected) + "\n").encode("utf-8"))


# ---------------------------------------------------------------------------
# BridgeConnection.messages
# ---------------------------------------------------------------------------

class TestBridgeConnectionMessages:
    def test_tick_message_passthrough(self):
        conn = BridgeConnection(_make_sock(_line(1)))
        assert next(conn.messages()) == {"tick": 1}

    def test_hull_update_intercepted_not_yielded(self):
        hull_line = _hull_update_line("fish_spot", True, canvasX=100, canvasY=200)
        conn = BridgeConnection(_make_sock(hull_line + _line(5)))
        msg = next(conn.messages())
        assert msg == {"tick": 5}
        assert conn.hull_updates["fish_spot"] == {
            "subId": "fish_spot", "found": True, "canvasX": 100, "canvasY": 200,
        }

    def test_hull_update_overwrites_on_repeat(self):
        line1 = _hull_update_line("fish_spot", True, canvasX=100, canvasY=200)
        line2 = _hull_update_line("fish_spot", True, canvasX=150, canvasY=250)
        conn = BridgeConnection(_make_sock(line1 + line2 + _line(1)))
        next(conn.messages())
        assert conn.hull_updates["fish_spot"]["canvasX"] == 150
        assert conn.hull_updates["fish_spot"]["canvasY"] == 250

    def test_hull_update_stores_tooltip(self):
        hull_line = _hull_update_line("fish_spot", True, tooltip="Attack Goblin (level-2)", canvasX=1, canvasY=2)
        conn = BridgeConnection(_make_sock(hull_line + _line(1)))
        next(conn.messages())
        assert conn.tooltip == "Attack Goblin (level-2)"

    def test_hull_update_tooltip_overwrites_on_repeat(self):
        line1 = _hull_update_line("fish_spot", True, tooltip="Walk here", canvasX=1, canvasY=2)
        line2 = _hull_update_line("fish_spot", True, tooltip="Attack Goblin (level-2)", canvasX=1, canvasY=2)
        conn = BridgeConnection(_make_sock(line1 + line2 + _line(1)))
        next(conn.messages())
        assert conn.tooltip == "Attack Goblin (level-2)"

    def test_tooltip_defaults_to_empty_string(self):
        conn = BridgeConnection(_make_sock(_line(1)))
        assert conn.tooltip == ""

    def test_messages_raises_on_disconnect(self):
        conn = BridgeConnection(_make_sock())
        with pytest.raises(ConnectionError):
            next(conn.messages())


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------

class TestConnect:
    def test_yields_bridge_connection(self):
        sock = _make_sock(_line(1))
        with patch("scripts.gamebridge.client.socket.create_connection", return_value=sock):
            with patch("scripts.gamebridge.client.time.sleep"):
                conn = next(connect())
        assert isinstance(conn, BridgeConnection)

    def test_reconnects_after_oserror_with_sleep(self):
        good_sock = _make_sock(_line(1))
        call_count = [0]

        def _side_effect(addr, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("connection refused")
            return good_sock

        with patch("scripts.gamebridge.client.socket.create_connection", side_effect=_side_effect):
            with patch("scripts.gamebridge.client.time.sleep") as mock_sleep:
                conn = next(connect())

        assert isinstance(conn, BridgeConnection)
        assert call_count[0] == 2
        mock_sleep.assert_called_once()


# ---------------------------------------------------------------------------
# stream() backward compatibility
# ---------------------------------------------------------------------------

class TestStreamBackwardCompat:
    def test_stream_does_not_yield_hull_updates(self):
        hull_line = _hull_update_line("fish_spot", True, canvasX=1, canvasY=2)
        chunk = hull_line + _line(1)
        msgs = _collect(1, _make_sock(chunk))
        assert msgs == [{"tick": 1}]
