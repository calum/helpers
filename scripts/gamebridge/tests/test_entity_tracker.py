"""
Unit tests for EntityTracker (cross-tick identity & velocity tracking).

Run with:
    python -m pytest scripts/gamebridge/tests/
"""
from scripts.gamebridge.state.entity_tracker import (
    EntityTracker,
    npc_key,
    object_key,
    player_key,
)
from scripts.gamebridge.state.game_state import GameState


def _npc(index=14271, npc_id=3106, name="Goblin", x=3225, y=3215, on_screen=True):
    return {
        "id": npc_id, "index": index, "name": name,
        "worldX": x, "worldY": y, "plane": 0,
        "animation": -1, "combatLevel": 2,
        "onScreen": on_screen,
        "canvasX": 412 if on_screen else None,
        "canvasY": 380 if on_screen else None,
        "hull": [[400, 370], [420, 370], [420, 390], [400, 390]] if on_screen else None,
    }


def _player(player_id=17, name="Hans", x=3224, y=3216, on_screen=True):
    return {
        "id": player_id, "name": name, "worldX": x, "worldY": y, "plane": 0,
        "animation": -1, "combatLevel": 5,
        "onScreen": on_screen,
        "canvasX": 430 if on_screen else None,
        "canvasY": 360 if on_screen else None,
        "hull": [[420, 350], [440, 350], [440, 370], [420, 370]] if on_screen else None,
    }


def _obj(obj_id=1276, name="Oak tree", x=3225, y=3215, on_screen=True):
    return {
        "id": obj_id, "name": name, "category": "game",
        "worldX": x, "worldY": y, "plane": 0,
        "onScreen": on_screen,
        "canvasX": 350 if on_screen else None,
        "canvasY": 290 if on_screen else None,
        "hull": [[340, 280], [360, 280], [360, 300], [340, 300]] if on_screen else None,
    }


def _ground_item(item_id=526, name="Bones", quantity=1, x=3225, y=3215, on_screen=True):
    return {
        "id": item_id, "name": name, "quantity": quantity,
        "worldX": x, "worldY": y, "plane": 0,
        "onScreen": on_screen,
        "canvasX": 412 if on_screen else None,
        "canvasY": 395 if on_screen else None,
        "hull": [[402, 388], [422, 388], [422, 402], [402, 402]] if on_screen else None,
    }


def _msg(tick, npcs=None, players=None, objects=None):
    msg = {"tick": tick, "events": []}
    if npcs is not None:
        msg["npcs"] = npcs
    if players is not None:
        msg["players"] = players
    if objects is not None:
        msg["objects"] = objects
    return msg


def _game(tick, **kwargs) -> GameState:
    g = GameState()
    g.update(_msg(tick, **kwargs))
    return g


# ---------------------------------------------------------------------------
# Identity key functions
# ---------------------------------------------------------------------------

class TestKeyFunctions:
    def test_npc_key_is_index(self):
        assert npc_key(_npc(index=14271)) == 14271

    def test_player_key_is_id(self):
        assert player_key(_player(player_id=17)) == 17

    def test_object_key_is_id_and_position(self):
        assert object_key(_obj(obj_id=1276, x=3225, y=3215)) == (1276, 3225, 3215)

    def test_object_key_distinguishes_same_id_different_position(self):
        assert object_key(_obj(obj_id=1276, x=3225, y=3215)) != object_key(_obj(obj_id=1276, x=3226, y=3215))

    def test_object_key_distinguishes_different_id_same_position(self):
        """E.g. a tree (id=1276) chopped down to a stump (different id) at the same tile."""
        assert object_key(_obj(obj_id=1276, x=3225, y=3215)) != object_key(_obj(obj_id=1277, x=3225, y=3215))


# ---------------------------------------------------------------------------
# First sighting -> no velocity yet
# ---------------------------------------------------------------------------

class TestFirstSightingHasNoVelocity:
    def test_npc_first_sighting_returns_none(self):
        tracker = EntityTracker()
        npc = _npc()
        tracker.update(_game(1, npcs=[npc]))
        assert tracker.npc_velocity(npc) is None
        assert tracker.npc_velocity(npc, "canvas") is None

    def test_player_first_sighting_returns_none(self):
        tracker = EntityTracker()
        p = _player()
        tracker.update(_game(1, players=[p]))
        assert tracker.player_velocity(p) is None

    def test_object_first_sighting_returns_none(self):
        tracker = EntityTracker()
        o = _obj()
        tracker.update(_game(1, objects=[o]))
        assert tracker.object_velocity(o) is None


# ---------------------------------------------------------------------------
# World-space velocity across consecutive ticks
# ---------------------------------------------------------------------------

