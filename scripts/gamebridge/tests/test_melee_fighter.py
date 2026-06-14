"""
Tests for the MeleeFighterRoutine state machine.

Covers:
  - target selection: nearest NPC by name, excluding ones near other players
  - camera/occlusion/idle-settle gating before the attack gesture (mirrors iron_mining)
  - "verify before you click": right-click → confirm "Attack <name>"/"Take <name>"
    is actually in the context menu → click that row, for both targeting and looting
  - death detection via the unique per-instance `index` (not the shared `id`)
  - looting: one pickup gesture at a time, each item attempted exactly once,
    re-resolved from live state every tick, transition back once the loot
    window elapses
"""
from __future__ import annotations

from unittest.mock import MagicMock

from scripts.gamebridge.input.keyboard import Key
from scripts.gamebridge.routines.examples.melee_fighter import MeleeFighterRoutine
from scripts.gamebridge.routines.interaction import InteractionRoutine, OCCLUSION_NUDGE_YAW
from scripts.gamebridge.state.game_state import GameState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game(
    tick: int = 1,
    player_x: int = 3220,
    player_y: int = 3218,
    npcs: list | None = None,
    players: list | None = None,
    ground_items: list | None = None,
) -> GameState:
    game = GameState()
    game.tick = tick
    game.player = {"worldX": player_x, "worldY": player_y, "plane": 0, "animation": -1}
    game.npcs = npcs if npcs is not None else []
    game.players = players if players is not None else []
    game.ground_items = ground_items if ground_items is not None else []
    game.camera = {"yaw": 0, "pitch": 256}
    return game


def _ctrl() -> MagicMock:
    return MagicMock()


def _routine() -> MeleeFighterRoutine:
    return MeleeFighterRoutine()


def _rival(x: int, y: int, player_id: int = 5, name: str = "Rival") -> dict:
    return {"id": player_id, "name": name, "worldX": x, "worldY": y, "plane": 0,
            "animation": -1, "combatLevel": 30, "onScreen": False,
            "canvasX": None, "canvasY": None, "hull": None}


GOBLIN_ON_SCREEN = {
    "id": 100, "name": "Goblin", "index": 42,
    "worldX": 3221, "worldY": 3219, "plane": 0,
    "animation": -1, "combatLevel": 2,
    "onScreen": True, "canvasX": 400, "canvasY": 300,
    "hull": [[390, 290], [410, 290], [410, 310], [390, 310]],
}

GOBLIN_OFF_SCREEN = {
    "id": 100, "name": "Goblin", "index": 7,
    "worldX": 3230, "worldY": 3230, "plane": 0,
    "animation": -1, "combatLevel": 2,
    "onScreen": False, "canvasX": None, "canvasY": None, "hull": None,
}

BONES = {
    "id": 526, "name": "Bones", "quantity": 1,
    "worldX": 3225, "worldY": 3215, "plane": 0,
    "onScreen": True, "canvasX": 412, "canvasY": 395,
    "hull": [[402, 388], [422, 388], [422, 402], [402, 402]],
}

COINS_OFF_SCREEN = {
    "id": 995, "name": "Coins", "quantity": 25,
    "worldX": 3225, "worldY": 3215, "plane": 0,
    "onScreen": False, "canvasX": None, "canvasY": None, "hull": None,
}

COINS_ON_SCREEN = {**COINS_OFF_SCREEN, "onScreen": True, "canvasX": 420, "canvasY": 400,
                   "hull": [[410, 390], [430, 390], [430, 410], [410, 410]]}


# ---------------------------------------------------------------------------
# find_target — target selection (nearest NPC by name, excluding contested ones)
# ---------------------------------------------------------------------------

