"""
Unit tests for GameState inventory helpers.

Run with:
    python -m pytest scripts/gamebridge/tests/
"""
import pytest
from scripts.gamebridge.state.game_state import GameState


def _slot(slot: int, item_id: int, qty: int = 1) -> dict:
    return {"slot": slot, "itemId": item_id, "qty": qty}


def _empty(slot: int) -> dict:
    """Slot that was explicitly cleared by the server (itemId = -1)."""
    return _slot(slot, -1, 0)


def _never_used(slot: int) -> dict:
    """Slot that was never occupied — arrives as itemId = 0."""
    return _slot(slot, 0, 0)


def _full_empty_inventory() -> list:
    """28-slot inventory where all slots are explicitly empty (itemId = -1)."""
    return [_empty(i) for i in range(28)]


def _full_zero_inventory() -> list:
    """28-slot inventory where all slots are itemId = 0 (never occupied)."""
    return [_never_used(i) for i in range(28)]


def _inventory_with_item(item_id: int = 1440) -> list:
    """28-slot inventory: one ore in slot 0, rest itemId = 0."""
    return [_slot(0, item_id)] + [_never_used(i) for i in range(1, 28)]


def _full_inventory(item_id: int = 1440) -> list:
    """28 occupied slots."""
    return [_slot(i, item_id) for i in range(28)]


# ---------------------------------------------------------------------------
# inventory_free_slots
# ---------------------------------------------------------------------------

class TestInventoryFreeSlots:
    def test_no_data_returns_zero(self):
        g = GameState()
        assert g.inventory_free_slots() == 0

    def test_all_explicit_empty(self):
        g = GameState()
        g.inventory = _full_empty_inventory()
        assert g.inventory_free_slots() == 28

    def test_all_zero_sentinel(self):
        # Never-occupied slots arrive with itemId = 0; should count as free.
        g = GameState()
        g.inventory = _full_zero_inventory()
        assert g.inventory_free_slots() == 28

    def test_one_item_rest_zero(self):
        # The core bug: 1 ore, 27 never-used slots.
        g = GameState()
        g.inventory = _inventory_with_item()
        assert g.inventory_free_slots() == 27

    def test_one_item_rest_explicit_minus_one(self):
        # Same but server sent all 28 slots with -1 for empty ones.
        g = GameState()
        g.inventory = [_slot(0, 1440)] + [_empty(i) for i in range(1, 28)]
        assert g.inventory_free_slots() == 27

    def test_full_inventory(self):
        g = GameState()
        g.inventory = _full_inventory()
        assert g.inventory_free_slots() == 0

    def test_after_deposit_one_slot_cleared(self):
        # Deposit box: server sends only the cleared slot back as -1;
        # the remaining 27 slots have itemId = 0 (never changed).
        g = GameState()
        g.inventory = [_empty(0)] + [_never_used(i) for i in range(1, 28)]
        assert g.inventory_free_slots() == 28


# ---------------------------------------------------------------------------
# inventory_full / inventory_empty
# ---------------------------------------------------------------------------

class TestInventoryFullEmpty:
    def test_no_data_not_full(self):
        g = GameState()
        assert g.inventory_full() is False

    def test_no_data_not_empty(self):
        g = GameState()
        assert g.inventory_empty() is False

    def test_one_item_not_full(self):
        g = GameState()
        g.inventory = _inventory_with_item()
        assert g.inventory_full() is False

    def test_full_inventory_is_full(self):
        g = GameState()
        g.inventory = _full_inventory()
        assert g.inventory_full() is True

    def test_all_zeros_is_empty(self):
        g = GameState()
        g.inventory = _full_zero_inventory()
        assert g.inventory_empty() is True

    def test_all_explicit_empty_is_empty(self):
        g = GameState()
        g.inventory = _full_empty_inventory()
        assert g.inventory_empty() is True

    def test_one_item_not_empty(self):
        g = GameState()
        g.inventory = _inventory_with_item()
        assert g.inventory_empty() is False


# ---------------------------------------------------------------------------
# inventory_used_slots
# ---------------------------------------------------------------------------

