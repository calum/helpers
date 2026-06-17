"""
Tests for SmithingHelmsRoutine.

Coverage:
  banking —
    * has bars, no helms, bank closed  → walk_to_anvil immediately
    * has bars, no helms, bank open    → Esc then walk_to_anvil
    * bank closed                      → approach booth two ticks then click
    * bank closed, booth just clicked  → grace period, no re-click
    * bank open, has helms             → click deposit button (throttled)
    * bank open, no helms, no bars     → click bar slot (throttled)
    * bar slot missing from bank       → warning, stay
    * deposit button missing           → no click
    * booth not in scene               → warning, stay

  walk_to_anvil —
    * near anvil   → smith
    * far           → approach two ticks then click
    * anvil not in scene → warning, stay
    * bring_entity_on_screen False → no click

  smith —
    * G312 open with Bronze full helm  → click_widget + smithing
    * G312 open, helm not found        → stay (wait one tick)
    * G312 not open, anvil not clicked → approach settle then click
    * anvil already clicked, within timeout → stay
    * anvil clicked, past timeout      → reset and retry approach
    * anvil not in scene               → walk_to_anvil
    * click_live returns False         → _anvil_clicked stays False

  smithing —
    * bars gone, player idle           → banking
    * bars gone, player animating      → stay
    * bars remain, animating           → stay
    * bars remain, idle, past grace    → smith
    * bars remain, idle, within grace  → stay
    * _smith_start_tick is None        → stay (edge case)

Design note: InteractionRoutine.click_live() calls ctrl.click_entity() internally;
tests assert on ctrl.click_entity, not ctrl.click_live.
approach() requires the entity on-screen AND two consecutive idle ticks; tests that
need a click to fire must call the state function twice with incrementing game.tick.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scripts.gamebridge.input.keyboard import Key
from scripts.gamebridge.routines.examples.smithing_helms import SmithingHelmsRoutine
from scripts.gamebridge.state.game_state import GameState
from scripts.gamebridge.widget_ids import Bankmain, Smithing


# ---------------------------------------------------------------------------
# Constants mirroring the routine
# ---------------------------------------------------------------------------

BRONZE_BAR_ID  = SmithingHelmsRoutine.BRONZE_BAR_ID   # 2349
BRONZE_HELM_ID = SmithingHelmsRoutine.BRONZE_HELM_ID  # 1155


# ---------------------------------------------------------------------------
# Entity fixtures
# ---------------------------------------------------------------------------

ANVIL = {
    "id": 2097,
    "name": "Anvil",
    "worldX": 2983, "worldY": 3339, "plane": 0,
    "onScreen": True,
    "canvasX": 340, "canvasY": 260,
    "hull": [[330, 250], [350, 250], [350, 270], [330, 270]],
    "minimapX": 625, "minimapY": 88,
}

BANK_BOOTH = {
    "id": 24101,
    "name": "Bank booth",
    "worldX": 2947, "worldY": 3367, "plane": 0,
    "onScreen": True,
    "canvasX": 250, "canvasY": 190,
    "hull": [[240, 180], [260, 180], [260, 200], [240, 200]],
    "minimapX": 600, "minimapY": 83,
}

# Bankmain deposit-inventory button widget (childId = Bankmain.DEPOSITINV[1] = 48 = 0x30)
DEPOSIT_BTN = {
    "groupId": Bankmain.GROUP,
    "childId": Bankmain.DEPOSITINV[1],
    "itemId": -1, "quantity": 0,
    "bounds": {"x": 347, "y": 301, "width": 29, "height": 22},
    "text": "",
}

# Bankmain Bronze bar slot widget
BAR_SLOT = {
    "groupId": Bankmain.GROUP,
    "childId": 10,
    "itemId": BRONZE_BAR_ID, "quantity": 100,
    "bounds": {"x": 361, "y": 155, "width": 36, "height": 32},
    "text": "",
}

# G312 Bronze full helm slot
HELM_SLOT = {
    "groupId": Smithing.GROUP,
    "childId": 1,
    "itemId": BRONZE_HELM_ID, "quantity": 1,
    "bounds": {"x": 255, "y": 104, "width": 36, "height": 32},
    "text": "",
}


# ---------------------------------------------------------------------------
# Inventory presets
# ---------------------------------------------------------------------------

_INV_EMPTY   = [{"slot": i, "itemId": -1,              "qty": 0} for i in range(28)]
_INV_ONE_BAR = ([{"slot": 0, "itemId": BRONZE_BAR_ID, "qty": 1}] +
                [{"slot": i, "itemId": -1,             "qty": 0} for i in range(1, 28)])
_INV_BARS    = ([{"slot": i, "itemId": BRONZE_BAR_ID, "qty": 1} for i in range(14)] +
                [{"slot": i, "itemId": -1,             "qty": 0} for i in range(14, 28)])
_INV_HELMS   = ([{"slot": i, "itemId": BRONZE_HELM_ID, "qty": 1} for i in range(13)] +
              [{"slot": i, "itemId": -1,              "qty": 0} for i in range(13, 28)])


# ---------------------------------------------------------------------------
# Interface root widgets (make is_interface_open return True)
# ---------------------------------------------------------------------------

_BANK_IFACE_ROOT = {
    "groupId": 12, "childId": 0,
    "itemId": -1, "quantity": 0,
    "bounds": {"x": 4, "y": 4, "width": 512, "height": 334},
    "text": "",
}

_SMITH_IFACE_ROOT = {
    "groupId": Smithing.GROUP, "childId": 0,
    "itemId": -1, "quantity": 0,
    "bounds": {"x": 10, "y": 11, "width": 500, "height": 320},
    "text": "",
}


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _make_game(
    tick: int = 100,
    player_x: int = 2947,
    player_y: int = 3368,
    inventory: list | None = None,
    objects: list | None = None,
    interfaces: list | None = None,
    animating: bool = False,
) -> GameState:
    game = GameState()
    game.tick   = tick
    game.player = {
        "worldX": player_x, "worldY": player_y, "plane": 0,
        "animation": 898 if animating else -1,
    }
    game.inventory  = inventory  if inventory  is not None else list(_INV_EMPTY)
    game.objects    = objects    if objects    is not None else [ANVIL, BANK_BOOTH]
    game.interfaces = interfaces if interfaces is not None else []
    game.camera     = {"yaw": 0, "pitch": 362}
    return game


class _AnyTooltip(str):
    def __contains__(self, item): return True
    def lower(self): return self

_ANY = _AnyTooltip()


def _ctrl() -> MagicMock:
    ctrl = MagicMock()
    ctrl.tooltip.return_value = _ANY
    ctrl.bring_entity_on_screen.return_value = True
    ctrl.hull_update.return_value = None
    return ctrl


def _routine() -> SmithingHelmsRoutine:
    return SmithingHelmsRoutine()


# ---------------------------------------------------------------------------
# banking — open bank
# ---------------------------------------------------------------------------

class TestBankingOpenBank:
    def test_no_click_on_first_approach_tick(self):
        """approach() blocks the click on the first idle tick (settle buffer)."""
        game = _make_game(tick=100)
        ctrl = _ctrl()
        _routine().banking(game, ctrl)
        ctrl.click_entity.assert_not_called()

    def test_clicks_bank_booth_on_second_approach_tick(self):
        game = _make_game(tick=100)
        ctrl = _ctrl()
        r = _routine()
        r.banking(game, ctrl)       # tick 100: settle
        game.tick = 101
        r.banking(game, ctrl)       # tick 101: click
        ctrl.click_entity.assert_called_once()

    def test_records_bank_clicked_tick_after_click(self):
        game = _make_game(tick=100)
        ctrl = _ctrl()
        r = _routine()
        r.banking(game, ctrl)
        game.tick = 101
        r.banking(game, ctrl)
        assert r._bank_clicked_tick == 101

    def test_grace_period_prevents_re_click(self):
        r = _routine()
        r._bank_clicked_tick = 50
        ctrl = _ctrl()
        for delta in (1, 2, 3):
            r.banking(_make_game(tick=50 + delta), ctrl)
        ctrl.click_entity.assert_not_called()

    def test_retries_after_grace_period(self):
        grace = SmithingHelmsRoutine.BANK_OPEN_GRACE_TICKS
        r = _routine()
        r._bank_clicked_tick = 50
        ctrl = _ctrl()
        r.banking(_make_game(tick=50 + grace), ctrl)      # settle
        r.banking(_make_game(tick=50 + grace + 1), ctrl)  # click
        ctrl.click_entity.assert_called_once()

    def test_no_bank_booth_logs_warning(self, caplog):
        game = _make_game(objects=[ANVIL])
        with caplog.at_level("WARNING"):
            result = _routine().banking(game, _ctrl())
        assert result is None
        assert "bank" in caplog.text.lower()

    def test_off_screen_blocks_click(self):
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = False
        r = _routine()
        r.banking(_make_game(tick=100), ctrl)
        r.banking(_make_game(tick=101), ctrl)
        ctrl.click_entity.assert_not_called()


# ---------------------------------------------------------------------------
# banking — deposit helms
# ---------------------------------------------------------------------------

class TestBankingDeposit:
    def _game_with_helms(self, tick=100):
        return _make_game(
            tick=tick,
            inventory=list(_INV_HELMS),
            interfaces=[_BANK_IFACE_ROOT, DEPOSIT_BTN],
        )

    def test_clicks_deposit_when_helms_present(self):
        ctrl = _ctrl()
        _routine().banking(self._game_with_helms(), ctrl)
        ctrl.click_widget.assert_called_once_with(DEPOSIT_BTN)

    def test_deposit_throttled_within_8_ticks(self):
        r = _routine()
        ctrl = _ctrl()
        r.banking(self._game_with_helms(tick=100), ctrl)
        ctrl.reset_mock()
        for delta in (1, 4, 7):
            r.banking(self._game_with_helms(tick=100 + delta), ctrl)
        ctrl.click_widget.assert_not_called()

    def test_deposit_allowed_at_8_ticks(self):
        r = _routine()
        ctrl = _ctrl()
        r.banking(self._game_with_helms(tick=100), ctrl)
        ctrl.reset_mock()
        r.banking(self._game_with_helms(tick=108), ctrl)
        ctrl.click_widget.assert_called_once()

    def test_returns_none_while_depositing(self):
        assert _routine().banking(self._game_with_helms(), _ctrl()) is None

    def test_no_deposit_btn_does_not_click(self):
        game = _make_game(inventory=list(_INV_HELMS), interfaces=[_BANK_IFACE_ROOT])
        ctrl = _ctrl()
        _routine().banking(game, ctrl)
        ctrl.click_widget.assert_not_called()


# ---------------------------------------------------------------------------
# banking — withdraw bars
# ---------------------------------------------------------------------------

class TestBankingWithdrawBars:
    def _bank_ifaces(self, has_bar_slot=True):
        ifaces = [_BANK_IFACE_ROOT]
        if has_bar_slot:
            ifaces.append(BAR_SLOT)
        return ifaces

    def test_withdraws_bars_when_none_in_inventory(self):
        game = _make_game(inventory=list(_INV_EMPTY), interfaces=self._bank_ifaces())
        ctrl = _ctrl()
        _routine().banking(game, ctrl)
        ctrl.click_widget.assert_called_once_with(BAR_SLOT)

    def test_withdraw_throttled(self):
        r = _routine()
        ctrl = _ctrl()
        game = _make_game(tick=100, inventory=list(_INV_EMPTY), interfaces=self._bank_ifaces())
        r.banking(game, ctrl)
        ctrl.reset_mock()
        for delta in (1, 2, 3):
            r.banking(_make_game(tick=100 + delta, inventory=list(_INV_EMPTY),
                                 interfaces=self._bank_ifaces()), ctrl)
        ctrl.click_widget.assert_not_called()

    def test_withdraw_allowed_after_throttle(self):
        throttle = SmithingHelmsRoutine.WITHDRAW_THROTTLE_TICKS
        r = _routine()
        ctrl = _ctrl()
        game = _make_game(tick=100, inventory=list(_INV_EMPTY), interfaces=self._bank_ifaces())
        r.banking(game, ctrl)
        ctrl.reset_mock()
        r.banking(_make_game(tick=100 + throttle, inventory=list(_INV_EMPTY),
                             interfaces=self._bank_ifaces()), ctrl)
        ctrl.click_widget.assert_called_once()

    def test_no_bar_slot_logs_warning(self, caplog):
        game = _make_game(inventory=list(_INV_EMPTY), interfaces=self._bank_ifaces(False))
        with caplog.at_level("WARNING"):
            result = _routine().banking(game, _ctrl())
        assert result is None
        assert "bronze bar" in caplog.text.lower()

    def test_returns_none_while_withdrawing(self):
        game = _make_game(inventory=list(_INV_EMPTY), interfaces=self._bank_ifaces())
        assert _routine().banking(game, _ctrl()) is None


# ---------------------------------------------------------------------------
# banking — close bank and walk to anvil
# ---------------------------------------------------------------------------

class TestBankingCloseAndWalk:
    def test_transitions_with_esc_when_bars_ready_bank_open(self):
        game = _make_game(inventory=list(_INV_BARS), interfaces=[_BANK_IFACE_ROOT])
        ctrl = _ctrl()
        result = _routine().banking(game, ctrl)
        ctrl.press_key.assert_called_once_with(Key.ESCAPE)
        assert result == "walk_to_anvil"

    def test_transitions_without_esc_when_bank_closed(self):
        game = _make_game(inventory=list(_INV_BARS))
        ctrl = _ctrl()
        result = _routine().banking(game, ctrl)
        ctrl.press_key.assert_not_called()
        assert result == "walk_to_anvil"

    def test_does_not_transition_when_bars_and_helms_both_present(self):
        """Having bars AND helms means the deposit hasn't cleared — deposit first."""
        mixed = (
            [{"slot": i, "itemId": BRONZE_BAR_ID,  "qty": 1} for i in range(14)] +
            [{"slot": i, "itemId": BRONZE_HELM_ID, "qty": 1} for i in range(14, 18)] +
            [{"slot": i, "itemId": -1,             "qty": 0} for i in range(18, 28)]
        )
        game = _make_game(inventory=mixed, interfaces=[_BANK_IFACE_ROOT, DEPOSIT_BTN])
        ctrl = _ctrl()
        result = _routine().banking(game, ctrl)
        assert result is None
        ctrl.click_widget.assert_called_once_with(DEPOSIT_BTN)

    def test_does_not_transition_with_only_one_bar(self):
        """One bar is not enough to make a helm (needs 2) — treat it as no bars."""
        game = _make_game(inventory=list(_INV_ONE_BAR), interfaces=[_BANK_IFACE_ROOT, BAR_SLOT])
        ctrl = _ctrl()
        result = _routine().banking(game, ctrl)
        assert result is None
        ctrl.click_widget.assert_called_once_with(BAR_SLOT)


