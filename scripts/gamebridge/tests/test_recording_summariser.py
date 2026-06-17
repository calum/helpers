"""
Tests for scripts.gamebridge.recording.summariser.

Coverage:
  _aggregate_inventory  — sums qty per itemId, filters empty slots
  _inventory_delta      — added / removed dicts
  _SummariserState      — first-tick initialisation (no events), subsequent deltas
  summarise()           — end-to-end: reads a .jsonl, writes .summary.jsonl
  SessionRecorder.stop  — auto-summarises on stop, summaryPath in return dict
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.gamebridge.recording.recorder as recorder_module
from scripts.gamebridge.recording.recorder import SessionRecorder
from scripts.gamebridge.recording.summariser import (
    _SummariserState,
    _aggregate_inventory,
    _inventory_delta,
    summarise,
)
from scripts.gamebridge.state.game_state import GameState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _read_summary(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _tick(tick_num: int, **msg_fields) -> dict:
    return {"type": "tick", "wallTime": 0.0, "msg": {"tick": tick_num, **msg_fields}}


def _container_event(items: list[dict]) -> dict:
    return {"type": "container", "containerId": 93, "items": items}


def _iface_widget(group_id: int) -> dict:
    return {"groupId": group_id, "childId": 0,
            "itemId": -1, "quantity": 0,
            "bounds": {"x": 0, "y": 0, "width": 100, "height": 50},
            "text": ""}


@pytest.fixture(autouse=True)
def _redirect_recordings_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder_module, "RECORDINGS_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# _aggregate_inventory
# ---------------------------------------------------------------------------

class TestAggregateInventory:
    def test_sums_qty_for_same_item_across_slots(self):
        items = [{"itemId": 438, "qty": 1}] * 14  # 14 non-stackable tin ores
        assert _aggregate_inventory(items) == {438: 14}

    def test_filters_empty_slots(self):
        items = [{"itemId": -1, "qty": 0}, {"itemId": 0, "qty": 0},
                 {"itemId": 438, "qty": 1}]
        assert _aggregate_inventory(items) == {438: 1}

    def test_stackable_item_single_slot(self):
        items = [{"itemId": 995, "qty": 1000}]
        assert _aggregate_inventory(items) == {995: 1000}

    def test_multiple_different_items(self):
        items = [{"itemId": 438, "qty": 1}, {"itemId": 436, "qty": 1},
                 {"itemId": -1, "qty": 0}]
        assert _aggregate_inventory(items) == {438: 1, 436: 1}

    def test_empty_list_returns_empty_dict(self):
        assert _aggregate_inventory([]) == {}


# ---------------------------------------------------------------------------
# _inventory_delta
# ---------------------------------------------------------------------------

class TestInventoryDelta:
    def test_nothing_changed(self):
        d = _inventory_delta({438: 14}, {438: 14})
        assert d == {"added": [], "removed": []}

    def test_item_added(self):
        d = _inventory_delta({}, {438: 14})
        assert d["added"] == [{"itemId": 438, "qty": 14}]
        assert d["removed"] == []

    def test_item_removed(self):
        d = _inventory_delta({2349: 14}, {})
        assert d["added"] == []
        assert d["removed"] == [{"itemId": 2349, "qty": 14}]

    def test_partial_quantity_change(self):
        d = _inventory_delta({438: 14}, {438: 7})
        assert d["removed"] == [{"itemId": 438, "qty": 7}]
        assert d["added"] == []

    def test_swap_items(self):
        d = _inventory_delta({2349: 14}, {438: 14, 436: 14})
        assert {"itemId": 2349, "qty": 14} in d["removed"]
        assert {"itemId": 436, "qty": 14} in d["added"]
        assert {"itemId": 438, "qty": 14} in d["added"]

    def test_results_sorted_by_item_id(self):
        d = _inventory_delta({}, {436: 1, 438: 1})
        assert [e["itemId"] for e in d["added"]] == [436, 438]


# ---------------------------------------------------------------------------
# _SummariserState — first tick absorbs initial state
# ---------------------------------------------------------------------------

class TestSummariserStateInit:
    def test_first_container_event_does_not_emit_delta(self):
        state = _SummariserState()
        tick = _tick(1, events=[_container_event([{"itemId": 438, "qty": 1}] * 14)])
        events = state.process_tick(tick)
        assert not any(e["type"] == "inventory_delta" for e in events)

    def test_first_tick_interfaces_do_not_emit_opened(self):
        state = _SummariserState()
        tick = _tick(1, interfaces=[_iface_widget(12)])  # bank open from start
        events = state.process_tick(tick)
        assert not any(e["type"] == "interface_opened" for e in events)

    def test_first_tick_animation_does_not_emit_changed(self):
        state = _SummariserState()
        tick = _tick(1, player={"animation": 899})
        events = state.process_tick(tick)
        assert not any(e["type"] == "animation_changed" for e in events)

    def test_tick_with_no_fields_emits_nothing(self):
        state = _SummariserState()
        assert state.process_tick(_tick(1)) == []
        assert state.process_tick(_tick(2)) == []


# ---------------------------------------------------------------------------
# _SummariserState — subsequent ticks emit deltas
# ---------------------------------------------------------------------------

class TestSummariserStateDeltas:
    def _state_after_init(self, inv=None, ifaces=None, anim=-1):
        """Return a state that has absorbed an initial tick."""
        state = _SummariserState()
        msg = {"tick": 1, "player": {"animation": anim}}
        if inv is not None:
            msg["events"] = [_container_event(inv)]
        if ifaces is not None:
            msg["interfaces"] = [_iface_widget(gid) for gid in ifaces]
        state.process_tick({"type": "tick", "msg": msg})
        return state

    # inventory
    def test_second_container_event_emits_delta(self):
        state = self._state_after_init(inv=[{"itemId": 2349, "qty": 1}] * 14)
        tick = _tick(2, events=[_container_event([{"itemId": 438, "qty": 1}] * 14)])
        events = state.process_tick(tick)
        inv_events = [e for e in events if e["type"] == "inventory_delta"]
        assert len(inv_events) == 1
        assert {"itemId": 2349, "qty": 14} in inv_events[0]["removed"]
        assert {"itemId": 438, "qty": 14} in inv_events[0]["added"]

    def test_no_delta_emitted_when_inventory_unchanged(self):
        state = self._state_after_init(inv=[{"itemId": 438, "qty": 1}] * 14)
        tick = _tick(2, events=[_container_event([{"itemId": 438, "qty": 1}] * 14)])
        events = state.process_tick(tick)
        assert not any(e["type"] == "inventory_delta" for e in events)

    def test_no_inventory_event_when_no_container_event(self):
        state = self._state_after_init(inv=[{"itemId": 438, "qty": 1}])
        events = state.process_tick(_tick(2))  # no events field
        assert not any(e["type"] == "inventory_delta" for e in events)

    # interfaces
    def test_interface_opened_when_new_registered_group_appears(self):
        state = self._state_after_init(ifaces=[149])  # inventory always on
        tick = _tick(2, interfaces=[_iface_widget(149), _iface_widget(12)])  # bank opens
        events = state.process_tick(tick)
        opened = [e for e in events if e["type"] == "interface_opened"]
        assert len(opened) == 1
        assert opened[0]["groupId"] == 12
        assert opened[0]["name"] == "bank"

    def test_interface_closed_when_registered_group_disappears(self):
        state = self._state_after_init(ifaces=[149, 12])  # bank was open
        tick = _tick(2, interfaces=[_iface_widget(149)])  # bank closes
        events = state.process_tick(tick)
        closed = [e for e in events if e["type"] == "interface_closed"]
        assert len(closed) == 1
        assert closed[0]["groupId"] == 12
        assert closed[0]["name"] == "bank"

    def test_unregistered_group_does_not_emit_events(self):
        state = self._state_after_init(ifaces=[])
        tick = _tick(2, interfaces=[{"groupId": 9999, "childId": 0,
                                     "bounds": {"x": 0, "y": 0, "width": 10, "height": 10},
                                     "itemId": -1, "quantity": 0, "text": ""}])
        events = state.process_tick(tick)
        assert not any(e["type"].startswith("interface_") for e in events)

    def test_interface_tick_number_is_correct(self):
        state = self._state_after_init(ifaces=[])
        tick = _tick(42, interfaces=[_iface_widget(12)])
        events = state.process_tick(tick)
        assert events[0]["tick"] == 42

    # animation
    def test_animation_changed_emitted_on_transition(self):
        state = self._state_after_init(anim=-1)
        tick = _tick(2, player={"animation": 899})
        events = state.process_tick(tick)
        anim_events = [e for e in events if e["type"] == "animation_changed"]
        assert len(anim_events) == 1
        assert anim_events[0] == {"type": "animation_changed", "tick": 2, "from": -1, "to": 899}

    def test_animation_not_emitted_when_unchanged(self):
        state = self._state_after_init(anim=899)
        tick = _tick(2, player={"animation": 899})
        events = state.process_tick(tick)
        assert not any(e["type"] == "animation_changed" for e in events)

    def test_animation_defaults_to_minus_one_when_missing(self):
        state = self._state_after_init(anim=-1)
        tick = _tick(2, player={})  # no animation field
        events = state.process_tick(tick)
        assert not any(e["type"] == "animation_changed" for e in events)


# ---------------------------------------------------------------------------
# summarise() — end-to-end
# ---------------------------------------------------------------------------

_SESSION_START = {"type": "session_start", "startedAt": 0.0, "playerName": "Zezima"}
_SESSION_END   = {"type": "session_end",   "endedAt": 1.0,  "ticks": 3, "clicks": 1}
_CLICK = {
    "type": "click", "wallTime": 0.5, "button": "left",
    "tick": 2, "screenX": 100, "screenY": 100,
    "canvasX": 90.0, "canvasY": 80.0,
    "playerWorldX": 2947, "playerWorldY": 3368,
    "playerAnimation": -1, "interactingWith": None,
    "resolved": {"kind": "object", "name": "Furnace", "id": 24009,
                 "worldX": 2976, "worldY": 3369,
                 "summary": 'object "Furnace" (id=24009) at world (2976, 3369)'},
}


def _make_recording(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "recording-20260617-164807.jsonl"
    _write_jsonl(path, records)
    return path


class TestSummariseEndToEnd:
    def test_summary_file_created_next_to_recording(self, tmp_path):
        rec_path = _make_recording(tmp_path, [_SESSION_START, _SESSION_END])
        summary_path = summarise(rec_path)
        assert summary_path == tmp_path / "recording-20260617-164807.summary.jsonl"
        assert summary_path.exists()

    def test_session_start_and_end_passed_through(self, tmp_path):
        rec_path = _make_recording(tmp_path, [_SESSION_START, _SESSION_END])
        records = _read_summary(summarise(rec_path))
        types = [r["type"] for r in records]
        assert "session_start" in types
        assert "session_end" in types

    def test_click_records_passed_through(self, tmp_path):
        rec_path = _make_recording(tmp_path, [_SESSION_START, _CLICK, _SESSION_END])
        records = _read_summary(summarise(rec_path))
        clicks = [r for r in records if r["type"] == "click"]
        assert len(clicks) == 1
        assert clicks[0]["resolved"]["name"] == "Furnace"

    def test_tick_records_not_in_summary(self, tmp_path):
        rec_path = _make_recording(tmp_path, [
            _SESSION_START,
            _tick(1), _tick(2), _tick(3),
            _SESSION_END,
        ])
        records = _read_summary(summarise(rec_path))
        assert not any(r["type"] == "tick" for r in records)

    def test_inventory_delta_emitted(self, tmp_path):
        ore_items = [{"itemId": 438, "qty": 1}] * 14
        bar_items  = [{"itemId": 2349, "qty": 1}] * 14
        rec_path = _make_recording(tmp_path, [
            _SESSION_START,
            _tick(1, events=[_container_event(bar_items)]),   # init: bars in inv
            _tick(2, events=[_container_event(ore_items)]),   # deposit bars, get ores
            _SESSION_END,
        ])
        records = _read_summary(summarise(rec_path))
        deltas = [r for r in records if r["type"] == "inventory_delta"]
        assert len(deltas) == 1
        assert {"itemId": 2349, "qty": 14} in deltas[0]["removed"]
        assert {"itemId": 438,  "qty": 14} in deltas[0]["added"]

    def test_interface_opened_emitted(self, tmp_path):
        rec_path = _make_recording(tmp_path, [
            _SESSION_START,
            _tick(1, interfaces=[_iface_widget(149)]),        # init: only inventory
            _tick(2, interfaces=[_iface_widget(149),
                                 _iface_widget(12)]),         # bank opens
            _SESSION_END,
        ])
        records = _read_summary(summarise(rec_path))
        opened = [r for r in records if r["type"] == "interface_opened"]
        assert any(r["groupId"] == 12 for r in opened)

    def test_interface_closed_emitted(self, tmp_path):
        rec_path = _make_recording(tmp_path, [
            _SESSION_START,
            _tick(1, interfaces=[_iface_widget(149), _iface_widget(12)]),  # bank open
            _tick(2, interfaces=[_iface_widget(149)]),                     # bank closes
            _SESSION_END,
        ])
        records = _read_summary(summarise(rec_path))
        closed = [r for r in records if r["type"] == "interface_closed"]
        assert any(r["groupId"] == 12 for r in closed)

    def test_animation_changed_emitted(self, tmp_path):
        rec_path = _make_recording(tmp_path, [
            _SESSION_START,
            _tick(1, player={"animation": -1}),    # init: idle
            _tick(2, player={"animation": 899}),   # smelting starts
            _SESSION_END,
        ])
        records = _read_summary(summarise(rec_path))
        anim = [r for r in records if r["type"] == "animation_changed"]
        assert len(anim) == 1
        assert anim[0]["from"] == -1 and anim[0]["to"] == 899

    def test_chronological_order_preserved(self, tmp_path):
        rec_path = _make_recording(tmp_path, [
            _SESSION_START,
            _tick(1, interfaces=[_iface_widget(149)]),
            _tick(2, interfaces=[_iface_widget(149), _iface_widget(12)]),
            _CLICK,
            _tick(3, interfaces=[_iface_widget(149)]),
            _SESSION_END,
        ])
        records = _read_summary(summarise(rec_path))
        types = [r["type"] for r in records]
        open_idx  = types.index("interface_opened")
        click_idx = types.index("click")
        close_idx = types.index("interface_closed")
        assert open_idx < click_idx < close_idx

    def test_malformed_line_is_skipped(self, tmp_path):
        path = tmp_path / "recording-bad.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(_SESSION_START) + "\n")
            f.write("not json {{{{\n")
            f.write(json.dumps(_SESSION_END) + "\n")
        records = _read_summary(summarise(path))
        assert [r["type"] for r in records] == ["session_start", "session_end"]

    def test_empty_recording_produces_empty_summary(self, tmp_path):
        path = tmp_path / "recording-empty.jsonl"
        path.write_text("", encoding="utf-8")
        records = _read_summary(summarise(path))
        assert records == []

    def test_rerunning_overwrites_previous_summary(self, tmp_path):
        rec_path = _make_recording(tmp_path, [_SESSION_START, _SESSION_END])
        summarise(rec_path)
        summarise(rec_path)  # second run must not raise or double-up lines
        records = _read_summary(rec_path.with_name(rec_path.stem + ".summary.jsonl"))
        assert [r["type"] for r in records] == ["session_start", "session_end"]


# ---------------------------------------------------------------------------
# SessionRecorder.stop() integration
# ---------------------------------------------------------------------------

def _game_state() -> GameState:
    g = GameState()
    g.tick = 1
    g.player = {"worldX": 3200, "worldY": 3200, "plane": 0, "animation": -1}
    return g


class TestRecorderAutoSummarise:
    def test_stop_creates_summary_file(self, tmp_path):
        rec = SessionRecorder()
        path = rec.start(player_name="Zezima")
        rec.record_tick({"tick": 1})
        rec.stop()
        summary_path = tmp_path / (path.stem + ".summary.jsonl")
        assert summary_path.exists()

    def test_stop_returns_summary_path(self, tmp_path):
        rec = SessionRecorder()
        path = rec.start()
        result = rec.stop()
        expected = tmp_path / (path.stem + ".summary.jsonl")
        assert result["summaryPath"] == expected

    def test_stop_summary_contains_session_bookends(self, tmp_path):
        rec = SessionRecorder()
        path = rec.start(player_name="Zezima")
        rec.record_tick({"tick": 1, "player": {"animation": -1}})
        rec.stop()
        summary_path = tmp_path / (path.stem + ".summary.jsonl")
        records = _read_summary(summary_path)
        types = [r["type"] for r in records]
        assert types[0] == "session_start"
        assert types[-1] == "session_end"

    def test_stop_summary_path_is_none_when_summariser_fails(self, tmp_path, monkeypatch):
        """A summariser crash must not propagate — raw recording stays intact."""
        import scripts.gamebridge.recording.recorder as mod
        monkeypatch.setattr(mod, "summarise", lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
        rec = SessionRecorder()
        rec.start()
        result = rec.stop()  # must not raise
        assert result["summaryPath"] is None

    def test_raw_recording_intact_after_stop(self, tmp_path):
        rec = SessionRecorder()
        path = rec.start()
        rec.record_tick({"tick": 1})
        rec.stop()
        lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        types = [l["type"] for l in lines]
        assert types == ["session_start", "tick", "session_end"]