class TestWorldVelocity:
    def test_npc_velocity_computed_after_second_sighting(self):
        tracker = EntityTracker()
        tracker.update(_game(1, npcs=[_npc(x=3225, y=3215)]))
        moved = _npc(x=3227, y=3216)
        tracker.update(_game(2, npcs=[moved]))
        assert tracker.npc_velocity(moved) == (2.0, 1.0)

    def test_player_velocity_computed_after_second_sighting(self):
        tracker = EntityTracker()
        tracker.update(_game(1, players=[_player(x=3224, y=3216)]))
        moved = _player(x=3220, y=3216)
        tracker.update(_game(2, players=[moved]))
        assert tracker.player_velocity(moved) == (-4.0, 0.0)

    def test_stationary_object_has_zero_velocity(self):
        tracker = EntityTracker()
        tracker.update(_game(1, objects=[_obj()]))
        same = _obj()
        tracker.update(_game(2, objects=[same]))
        assert tracker.object_velocity(same) == (0.0, 0.0)

    def test_velocity_accounts_for_tick_gap(self):
        """A 4-tick gap covering an 8-tile move yields 2.0 tiles/tick, not 8.0."""
        tracker = EntityTracker()
        tracker.update(_game(1, npcs=[_npc(x=3225, y=3215)]))
        moved = _npc(x=3233, y=3215)
        tracker.update(_game(5, npcs=[moved]))
        assert tracker.npc_velocity(moved) == (8.0 / 4, 0.0)

    def test_duplicate_tick_returns_none(self):
        """Same tick number twice -> zero time delta -> no meaningful velocity."""
        tracker = EntityTracker()
        tracker.update(_game(1, npcs=[_npc(x=3225, y=3215)]))
        moved = _npc(x=3227, y=3215)
        tracker.update(_game(1, npcs=[moved]))
        assert tracker.npc_velocity(moved) is None


# ---------------------------------------------------------------------------
# Canvas-space velocity (requires on-screen samples)
# ---------------------------------------------------------------------------

class TestCanvasVelocity:
    def test_canvas_velocity_computed_when_both_samples_on_screen(self):
        tracker = EntityTracker()
        tracker.update(_game(1, npcs=[_npc(on_screen=True)]))
        moved = dict(_npc(on_screen=True), canvasX=420, canvasY=388)
        tracker.update(_game(2, npcs=[moved]))
        assert tracker.npc_velocity(moved, "canvas") == (8.0, 8.0)

    def test_canvas_velocity_none_when_previous_sample_off_screen(self):
        tracker = EntityTracker()
        tracker.update(_game(1, npcs=[_npc(on_screen=False)]))
        now_visible = _npc(on_screen=True)
        tracker.update(_game(2, npcs=[now_visible]))
        assert tracker.npc_velocity(now_visible, "canvas") is None
        # world velocity is unaffected by on-screen status
        assert tracker.npc_velocity(now_visible) == (0.0, 0.0)

    def test_canvas_velocity_none_when_current_sample_off_screen(self):
        tracker = EntityTracker()
        tracker.update(_game(1, npcs=[_npc(on_screen=True)]))
        now_hidden = _npc(on_screen=False)
        tracker.update(_game(2, npcs=[now_hidden]))
        assert tracker.npc_velocity(now_hidden, "canvas") is None


# ---------------------------------------------------------------------------
# Identity reset on despawn / index reuse
# ---------------------------------------------------------------------------

class TestIdentityResetOnGap:
    def test_npc_missing_for_a_tick_resets_history(self):
        tracker = EntityTracker()
        tracker.update(_game(1, npcs=[_npc(index=14271, x=3225, y=3215)]))
        tracker.update(_game(2, npcs=[]))  # despawned
        # A different NPC reuses the same index far away — must not be treated
        # as a continuation of the original (which would produce a bogus spike).
        reused = _npc(index=14271, x=3300, y=3300)
        tracker.update(_game(3, npcs=[reused]))
        assert tracker.npc_velocity(reused) is None

    def test_player_missing_for_a_tick_resets_history(self):
        tracker = EntityTracker()
        tracker.update(_game(1, players=[_player(player_id=17, x=3224, y=3216)]))
        tracker.update(_game(2, players=[]))
        reappeared = _player(player_id=17, x=3300, y=3300)
        tracker.update(_game(3, players=[reappeared]))
        assert tracker.player_velocity(reappeared) is None

    def test_object_replaced_in_place_is_tracked_as_new_entity(self):
        """A tree (id=1276) chopped to a stump (id=1277) at the same tile must
        not inherit the tree's (zero) velocity history as if it were continuous."""
        tracker = EntityTracker()
        tree = _obj(obj_id=1276, x=3225, y=3215)
        tracker.update(_game(1, objects=[tree]))
        tracker.update(_game(2, objects=[tree]))
        assert tracker.object_velocity(tree) == (0.0, 0.0)

        stump = _obj(obj_id=1277, x=3225, y=3215)
        tracker.update(_game(3, objects=[stump]))
        assert tracker.object_velocity(stump) is None


