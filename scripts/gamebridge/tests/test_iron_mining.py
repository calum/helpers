"""
Tests for the IronMiningRoutine deposit state.

Fixes covered:
  - deposit must never use blocking ctrl.wait()
  - esc is always pressed when inventory empties (UI may not auto-close)
  - throttle is 8 ticks so one click covers the full server round-trip
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scripts.gamebridge.input.keyboard import Key
from scripts.gamebridge.routines.examples.iron_mining import IronMiningRoutine
from scripts.gamebridge.routines.interaction import InteractionRoutine, OCCLUSION_NUDGE_YAW
from scripts.gamebridge.state.game_state import GameState
from scripts.gamebridge.widget_ids import BankDepositBox


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEPOSIT_BTN = {
    "groupId": BankDepositBox.GROUP,
    "childId": 0x1f,
    "itemId": -1,
    "quantity": 0,
    "bounds": {"x": 100, "y": 300, "width": 80, "height": 20},
    "text": "",
}

MINE_CART = {
    "id": 999,
    "name": "Mine cart",
    "worldX": 3220,
    "worldY": 3218,
    "plane": 0,
    "onScreen": True,
    "canvasX": 457,
    "canvasY": 87,
    "hull": [[440, 80], [475, 80], [475, 95], [440, 95]],
}


def _make_game(
    tick: int = 100,
    inventory_full: bool = True,
    widgets: list | None = None,
    player_x: int = 3220,
    player_y: int = 3218,
    objects: list | None = None,
) -> GameState:
    game = GameState()
    game.tick = tick
    game.player = {"worldX": player_x, "worldY": player_y, "plane": 0, "animation": -1}
    if inventory_full:
        game.inventory = [{"slot": i, "itemId": 440, "qty": 1} for i in range(28)]
    else:
        game.inventory = [{"slot": i, "itemId": -1, "qty": 0} for i in range(28)]
    game.widgets = widgets if widgets is not None else [DEPOSIT_BTN]
    game.objects = objects if objects is not None else [MINE_CART]
    return game


def _ctrl() -> MagicMock:
    return MagicMock()


def _routine() -> IronMiningRoutine:
    return IronMiningRoutine()


# ---------------------------------------------------------------------------
# deposit — inventory-empty exit paths
# ---------------------------------------------------------------------------

class TestDepositFreeSlots:
    def test_any_free_slot_returns_find_ore(self):
        """One free slot is enough to exit deposit — routine mines until full."""
        partial = [{"slot": i, "itemId": 440 if i < 27 else -1, "qty": 1 if i < 27 else 0}
                   for i in range(28)]
        game = _make_game(inventory_full=False, widgets=[DEPOSIT_BTN])
        game.inventory = partial
        assert _routine().deposit(game, _ctrl()) == "find_ore"

    def test_free_slots_always_presses_esc(self):
        """Esc is pressed unconditionally when exiting — safe no-op if UI already closed."""
        for widgets in ([], [DEPOSIT_BTN]):
            ctrl = _ctrl()
            _routine().deposit(_make_game(inventory_full=False, widgets=widgets), ctrl)
            ctrl.press_key.assert_called_once_with(Key.ESCAPE)

    def test_full_inventory_does_not_press_esc(self):
        """Esc must not fire while we're still waiting for the deposit to process."""
        ctrl = _ctrl()
        _routine().deposit(_make_game(inventory_full=True), ctrl)
        ctrl.press_key.assert_not_called()


# ---------------------------------------------------------------------------
# deposit — throttle: one click per 8 ticks
# ---------------------------------------------------------------------------