class TestFindTargetSelection:
    def test_no_click_when_no_matching_npc_in_scene(self):
        game = _make_game(npcs=[])
        ctrl = _ctrl()
        result = _routine().find_target(game, ctrl)
        ctrl.bring_entity_on_screen.assert_not_called()
        ctrl.right_click_entity.assert_not_called()
        assert result is None

    def test_no_click_when_only_candidate_is_near_other_player(self):
        contested = {**GOBLIN_ON_SCREEN, "index": 1}
        rival = _rival(contested["worldX"], contested["worldY"])
        game = _make_game(npcs=[contested], players=[rival])
        ctrl = _ctrl()
        result = _routine().find_target(game, ctrl)
        ctrl.bring_entity_on_screen.assert_not_called()
        ctrl.right_click_entity.assert_not_called()
        assert result is None

    def test_picks_nearest_uncontested_npc(self):
        contested_close = {**GOBLIN_ON_SCREEN, "index": 1, "worldX": 3221, "worldY": 3218}
        uncontested_near = {**GOBLIN_ON_SCREEN, "index": 2, "worldX": 3223, "worldY": 3218}
        uncontested_far = {**GOBLIN_ON_SCREEN, "index": 3, "worldX": 3230, "worldY": 3230}
        rival = _rival(contested_close["worldX"], contested_close["worldY"])
        game = _make_game(npcs=[contested_close, uncontested_near, uncontested_far], players=[rival])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        ctrl.click_menu_entry.return_value = True

        r = _routine()
        r.find_target(game, ctrl)            # tick 1: settle buffer starts
        game.tick = 2
        r.find_target(game, ctrl)            # tick 2: settle complete — right-clicks
        game.tick = 3
        result = r.find_target(game, ctrl)   # tick 3: "Attack Goblin" verified — commits

        ctrl.right_click_entity.assert_called_once_with(uncontested_near, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID)
        ctrl.click_menu_entry.assert_called_once_with(game, "Attack", r.NPC_NAME)
        assert result == "fighting"
        assert r._target_index == uncontested_near["index"]
        assert r._target == uncontested_near


# ---------------------------------------------------------------------------
# find_target — camera adjustment / idle settle buffer (mirrors iron_mining)
# ---------------------------------------------------------------------------

class TestFindTargetCameraAndSettleBuffer:
    def test_adjusts_camera_when_target_off_screen(self):
        game = _make_game(tick=1, npcs=[GOBLIN_OFF_SCREEN])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = False
        result = _routine().find_target(game, ctrl)
        ctrl.bring_entity_on_screen.assert_called_once_with(GOBLIN_OFF_SCREEN, game)
        ctrl.right_click_entity.assert_not_called()
        assert result is None

    def test_does_not_click_while_player_moving(self):
        game = _make_game(tick=2, npcs=[GOBLIN_OFF_SCREEN])
        game._prev_pos = (game.player_pos[0] - 1, game.player_pos[1])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        result = _routine().find_target(game, ctrl)
        ctrl.right_click_entity.assert_not_called()
        assert result is None

    def test_waits_one_tick_after_settle_then_attacks_and_transitions(self):
        game = _make_game(tick=1, npcs=[GOBLIN_OFF_SCREEN])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        ctrl.click_menu_entry.return_value = True
        r = _routine()

        result = r.find_target(game, ctrl)   # tick 1: records settle tick, no click
        ctrl.right_click_entity.assert_not_called()
        assert result is None

        game.tick = 2
        result = r.find_target(game, ctrl)   # tick 2: settle complete — right-clicks
        ctrl.right_click_entity.assert_called_once_with(GOBLIN_OFF_SCREEN, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID)
        assert r._attack_target == GOBLIN_OFF_SCREEN
        assert result is None

        game.tick = 3
        result = r.find_target(game, ctrl)   # tick 3: "Attack Goblin" verified — commits
        ctrl.click_menu_entry.assert_called_once_with(game, "Attack", r.NPC_NAME)
        assert result == "fighting"
        assert r._target_index == GOBLIN_OFF_SCREEN["index"]
        assert r._target == GOBLIN_OFF_SCREEN
        assert r._attack_target is None

    def test_resets_buffer_when_camera_adjusts_mid_settle(self):
        game = _make_game(tick=1, npcs=[GOBLIN_OFF_SCREEN])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        r = _routine()

        r.find_target(game, ctrl)
        assert r._approach_idle_since_tick == 1

        ctrl.bring_entity_on_screen.return_value = False
        game.tick = 2
        r.find_target(game, ctrl)
        assert r._approach_idle_since_tick == -1

    def test_resets_buffer_when_player_moves(self):
        game = _make_game(tick=1, npcs=[GOBLIN_OFF_SCREEN])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        r = _routine()

        r.find_target(game, ctrl)
        assert r._approach_idle_since_tick == 1

        game.tick = 2
        game._prev_pos = game.player_pos
        game.player = {**game.player, "worldX": game.player["worldX"] + 1}
        r.find_target(game, ctrl)
        assert r._approach_idle_since_tick == -1

    def test_buffer_resets_after_right_click(self):
        game = _make_game(tick=1, npcs=[GOBLIN_OFF_SCREEN])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        r = _routine()

        r.find_target(game, ctrl)   # tick 1: buffer start
        game.tick = 2
        r.find_target(game, ctrl)   # tick 2: right-clicks — gesture started
        assert r._approach_idle_since_tick == -1


