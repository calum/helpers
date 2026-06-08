"""Tests for scripts.gamebridge.recording.recorder.SessionRecorder.

Verifies the observable contract: starting/stopping produces a JSONL file
whose lines parse back into the documented record shapes (session_start,
tick, click, session_end), counters and the returned summary match what was
written, and capture calls outside an active session are safely no-ops.
"""
from __future__ import annotations

import json

import pytest

from scripts.gamebridge.recording import recorder as recorder_module
from scripts.gamebridge.recording.recorder import ClickRecord, SessionRecorder
from scripts.gamebridge.state.game_state import GameState


@pytest.fixture(autouse=True)
def _redirect_recordings_dir(tmp_path, monkeypatch):
    """Never touch the user's real ~/.gamebridge/recordings directory in tests."""
    monkeypatch.setattr(recorder_module, "RECORDINGS_DIR", tmp_path)
    return tmp_path


def _read_lines(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _game(tick=5, world_x=3200, world_y=3200, animation=-1, interacting_with=None):
    g = GameState()
    g.tick = tick
    g.player = {"name": "Zezima", "worldX": world_x, "worldY": world_y,
                "plane": 0, "animation": animation, "hp": 99, "prayer": 50}
    g.interacting_with = interacting_with
    return g


class TestLifecycle:
    def test_start_creates_file_with_session_start_record(self, tmp_path):
        rec = SessionRecorder()

        path = rec.start(player_name="Zezima")

        assert path.parent == tmp_path
        assert path.exists()
        assert rec.is_recording is True
        records = _read_lines(path)
        assert records[0]["type"] == "session_start"
        assert records[0]["playerName"] == "Zezima"
        assert "startedAt" in records[0]

    def test_start_twice_raises(self):
        rec = SessionRecorder()
        rec.start()

        with pytest.raises(RuntimeError):
            rec.start()

    def test_stop_without_start_raises(self):
        rec = SessionRecorder()

        with pytest.raises(RuntimeError):
            rec.stop()

    def test_stop_writes_session_end_and_returns_summary(self):
        rec = SessionRecorder()
        path = rec.start()
        rec.record_tick({"tick": 1})
        rec.record_tick({"tick": 2})

        summary = rec.stop()

        assert summary["path"] == path
        assert summary["ticks"] == 2
        assert summary["clicks"] == 0
        assert summary["durationSeconds"] >= 0
        assert rec.is_recording is False

        records = _read_lines(path)
        assert records[-1]["type"] == "session_end"
        assert records[-1]["ticks"] == 2
        assert records[-1]["clicks"] == 0

    def test_stopping_closes_file_so_it_can_be_reopened_elsewhere(self):
        rec = SessionRecorder()
        path = rec.start()
        rec.stop()

        # Would raise on Windows (file still open / locked) if stop() didn't close it.
        with open(path, "a", encoding="utf-8"):
            pass


class TestRecordTick:
    def test_appends_raw_message_verbatim_and_increments_count(self):
        rec = SessionRecorder()
        path = rec.start()
        msg = {"tick": 42, "player": {"name": "Zezima"}, "events": [{"type": "xp", "skill": "MINING"}]}

        rec.record_tick(msg)

        assert rec.tick_count == 1
        records = _read_lines(path)
        tick_records = [r for r in records if r["type"] == "tick"]
        assert len(tick_records) == 1
        assert tick_records[0]["msg"] == msg
        assert "wallTime" in tick_records[0]

    def test_does_nothing_when_not_recording(self):
        rec = SessionRecorder()

        rec.record_tick({"tick": 1})  # no start() — must be a safe no-op

        assert rec.tick_count == 0
        assert rec.is_recording is False


class TestRecordClick:
    def test_resolves_and_appends_click_with_player_context(self):
        rec = SessionRecorder()
        path = rec.start()
        game = _game(tick=7, world_x=3211, world_y=3311, animation=875, interacting_with="Goblin")
        game.npcs = [{"id": 3107, "name": "Goblin", "worldX": 3211, "worldY": 3311,
                      "hull": [[400, 370], [420, 370], [420, 390], [400, 390]]}]

        result = rec.record_click("left", screen_x=900, screen_y=500,
                                  canvas_x=410, canvas_y=380, game=game)

        assert isinstance(result, ClickRecord)
        assert result.button == "left"
        assert "Goblin" in result.summary
        assert rec.click_count == 1

        records = _read_lines(path)
        click_records = [r for r in records if r["type"] == "click"]
        assert len(click_records) == 1
        click = click_records[0]
        assert click["button"] == "left"
        assert click["screenX"] == 900 and click["screenY"] == 500
        assert click["canvasX"] == 410 and click["canvasY"] == 380
        assert click["tick"] == 7
        assert click["playerWorldX"] == 3211 and click["playerWorldY"] == 3311
        assert click["playerAnimation"] == 875
        assert click["interactingWith"] == "Goblin"
        assert click["resolved"]["kind"] == "npc"
        assert click["resolved"]["name"] == "Goblin"

    def test_returns_none_and_does_not_write_when_not_recording(self, tmp_path):
        rec = SessionRecorder()
        game = _game()

        result = rec.record_click("right", 0, 0, 0, 0, game)

        assert result is None
        assert rec.click_count == 0
        assert list(tmp_path.iterdir()) == []


class TestSessionRoundTrip:
    def test_full_session_reads_back_in_chronological_order(self):
        rec = SessionRecorder()
        path = rec.start(player_name="Zezima")
        rec.record_tick({"tick": 1})
        rec.record_click("left", 100, 100, 50, 50, _game(tick=1))
        rec.record_tick({"tick": 2})
        summary = rec.stop()

        records = _read_lines(path)

        assert [r["type"] for r in records] == [
            "session_start", "tick", "click", "tick", "session_end",
        ]
        assert summary["ticks"] == 2
        assert summary["clicks"] == 1