# ---------------------------------------------------------------------------
# walk_to_anvil
# ---------------------------------------------------------------------------

class TestWalkToAnvil:
    def test_transitions_to_smith_when_near_anvil(self):
        # Manhattan distance: |2983-2982| + |3339-3339| = 1 <= ANVIL_NEAR_TILES(2)
        game = _make_game(player_x=2982, player_y=3339)
        assert _routine().walk_to_anvil(game, _ctrl()) == "smith"

    def test_no_click_on_first_approach_tick_when_far(self):
        game = _make_game(tick=100, player_x=2947, player_y=3368)
        ctrl = _ctrl()
        _routine().walk_to_anvil(game, ctrl)
        ctrl.click_entity.assert_not_called()

    def test_clicks_anvil_on_second_approach_tick(self):
        game = _make_game(tick=100, player_x=2947, player_y=3368)
        ctrl = _ctrl()
        r = _routine()
        r.walk_to_anvil(game, ctrl)     # tick 100: settle
        game.tick = 101
        r.walk_to_anvil(game, ctrl)     # tick 101: click
        ctrl.click_entity.assert_called_once()

    def test_returns_none_when_far(self):
        game = _make_game(player_x=2947, player_y=3368)
        assert _routine().walk_to_anvil(game, _ctrl()) is None

    def test_returns_none_when_anvil_not_in_scene(self, caplog):
        game = _make_game(objects=[BANK_BOOTH])
        with caplog.at_level("WARNING"):
            result = _routine().walk_to_anvil(game, _ctrl())
        assert result is None
        assert "anvil" in caplog.text.lower()

    def test_off_screen_blocks_click(self):
        game = _make_game(tick=100, player_x=2947, player_y=3368)
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = False
        _routine().walk_to_anvil(game, ctrl)
        ctrl.click_entity.assert_not_called()