# ---------------------------------------------------------------------------
# find_target — "verify before you click": confirm the menu before committing
# ---------------------------------------------------------------------------

class TestFindTargetMenuVerification:
    def _mid_gesture_routine(self, target: dict = GOBLIN_ON_SCREEN) -> MeleeFighterRoutine:
        r = _routine()
        r._attack_target = target
        return r

    def test_does_not_commit_while_menu_still_open_without_a_match(self):
        """The menu can take a tick to populate — don't abandon the gesture
        (or fall back to clicking blind) while it's still open with no
        "Attack Goblin" entry yet."""
        game = _make_game(tick=5)
        game.menu = {"open": True, "entries": []}
        ctrl = _ctrl()
        ctrl.click_menu_entry.return_value = False
        r = self._mid_gesture_routine()

        result = r.find_target(game, ctrl)

        assert r._attack_target == GOBLIN_ON_SCREEN
        assert result is None

    def test_dismisses_menu_open_without_a_match(self):
        """Right-click menus don't time out — if the row we need never shows
        up (e.g. the click landed on a tile or another entity), nothing else
        will close the menu. The routine must actively move the mouse off it
        rather than wait on it forever (this was observed live: the bot sat
        stuck with the menu open until the cursor was nudged away by hand)."""
        game = _make_game(tick=5)
        game.menu = {"open": True, "entries": []}
        ctrl = _ctrl()
        ctrl.click_menu_entry.return_value = False
        r = self._mid_gesture_routine()

        result = r.find_target(game, ctrl)

        ctrl.dismiss_menu.assert_called_once_with(game)
        assert r._attack_target == GOBLIN_ON_SCREEN
        assert result is None

    def test_retries_when_menu_closes_without_a_match(self):
        """The menu closed without ever showing "Attack Goblin" — e.g. the
        right-click landed on a tile or another entity. Reset and let
        find_target re-pick and re-click a target on a future tick rather
        than getting stuck waiting on a menu that's gone."""
        game = _make_game(tick=5)
        game.menu = {"open": False, "entries": []}
        ctrl = _ctrl()
        ctrl.click_menu_entry.return_value = False
        r = self._mid_gesture_routine()

        result = r.find_target(game, ctrl)

        assert r._attack_target is None
        assert r._target_index is None
        assert result is None

    def test_commits_target_once_attack_entry_is_verified_and_clicked(self):
        game = _make_game(tick=5)
        game.menu = {"open": True, "entries": [
            {"option": "Attack", "target": "<col=ffff00>Goblin<col=80ff00>  (level-2)",
             "bounds": {"x": 100, "y": 50, "width": 80, "height": 15}},
        ]}
        ctrl = _ctrl()
        ctrl.click_menu_entry.return_value = True
        r = self._mid_gesture_routine()

        result = r.find_target(game, ctrl)

        ctrl.click_menu_entry.assert_called_once_with(game, "Attack", r.NPC_NAME)
        assert result == "fighting"
        assert r._target_index == GOBLIN_ON_SCREEN["index"]
        assert r._target == GOBLIN_ON_SCREEN
        assert r._fight_start_tick == 5
        assert r._attack_target is None


# ---------------------------------------------------------------------------
# find_target — occlusion guard (mirrors iron_mining's TestOcclusionGuard)
# ---------------------------------------------------------------------------

# groupId 149 = inventory — a real occluding panel (see state/interfaces.py).
# childId 0 — only a panel's root widget (whose bounds span the whole panel)
# is checked; sub-widgets report their own small, often-stale bounds.
OCCLUDING_PANEL = {
    "groupId": 149,
    "childId": 0,
    "itemId": -1,
    "quantity": 0,
    "bounds": {"x": 570, "y": 20, "width": 150, "height": 150},
    "text": "",
}

GOBLIN_OCCLUDED = {**GOBLIN_ON_SCREEN, "canvasX": 600, "canvasY": 50}     # inside the panel
GOBLIN_CLEAR = {**GOBLIN_ON_SCREEN, "canvasX": 300, "canvasY": 300}       # outside the panel


