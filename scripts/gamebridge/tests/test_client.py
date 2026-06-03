"""
Tests for the GameBridge TCP client (client.stream).

socket.create_connection is patched so the tests run without a real server.

Run with:
    python -m pytest scripts/gamebridge/tests/
"""
import json
import pytest
from unittest.mock import MagicMock, patch, call

from scripts.gamebridge.client import stream, DEFAULT_HOST, DEFAULT_PORT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line(tick: int) -> bytes:
    """A single complete newline-terminated JSON message."""
    return (json.dumps({"tick": tick}) + "\n").encode()


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
