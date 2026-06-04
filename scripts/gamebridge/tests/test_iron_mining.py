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
from scripts.gamebridge.state.game_state import GameState
from scripts.gamebridge.ui.widgets import BankDepositBox


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