class TestFindTargetOcclusionGuard:
    def _game_with_panel(self, npc: dict, tick: int = 2) -> GameState:
        game = _make_game(tick=tick, npcs=[npc])
        game.interfaces = [OCCLUDING_PANEL]
        return game

    def test_does_not_click_when_occluded(self):
        game = self._game_with_panel(GOBLIN_OCCLUDED)
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        result = _routine().find_target(game, ctrl)

        ctrl.right_click_entity.assert_not_called()
        assert result is None

    def test_adjusts_camera_when_occluded(self):
        """Occlusion triggers an explicit camera nudge to clear the entity —
        `bring_entity_on_screen` is a no-op once `onScreen` is already true,
        so a real rotation (`rotate_camera`) is what actually moves it."""
        game = self._game_with_panel(GOBLIN_OCCLUDED)
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        _routine().find_target(game, ctrl)

        ctrl.rotate_camera.assert_called_once_with(Key.RIGHT, OCCLUSION_NUDGE_YAW)

    def test_resets_idle_buffer_when_occluded(self):
        game = self._game_with_panel(GOBLIN_OCCLUDED)
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        r = _routine()
        r._approach_idle_since_tick = 1
        r.find_target(game, ctrl)
        assert r._approach_idle_since_tick == -1

    def test_attacks_when_on_screen_and_clear(self):
        game = self._game_with_panel(GOBLIN_CLEAR)
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        ctrl.click_menu_entry.return_value = True

        r = _routine()
        r.find_target(game, ctrl)            # tick 2: settle buffer starts
        game.tick += 1
        r.find_target(game, ctrl)            # tick 3: settle complete — right-clicks
        game.tick += 1
        result = r.find_target(game, ctrl)   # tick 4: "Attack Goblin" verified — commits

        ctrl.right_click_entity.assert_called_once_with(GOBLIN_CLEAR, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID)
        assert result == "fighting"


# ---------------------------------------------------------------------------
# fighting — death detection via unique per-instance `index`
# ---------------------------------------------------------------------------

class TestFighting:
    def _engaged_routine(self, target_index: int = 42, target_pos=(3221, 3219),
                         fight_start_tick: int = 4) -> MeleeFighterRoutine:
        r = _routine()
        r._target_index = target_index
        r._target = {**GOBLIN_ON_SCREEN, "index": target_index,
                     "worldX": target_pos[0], "worldY": target_pos[1]}
        r._target_pos = target_pos
        r._fight_start_tick = fight_start_tick
        return r

    def test_stays_fighting_while_target_still_present(self):
        game = _make_game(tick=5, npcs=[GOBLIN_ON_SCREEN])
        result = self._engaged_routine().fighting(game, _ctrl())
        assert result is None

    def test_transitions_to_looting_when_target_vanishes(self):
        game = _make_game(tick=5, npcs=[])
        r = self._engaged_routine()
        result = r.fighting(game, _ctrl())
        assert result == "looting"
        assert r._death_tick == 5

    def test_uses_last_seen_position_as_death_tile_not_click_time_position(self):
        """NPCs walk around mid-fight — the corpse appears wherever it died,
        not where it was standing when we first clicked it, so `_target`
        must be refreshed from live state every tick it's still present."""
        moved_goblin = {**GOBLIN_ON_SCREEN, "worldX": 3250, "worldY": 3260}
        r = self._engaged_routine()  # clicked it at (3221, 3219)

        r.fighting(_make_game(tick=5, npcs=[moved_goblin]), _ctrl())  # still alive, moved
        result = r.fighting(_make_game(tick=6, npcs=[]), _ctrl())     # now it's gone

        assert result == "looting"
        assert r._target_pos == (3250, 3260)

    def test_clears_looted_keys_on_transition_to_looting(self):
        game = _make_game(tick=5, npcs=[])
        r = self._engaged_routine()
        r._looted_keys = {(526, 3221, 3219)}
        r.fighting(game, _ctrl())
        assert r._looted_keys == set()

    def test_uses_index_not_shared_composition_id_for_death_check(self):
        """Two Goblins share the same composition `id` (100) — only the unique
        per-instance `index` tells them apart, so a fresh spawn with the same
        `id` must NOT be mistaken for our still-living target."""
        fresh_spawn_same_id = {**GOBLIN_ON_SCREEN, "index": 99, "worldX": 3240, "worldY": 3240}
        game = _make_game(tick=5, npcs=[fresh_spawn_same_id])
        result = self._engaged_routine(target_index=42).fighting(game, _ctrl())
        assert result == "looting"

    def test_does_not_transition_when_index_still_present_among_others(self):
        other = {**GOBLIN_ON_SCREEN, "index": 99, "worldX": 3240, "worldY": 3240}
        game = _make_game(tick=5, npcs=[other, GOBLIN_ON_SCREEN])
        result = self._engaged_routine().fighting(game, _ctrl())
        assert result is None


