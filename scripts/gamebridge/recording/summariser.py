"""
recording/summariser.py — distil a raw .jsonl recording into a compact summary.

Reads a recording file written by SessionRecorder and produces a
``<stem>.summary.jsonl`` file alongside it.  Only events relevant to writing a
routine are emitted:

    session_start / session_end  — pass-through verbatim
    click                        — pass-through verbatim (already well-annotated)
    inventory_delta              — items added / removed when the inventory changes
    interface_opened             — a registered UI group appeared (bank, skillmulti, …)
    interface_closed             — a registered UI group disappeared
    animation_changed            — player animation id transition (e.g. -1 → 899)

Raw ``tick`` records are not emitted — they are the source material, not the output.

Example output for a smelting session (≈25 lines instead of 167 full ticks):

    {"type":"session_start","playerName":"Zezima",...}
    {"type":"click","tick":1147,...,"resolved":{"kind":"object","name":"Bank booth",...}}
    {"type":"interface_opened","tick":1148,"groupId":12,"name":"bank"}
    {"type":"inventory_delta","tick":1150,"added":[],"removed":[{"itemId":2349,"qty":14}]}
    {"type":"inventory_delta","tick":1151,"added":[{"itemId":438,"qty":14}],"removed":[]}
    {"type":"inventory_delta","tick":1153,"added":[{"itemId":436,"qty":14}],"removed":[]}
    {"type":"interface_closed","tick":1154,"groupId":12,"name":"bank"}
    {"type":"click","tick":1175,...,"resolved":{"kind":"object","name":"Furnace",...}}
    {"type":"interface_opened","tick":1178,"groupId":270,"name":"skillmulti"}
    {"type":"animation_changed","tick":1181,"from":-1,"to":899}
    ...
    {"type":"animation_changed","tick":1260,"from":899,"to":-1}
    {"type":"inventory_delta","tick":1261,"added":[{"itemId":2349,"qty":14}],...}
    {"type":"session_end",...}
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from ..state import interfaces as iface_registry

log = logging.getLogger(__name__)

_INVENTORY_CONTAINER_ID = 93


def summarise(recording_path: Path) -> Path:
    """Read *recording_path*, derive structured events, write a ``.summary.jsonl``
    file in the same directory, and return that path.

    Safe to re-run: overwrites any existing summary.  A summariser failure
    (malformed recording, IO error) propagates as an exception — the caller
    (``SessionRecorder.stop``) is responsible for catching it so a bad summary
    never corrupts the raw recording.
    """
    summary_path = recording_path.with_name(recording_path.stem + ".summary.jsonl")

    state = _SummariserState()
    out_lines: list[str] = []

    with open(recording_path, encoding="utf-8") as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                log.warning("summariser: skipping malformed line: %.80s", raw_line)
                continue

            t = record.get("type")
            if t in ("session_start", "session_end", "click"):
                out_lines.append(raw_line)
            elif t == "tick":
                for event in state.process_tick(record):
                    out_lines.append(json.dumps(event, separators=(",", ":")))

    with open(summary_path, "w", encoding="utf-8") as f:
        for line in out_lines:
            f.write(line + "\n")

    log.info("Summary written: %s (%d events)", summary_path, len(out_lines))
    return summary_path


class _SummariserState:
    """Incremental state machine that processes tick records in order and returns
    structured events whenever something interesting changes.

    Each field starts uninitialised (``None``).  The first tick that provides
    data for a field sets the baseline without emitting an event, so always-on
    state (inventory on entry, interfaces loaded at session start, initial
    animation) does not flood the summary with spurious "opened"/"changed" lines.
    """

    def __init__(self) -> None:
        self._inventory: Optional[dict[int, int]] = None  # itemId → total qty
        self._iface_groups: Optional[set[int]] = None     # registered groupIds visible
        self._animation: Optional[int] = None             # player animation id

    def process_tick(self, record: dict) -> list[dict]:
        """Return the (possibly empty) list of summary events derived from one
        ``{"type": "tick", "msg": {...}}`` record."""
        msg = record.get("msg", {})
        tick = msg.get("tick", 0)
        events: list[dict] = []

        # ── Inventory delta (from container events) ───────────────────────
        for ev in msg.get("events", []):
            if (ev.get("type") == "container"
                    and ev.get("containerId") == _INVENTORY_CONTAINER_ID):
                new_inv = _aggregate_inventory(ev.get("items", []))
                if self._inventory is None:
                    self._inventory = new_inv          # absorb initial state
                else:
                    delta = _inventory_delta(self._inventory, new_inv)
                    if delta["added"] or delta["removed"]:
                        events.append({"type": "inventory_delta", "tick": tick, **delta})
                    self._inventory = new_inv

        # ── Interface open / close ────────────────────────────────────────
        current: set[int] = {
            w["groupId"]
            for w in msg.get("interfaces", [])
            if iface_registry.name_for(w.get("groupId", -1)) is not None
        }
        if self._iface_groups is None:
            self._iface_groups = current               # absorb initial state
        else:
            for gid in sorted(current - self._iface_groups):
                events.append({
                    "type": "interface_opened", "tick": tick,
                    "groupId": gid, "name": iface_registry.name_for(gid),
                })
            for gid in sorted(self._iface_groups - current):
                events.append({
                    "type": "interface_closed", "tick": tick,
                    "groupId": gid, "name": iface_registry.name_for(gid),
                })
            self._iface_groups = current

        # ── Animation change ──────────────────────────────────────────────
        anim = msg.get("player", {}).get("animation", -1)
        if self._animation is None:
            self._animation = anim                     # absorb initial state
        elif anim != self._animation:
            events.append({
                "type": "animation_changed", "tick": tick,
                "from": self._animation, "to": anim,
            })
            self._animation = anim

        return events


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _aggregate_inventory(items: list[dict]) -> dict[int, int]:
    """Sum quantities per itemId, ignoring empty slots (itemId ≤ 0)."""
    totals: dict[int, int] = {}
    for item in items:
        iid = item.get("itemId", -1)
        if iid > 0:
            totals[iid] = totals.get(iid, 0) + item.get("qty", 0)
    return totals


def _inventory_delta(
    prev: dict[int, int],
    new: dict[int, int],
) -> dict:
    """Return ``{"added": [...], "removed": [...]}`` describing what changed."""
    added: list[dict] = []
    removed: list[dict] = []
    for iid in sorted(set(prev) | set(new)):
        old_qty = prev.get(iid, 0)
        new_qty = new.get(iid, 0)
        if new_qty > old_qty:
            added.append({"itemId": iid, "qty": new_qty - old_qty})
        elif new_qty < old_qty:
            removed.append({"itemId": iid, "qty": old_qty - new_qty})
    return {"added": added, "removed": removed}
