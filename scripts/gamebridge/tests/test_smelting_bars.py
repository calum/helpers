"""
Tests for SmeltingBarsRoutine.

Coverage:
  banking  — several scenarios:
    * has ores already, bank closed → walk_to_furnace immediately
    * has ores, bank open → Esc then walk_to_furnace
    * bank closed → approach booth two ticks then click to open it
    * bank closed, booth just clicked → grace period, no re-click
    * bank open, has bars → click deposit button (throttled)
    * bank open, no bars, no tin → click tin ore slot
    * bank open, has tin, no copper → click copper ore slot
    * bank open, has both ores, bank somehow open → Esc and walk_to_furnace
    * bank open, tin missing from bank → warning, stay
    * bank open, copper missing from bank → warning, stay

  walk_to_furnace —
    * near furnace → smelt
    * far from furnace → approach two ticks then click
    * furnace not in scene → warning, stay
    * bring_entity_on_screen returns False → no click

  smelt —
    * G270 dialog open with bronze bar → Space → smelting (no approach needed)
    * G270 dialog with wrong itemId → click furnace after 2-tick settle
    * G270 dialog not open, furnace not clicked → click furnace after settle
    * furnace already clicked → stay (wait for dialog)
    * furnace not in scene → walk_to_furnace
    * click_entity returns False → _furnace_clicked stays False

  smelting —
    * ores gone, player idle → banking
    * ores gone, player animating → stay
    * ores remain, player idle, past grace → smelt
    * ores remain, player idle, within grace → stay
    * ores remain, player animating → stay

Design note: InteractionRoutine.click_live() calls ctrl.click_entity() internally;
tests assert on ctrl.click_entity, not ctrl.click_live.
approach() requires the entity on-screen AND two consecutive idle ticks; tests that
need a click to fire must call the state function twice with incrementing game.tick.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from scripts.gamebridge.input.keyboard import Key
from scripts.gamebridge.routines.examples.smelting_bars import SmeltingBarsRoutine
from scripts.gamebridge.routines.interaction import InteractionRoutine
from scripts.gamebridge.state.game_state import GameState
from scripts.gamebridge.widget_ids import Bankmain


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TIN_ORE_ID    = SmeltingBarsRoutine.TIN_ORE_ID     # 438
COPPER_ORE_ID = SmeltingBarsRoutine.COPPER_ORE_ID  # 436
BRONZE_BAR_ID = SmeltingBarsRoutine.BRONZE_BAR_ID  # 2349

FURNACE = {
    "id": 24009,
    "name": "Furnace",
    "worldX": 2976, "worldY": 3369, "plane": 0,
    "onScreen": True,
    "canvasX": 350, "canvasY": 250,
    "hull": [[340, 240], [360, 240], [360, 260], [340, 260]],
    "minimapX": 630, "minimapY": 85,
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

DEPOSIT_BTN = {
    "groupId": Bankmain.GROUP,
    "childId": Bankmain.DEPOSITINV[1],  # 41
    "itemId": -1, "quantity": 0,
    "bounds": {"x": 347, "y": 301, "width": 29, "height": 22},
    "text": "",
}

TIN_SLOT = {
    "groupId": Bankmain.GROUP,
    "childId": 32,
    "itemId": TIN_ORE_ID, "quantity": 14,
    "bounds": {"x": 361, "y": 155, "width": 36, "height": 32},
    "text": "",
}

COPPER_SLOT = {
    "groupId": Bankmain.GROUP,
    "childId": 33,
    "itemId": COPPER_ORE_ID, "quantity": 14,
    "bounds": {"x": 409, "y": 155, "width": 36, "height": 32},
    "text": "",
}

# G270:38 — Skillmulti item slot with Bronze bar
SMELT_DIALOG_WIDGET = {
    "groupId": 270,
    "childId": 38,
    "itemId": BRONZE_BAR_ID, "quantity": 0,
    "bounds": {"x": 227, "y": 396, "width": 65, "height": 65},
    "text": "",
}

_INV_EMPTY  = [{"slot": i, "itemId": -1,           "qty": 0} for i in range(28)]
_INV_BARS   = ([{"slot": i, "itemId": BRONZE_BAR_ID, "qty": 1} for i in range(14)] +
               [{"slot": i, "itemId": -1,             "qty": 0} for i in range(14, 28)])
_INV_TIN    = ([{"slot": i, "itemId": TIN_ORE_ID,    "qty": 1} for i in range(14)] +
               [{"slot": i, "itemId": -1,             "qty": 0} for i in range(14, 28)])
_INV_ORES   = ([{"slot": i, "itemId": TIN_ORE_ID,    "qty": 1} for i in range(14)] +
               [{"slot": i, "itemId": COPPER_ORE_ID,  "qty": 1} for i in range(14, 28)])

# G12 root widget — makes is_interface_open("bank") return True
_BANK_IFACE_ROOT = {
    "groupId": 12, "childId": 0,
    "itemId": -1, "quantity": 0,
    "bounds": {"x": 4, "y": 4, "width": 512, "height": 334},
    "text": "",
}


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
        "animation": 899 if animating else -1,
    }
    game.inventory  = inventory  if inventory  is not None else list(_INV_EMPTY)
    game.objects    = objects    if objects    is not None else [FURNACE, BANK_BOOTH]
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
    # click_entity returns a truthy value by default (MagicMock), which makes
    # click_live() return True. Override to False in tests that need a miss.
    ctrl.bring_entity_on_screen.return_value = True
    ctrl.hull_update.return_value = None
    return ctrl


def _routine() -> SmeltingBarsRoutine:
    return SmeltingBarsRoutine()


# ---------------------------------------------------------------------------
# banking — approach + click bank booth
# ---------------------------------------------------------------------------
# approach() needs two consecutive idle ticks before returning True.
# Tick N: _approach_idle_since_tick is set to N, returns False.
# Tick N+1: resets and returns True → caller can click.

class TestBankingOpenBank:
    def test_no_click_on_first_approach_tick(self):
        """approach() blocks the click on the first idle tick (settle buffer)."""
        game = _make_game(tick=100)
        ctrl = _ctrl()
        _routine().banking(game, ctrl)
        ctrl.click_entity.assert_not_called()

    def test_clicks_bank_booth_on_second_approach_tick(self):
        """After the settle buffer, click_live fires on the second tick."""
        game = _make_game(tick=100)
        ctrl = _ctrl()
        r = _routine()
        r.banking(game, ctrl)          # tick 100: settle
        game.tick = 101
        r.banking(game, ctrl)          # tick 101: click
        ctrl.click_entity.assert_called_once()

    def test_records_bank_clicked_tick_after_successful_click(self):
        game = _make_game(tick=100)
        ctrl = _ctrl()
        r = _routine()
        r.banking(game, ctrl)
        game.tick = 101
        r.banking(game, ctrl)
        assert r._bank_clicked_tick == 101

    def test_grace_period_prevents_re_click(self):
        """Once the booth has been clicked, don't click again for BANK_OPEN_GRACE_TICKS."""
        r = _routine()
        r._bank_clicked_tick = 50
        ctrl = _ctrl()
        for delta in (1, 2, 3):
            r.banking(_make_game(tick=50 + delta), ctrl)
        ctrl.click_entity.assert_not_called()

    def test_returns_none_while_in_grace_period(self):
        r = _routine()
        r._bank_clicked_tick = 50
        assert r.banking(_make_game(tick=51), _ctrl()) is None

    def test_retries_booth_click_after_grace_period(self):
        """After BANK_OPEN_GRACE_TICKS pass, approach and click again."""
        grace = SmeltingBarsRoutine.BANK_OPEN_GRACE_TICKS
        r = _routine()
        r._bank_clicked_tick = 50
        ctrl = _ctrl()
        r.banking(_make_game(tick=50 + grace), ctrl)      # settle tick
        r.banking(_make_game(tick=50 + grace + 1), ctrl)  # click tick
        ctrl.click_entity.assert_called_once()

    def test_no_bank_booth_in_scene_logs_warning(self, caplog):
        game = _make_game(objects=[FURNACE])  # no bank booth
        with caplog.at_level("WARNING"):
            result = _routine().banking(game, _ctrl())
        assert result is None
        assert "bank" in caplog.text.lower()

    def test_bring_entity_off_screen_blocks_click(self):
        """If bring_entity_on_screen returns False, click_entity must not fire."""
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = False
        r = _routine()
        r.banking(_make_game(tick=100), ctrl)
        r.banking(_make_game(tick=101), ctrl)
        ctrl.click_entity.assert_not_called()