class TestInventoryUsedSlots:
    def test_no_data(self):
        g = GameState()
        assert g.inventory_used_slots() == 0

    def test_one_item(self):
        g = GameState()
        g.inventory = _inventory_with_item()
        assert g.inventory_used_slots() == 1

    def test_full(self):
        g = GameState()
        g.inventory = _full_inventory()
        assert g.inventory_used_slots() == 28

    def test_after_deposit(self):
        # After depositing the only item: server sends 1 cleared slot + 27 zeros.
        g = GameState()
        g.inventory = [_empty(0)] + [_never_used(i) for i in range(1, 28)]
        assert g.inventory_used_slots() == 0


# ---------------------------------------------------------------------------
# update() — container event integration
# ---------------------------------------------------------------------------

class TestContainerEventIntegration:
    def _make_container_msg(self, container_id: int, slots: list) -> dict:
        return {
            "tick": 1,
            "events": [{"type": "container", "containerId": container_id, "items": slots}],
        }

    def test_inventory_update_sets_inventory(self):
        g = GameState()
        slots = [_slot(0, 1440)] + [_never_used(i) for i in range(1, 28)]
        g.update(self._make_container_msg(93, slots))
        assert g.inventory_free_slots() == 27
        assert g.inventory_full() is False

    def test_equipment_update_sets_equipment(self):
        g = GameState()
        slots = [_slot(0, 4151)]  # a weapon
        g.update(self._make_container_msg(94, slots))  # 94 = Equipment (worn items)
        assert g.equipment == slots

    def test_full_inventory_triggers_full(self):
        g = GameState()
        g.update(self._make_container_msg(93, _full_inventory()))
        assert g.inventory_full() is True
        assert g.inventory_free_slots() == 0

    def test_empty_after_deposit(self):
        g = GameState()
        # First: pick up one item
        g.update(self._make_container_msg(93, _inventory_with_item()))
        assert g.inventory_full() is False
        # Then: deposit clears it (server sends only the cleared slot + zeros)
        after_deposit = [_empty(0)] + [_never_used(i) for i in range(1, 28)]
        g.update(self._make_container_msg(93, after_deposit))
        assert g.inventory_empty() is True
        assert g.inventory_used_slots() == 0


# ---------------------------------------------------------------------------
# Helpers shared by the extended tests below
# ---------------------------------------------------------------------------

def _player(x=3221, y=3218, plane=0, animation=-1, hp=99, prayer=50):
    return {
        "name": "Test", "worldX": x, "worldY": y, "plane": plane,
        "animation": animation, "hp": hp, "prayer": prayer,
    }


def _npc(npc_id=1, name="Goblin", x=3221, y=3218, on_screen=True):
    return {
        "id": npc_id, "name": name, "worldX": x, "worldY": y, "plane": 0,
        "animation": -1, "combatLevel": 2,
        "onScreen": on_screen,
        "canvasX": 400 if on_screen else None,
        "canvasY": 300 if on_screen else None,
        "hull": [[390, 290], [410, 290], [410, 310], [390, 310]] if on_screen else None,
    }


def _obj(obj_id=1, name="Oak tree", x=3225, y=3218, on_screen=True):
    return {
        "id": obj_id, "name": name, "worldX": x, "worldY": y, "plane": 0,
        "onScreen": on_screen,
        "canvasX": 500 if on_screen else None,
        "canvasY": 400 if on_screen else None,
        "hull": None,
    }


def _widget(group_id=149, child_id=0, item_id=995, qty=100):
    return {
        "groupId": group_id, "childId": child_id,
        "itemId": item_id, "quantity": qty,
        "bounds": {"x": 560, "y": 210, "width": 32, "height": 32},
        "text": "",
    }


def _base_msg(tick=1, **kwargs):
    msg = {"tick": tick, "events": []}
    msg.update(kwargs)
    return msg


# ---------------------------------------------------------------------------
# Top-level inventory / equipment snapshots
# ---------------------------------------------------------------------------

