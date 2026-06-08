"""Tests for scripts.gamebridge.recording.resolver.resolve_click.

Each test plants exactly the live-game-state geometry resolve_click hit-tests
against (menu entries, interface bounds, entity hulls) and asserts both the
matched "kind" and that higher-priority matches win when several overlap —
mirroring how a player's click would actually be interpreted in-game (an open
context menu always wins over the entity/tile beneath it, etc.).
"""
from __future__ import annotations

from scripts.gamebridge.recording.resolver import resolve_click
from scripts.gamebridge.state.game_state import GameState


def _menu_entry(option, target="", x=480, y=379, w=140, h=15, **kw):
    return {"option": option, "target": target,
            "identifier": kw.get("identifier", 0), "type": kw.get("type", 0),
            "bounds": {"x": x, "y": y, "width": w, "height": h}}


def _open_menu(*entries):
    return {"open": True, "x": 480, "y": 360, "width": 140, "height": 64,
            "entries": list(entries)}


def _iface_widget(group_id, child_id, x, y, w, h, **kw):
    return {"groupId": group_id, "childId": child_id,
            "bounds": {"x": x, "y": y, "width": w, "height": h},
            "itemId": kw.get("itemId", -1), "quantity": kw.get("quantity", 0),
            "text": kw.get("text", "")}


def _entity(name, entity_id, world_x, world_y, hull):
    return {"id": entity_id, "name": name, "worldX": world_x, "worldY": world_y, "hull": hull}


_SQUARE_HULL = [[400, 370], [420, 370], [420, 390], [400, 390]]


class TestMenuEntryResolution:
    def test_click_inside_entry_bounds_resolves_to_menu_entry(self):
        g = GameState()
        g.menu = _open_menu(_menu_entry("Attack", "Goblin (level-2)", identifier=21, type=9))

        result = resolve_click(490, 385, g)

        assert result["kind"] == "menuEntry"
        assert result["option"] == "Attack"
        assert result["target"] == "Goblin (level-2)"
        assert result["identifier"] == 21
        assert result["menuActionType"] == 9
        assert result["index"] == 0
        assert "Attack Goblin (level-2)" in result["summary"]

    def test_picks_correct_row_by_index(self):
        g = GameState()
        g.menu = _open_menu(
            _menu_entry("Attack", "Goblin (level-2)", y=379),
            _menu_entry("Examine", "Goblin (level-2)", y=394),
            _menu_entry("Cancel", "", y=409),
        )

        result = resolve_click(490, 400, g)

        assert result["kind"] == "menuEntry"
        assert result["option"] == "Examine"
        assert result["index"] == 1

    def test_closed_menu_is_ignored(self):
        g = GameState()
        g.menu = {"open": False, "entries": [_menu_entry("Attack", "Goblin", y=379)]}

        result = resolve_click(490, 385, g)

        assert result["kind"] != "menuEntry"

    def test_click_outside_all_entry_rows_falls_through(self):
        g = GameState()
        g.menu = _open_menu(_menu_entry("Attack", "Goblin (level-2)", y=379))

        result = resolve_click(490, 1000, g)

        assert result["kind"] != "menuEntry"


class TestWidgetResolution:
    def test_click_inside_widget_bounds_resolves_to_widget(self):
        g = GameState()
        g.interfaces = [_iface_widget(149, 3, 560, 210, 32, 32, itemId=995, quantity=1000,
                                       text="Coins")]

        result = resolve_click(570, 220, g)

        assert result["kind"] == "widget"
        assert result["groupId"] == 149
        assert result["childId"] == 3
        assert result["itemId"] == 995
        assert result["quantity"] == 1000
        assert "Coins" in result["summary"]

    def test_widget_outside_bounds_does_not_match(self):
        g = GameState()
        g.interfaces = [_iface_widget(149, 3, 560, 210, 32, 32)]

        result = resolve_click(0, 0, g)

        assert result["kind"] != "widget"

    def test_menu_takes_priority_over_overlapping_widget(self):
        g = GameState()
        g.menu = _open_menu(_menu_entry("Attack", "Goblin", x=480, y=379, w=140, h=15))
        g.interfaces = [_iface_widget(149, 0, 470, 370, 200, 60)]  # overlaps the menu

        result = resolve_click(490, 385, g)

        assert result["kind"] == "menuEntry"


class TestEntityResolution:
    def test_click_inside_npc_hull_resolves_to_npc(self):
        g = GameState()
        g.npcs = [_entity("Goblin", 3107, 3211, 3311, _SQUARE_HULL)]

        result = resolve_click(410, 380, g)

        assert result["kind"] == "npc"
        assert result["id"] == 3107
        assert result["name"] == "Goblin"
        assert result["worldX"] == 3211
        assert result["worldY"] == 3311
        assert result["hull"] == _SQUARE_HULL
        assert "Goblin" in result["summary"]
        assert "3211" in result["summary"] and "3311" in result["summary"]

    def test_click_inside_object_hull_resolves_to_object(self):
        g = GameState()
        g.objects = [_entity("Iron rocks", 11364, 3185, 3304, _SQUARE_HULL)]

        result = resolve_click(410, 380, g)

        assert result["kind"] == "object"
        assert result["name"] == "Iron rocks"

    def test_click_inside_player_hull_resolves_to_player(self):
        g = GameState()
        g.players = [_entity("Zezima", -1, 3200, 3200, _SQUARE_HULL)]

        result = resolve_click(410, 380, g)

        assert result["kind"] == "player"
        assert result["name"] == "Zezima"

    def test_click_inside_ground_item_hull_resolves_to_ground_item(self):
        g = GameState()
        g.ground_items = [_entity("Iron ore", 440, 3185, 3304, _SQUARE_HULL)]

        result = resolve_click(410, 380, g)

        assert result["kind"] == "groundItem"
        assert result["name"] == "Iron ore"

    def test_npc_takes_priority_over_overlapping_object(self):
        g = GameState()
        g.npcs = [_entity("Goblin", 3107, 3211, 3311, _SQUARE_HULL)]
        g.objects = [_entity("Iron rocks", 11364, 3185, 3304, _SQUARE_HULL)]

        result = resolve_click(410, 380, g)

        assert result["kind"] == "npc"

    def test_entity_without_hull_is_skipped(self):
        g = GameState()
        g.npcs = [{"id": 1, "name": "Offscreen goblin", "worldX": 0, "worldY": 0, "hull": None}]

        result = resolve_click(410, 380, g)

        assert result["kind"] != "npc"


class TestViewportFallback:
    def test_click_matching_nothing_is_unresolved_viewport(self):
        g = GameState()

        result = resolve_click(640, 360, g)

        assert result["kind"] == "viewport"
        assert "640" in result["summary"]
        assert "360" in result["summary"]