# ---------------------------------------------------------------------------
# banking — deposit bars
# ---------------------------------------------------------------------------

class TestBankingDeposit:
    def _game_with_bars(self, tick=100):
        return _make_game(
            tick=tick,
            inventory=list(_INV_BARS),
            interfaces=[_BANK_IFACE_ROOT, DEPOSIT_BTN],
        )

    def test_clicks_deposit_when_bars_present(self):
        ctrl = _ctrl()
        _routine().banking(self._game_with_bars(), ctrl)
        ctrl.click_widget.assert_called_once_with(DEPOSIT_BTN)

    def test_deposit_throttled_within_8_ticks(self):
        r = _routine()
        ctrl = _ctrl()
        r.banking(self._game_with_bars(tick=100), ctrl)
        ctrl.reset_mock()
        for delta in (1, 4, 7):
            r.banking(self._game_with_bars(tick=100 + delta), ctrl)
        ctrl.click_widget.assert_not_called()

    def test_deposit_allowed_at_8_ticks(self):
        r = _routine()
        ctrl = _ctrl()
        r.banking(self._game_with_bars(tick=100), ctrl)
        ctrl.reset_mock()
        r.banking(self._game_with_bars(tick=108), ctrl)
        ctrl.click_widget.assert_called_once()

    def test_returns_none_while_depositing(self):
        assert _routine().banking(self._game_with_bars(), _ctrl()) is None

    def test_no_deposit_btn_does_not_click(self):
        game = _make_game(inventory=list(_INV_BARS), interfaces=[_BANK_IFACE_ROOT])
        ctrl = _ctrl()
        _routine().banking(game, ctrl)
        ctrl.click_widget.assert_not_called()