class TestTopLevelInventoryEquipment:
    def test_update_sets_inventory_from_top_level(self):
        g = GameState()
        slots = [_slot(0, 440)]
        g.update(_base_msg(inventory=slots))
        assert g.inventory == slots

    def test_update_sets_equipment_from_top_level(self):
        g = GameState()
        slots = [_slot(3, 1163)]
        g.update(_base_msg(equipment=slots))
        assert g.equipment == slots

    def test_top_level_inventory_overwrites_previous(self):
        g = GameState()
        g.update(_base_msg(inventory=[_slot(0, 440)]))
        g.update(_base_msg(inventory=[_slot(0, 995), _slot(1, 1440)]))
        assert len(g.inventory) == 2
        assert g.inventory[0]["itemId"] == 995

    def test_missing_inventory_key_preserves_existing(self):
        g = GameState()
        slots = [_slot(0, 440)]
        g.update(_base_msg(inventory=slots))
        g.update(_base_msg(tick=2))  # no inventory key
        assert g.inventory == slots

    def test_container_event_cid93_updates_inventory(self):
        g = GameState()
        slots = [_slot(0, 440)]
        msg = {"tick": 1, "events": [{"type": "container", "containerId": 93, "items": slots}]}
        g.update(msg)
        assert g.inventory == slots

    def test_container_event_cid94_updates_equipment(self):
        g = GameState()
        slots = [_slot(3, 1163)]
        msg = {"tick": 1, "events": [{"type": "container", "containerId": 94, "items": slots}]}
        g.update(msg)
        assert g.equipment == slots

    def test_container_event_cid95_bank_not_stored(self):
        g = GameState()
        bank_slots = [_slot(0, 995, qty=10000)]
        msg = {"tick": 1, "events": [{"type": "container", "containerId": 95, "items": bank_slots}]}
        g.update(msg)
        # Bank events are not stored on GameState
        assert g.inventory == []
        assert g.equipment == []


# ---------------------------------------------------------------------------
# XP events
# ---------------------------------------------------------------------------

class TestXpEvents:
    def _xp_event(self, skill, xp, level=70, boosted=70):
        return {"type": "xp", "skill": skill, "xp": xp, "level": level, "boostedLevel": boosted}

    def test_xp_event_updates_xp(self):
        g = GameState()
        g.update({"tick": 1, "events": [self._xp_event("WOODCUTTING", 1204050)]})
        assert g.xp["WOODCUTTING"] == 1204050

    def test_xp_event_updates_level(self):
        g = GameState()
        g.update({"tick": 1, "events": [self._xp_event("MINING", 500000, level=72)]})
        assert g.levels["MINING"] == 72

    def test_xp_event_updates_boosted_level(self):
        g = GameState()
        g.update({"tick": 1, "events": [self._xp_event("ATTACK", 100, boosted=80)]})
        assert g.boosted_levels["ATTACK"] == 80

    def test_multiple_skills_tracked_independently(self):
        g = GameState()
        g.update({"tick": 1, "events": [
            self._xp_event("WOODCUTTING", 1000),
            self._xp_event("MINING", 2000),
        ]})
        assert g.xp["WOODCUTTING"] == 1000
        assert g.xp["MINING"] == 2000

    def test_tick_without_xp_does_not_clear(self):
        g = GameState()
        g.update({"tick": 1, "events": [self._xp_event("FISHING", 9999)]})
        g.update({"tick": 2, "events": []})
        assert g.xp["FISHING"] == 9999


# ---------------------------------------------------------------------------
# Varbit events
# ---------------------------------------------------------------------------

class TestVarbitEvents:
    def _varbit_event(self, varp_id, varbit_id, value):
        return {"type": "varbit", "varpId": varp_id, "varbitId": varbit_id, "value": value}

    def test_varbit_event_stored(self):
        g = GameState()
        g.update({"tick": 1, "events": [self._varbit_event(2, 9178, 3)]})
        assert g.get_varbit(2, 9178) == 3

    def test_varplayer_event_stored(self):
        g = GameState()
        g.update({"tick": 1, "events": [self._varbit_event(1, -1, 7)]})
        assert g.get_varbit(1, -1) == 7

    def test_get_varbit_returns_none_for_unknown(self):
        g = GameState()
        assert g.get_varbit(999, 999) is None

    def test_varbit_overwritten_next_tick(self):
        g = GameState()
        g.update({"tick": 1, "events": [self._varbit_event(2, 9178, 1)]})
        g.update({"tick": 2, "events": [self._varbit_event(2, 9178, 5)]})
        assert g.get_varbit(2, 9178) == 5

    def test_multiple_varbits_independent(self):
        g = GameState()
        g.update({"tick": 1, "events": [
            self._varbit_event(1, 10, 42),
            self._varbit_event(2, 20, 99),
        ]})
        assert g.get_varbit(1, 10) == 42
        assert g.get_varbit(2, 20) == 99