# ---------------------------------------------------------------------------
# smith
# ---------------------------------------------------------------------------

class TestSmith:
    def _game_at_anvil(self, tick=100, interfaces=None):
        return _make_game(
            tick=tick,
            player_x=2982, player_y=3339,  # adjacent to anvil: distance 1
            inventory=list(_INV_BARS),
            interfaces=interfaces or [],
        )

    def test_clicks_helm_widget_when_dialog_open(self):
        game = self._game_at_anvil(interfaces=[_SMITH_IFACE_ROOT, HELM_SLOT])
        ctrl = _ctrl()
        result = _routine().smith(game, ctrl)
        ctrl.click_widget.assert_called_once_with(HELM_SLOT)
        assert result == "smithing"

    def test_dialog_click_fires_in_one_tick_no_approach_needed(self):
        """Dialog check short-circuits before approach(); no settle tick needed."""
        game = self._game_at_anvil(tick=100, interfaces=[_SMITH_IFACE_ROOT, HELM_SLOT])
        ctrl = _ctrl()
        r = _routine()
        result = r.smith(game, ctrl)
        ctrl.click_widget.assert_called_once_with(HELM_SLOT)
        assert result == "smithing"

    def test_records_smith_start_tick_on_dialog_click(self):
        game = self._game_at_anvil(tick=77, interfaces=[_SMITH_IFACE_ROOT, HELM_SLOT])
        r = _routine()
        r.smith(game, _ctrl())
        assert r._smith_start_tick == 77

    def test_resets_anvil_clicked_after_dialog_click(self):
        game = self._game_at_anvil(interfaces=[_SMITH_IFACE_ROOT, HELM_SLOT])
        r = _routine()
        r._anvil_clicked = True
        r.smith(game, _ctrl())
        assert r._anvil_clicked is False

    def test_stays_when_dialog_open_but_helm_not_found(self):
        """Dialog root present but no Bronze full helm widget — wait one tick."""
        other_item = {**HELM_SLOT, "itemId": 1205}  # e.g. Bronze med helm
        game = self._game_at_anvil(interfaces=[_SMITH_IFACE_ROOT, other_item])
        ctrl = _ctrl()
        result = _routine().smith(game, ctrl)
        ctrl.click_widget.assert_not_called()
        assert result is None

    def test_no_click_on_first_approach_tick_without_dialog(self):
        """Without dialog, approach settle buffer prevents clicking anvil immediately."""
        game = self._game_at_anvil(tick=100)
        ctrl = _ctrl()
        _routine().smith(game, ctrl)
        ctrl.click_entity.assert_not_called()

    def test_clicks_anvil_after_settle_when_no_dialog(self):
        game = self._game_at_anvil(tick=100)
        ctrl = _ctrl()
        r = _routine()
        r.smith(game, ctrl)     # tick 100: settle
        game.tick = 101
        r.smith(game, ctrl)     # tick 101: click
        ctrl.click_entity.assert_called_once()

    def test_sets_anvil_clicked_after_click_lands(self):
        game = self._game_at_anvil(tick=100)
        ctrl = _ctrl()
        r = _routine()
        r.smith(game, ctrl)     # settle
        game.tick = 101
        r.smith(game, ctrl)     # click lands (MagicMock truthy default)
        assert r._anvil_clicked is True

    def test_does_not_set_anvil_clicked_when_click_misses(self):
        game = self._game_at_anvil(tick=100)
        ctrl = _ctrl()
        ctrl.click_entity.return_value = False
        r = _routine()
        r.smith(game, ctrl)     # settle
        game.tick = 101
        r.smith(game, ctrl)     # click miss
        assert r._anvil_clicked is False

    def test_stays_after_anvil_clicked_within_timeout(self):
        r = _routine()
        r._anvil_clicked = True
        r._anvil_clicked_tick = 50
        timeout = SmithingHelmsRoutine.ANVIL_DIALOG_TIMEOUT_TICKS
        ctrl = _ctrl()
        result = r.smith(_make_game(tick=50 + timeout - 1), ctrl)
        ctrl.click_entity.assert_not_called()
        assert result is None

    def test_resets_anvil_clicked_after_timeout(self):
        r = _routine()
        r._anvil_clicked = True
        r._anvil_clicked_tick = 50
        timeout = SmithingHelmsRoutine.ANVIL_DIALOG_TIMEOUT_TICKS
        r.smith(_make_game(tick=50 + timeout), _ctrl())
        assert r._anvil_clicked is False

    def test_returns_walk_to_anvil_when_anvil_missing(self, caplog):
        game = _make_game(objects=[BANK_BOOTH])
        with caplog.at_level("WARNING"):
            result = _routine().smith(game, _ctrl())
        assert result == "walk_to_anvil"