# ---------------------------------------------------------------------------
# banking — withdraw ores
# ---------------------------------------------------------------------------

class TestBankingWithdrawOres:
    def _bank_ifaces(self, tin=True, copper=True):
        ifaces = [_BANK_IFACE_ROOT]
        if tin:
            ifaces.append(TIN_SLOT)
        if copper:
            ifaces.append(COPPER_SLOT)
        return ifaces

    def test_withdraws_tin_when_no_tin_in_inventory(self):
        game = _make_game(inventory=list(_INV_EMPTY), interfaces=self._bank_ifaces())
        ctrl = _ctrl()
        _routine().banking(game, ctrl)
        ctrl.click_widget.assert_called_once_with(TIN_SLOT)

    def test_withdraw_tin_throttled(self):
        r = _routine()
        ctrl = _ctrl()
        game = _make_game(tick=100, inventory=list(_INV_EMPTY), interfaces=self._bank_ifaces())
        r.banking(game, ctrl)
        ctrl.reset_mock()
        for delta in (1, 2, 3):
            r.banking(_make_game(tick=100+delta, inventory=list(_INV_EMPTY),
                                 interfaces=self._bank_ifaces()), ctrl)
        ctrl.click_widget.assert_not_called()

    def test_withdraws_copper_when_no_copper_has_tin(self):
        game = _make_game(inventory=list(_INV_TIN), interfaces=self._bank_ifaces())
        ctrl = _ctrl()
        _routine().banking(game, ctrl)
        ctrl.click_widget.assert_called_once_with(COPPER_SLOT)

    def test_tin_before_copper_when_both_missing(self):
        """With no tin and no copper in inv, only the TIN slot should be clicked."""
        game = _make_game(inventory=list(_INV_EMPTY), interfaces=self._bank_ifaces())
        ctrl = _ctrl()
        r = _routine()
        r.banking(game, ctrl)
        assert ctrl.click_widget.call_args_list == [call(TIN_SLOT)]

    def test_no_tin_in_bank_logs_warning(self, caplog):
        game = _make_game(
            inventory=list(_INV_EMPTY),
            interfaces=self._bank_ifaces(tin=False),
        )
        with caplog.at_level("WARNING"):
            result = _routine().banking(game, _ctrl())
        assert result is None
        assert "tin" in caplog.text.lower()

    def test_no_copper_in_bank_logs_warning(self, caplog):
        game = _make_game(
            inventory=list(_INV_TIN),
            interfaces=self._bank_ifaces(copper=False),
        )
        with caplog.at_level("WARNING"):
            result = _routine().banking(game, _ctrl())
        assert result is None
        assert "copper" in caplog.text.lower()

    def test_returns_none_while_withdrawing(self):
        game = _make_game(inventory=list(_INV_EMPTY), interfaces=self._bank_ifaces())
        assert _routine().banking(game, _ctrl()) is None