# ---------------------------------------------------------------------------
# Chat events
# ---------------------------------------------------------------------------

class TestChatEvents:
    def _chat(self, message, msg_type="GAMEMESSAGE", name=""):
        return {"type": "chat", "msgType": msg_type, "name": name, "message": message}

    def test_chat_event_appended(self):
        g = GameState()
        g.update({"tick": 1, "events": [self._chat("You chop some logs.")]})
        assert len(g.chat_log) == 1
        assert g.chat_log[0]["message"] == "You chop some logs."

    def test_chat_log_capped_at_200(self):
        g = GameState()
        events = [self._chat(f"msg {i}") for i in range(250)]
        g.update({"tick": 1, "events": events})
        assert len(g.chat_log) == 200
        assert g.chat_log[-1]["message"] == "msg 249"

    def test_last_chat_matching_found(self):
        g = GameState()
        g.update({"tick": 1, "events": [
            self._chat("You swing your pick."),
            self._chat("You mine some iron ore."),
        ]})
        result = g.last_chat_matching("iron ore")
        assert result is not None
        assert "iron ore" in result["message"].lower()

    def test_last_chat_matching_case_insensitive(self):
        g = GameState()
        g.update({"tick": 1, "events": [self._chat("You chop some LOGS.")]})
        assert g.last_chat_matching("logs") is not None

    def test_last_chat_matching_not_found(self):
        g = GameState()
        g.update({"tick": 1, "events": [self._chat("You mine some iron ore.")]})
        assert g.last_chat_matching("fishing") is None

    def test_last_chat_matching_returns_most_recent(self):
        g = GameState()
        g.update({"tick": 1, "events": [
            self._chat("Iron ore 1."),
            self._chat("Iron ore 2."),
        ]})
        result = g.last_chat_matching("iron ore")
        assert result["message"] == "Iron ore 2."


# ---------------------------------------------------------------------------
# Interacting events
# ---------------------------------------------------------------------------

class TestInteractingEvents:
    def test_interacting_sets_target(self):
        g = GameState()
        g.update({"tick": 1, "events": [{"type": "interacting", "target": "Goblin"}]})
        assert g.interacting_with == "Goblin"

    def test_interacting_null_clears_target(self):
        g = GameState()
        g.update({"tick": 1, "events": [{"type": "interacting", "target": "Goblin"}]})
        g.update({"tick": 2, "events": [{"type": "interacting", "target": None}]})
        assert g.interacting_with is None

    def test_interacting_not_cleared_without_event(self):
        g = GameState()
        g.update({"tick": 1, "events": [{"type": "interacting", "target": "Cow"}]})
        g.update({"tick": 2, "events": []})
        assert g.interacting_with == "Cow"


# ---------------------------------------------------------------------------
# Player queries
# ---------------------------------------------------------------------------

class TestPlayerQueries:
    def test_player_pos(self):
        g = GameState()
        g.update(_base_msg(player=_player(x=3221, y=3218)))
        assert g.player_pos == (3221, 3218)

    def test_plane(self):
        g = GameState()
        g.update(_base_msg(player=_player(plane=2)))
        assert g.plane == 2

    def test_player_hp(self):
        g = GameState()
        g.update(_base_msg(player=_player(hp=85)))
        assert g.player_hp() == 85

    def test_player_prayer(self):
        g = GameState()
        g.update(_base_msg(player=_player(prayer=43)))
        assert g.player_prayer() == 43

    def test_player_animating_true(self):
        g = GameState()
        g.update(_base_msg(player=_player(animation=808)))
        assert g.player_animating() is True

    def test_player_animating_false(self):
        g = GameState()
        g.update(_base_msg(player=_player(animation=-1)))
        assert g.player_animating() is False

    def test_player_pos_defaults_before_login(self):
        g = GameState()
        assert g.player_pos == (0, 0)


# ---------------------------------------------------------------------------
# Animation / movement tracking
# ---------------------------------------------------------------------------