class TestDepositThrottle:
    def test_first_call_clicks_deposit(self):
        r = _routine()
        ctrl = _ctrl()
        r.deposit(_make_game(tick=100), ctrl)
        ctrl.click_widget.assert_called_once()

    def test_first_call_records_tick(self):
        r = _routine()
        ctrl = _ctrl()
        r.deposit(_make_game(tick=100), ctrl)
        assert r._deposit_clicked_tick == 100

    def test_click_throttled_within_8_ticks(self):
        """Any call within 8 ticks of the last click must be suppressed."""
        r = _routine()
        ctrl = _ctrl()
        r.deposit(_make_game(tick=100), ctrl)
        ctrl.reset_mock()
        for delta in (1, 4, 7):
            r.deposit(_make_game(tick=100 + delta), ctrl)
        ctrl.click_widget.assert_not_called()

    def test_click_allowed_at_8_ticks(self):
        """Exactly 8 ticks after the last click the throttle expires."""
        r = _routine()
        ctrl = _ctrl()
        r.deposit(_make_game(tick=100), ctrl)
        ctrl.reset_mock()
        r.deposit(_make_game(tick=108), ctrl)
        ctrl.click_widget.assert_called_once()

    def test_no_blocking_wait_called(self):
        """ctrl.wait() must never be called — it blocks the tick loop."""
        ctrl = _ctrl()
        _routine().deposit(_make_game(tick=100), ctrl)
        ctrl.wait.assert_not_called()

    def test_returns_none_while_waiting_for_deposit(self):
        result = _routine().deposit(_make_game(tick=100), _ctrl())
        assert result is None


# ---------------------------------------------------------------------------
# deposit — UI not open: clicking the Mine cart to open it
# ---------------------------------------------------------------------------

class TestDepositOpenUI:
    def test_clicks_mine_cart_when_no_deposit_btn(self):
        """When deposit UI is absent, click Mine cart to open it."""
        ctrl = _ctrl()
        _routine().deposit(_make_game(tick=100, widgets=[]), ctrl)
        ctrl.click_entity.assert_called_once()

    def test_does_not_click_mine_cart_if_offscreen(self):
        offscreen_cart = {**MINE_CART, "onScreen": False}
        ctrl = _ctrl()
        _routine().deposit(_make_game(tick=100, widgets=[], objects=[offscreen_cart]), ctrl)
        ctrl.click_entity.assert_not_called()

    def test_returns_walk_to_bank_when_box_not_near(self):
        ctrl = _ctrl()
        game = _make_game(tick=100, widgets=[], player_x=3210, player_y=3210)
        assert _routine().deposit(game, ctrl) == "walk_to_bank"

    def test_returns_walk_to_bank_when_no_cart_in_scene(self):
        assert _routine().deposit(_make_game(tick=100, widgets=[], objects=[]), _ctrl()) == "walk_to_bank"


# ---------------------------------------------------------------------------
# Camera rotation integration
# ---------------------------------------------------------------------------

ORE_OFF_SCREEN = {
    "id": 440,
    "name": "Iron rocks",
    "worldX": 3230,
    "worldY": 3230,
    "plane": 0,
    "onScreen": False,
    "canvasX": None,
    "canvasY": None,
    "hull": None,
}

MINE_CART_OFF_SCREEN = {**MINE_CART, "onScreen": False, "canvasX": None, "canvasY": None, "hull": None}