# ---------------------------------------------------------------------------
# smithing
# ---------------------------------------------------------------------------

class TestSmithing:
    def _game(self, tick=100, inventory=None, animating=False):
        return _make_game(tick=tick, inventory=inventory, animating=animating)

    def test_transitions_to_banking_when_bars_gone_and_idle(self):
        r = _routine()
        r._smith_start_tick = 80
        game = self._game(tick=100, inventory=list(_INV_EMPTY), animating=False)
        assert r.smithing(game, _ctrl()) == "banking"

    def test_stays_when_bars_gone_but_animating(self):
        r = _routine()
        r._smith_start_tick = 80
        game = self._game(tick=100, inventory=list(_INV_EMPTY), animating=True)
        assert r.smithing(game, _ctrl()) is None

    def test_stays_while_smithing_in_progress(self):
        r = _routine()
        r._smith_start_tick = 98
        game = self._game(tick=100, inventory=list(_INV_BARS), animating=True)
        assert r.smithing(game, _ctrl()) is None

    def test_retries_smith_when_idle_with_bars_past_grace(self):
        grace = SmithingHelmsRoutine.SMITH_GRACE_TICKS
        r = _routine()
        r._smith_start_tick = 100
        game = self._game(tick=100 + grace, inventory=list(_INV_BARS), animating=False)
        assert r.smithing(game, _ctrl()) == "smith"

    def test_stays_within_grace_period_even_if_idle(self):
        grace = SmithingHelmsRoutine.SMITH_GRACE_TICKS
        r = _routine()
        r._smith_start_tick = 100
        game = self._game(tick=100 + grace - 1, inventory=list(_INV_BARS), animating=False)
        assert r.smithing(game, _ctrl()) is None

    def test_stays_when_bars_remain_and_animating_past_grace(self):
        grace = SmithingHelmsRoutine.SMITH_GRACE_TICKS
        r = _routine()
        r._smith_start_tick = 100
        game = self._game(tick=100 + grace + 10, inventory=list(_INV_BARS), animating=True)
        assert r.smithing(game, _ctrl()) is None

    def test_transitions_to_banking_with_one_bar_remaining(self):
        """One leftover bar (< BARS_PER_HELM) is treated as batch complete."""
        r = _routine()
        r._smith_start_tick = 80
        game = self._game(tick=100, inventory=list(_INV_ONE_BAR), animating=False)
        assert r.smithing(game, _ctrl()) == "banking"

    def test_stays_when_smith_start_tick_not_set(self):
        """If _smith_start_tick is None, idle-with-bars is ignored (can't happen normally)."""
        r = _routine()
        r._smith_start_tick = None
        game = self._game(tick=200, inventory=list(_INV_BARS), animating=False)
        assert r.smithing(game, _ctrl()) is None
