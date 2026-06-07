"""
Contract tests — GameBridge wire format.

contract.json is the single source of truth for the JSON schema sent by the
Java plugin.  These tests have two jobs:

  1. Schema integrity  — assert the contract file itself is well-formed and
     covers every top-level key, object category, and event type that the
     plugin can emit.  If a field is added/removed in Java, contract.json
     must be updated first; this suite will then fail until the Python
     consumer is updated to match.

  2. GameState integration  — feed the contract message through
     GameState.update() and assert every field is correctly parsed and every
     query helper returns the expected result.

Run with:
    python -m pytest scripts/gamebridge/tests/test_contract.py -v
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.gamebridge.state.game_state import GameState

_CONTRACT_PATH = Path(__file__).parent / "contract.json"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    return json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def state(contract: dict[str, Any]) -> GameState:
    g = GameState()
    g.update(contract)
    return g


# ---------------------------------------------------------------------------
# Schema integrity — the contract file must be internally consistent
# ---------------------------------------------------------------------------

class TestContractSchema:
    _TOP_LEVEL = {"tick", "player", "camera", "npcs", "objects", "widgets", "interfaces",
                  "inventory", "equipment", "events"}
    _PLAYER    = {"name", "worldX", "worldY", "plane", "animation", "hp", "prayer"}
    _CAMERA    = {"yaw", "pitch", "x", "y", "z"}
    _NPC       = {"id", "name", "worldX", "worldY", "plane", "animation", "combatLevel",
                  "onScreen", "canvasX", "canvasY", "hull", "minimapX", "minimapY"}
    _OBJECT    = {"id", "name", "category", "worldX", "worldY", "plane",
                  "onScreen", "canvasX", "canvasY", "hull", "minimapX", "minimapY"}
    _WIDGET    = {"groupId", "childId", "itemId", "quantity", "bounds", "text"}
    _INTERFACE = {"groupId", "childId", "itemId", "quantity", "bounds", "text"}
    _BOUNDS    = {"x", "y", "width", "height"}
    _SLOT      = {"slot", "itemId", "qty"}
    _EVENT_TYPES      = {"xp", "chat", "container", "animation", "varbit", "interacting"}
    _OBJECT_CATEGORIES = {"game", "wall", "ground", "decorative"}

    def test_contract_file_exists(self):
        assert _CONTRACT_PATH.exists(), f"contract.json not found at {_CONTRACT_PATH}"

    def test_top_level_fields(self, contract):
        assert self._TOP_LEVEL <= contract.keys()

    def test_player_fields(self, contract):
        assert self._PLAYER <= contract["player"].keys()

    def test_camera_fields(self, contract):
        assert self._CAMERA <= contract["camera"].keys()

    def test_npc_fields(self, contract):
        npcs = contract["npcs"]
        assert len(npcs) >= 1, "contract must include at least one NPC"
        for npc in npcs:
            missing = self._NPC - npc.keys()
            assert not missing, f"NPC missing fields: {missing}  entry={npc}"

    def test_object_fields(self, contract):
        objects = contract["objects"]
        assert len(objects) >= 1, "contract must include at least one object"
        for obj in objects:
            missing = self._OBJECT - obj.keys()
            assert not missing, f"Object missing fields: {missing}  entry={obj}"

    def test_widget_fields(self, contract):
        for w in contract["widgets"]:
            assert self._WIDGET <= w.keys()
            assert self._BOUNDS <= w["bounds"].keys()

    def test_interface_fields(self, contract):
        ifaces = contract["interfaces"]
        assert isinstance(ifaces, list), "interfaces must be a list"
        assert len(ifaces) >= 1, "contract must include at least one interface entry"
        for iface in ifaces:
            missing = self._INTERFACE - iface.keys()
            assert not missing, f"interface entry missing fields: {missing}  entry={iface}"
            assert self._BOUNDS <= iface["bounds"].keys()

    def test_interface_bounds_have_positive_area(self, contract):
        for iface in contract["interfaces"]:
            b = iface["bounds"]
            assert b["width"] > 0,  f"interface bounds width must be > 0: {iface}"
            assert b["height"] > 0, f"interface bounds height must be > 0: {iface}"

    def test_npc_minimap_fields_present(self, contract):
        for npc in contract["npcs"]:
            assert "minimapX" in npc, f"NPC missing minimapX: {npc['name']}"
            assert "minimapY" in npc, f"NPC missing minimapY: {npc['name']}"

    def test_object_minimap_fields_present(self, contract):
        for obj in contract["objects"]:
            assert "minimapX" in obj, f"object missing minimapX: {obj['name']}"
            assert "minimapY" in obj, f"object missing minimapY: {obj['name']}"

    def test_off_screen_entities_have_null_minimap(self, contract):
        for npc in contract["npcs"]:
            if not npc["onScreen"]:
                assert npc["minimapX"] is None, f"off-screen NPC should have null minimapX: {npc['name']}"
                assert npc["minimapY"] is None, f"off-screen NPC should have null minimapY: {npc['name']}"

    def test_inventory_slot_fields(self, contract):
        for slot in contract["inventory"]:
            assert self._SLOT <= slot.keys()

    def test_equipment_slot_fields(self, contract):
        for slot in contract["equipment"]:
            assert self._SLOT <= slot.keys()

    def test_all_event_types_covered(self, contract):
        found = {e["type"] for e in contract["events"]}
        missing = self._EVENT_TYPES - found
        assert not missing, f"contract events missing types: {missing}"

    def test_no_unknown_event_types(self, contract):
        found = {e["type"] for e in contract["events"]}
        unknown = found - self._EVENT_TYPES
        assert not unknown, f"contract contains undocumented event types: {unknown}"

    def test_all_object_categories_covered(self, contract):
        found = {o["category"] for o in contract["objects"]}
        missing = self._OBJECT_CATEGORIES - found
        assert not missing, f"contract missing categories: {missing}"

    def test_on_screen_entities_have_hull_and_canvas(self, contract):
        for npc in contract["npcs"]:
            if npc["onScreen"]:
                assert npc["hull"] is not None, f"on-screen NPC has null hull: {npc['name']}"
                assert npc["canvasX"] is not None
                assert npc["canvasY"] is not None

    def test_off_screen_entities_have_null_hull(self, contract):
        for npc in contract["npcs"]:
            if not npc["onScreen"]:
                assert npc["hull"] is None, f"off-screen NPC has non-null hull: {npc['name']}"
                assert npc["canvasX"] is None
        for obj in contract["objects"]:
            if not obj["onScreen"]:
                assert obj["hull"] is None

    def test_hull_points_are_int_pairs(self, contract):
        for npc in contract["npcs"]:
            for pt in (npc["hull"] or []):
                assert len(pt) == 2
                assert all(isinstance(c, int) for c in pt)
        for obj in contract["objects"]:
            for pt in (obj["hull"] or []):
                assert len(pt) == 2
                assert all(isinstance(c, int) for c in pt)

    def test_tick_is_integer(self, contract):
        assert isinstance(contract["tick"], int)

    def test_world_coordinates_are_integers(self, contract):
        for field in ("worldX", "worldY", "plane"):
            assert isinstance(contract["player"][field], int)


# ---------------------------------------------------------------------------
# GameState integration — the contract message is correctly parsed
# ---------------------------------------------------------------------------

class TestContractGameStateIntegration:
    def test_tick_parsed(self, state, contract):
        assert state.tick == contract["tick"]

    def test_player_pos(self, state, contract):
        p = contract["player"]
        assert state.player_pos == (p["worldX"], p["worldY"])

    def test_player_hp(self, state, contract):
        assert state.player_hp() == contract["player"]["hp"]

    def test_player_prayer(self, state, contract):
        assert state.player_prayer() == contract["player"]["prayer"]

    def test_player_name(self, state, contract):
        assert state.player["name"] == contract["player"]["name"]

    def test_player_animation(self, state, contract):
        assert state.player["animation"] == contract["player"]["animation"]

    def test_camera_yaw(self, state, contract):
        assert state.camera["yaw"] == contract["camera"]["yaw"]

    def test_camera_pitch(self, state, contract):
        assert state.camera["pitch"] == contract["camera"]["pitch"]

    def test_npcs_count(self, state, contract):
        assert len(state.npcs) == len(contract["npcs"])

    def test_on_screen_npc_accessible(self, state):
        on_screen = state.npcs_on_screen()
        assert len(on_screen) >= 1
        npc = on_screen[0]
        assert npc["hull"] is not None
        assert npc["canvasX"] is not None

    def test_objects_count(self, state, contract):
        assert len(state.objects) == len(contract["objects"])

    def test_object_category_field_preserved(self, state):
        categories = {o["category"] for o in state.objects}
        assert categories == {"game", "wall", "ground", "decorative"}

    def test_widgets_count(self, state, contract):
        assert len(state.widgets) == len(contract["widgets"])

    def test_interfaces_count(self, state, contract):
        assert len(state.interfaces) == len(contract["interfaces"])

    def test_interface_is_occluded_with_known_widget(self, state, contract):
        """A widget from a real panel group (160) occludes its own centre point.

        contract["interfaces"][0] (groupId 161) is the toplevel viewport
        container — see state/interfaces.py — and is intentionally excluded
        from occlusion checks, so we assert against a registered panel group
        instead (and confirm the toplevel widget's centre is *not* reported
        as occluded, demonstrating the exclusion against real captured data).
        """
        from scripts.gamebridge.state import interfaces as iface_registry

        toplevel = contract["interfaces"][0]
        assert iface_registry.occludes(toplevel["groupId"]) is False
        tb = toplevel["bounds"]
        assert state.is_occluded(tb["x"] + tb["width"] / 2, tb["y"] + tb["height"] / 2) is False

        panel = contract["interfaces"][1]
        assert iface_registry.occludes(panel["groupId"]) is True
        b = panel["bounds"]
        cx = b["x"] + b["width"] / 2
        cy = b["y"] + b["height"] / 2
        assert state.is_occluded(cx, cy) is True

    def test_find_interface_widget_returns_match(self, state, contract):
        iface = contract["interfaces"][0]
        result = state.find_interface_widget(iface["groupId"], iface["childId"])
        assert result is not None
        assert result["groupId"] == iface["groupId"]

    def test_inventory_count(self, state, contract):
        assert len(state.inventory) == len(contract["inventory"])

    def test_equipment_count(self, state, contract):
        assert len(state.equipment) == len(contract["equipment"])

    # note: widgets use "quantity", item slots use "qty" — both preserved
    def test_widget_uses_quantity_key(self, state, contract):
        w0 = contract["widgets"][0]
        found = state.find_widget(w0["groupId"], w0["childId"])
        assert found is not None
        assert "quantity" in found
        assert found["quantity"] == w0["quantity"]

    def test_inventory_slot_uses_qty_key(self, state, contract):
        occupied = [s for s in state.inventory if s["itemId"] > 0]
        assert len(occupied) >= 1
        assert "qty" in occupied[0]


# ---------------------------------------------------------------------------
# Event parsing — every event type is handled correctly
# ---------------------------------------------------------------------------

class TestContractEvents:
    def _event(self, contract, event_type):
        return next(e for e in contract["events"] if e["type"] == event_type)

    def test_xp_event_updates_xp(self, state, contract):
        ev = self._event(contract, "xp")
        assert state.xp[ev["skill"]] == ev["xp"]

    def test_xp_event_updates_level(self, state, contract):
        ev = self._event(contract, "xp")
        assert state.levels[ev["skill"]] == ev["level"]

    def test_xp_event_updates_boosted_level(self, state, contract):
        ev = self._event(contract, "xp")
        assert state.boosted_levels[ev["skill"]] == ev["boostedLevel"]

    def test_chat_event_in_log(self, state, contract):
        ev = self._event(contract, "chat")
        matches = [m for m in state.chat_log if m.get("message") == ev["message"]]
        assert len(matches) == 1

    def test_chat_event_stamped_with_tick(self, state, contract):
        ev = self._event(contract, "chat")
        entry = next(m for m in state.chat_log if m.get("message") == ev["message"])
        assert entry["_tick"] == contract["tick"]

    def test_chat_event_preserves_original_fields(self, state, contract):
        ev = self._event(contract, "chat")
        entry = next(m for m in state.chat_log if m.get("message") == ev["message"])
        assert entry["msgType"] == ev["msgType"]
        assert entry["name"] == ev["name"]

    def test_varbit_event_stored(self, state, contract):
        ev = self._event(contract, "varbit")
        assert state.get_varbit(ev["varpId"], ev["varbitId"]) == ev["value"]

    def test_interacting_event_sets_target(self, state, contract):
        ev = self._event(contract, "interacting")
        assert state.interacting_with == ev["target"]

    def test_container_event_updates_inventory(self, state, contract):
        ev = self._event(contract, "container")
        if ev["containerId"] == 93:
            item_ids = {s["itemId"] for s in ev["items"]}
            state_ids = {s["itemId"] for s in state.inventory}
            assert item_ids <= state_ids


# ---------------------------------------------------------------------------
# Query helpers — all GameState methods work with contract data
# ---------------------------------------------------------------------------

class TestContractQueryHelpers:
    def test_nearest_npc(self, state, contract):
        name = contract["npcs"][0]["name"]
        assert state.nearest_npc(name) is not None

    def test_nearest_npc_on_screen(self, state, contract):
        on_screen = next(n for n in contract["npcs"] if n["onScreen"])
        result = state.nearest_npc_on_screen(on_screen["name"])
        assert result is not None
        assert result["onScreen"] is True

    def test_nearest_npc_on_screen_not_found_for_offscreen_only_name(self, state, contract):
        off_screen_names = {n["name"] for n in contract["npcs"] if not n["onScreen"]}
        on_screen_names  = {n["name"] for n in contract["npcs"] if n["onScreen"]}
        exclusive = off_screen_names - on_screen_names
        if exclusive:
            name = next(iter(exclusive))
            assert state.nearest_npc_on_screen(name) is None

    def test_nearest_object(self, state, contract):
        name = contract["objects"][0]["name"]
        assert state.nearest_object(name) is not None

    def test_nearest_object_on_screen(self, state, contract):
        on_screen_obj = next(o for o in contract["objects"] if o["onScreen"])
        result = state.nearest_object_on_screen(on_screen_obj["name"])
        assert result is not None
        assert result["onScreen"] is True

    def test_objects_on_screen_count(self, state, contract):
        expected = sum(1 for o in contract["objects"] if o["onScreen"])
        assert len(state.objects_on_screen()) == expected

    def test_npcs_on_screen_count(self, state, contract):
        expected = sum(1 for n in contract["npcs"] if n["onScreen"])
        assert len(state.npcs_on_screen()) == expected

    def test_distance_to(self, state, contract):
        npc = contract["npcs"][0]
        px, py = state.player_pos
        expected = abs(npc["worldX"] - px) + abs(npc["worldY"] - py)
        assert state.distance_to(npc) == expected

    def test_player_near_adjacent_npc(self, state, contract):
        # Player at (3221,3218), nearest NPC at (3225,3215) → manhattan = 7
        npc = next(n for n in contract["npcs"] if n["onScreen"])
        dist = state.distance_to(npc)
        assert state.player_near(npc, tiles=dist) is True
        assert state.player_near(npc, tiles=dist - 1) is False

    def test_find_widget(self, state, contract):
        w = contract["widgets"][0]
        found = state.find_widget(w["groupId"], w["childId"])
        assert found is not None
        assert found["itemId"] == w["itemId"]

    def test_inventory_count(self, state, contract):
        occupied = [s for s in contract["inventory"] if s["itemId"] > 0]
        if occupied:
            item_id = occupied[0]["itemId"]
            expected = sum(s["qty"] for s in contract["inventory"] if s["itemId"] == item_id)
            assert state.inventory_count(item_id) == expected

    def test_inventory_has_item(self, state, contract):
        occupied = [s for s in contract["inventory"] if s["itemId"] > 0]
        if occupied:
            assert state.inventory_has_item(occupied[0]["itemId"]) is True

    def test_inventory_not_full(self, state, contract):
        empty_slots = sum(1 for s in contract["inventory"] if s["itemId"] <= 0)
        if empty_slots > 0:
            assert state.inventory_full() is False

    def test_chat_since_tick(self, state, contract):
        results = state.chat_since_tick(contract["tick"])
        assert len(results) >= 1

    def test_last_chat_matching(self, state, contract):
        ev = next(e for e in contract["events"] if e["type"] == "chat")
        keyword = ev["message"].split()[0]
        assert state.last_chat_matching(keyword) is not None

    def test_get_varbit(self, state, contract):
        ev = next(e for e in contract["events"] if e["type"] == "varbit")
        assert state.get_varbit(ev["varpId"], ev["varbitId"]) == ev["value"]

    def test_player_animating_false_when_idle(self, state, contract):
        if contract["player"]["animation"] == -1:
            assert state.player_animating() is False

    def test_plane(self, state, contract):
        assert state.plane == contract["player"]["plane"]