# ---------------------------------------------------------------------------
# banking — close bank and walk to furnace
# ---------------------------------------------------------------------------

class TestBankingCloseAndWalk:
    def test_presses_esc_and_transitions_when_ores_ready_bank_open(self):
        game = _make_game(inventory=list(_INV_ORES), interfaces=[_BANK_IFACE_ROOT])
        ctrl = _ctrl()
        result = _routine().banking(game, ctrl)
        ctrl.press_key.assert_called_once_with(Key.ESCAPE)
        assert result == "walk_to_furnace"

    def test_transitions_without_esc_when_bank_closed(self):
        game = _make_game(inventory=list(_INV_ORES))  # no bank iface
        ctrl = _ctrl()
        result = _routine().banking(game, ctrl)
        ctrl.press_key.assert_not_called()
        assert result == "walk_to_furnace"

    def test_does_not_transition_when_ores_present_with_bars(self):
        """Having both ores AND bars means deposit hasn't cleared yet — deposit first."""
        mixed = (
            [{"slot": i, "itemId": TIN_ORE_ID,    "qty": 1} for i in range(7)] +
            [{"slot": i, "itemId": COPPER_ORE_ID,  "qty": 1} for i in range(7, 14)] +
            [{"slot": i, "itemId": BRONZE_BAR_ID,  "qty": 1} for i in range(14, 18)] +
            [{"slot": i, "itemId": -1,             "qty": 0} for i in range(18, 28)]
        )
        game = _make_game(inventory=mixed, interfaces=[_BANK_IFACE_ROOT, DEPOSIT_BTN])
        ctrl = _ctrl()
        result = _routine().banking(game, ctrl)
        assert result is None
        ctrl.click_widget.assert_called_once_with(DEPOSIT_BTN)


# ---------------------------------------------------------------------------
# walk_to_furnace
# ---------------------------------------------------------------------------