class TestCameraRotationInRoutine:
    def test_find_ore_adjusts_camera_when_not_visible(self):
        """find_ore delegates to bring_entity_on_screen when ore is off-screen."""
        game = GameState()
        game.tick = 1
        game.player = {"worldX": 3220, "worldY": 3218, "plane": 0, "animation": -1}
        game.inventory = [{"slot": i, "itemId": -1, "qty": 0} for i in range(28)]
        game.objects = [ORE_OFF_SCREEN]
        game.camera = {"yaw": 0, "pitch": 256}

        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = False  # camera adjustment made
        result = _routine().find_ore(game, ctrl)

        ctrl.bring_entity_on_screen.assert_called_once_with(ORE_OFF_SCREEN, game)
        assert result is None  # stay in state; next tick re-evaluates

    def test_find_ore_clicks_ore_when_bring_on_screen_succeeds(self):
        """find_ore waits one tick after entity becomes visible, then clicks on the next tick."""
        game = GameState()
        game.tick = 1
        game.player = {"worldX": 3220, "worldY": 3218, "plane": 0, "animation": -1}
        game.inventory = [{"slot": i, "itemId": -1, "qty": 0} for i in range(28)]
        game.objects = [ORE_OFF_SCREEN]
        game.camera = {"yaw": 0, "pitch": 256}

        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        r = _routine()
        # Tick 1: entity visible, player idle — records settle tick, does not click yet
        result = r.find_ore(game, ctrl)
        ctrl.click_entity.assert_not_called()
        assert result is None

        # Tick 2: settle complete — clicks and transitions to mining
        game.tick = 2
        result = r.find_ore(game, ctrl)
        ctrl.click_entity.assert_called_once_with(ORE_OFF_SCREEN)
        assert result == "mining"

    def test_walk_to_bank_adjusts_camera_when_not_visible(self):
        """walk_to_bank delegates to bring_entity_on_screen when bank is off-screen."""
        game = _make_game(
            tick=1,
            inventory_full=True,
            player_x=3200,
            player_y=3200,
            objects=[MINE_CART_OFF_SCREEN],
        )
        game.camera = {"yaw": 0, "pitch": 256}

        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = False  # camera adjustment made
        result = _routine().walk_to_bank(game, ctrl)

        ctrl.bring_entity_on_screen.assert_called_once_with(MINE_CART_OFF_SCREEN, game)
        ctrl.click_entity.assert_not_called()
        assert result is None  # still walking

    def test_walk_to_bank_clicks_when_visible(self):
        """walk_to_bank waits one tick after entity becomes visible, then clicks on the next tick."""
        game = _make_game(
            tick=1,
            inventory_full=True,
            player_x=3200,
            player_y=3200,
            objects=[MINE_CART_OFF_SCREEN],
        )
        game.camera = {"yaw": 0, "pitch": 256}

        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        r = _routine()
        # Tick 1: entity visible, player idle — records settle tick, does not click yet
        result = r.walk_to_bank(game, ctrl)
        ctrl.click_entity.assert_not_called()
        assert result is None

        # Tick 2: settle complete — clicks to start walking
        game.tick = 2
        result = r.walk_to_bank(game, ctrl)
        ctrl.click_entity.assert_called_once_with(MINE_CART_OFF_SCREEN)
        assert result is None


# ---------------------------------------------------------------------------
# Idle settle buffer
# ---------------------------------------------------------------------------

class TestIdleSettleBuffer:
    def _idle_game(self, tick: int = 1, player_x: int = 3220, player_y: int = 3218) -> GameState:
        game = GameState()
        game.tick = tick
        game.player = {"worldX": player_x, "worldY": player_y, "plane": 0, "animation": -1}
        game.inventory = [{"slot": i, "itemId": -1, "qty": 0} for i in range(28)]
        game.objects = [ORE_OFF_SCREEN]
        game.camera = {"yaw": 0, "pitch": 256}
        return game

    def _moving_game(self, tick: int = 2, player_x: int = 3221, player_y: int = 3218) -> GameState:
        game = self._idle_game(tick, player_x, player_y)
        game._prev_pos = (player_x - 1, player_y)  # moved one tile west this tick
        return game

    def test_find_ore_does_not_click_while_player_moving(self):
        """find_ore must not click while the player is in motion."""
        game = self._moving_game()
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        result = _routine().find_ore(game, ctrl)
        ctrl.click_entity.assert_not_called()
        assert result is None

    def test_walk_to_bank_does_not_click_while_player_moving(self):
        """walk_to_bank must not issue a walk command while player is already en route.

        Gating order matches `InteractionRoutine.approach` (shared with
        find_ore/find_target): camera/occlusion is settled first so the
        entity's on-screen position is current, then the idle check gates
        the click — so bring_entity_on_screen *is* still called while moving,
        it just never reaches click_entity until the player stops.
        """
        game = _make_game(tick=2, inventory_full=True, player_x=3210, player_y=3210)
        game._prev_pos = (3209, 3210)  # player moved this tick
        game.camera = {"yaw": 0, "pitch": 256}
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        result = _routine().walk_to_bank(game, ctrl)
        ctrl.click_entity.assert_not_called()
        assert result is None

    def test_find_ore_resets_buffer_when_camera_adjusts(self):
        """If camera adjustment is needed after the buffer starts, the buffer resets."""
        game = self._idle_game(tick=1)
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        r = _routine()
        r.find_ore(game, ctrl)           # tick 1: sets _approach_idle_since_tick=1
        assert r._approach_idle_since_tick == 1

        ctrl.bring_entity_on_screen.return_value = False
        game.tick = 2
        r.find_ore(game, ctrl)           # tick 2: camera adjust resets buffer
        assert r._approach_idle_since_tick == -1

    def test_find_ore_resets_buffer_when_player_moves(self):
        """If the player starts moving while the buffer is active, the buffer resets."""
        game = self._idle_game(tick=1)
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        r = _routine()
        r.find_ore(game, ctrl)           # tick 1: sets _approach_idle_since_tick=1
        assert r._approach_idle_since_tick == 1

        game.tick = 2
        game._prev_pos = game.player_pos
        game.player = {**game.player, "worldX": 3222}  # moved
        r.find_ore(game, ctrl)           # tick 2: player moving resets buffer
        assert r._approach_idle_since_tick == -1

    def test_find_ore_buffer_resets_after_successful_click(self):
        """_approach_idle_since_tick returns to -1 after the click fires so the next ore uses a fresh buffer."""
        game = self._idle_game(tick=1)
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        r = _routine()
        r.find_ore(game, ctrl)  # tick 1: buffer start
        game.tick = 2
        r.find_ore(game, ctrl)  # tick 2: click
        assert r._approach_idle_since_tick == -1