# ---------------------------------------------------------------------------
# fighting — miss-click detection via combat xp drops
# ---------------------------------------------------------------------------

class TestFightingMissclickDetection:
    def _engaged_routine(self, fight_start_tick: int) -> MeleeFighterRoutine:
        r = _routine()
        r._target_index = 42
        r._target = GOBLIN_ON_SCREEN
        r._target_pos = (3221, 3219)
        r._fight_start_tick = fight_start_tick
        return r

    def test_keeps_fighting_within_timeout_when_no_xp_yet(self):
        """A real attack takes a tick or two to land — don't bail early."""
        game = _make_game(tick=10, npcs=[GOBLIN_ON_SCREEN])
        r = self._engaged_routine(fight_start_tick=5)  # 5 ticks elapsed, <= timeout
        result = r.fighting(game, _ctrl())
        assert result is None

    def test_returns_to_find_target_when_no_xp_drop_after_timeout(self):
        """No combat xp landed within MISCLICK_TIMEOUT_TICKS — assume the
        click missed (e.g. hit a tile/entity behind the NPC) and re-target."""
        game = _make_game(tick=20, npcs=[GOBLIN_ON_SCREEN])
        r = self._engaged_routine(fight_start_tick=5)  # 15 ticks elapsed, > timeout
        result = r.fighting(game, _ctrl())
        assert result == "find_target"

    def test_keeps_fighting_past_timeout_once_xp_drop_seen(self):
        """Any combat xp received since the click confirms it landed — keep
        fighting even if there's a later lull between hits."""
        game = _make_game(tick=20, npcs=[GOBLIN_ON_SCREEN])
        game.last_xp_tick["STRENGTH"] = 7
        r = self._engaged_routine(fight_start_tick=5)  # 15 ticks elapsed, > timeout
        result = r.fighting(game, _ctrl())
        assert result is None

    def test_ignores_xp_drops_that_predate_the_current_attack(self):
        """An xp drop logged before we clicked this target (e.g. from the
        previous kill) must not be mistaken for confirmation that this
        attack landed."""
        game = _make_game(tick=20, npcs=[GOBLIN_ON_SCREEN])
        game.last_xp_tick["ATTACK"] = 3  # before fight_start_tick
        r = self._engaged_routine(fight_start_tick=5)  # 15 ticks elapsed, > timeout
        result = r.fighting(game, _ctrl())
        assert result == "find_target"


# ---------------------------------------------------------------------------
# looting — one pickup gesture at a time, "verify before you click", re-resolved live
# ---------------------------------------------------------------------------