class TestWalkToFurnace:
    def test_transitions_to_smelt_when_near_furnace(self):
        # Manhattan distance: |2976-2975| + |3369-3369| = 1 <= FURNACE_NEAR_TILES(2)
        game = _make_game(player_x=2975, player_y=3369)
        assert _routine().walk_to_furnace(game, _ctrl()) == "smelt"

    def test_no_click_on_first_approach_tick_when_far(self):
        """approach() settle buffer: no click on the first idle tick."""
        game = _make_game(tick=100, player_x=2947, player_y=3368)
        ctrl = _ctrl()
        _routine().walk_to_furnace(game, ctrl)
        ctrl.click_entity.assert_not_called()

    def test_clicks_furnace_on_second_approach_tick(self):
        game = _make_game(tick=100, player_x=2947, player_y=3368)
        ctrl = _ctrl()
        r = _routine()
        r.walk_to_furnace(game, ctrl)          # tick 100: settle
        game.tick = 101
        r.walk_to_furnace(game, ctrl)          # tick 101: click
        ctrl.click_entity.assert_called_once()

    def test_returns_none_when_far_from_furnace(self):
        game = _make_game(player_x=2947, player_y=3368)
        assert _routine().walk_to_furnace(game, _ctrl()) is None

    def test_returns_none_when_furnace_not_in_scene(self, caplog):
        game = _make_game(objects=[BANK_BOOTH])
        with caplog.at_level("WARNING"):
            result = _routine().walk_to_furnace(game, _ctrl())
        assert result is None
        assert "furnace" in caplog.text.lower()

    def test_approach_gating_prevents_click_when_off_screen(self):
        """If bring_entity_on_screen returns False, click_entity must not be called."""
        game = _make_game(tick=100, player_x=2947, player_y=3368)
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = False
        _routine().walk_to_furnace(game, ctrl)
        ctrl.click_entity.assert_not_called()


# ---------------------------------------------------------------------------
# smelt
# ---------------------------------------------------------------------------

class TestSmelt:
    def _game_at_furnace(self, tick=100, interfaces=None):
        return _make_game(
            tick=tick,
            player_x=2975, player_y=3369,  # adjacent to furnace: distance 1
            inventory=list(_INV_ORES),
            interfaces=interfaces or [],
        )

    def test_presses_space_when_dialog_open(self):
        game = self._game_at_furnace(interfaces=[SMELT_DIALOG_WIDGET])
        ctrl = _ctrl()
        result = _routine().smelt(game, ctrl)
        ctrl.press_key.assert_called_once_with(Key.SPACE)
        assert result == "smelting"

    def test_space_fires_in_one_tick_no_approach_needed(self):
        """Dialog check is before approach(); pressing Space doesn't need two ticks."""
        game = self._game_at_furnace(tick=100, interfaces=[SMELT_DIALOG_WIDGET])
        ctrl = _ctrl()
        r = _routine()
        result = r.smelt(game, ctrl)  # single call — dialog check short-circuits
        ctrl.press_key.assert_called_once_with(Key.SPACE)
        assert result == "smelting"

    def test_records_smelt_start_tick_on_space(self):
        game = self._game_at_furnace(tick=55, interfaces=[SMELT_DIALOG_WIDGET])
        r = _routine()
        r.smelt(game, _ctrl())
        assert r._smelt_start_tick == 55

    def test_resets_furnace_clicked_on_space(self):
        game = self._game_at_furnace(interfaces=[SMELT_DIALOG_WIDGET])
        r = _routine()
        r._furnace_clicked = True
        r.smelt(game, _ctrl())
        assert r._furnace_clicked is False

    def test_ignores_dialog_with_wrong_item_id(self):
        """G270:38 with a different itemId must not trigger smelting."""
        wrong_item = {**SMELT_DIALOG_WIDGET, "itemId": 334}  # not a bronze bar
        game = self._game_at_furnace(tick=100, interfaces=[wrong_item])
        ctrl = _ctrl()
        r = _routine()
        r.smelt(game, ctrl)      # tick 100: settle (dialog check fails, approach settle)
        game.tick = 101
        r.smelt(game, ctrl)      # tick 101: click tick
        ctrl.press_key.assert_not_called()

    def test_no_click_on_first_approach_tick_without_dialog(self):
        """Without dialog, approach settle buffer prevents clicking immediately."""
        game = self._game_at_furnace(tick=100)
        ctrl = _ctrl()
        _routine().smelt(game, ctrl)
        ctrl.click_entity.assert_not_called()

    def test_clicks_furnace_after_settle_when_dialog_not_open(self):
        game = self._game_at_furnace(tick=100)
        ctrl = _ctrl()
        r = _routine()
        r.smelt(game, ctrl)          # tick 100: settle
        game.tick = 101
        r.smelt(game, ctrl)          # tick 101: click
        ctrl.click_entity.assert_called_once()

    def test_sets_furnace_clicked_after_click_lands(self):
        # click_entity returns a truthy MagicMock by default → click_live returns True
        game = self._game_at_furnace(tick=100)
        ctrl = _ctrl()
        r = _routine()
        r.smelt(game, ctrl)    # settle
        game.tick = 101
        r.smelt(game, ctrl)    # click lands
        assert r._furnace_clicked is True

    def test_does_not_set_furnace_clicked_when_click_misses(self):
        """If click_entity returns False the click didn't land — allow retry next tick."""
        game = self._game_at_furnace(tick=100)
        ctrl = _ctrl()
        ctrl.click_entity.return_value = False
        r = _routine()
        r.smelt(game, ctrl)    # settle
        game.tick = 101
        r.smelt(game, ctrl)    # click attempt that misses
        assert r._furnace_clicked is False

    def test_stays_after_furnace_clicked(self):
        """Once the furnace has been clicked, don't click again — wait for dialog."""
        r = _routine()
        r._furnace_clicked = True
        game = self._game_at_furnace(tick=100)
        ctrl = _ctrl()
        result = r.smelt(game, ctrl)
        ctrl.click_entity.assert_not_called()
        assert result is None

    def test_returns_walk_to_furnace_when_furnace_missing(self, caplog):
        game = _make_game(objects=[BANK_BOOTH])  # no furnace
        with caplog.at_level("WARNING"):
            result = _routine().smelt(game, _ctrl())
        assert result == "walk_to_furnace"