# ---------------------------------------------------------------------------
# Occlusion guard — don't click entities hidden behind UI panels (minimap,
# inventory, prayer orbs, etc.)
# ---------------------------------------------------------------------------

# groupId 149 = inventory — a real, separate occluding panel (see
# state/interfaces.py). The toplevel viewport container (161) is excluded
# from occlusion checks, so fixtures must use an actual panel group here.
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

ORE_ON_SCREEN = {
    "id": 440,
    "name": "Iron rocks",
    "worldX": 3221,
    "worldY": 3219,
    "plane": 0,
    "onScreen": True,
    "canvasX": 600,   # inside OCCLUDING_PANEL bounds
    "canvasY": 50,
    "hull": [[585, 35], [615, 35], [615, 65], [585, 65]],
}

ORE_ON_SCREEN_CLEAR = {**ORE_ON_SCREEN, "canvasX": 300, "canvasY": 300}  # outside the panel

MINE_CART_OCCLUDED = {**MINE_CART, "canvasX": 600, "canvasY": 50}


class TestOcclusionGuard:
    def _game_with_panel(self, objects: list, tick: int = 2) -> GameState:
        game = GameState()
        game.tick = tick
        game.player = {"worldX": 3220, "worldY": 3218, "plane": 0, "animation": -1}
        game.inventory = [{"slot": i, "itemId": -1, "qty": 0} for i in range(28)]
        game.objects = objects
        game.camera = {"yaw": 0, "pitch": 256}
        game.interfaces = [OCCLUDING_PANEL]
        return game

    def test_find_ore_does_not_click_when_occluded(self):
        """An on-screen ore hidden behind the minimap must not be clicked."""
        game = self._game_with_panel([ORE_ON_SCREEN])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        result = _routine().find_ore(game, ctrl)

        ctrl.click_entity.assert_not_called()
        assert result is None

    def test_find_ore_adjusts_camera_when_occluded(self):
        """Occlusion triggers an explicit camera nudge to clear the entity —
        `bring_entity_on_screen` is a no-op once `onScreen` is already true,
        so a real rotation (`rotate_camera`) is what actually moves it."""
        game = self._game_with_panel([ORE_ON_SCREEN])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        _routine().find_ore(game, ctrl)

        ctrl.rotate_camera.assert_called_once_with(Key.RIGHT, OCCLUSION_NUDGE_YAW)

    def test_find_ore_resets_idle_buffer_when_occluded(self):
        """Occlusion must reset the settle buffer like any other camera disruption."""
        game = self._game_with_panel([ORE_ON_SCREEN])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        r = _routine()
        r._approach_idle_since_tick = 1
        r.find_ore(game, ctrl)
        assert r._approach_idle_since_tick == -1

    def test_find_ore_clicks_when_on_screen_and_clear(self):
        """Sanity check: an on-screen ore outside any UI panel is still clickable."""
        game = self._game_with_panel([ORE_ON_SCREEN_CLEAR])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        r = _routine()
        r.find_ore(game, ctrl)             # tick 1 (settle buffer starts)
        game.tick += 1
        result = r.find_ore(game, ctrl)    # tick 2: settle complete — click fires

        ctrl.click_entity.assert_called_once_with(ORE_ON_SCREEN_CLEAR)
        assert result == "mining"

    def test_walk_to_bank_does_not_click_when_occluded(self):
        """An on-screen bank object hidden behind a UI panel must not be clicked."""
        game = self._game_with_panel([MINE_CART_OCCLUDED], tick=1)
        game.player = {"worldX": 3200, "worldY": 3200, "plane": 0, "animation": -1}
        game.inventory = [{"slot": i, "itemId": 440, "qty": 1} for i in range(28)]
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        result = _routine().walk_to_bank(game, ctrl)

        ctrl.click_entity.assert_not_called()
        assert result is None

    def test_deposit_does_not_click_mine_cart_when_occluded(self):
        """The deposit state must not click the Mine cart while it's hidden behind UI."""
        ctrl = _ctrl()
        game = self._game_with_panel([MINE_CART_OCCLUDED], tick=100)
        game.inventory = [{"slot": i, "itemId": 440, "qty": 1} for i in range(28)]
        game.widgets = []

        _routine().deposit(game, ctrl)

        ctrl.click_entity.assert_not_called()