class TestLooting:
    def _looting_routine(self, target_pos=(3225, 3215), death_tick: int = 10) -> MeleeFighterRoutine:
        r = _routine()
        r._target_pos = target_pos
        r._death_tick = death_tick
        return r

    def _take_entry(self, name: str) -> dict:
        return {"option": "Take", "target": f"<col=ff9040>{name}",
                "bounds": {"x": 100, "y": 50, "width": 80, "height": 15}}

    def test_right_clicks_first_unlooted_onscreen_item(self):
        """Picking an item up starts with a right-click — it isn't recorded
        in _looted_keys (and so isn't "committed") until the menu confirms
        the matching "Take <name>" entry is actually present."""
        game = _make_game(tick=11, ground_items=[BONES])
        ctrl = _ctrl()
        r = self._looting_routine()

        result = r.looting(game, ctrl)

        ctrl.right_click_entity.assert_called_once_with(BONES, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID)
        assert r._loot_target == BONES
        assert r._looted_keys == set()
        assert result is None

    def test_does_not_start_a_new_gesture_mid_pickup(self):
        """While a pickup gesture is in flight, looting must keep verifying
        that one rather than scanning the tile and right-clicking something
        else (which would abandon the in-flight gesture)."""
        game = _make_game(tick=11, ground_items=[BONES, COINS_ON_SCREEN])
        ctrl = _ctrl()
        ctrl.click_menu_entry.return_value = False
        game.menu = {"open": True, "entries": []}
        r = self._looting_routine()
        r._loot_target = BONES

        result = r.looting(game, ctrl)

        ctrl.right_click_entity.assert_not_called()
        ctrl.click_menu_entry.assert_called_once_with(game, "Take", BONES["name"])
        assert r._loot_target == BONES
        assert result is None

    def test_records_item_once_take_entry_is_verified_and_clicked(self):
        game = _make_game(tick=11, ground_items=[BONES])
        ctrl = _ctrl()
        ctrl.click_menu_entry.return_value = True
        r = self._looting_routine()
        r._loot_target = BONES

        result = r.looting(game, ctrl)

        ctrl.click_menu_entry.assert_called_once_with(game, "Take", BONES["name"])
        assert (BONES["id"], 3225, 3215) in r._looted_keys
        assert r._loot_target is None
        assert result is None

    def test_retries_pickup_when_menu_closes_without_a_match(self):
        """The menu closed without ever showing "Take Bones" — e.g. the
        right-click landed on the corpse or another stack instead. The item
        was never actually clicked, so reset and let looting re-resolve and
        re-attempt it on a future tick rather than abandoning it."""
        game = _make_game(tick=11, ground_items=[BONES])
        ctrl = _ctrl()
        ctrl.click_menu_entry.return_value = False
        game.menu = {"open": False, "entries": []}
        r = self._looting_routine()
        r._loot_target = BONES

        result = r.looting(game, ctrl)

        assert r._loot_target is None
        assert r._looted_keys == set()
        assert result is None

    def test_dismisses_menu_open_without_a_take_match(self):
        """Same "stuck open menu" hazard as find_target — a right-click menu
        that never shows the "Take Bones" row won't close on its own, so the
        routine must actively move the mouse off it rather than wait forever."""
        game = _make_game(tick=11, ground_items=[BONES])
        ctrl = _ctrl()
        ctrl.click_menu_entry.return_value = False
        game.menu = {"open": True, "entries": []}
        r = self._looting_routine()
        r._loot_target = BONES

        result = r.looting(game, ctrl)

        ctrl.dismiss_menu.assert_called_once_with(game)
        assert r._loot_target == BONES
        assert result is None

    def test_does_not_reattempt_already_looted_item(self):
        game = _make_game(tick=11, ground_items=[BONES])
        ctrl = _ctrl()
        r = self._looting_routine()
        r._looted_keys = {(BONES["id"], 3225, 3215)}

        result = r.looting(game, ctrl)

        ctrl.right_click_entity.assert_not_called()
        assert result is None

    def test_skips_offscreen_item_without_marking_it_attempted(self):
        """An item that hasn't rendered yet is left alone — not yet 'attempted' —
        so it can still be picked up once it appears."""
        game = _make_game(tick=11, ground_items=[COINS_OFF_SCREEN])
        ctrl = _ctrl()
        r = self._looting_routine()

        result = r.looting(game, ctrl)

        ctrl.right_click_entity.assert_not_called()
        assert r._looted_keys == set()
        assert result is None

    def test_attempts_only_one_item_per_tick(self):
        game = _make_game(tick=11, ground_items=[BONES, COINS_ON_SCREEN])
        ctrl = _ctrl()
        r = self._looting_routine()

        result = r.looting(game, ctrl)

        ctrl.right_click_entity.assert_called_once_with(BONES, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID)
        assert result is None

    def test_picks_up_items_one_full_gesture_at_a_time(self):
        """Coordinates aren't cached: each pickup is its own right-click →
        verify → click gesture. Once one resolves (recorded here), the next
        tick re-resolves the tile from live state — Bones is gone and Coins
        has rendered — and starts a fresh gesture on whatever's there now,
        rather than reusing a stale position."""
        ctrl = _ctrl()
        ctrl.click_menu_entry.return_value = True
        r = self._looting_routine()

        # tick 11: right-click Bones
        r.looting(_make_game(tick=11, ground_items=[BONES]), ctrl)
        assert r._loot_target == BONES
        ctrl.reset_mock()

        # tick 12: "Take Bones" verified — recorded, gesture resolved
        r.looting(_make_game(tick=12, ground_items=[BONES]), ctrl)
        assert (BONES["id"], 3225, 3215) in r._looted_keys
        assert r._loot_target is None
        ctrl.reset_mock()

        # tick 13: re-resolved from live state — start a fresh gesture on Coins
        result = r.looting(_make_game(tick=13, ground_items=[COINS_ON_SCREEN]), ctrl)

        ctrl.right_click_entity.assert_called_once_with(COINS_ON_SCREEN, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID)
        assert r._loot_target == COINS_ON_SCREEN
        assert result is None

    def test_does_not_start_next_pickup_while_still_walking_to_previous_one(self):
        """The previous pickup's click started the player walking toward its
        tile — every other item's canvas position shifts mid-stride, so a
        right-click fired before the player settles lands on a stale position
        (this was the reported "loots only the top item" bug). We must wait
        for player_idle() before starting the next gesture."""
        game = _make_game(tick=12, ground_items=[BONES, COINS_ON_SCREEN])
        game._prev_pos = (game.player_pos[0] - 1, game.player_pos[1])  # mid-walk
        ctrl = _ctrl()
        r = self._looting_routine()
        r._looted_keys = {(BONES["id"], 3225, 3215)}

        result = r.looting(game, ctrl)

        ctrl.right_click_entity.assert_not_called()
        assert result is None

    def test_starts_next_pickup_once_player_settles_after_previous_one(self):
        game = _make_game(tick=13, ground_items=[BONES, COINS_ON_SCREEN])
        game._prev_pos = game.player_pos  # settled — no movement this tick
        ctrl = _ctrl()
        r = self._looting_routine()
        r._looted_keys = {(BONES["id"], 3225, 3215)}

        result = r.looting(game, ctrl)

        ctrl.right_click_entity.assert_called_once_with(COINS_ON_SCREEN, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID)
        assert result is None

    def test_stays_in_looting_before_window_elapses_with_nothing_to_loot(self):
        game = _make_game(tick=12, ground_items=[])  # 12 - 10 = 2 < LOOT_WINDOW_TICKS (5)
        result = self._looting_routine(death_tick=10).looting(game, _ctrl())
        assert result is None

    def test_returns_to_find_target_once_window_elapses_with_nothing_to_loot(self):
        game = _make_game(tick=15, ground_items=[])  # 15 - 10 = 5 >= LOOT_WINDOW_TICKS
        result = self._looting_routine(death_tick=10).looting(game, _ctrl())
        assert result == "find_target"

    def test_does_not_abandon_an_unlooted_item_when_window_elapses(self):
        """The window only ends the search once nothing is left to attempt —
        a freshly-visible drop still gets its gesture started even on the
        last tick."""
        game = _make_game(tick=16, ground_items=[BONES])  # window already elapsed
        ctrl = _ctrl()
        r = self._looting_routine(death_tick=10)

        result = r.looting(game, ctrl)

        ctrl.right_click_entity.assert_called_once_with(BONES, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID)
        assert r._loot_target == BONES
        assert result is None