# ---------------------------------------------------------------------------
# smelting
# ---------------------------------------------------------------------------

class TestSmelting:
    def _game(self, tick=100, inventory=None, animating=False):
        return _make_game(tick=tick, inventory=inventory, animating=animating)

    def test_transitions_to_banking_when_ores_gone_and_idle(self):
        r = _routine()
        r._smelt_start_tick = 80
        game = self._game(tick=100, inventory=list(_INV_EMPTY), animating=False)
        assert r.smelting(game, _ctrl()) == "banking"

    def test_stays_when_ores_gone_but_animating(self):
        r = _routine()
        r._smelt_start_tick = 80
        game = self._game(tick=100, inventory=list(_INV_EMPTY), animating=True)
        assert r.smelting(game, _ctrl()) is None

    def test_stays_while_smelting_in_progress(self):
        r = _routine()
        r._smelt_start_tick = 98
        game = self._game(tick=100, inventory=list(_INV_ORES), animating=True)
        assert r.smelting(game, _ctrl()) is None

    def test_retries_smelt_when_idle_with_ores_past_grace(self):
        grace = SmeltingBarsRoutine.SMELT_GRACE_TICKS
        r = _routine()
        r._smelt_start_tick = 100
        game = self._game(tick=100 + grace, inventory=list(_INV_ORES), animating=False)
        assert r.smelting(game, _ctrl()) == "smelt"

    def test_stays_within_grace_period_even_if_idle(self):
        grace = SmeltingBarsRoutine.SMELT_GRACE_TICKS
        r = _routine()
        r._smelt_start_tick = 100
        game = self._game(tick=100 + grace - 1, inventory=list(_INV_ORES), animating=False)
        assert r.smelting(game, _ctrl()) is None

    def test_stays_when_ores_remain_and_animating_past_grace(self):
        grace = SmeltingBarsRoutine.SMELT_GRACE_TICKS
        r = _routine()
        r._smelt_start_tick = 100
        game = self._game(tick=100 + grace + 10, inventory=list(_INV_ORES), animating=True)
        assert r.smelting(game, _ctrl()) is None

    def test_stays_when_smelt_start_tick_not_set(self):
        """If _smelt_start_tick is None (shouldn't happen normally) idle-with-ores is ignored."""
        r = _routine()
        r._smelt_start_tick = None
        game = self._game(tick=200, inventory=list(_INV_ORES), animating=False)
        assert r.smelting(game, _ctrl()) is None