# ---------------------------------------------------------------------------
# Live clickbox subscriptions — find_ore/walk_to_bank/deposit subscribe for
# fresh hull updates on the entity they're about to click
# ---------------------------------------------------------------------------

class TestLiveHullSubscriptions:
    def test_find_ore_subscribes_to_ore_before_clicking(self):
        game = GameState()
        game.tick = 1
        game.player = {"worldX": 3220, "worldY": 3218, "plane": 0, "animation": -1}
        game.inventory = [{"slot": i, "itemId": -1, "qty": 0} for i in range(28)]
        game.objects = [ORE_OFF_SCREEN]
        game.camera = {"yaw": 0, "pitch": 256}

        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        r = _routine()
        r.find_ore(game, ctrl)  # tick 1: settle buffer starts
        game.tick = 2
        r.find_ore(game, ctrl)  # tick 2: clicks

        ctrl.subscribe_to.assert_called_once_with(
            InteractionRoutine.LIVE_HULL_SUB_ID, "object",
            name=ORE_OFF_SCREEN["name"], id=ORE_OFF_SCREEN["id"],
        )

    def test_walk_to_bank_subscribes_to_mine_cart_before_clicking(self):
        game = _make_game(
            tick=1,
            inventory_full=True,
            player_x=3200,
            player_y=3200,
            objects=[MINE_CART_OFF_SCREEN],
        )
        game.camera = {"yaw": 0, "pitch": 256}

        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        r = _routine()
        r.walk_to_bank(game, ctrl)  # tick 1: settle buffer starts
        game.tick = 2
        r.walk_to_bank(game, ctrl)  # tick 2: clicks

        ctrl.subscribe_to.assert_called_once_with(
            InteractionRoutine.LIVE_HULL_SUB_ID, "object",
            name=MINE_CART_OFF_SCREEN["name"], id=MINE_CART_OFF_SCREEN["id"],
        )

    def test_deposit_subscribes_to_mine_cart_before_opening_ui(self):
        ctrl = _ctrl()
        _routine().deposit(_make_game(tick=100, widgets=[]), ctrl)

        ctrl.subscribe_to.assert_called_once_with(
            InteractionRoutine.LIVE_HULL_SUB_ID, "object",
            name=MINE_CART["name"], id=MINE_CART["id"],
        )