# ---------------------------------------------------------------------------
# Live clickbox subscriptions — find_target/looting subscribe for fresh hull
# updates on the entity they're about to right-click
# ---------------------------------------------------------------------------

class TestLiveHullSubscriptions:
    def test_find_target_subscribes_to_goblin_before_attacking(self):
        game = _make_game(tick=1, npcs=[GOBLIN_OFF_SCREEN])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        r = _routine()

        r.find_target(game, ctrl)  # tick 1: settle buffer starts
        game.tick = 2
        r.find_target(game, ctrl)  # tick 2: settle complete — right-clicks

        ctrl.subscribe_to.assert_called_once_with(
            InteractionRoutine.LIVE_HULL_SUB_ID, "npc",
            name=GOBLIN_OFF_SCREEN["name"], id=GOBLIN_OFF_SCREEN["id"],
        )

    def test_looting_subscribes_to_item_before_picking_up(self):
        game = _make_game(tick=11, ground_items=[BONES])
        ctrl = _ctrl()
        r = self._looting_routine_for_subscription_test()

        r.looting(game, ctrl)

        ctrl.subscribe_to.assert_called_once_with(
            InteractionRoutine.LIVE_HULL_SUB_ID, "groundItem",
            name=BONES["name"], id=BONES["id"],
        )

    @staticmethod
    def _looting_routine_for_subscription_test(target_pos=(3225, 3215), death_tick: int = 10) -> MeleeFighterRoutine:
        r = _routine()
        r._target_pos = target_pos
        r._death_tick = death_tick
        return r