class TestAnimationTracking:
    def _tick(self, g, animation=-1, x=3221, y=3218):
        g.update(_base_msg(player=_player(animation=animation, x=x, y=y)))

    def test_animation_started(self):
        g = GameState()
        self._tick(g, animation=-1)   # tick 1: idle
        self._tick(g, animation=808)  # tick 2: starts animating
        assert g.animation_started() is True

    def test_animation_started_false_when_already_animating(self):
        g = GameState()
        self._tick(g, animation=808)
        self._tick(g, animation=808)
        assert g.animation_started() is False

    def test_animation_ended(self):
        g = GameState()
        self._tick(g, animation=808)
        self._tick(g, animation=-1)
        assert g.animation_ended() is True

    def test_animation_ended_false_when_already_idle(self):
        g = GameState()
        self._tick(g, animation=-1)
        self._tick(g, animation=-1)
        assert g.animation_ended() is False

    def test_player_moving(self):
        g = GameState()
        self._tick(g, x=3221, y=3218)
        self._tick(g, x=3222, y=3218)
        assert g.player_moving() is True

    def test_player_not_moving(self):
        g = GameState()
        self._tick(g, x=3221, y=3218)
        self._tick(g, x=3221, y=3218)
        assert g.player_moving() is False

    def test_player_idle(self):
        g = GameState()
        self._tick(g, animation=-1, x=3221, y=3218)
        self._tick(g, animation=-1, x=3221, y=3218)
        assert g.player_idle() is True

    def test_player_not_idle_when_animating(self):
        g = GameState()
        self._tick(g, animation=808, x=3221, y=3218)
        self._tick(g, animation=808, x=3221, y=3218)
        assert g.player_idle() is False

    def test_player_not_idle_when_moving(self):
        g = GameState()
        self._tick(g, animation=-1, x=3221, y=3218)
        self._tick(g, animation=-1, x=3222, y=3218)
        assert g.player_idle() is False


# ---------------------------------------------------------------------------
# NPC queries
# ---------------------------------------------------------------------------

class TestNpcQueries:
    def test_npcs_named_exact(self):
        g = GameState()
        g.update(_base_msg(npcs=[_npc(name="Goblin"), _npc(name="Cow")]))
        assert len(g.npcs_named("Goblin")) == 1

    def test_npcs_named_case_insensitive(self):
        g = GameState()
        g.update(_base_msg(npcs=[_npc(name="Goblin")]))
        assert len(g.npcs_named("goblin")) == 1
        assert len(g.npcs_named("GOBLIN")) == 1

    def test_npcs_on_screen(self):
        g = GameState()
        g.update(_base_msg(npcs=[
            _npc(name="Goblin", on_screen=True),
            _npc(name="Cow", on_screen=False),
        ]))
        on_screen = g.npcs_on_screen()
        assert len(on_screen) == 1
        assert on_screen[0]["name"] == "Goblin"

    def test_nearest_npc(self):
        g = GameState()
        g.update(_base_msg(
            player=_player(x=3221, y=3218),
            npcs=[
                _npc(name="Goblin", x=3223, y=3218),  # 2 tiles away
                _npc(name="Goblin", x=3230, y=3218),  # 9 tiles away
            ],
        ))
        nearest = g.nearest_npc("Goblin")
        assert nearest["worldX"] == 3223

    def test_nearest_npc_none_when_not_found(self):
        g = GameState()
        g.update(_base_msg(npcs=[_npc(name="Cow")]))
        assert g.nearest_npc("Goblin") is None


# ---------------------------------------------------------------------------
# Object queries
# ---------------------------------------------------------------------------