# ---------------------------------------------------------------------------
# Multiple entities tracked independently
# ---------------------------------------------------------------------------

class TestMultipleEntitiesTrackedIndependently:
    def test_two_npcs_do_not_cross_contaminate(self):
        tracker = EntityTracker()
        a1 = _npc(index=1, x=3225, y=3215)
        b1 = _npc(index=2, x=3300, y=3300)
        tracker.update(_game(1, npcs=[a1, b1]))

        a2 = _npc(index=1, x=3226, y=3215)
        b2 = _npc(index=2, x=3300, y=3303)
        tracker.update(_game(2, npcs=[a2, b2]))

        assert tracker.npc_velocity(a2) == (1.0, 0.0)
        assert tracker.npc_velocity(b2) == (0.0, 3.0)

    def test_unrelated_npc_disappearing_does_not_affect_others(self):
        tracker = EntityTracker()
        a1 = _npc(index=1, x=3225, y=3215)
        b1 = _npc(index=2, x=3300, y=3300)
        tracker.update(_game(1, npcs=[a1, b1]))

        a2 = _npc(index=1, x=3226, y=3215)
        tracker.update(_game(2, npcs=[a2]))  # b despawned

        assert tracker.npc_velocity(a2) == (1.0, 0.0)


# ---------------------------------------------------------------------------
# Generic velocity() — dispatches to the right typed lookup by entity shape
# (used by GameController, which handles npcs/players/objects/ground items
# interchangeably and has no a-priori notion of which kind it has — see
# PLAN.md "Phase 4")
# ---------------------------------------------------------------------------

class TestGenericVelocityDispatch:
    def test_routes_npc_by_index_field(self):
        tracker = EntityTracker()
        a1 = _npc(index=1, x=3225, y=3215)
        tracker.update(_game(1, npcs=[a1]))
        a2 = _npc(index=1, x=3226, y=3215)
        tracker.update(_game(2, npcs=[a2]))

        assert tracker.velocity(a2) == tracker.npc_velocity(a2) == (1.0, 0.0)

    def test_routes_player_when_no_index_or_category_or_quantity(self):
        tracker = EntityTracker()
        p1 = _player(x=3224, y=3216)
        tracker.update(_game(1, players=[p1]))
        p2 = _player(x=3225, y=3216)
        tracker.update(_game(2, players=[p2]))

        assert tracker.velocity(p2) == tracker.player_velocity(p2) == (1.0, 0.0)

    def test_routes_object_by_category_field(self):
        tracker = EntityTracker()
        o1 = _obj(x=3225, y=3215)
        tracker.update(_game(1, objects=[o1]))

        # Stationary scenery: same id+tile -> same tracked instance, velocity (0, 0)
        o2 = _obj(x=3225, y=3215)
        tracker.update(_game(2, objects=[o2]))

        assert tracker.velocity(o2) == tracker.object_velocity(o2) == (0.0, 0.0)

    def test_ground_items_are_not_tracked_and_predict_as_static(self):
        """Ground items carry `quantity` (and no `index`/`category`) — they're
        deliberately excluded from tracking (see EntityTracker.velocity
        docstring): they're stationary, so `None` ("treat as static") is
        already the right answer, not a degraded one."""
        tracker = EntityTracker()
        item = _ground_item()
        tracker.update(_game(1, objects=[]))  # tracker has *some* state...
        tracker.update(_game(2, objects=[]))

        assert tracker.velocity(item) is None
        assert tracker.velocity(item, "canvas") is None

    def test_dispatch_does_not_cross_contaminate_id_keyspaces(self):
        """An object and an NPC that happen to share a numeric `id` must be
        tracked (and looked up) completely independently — velocity() routes
        purely on shape, never on id collision."""
        tracker = EntityTracker()
        npc = _npc(index=99, npc_id=500, x=3225, y=3215)
        obj = _obj(obj_id=500, x=3300, y=3300)
        tracker.update(_game(1, npcs=[npc], objects=[obj]))

        npc2 = _npc(index=99, npc_id=500, x=3226, y=3215)
        obj2 = _obj(obj_id=500, x=3300, y=3300)
        tracker.update(_game(2, npcs=[npc2], objects=[obj2]))

        assert tracker.velocity(npc2) == (1.0, 0.0)
        assert tracker.velocity(obj2) == (0.0, 0.0)