class TestObjectQueries:
    def test_objects_named(self):
        g = GameState()
        g.update(_base_msg(objects=[_obj(name="Iron rocks"), _obj(name="Oak tree")]))
        assert len(g.objects_named("Iron rocks")) == 1

    def test_nearest_object(self):
        g = GameState()
        g.update(_base_msg(
            player=_player(x=3221, y=3218),
            objects=[
                _obj(name="Iron rocks", x=3222, y=3218),  # 1 tile
                _obj(name="Iron rocks", x=3230, y=3218),  # 9 tiles
            ],
        ))
        nearest = g.nearest_object("Iron rocks")
        assert nearest["worldX"] == 3222

    def test_nearest_object_none_when_not_found(self):
        g = GameState()
        assert g.nearest_object("Iron rocks") is None

    def test_player_near_within_range(self):
        g = GameState()
        g.update(_base_msg(player=_player(x=3221, y=3218)))
        entity = _obj(x=3222, y=3218)  # 1 tile
        assert g.player_near(entity, tiles=2) is True

    def test_player_near_outside_range(self):
        g = GameState()
        g.update(_base_msg(player=_player(x=3221, y=3218)))
        entity = _obj(x=3230, y=3218)  # 9 tiles
        assert g.player_near(entity, tiles=2) is False

    def test_distance_to(self):
        g = GameState()
        g.update(_base_msg(player=_player(x=3221, y=3218)))
        entity = _obj(x=3225, y=3220)  # dx=4, dy=2 → manhattan = 6
        assert g.distance_to(entity) == 6


# ---------------------------------------------------------------------------
# Widget queries
# ---------------------------------------------------------------------------

class TestWidgetQueries:
    def test_find_widget_found(self):
        g = GameState()
        w = _widget(group_id=149, child_id=5, item_id=995)
        g.update(_base_msg(widgets=[w]))
        result = g.find_widget(149, 5)
        assert result is not None
        assert result["itemId"] == 995

    def test_find_widget_not_found(self):
        g = GameState()
        g.update(_base_msg(widgets=[_widget(group_id=149, child_id=0)]))
        assert g.find_widget(149, 99) is None

    def test_find_widget_matches_group_and_child(self):
        g = GameState()
        g.update(_base_msg(widgets=[
            _widget(group_id=149, child_id=0, item_id=440),
            _widget(group_id=149, child_id=1, item_id=995),
        ]))
        assert g.find_widget(149, 0)["itemId"] == 440
        assert g.find_widget(149, 1)["itemId"] == 995

    def test_widgets_cleared_on_update(self):
        g = GameState()
        g.update(_base_msg(widgets=[_widget(group_id=149, child_id=0)]))
        g.update(_base_msg(widgets=[]))
        assert g.find_widget(149, 0) is None


# ---------------------------------------------------------------------------
# Camera queries
# ---------------------------------------------------------------------------

class TestCameraQueries:
    def test_camera_yaw_to_east(self):
        g = GameState()
        g.update(_base_msg(player=_player(x=3200, y=3200)))
        # Target is directly east (+x)
        yaw = g.camera_yaw_to({"worldX": 3205, "worldY": 3200})
        # East is approximately yaw=512 in RS coordinates
        assert 450 <= yaw <= 570

    def test_camera_yaw_to_north(self):
        g = GameState()
        g.update(_base_msg(player=_player(x=3200, y=3200)))
        # Target is directly north (+y)
        yaw = g.camera_yaw_to({"worldX": 3200, "worldY": 3205})
        # North is yaw=0 (or 2048 wrapped)
        assert yaw < 50 or yaw > 2000


# ---------------------------------------------------------------------------
# inventory_count / inventory_has_item
# ---------------------------------------------------------------------------

class TestInventoryItemHelpers:
    def test_inventory_count_single_item(self):
        g = GameState()
        g.inventory = [_slot(0, 995, qty=500)] + [_never_used(i) for i in range(1, 28)]
        assert g.inventory_count(995) == 500

    def test_inventory_count_stacked_across_slots(self):
        g = GameState()
        g.inventory = [_slot(0, 440, qty=2), _slot(1, 440, qty=3)] + [
            _never_used(i) for i in range(2, 28)
        ]
        assert g.inventory_count(440) == 5

    def test_inventory_count_zero_when_absent(self):
        g = GameState()
        g.inventory = _full_inventory(item_id=440)
        assert g.inventory_count(995) == 0

    def test_inventory_has_item_true(self):
        g = GameState()
        g.inventory = [_slot(0, 1440)] + [_never_used(i) for i in range(1, 28)]
        assert g.inventory_has_item(1440) is True

    def test_inventory_has_item_false(self):
        g = GameState()
        g.inventory = _full_empty_inventory()
        assert g.inventory_has_item(1440) is False
