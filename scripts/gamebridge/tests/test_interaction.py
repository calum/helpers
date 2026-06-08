"""
Tests for InteractionRoutine — the shared "approach" and "verified menu
click" helpers reused by routines that click on game entities (mining,
fighting, looting, banking).

These exercise the helpers directly, in isolation from any concrete
routine, with `game`/`ctrl` mocked — the same gating behaviour iron_mining
and melee_fighter relied on before being refactored to share it (see
test_iron_mining.py / test_melee_fighter.py for the integration-level
coverage of those routines using these helpers).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from scripts.gamebridge.input.keyboard import Key
from scripts.gamebridge.routines.base import initial_state
from scripts.gamebridge.routines.interaction import InteractionRoutine, MenuClick, OCCLUSION_NUDGE_YAW


class _DummyRoutine(InteractionRoutine):
    """Minimal concrete routine — InteractionRoutine has no states of its own."""

    @initial_state
    def idling(self, game, ctrl):
        return None


ENTITY = {
    "id": 1, "name": "Iron rocks", "worldX": 3221, "worldY": 3219,
    "onScreen": True, "canvasX": 400, "canvasY": 300,
}


def _game(tick: int = 1, idle: bool = True, occluded: bool = False) -> MagicMock:
    game = MagicMock()
    game.tick = tick
    game.player_idle.return_value = idle
    game.is_occluded.return_value = occluded
    return game


def _ctrl(on_screen: bool = True) -> MagicMock:
    ctrl = MagicMock()
    ctrl.bring_entity_on_screen.return_value = on_screen
    return ctrl


def _routine() -> _DummyRoutine:
    return _DummyRoutine()


# ---------------------------------------------------------------------------
# approach — camera / occlusion / idle gating, with a one-tick settle buffer
# ---------------------------------------------------------------------------

class TestApproachCamera:
    def test_not_ready_when_entity_not_on_screen(self):
        game, ctrl = _game(), _ctrl(on_screen=False)
        assert _routine().approach(game, ctrl, ENTITY) is False
        ctrl.bring_entity_on_screen.assert_called_once_with(ENTITY, game)

    def test_resets_buffer_when_camera_adjustment_needed(self):
        game, ctrl = _game(), _ctrl(on_screen=True)
        r = _routine()
        r._approach_idle_since_tick = 1
        ctrl.bring_entity_on_screen.return_value = False

        assert r.approach(game, ctrl, ENTITY) is False
        assert r._approach_idle_since_tick == -1


class TestApproachOcclusion:
    def test_not_ready_when_occluded(self):
        game, ctrl = _game(occluded=True), _ctrl()
        assert _routine().approach(game, ctrl, ENTITY) is False

    def test_nudges_camera_when_occluded(self):
        """
        An on-screen-but-occluded entity needs an actual camera rotation to
        shift its projected position out from behind the panel —
        `bring_entity_on_screen`/`rotate_camera_to` both bail out as soon as
        `onScreen` is true, so calling either here would be a no-op and the
        entity would sit behind the panel forever.
        """
        game, ctrl = _game(occluded=True), _ctrl()
        _routine().approach(game, ctrl, ENTITY)
        ctrl.rotate_camera.assert_called_once_with(Key.RIGHT, OCCLUSION_NUDGE_YAW)

    def test_resets_buffer_when_occluded(self):
        game, ctrl = _game(occluded=True), _ctrl()
        r = _routine()
        r._approach_idle_since_tick = 1
        r.approach(game, ctrl, ENTITY)
        assert r._approach_idle_since_tick == -1

    def test_does_not_check_occlusion_when_entity_off_screen(self):
        """canvasX/canvasY are None while off-screen — is_occluded must not
        be called with them (it would blow up resolving screen coordinates)."""
        off_screen = {**ENTITY, "onScreen": False, "canvasX": None, "canvasY": None}
        game, ctrl = _game(), _ctrl(on_screen=True)
        _routine().approach(game, ctrl, off_screen)
        game.is_occluded.assert_not_called()


class TestApproachIdleSettleBuffer:
    def test_not_ready_while_player_moving(self):
        game, ctrl = _game(idle=False), _ctrl()
        assert _routine().approach(game, ctrl, ENTITY) is False

    def test_resets_buffer_while_player_moving(self):
        game, ctrl = _game(idle=False), _ctrl()
        r = _routine()
        r._approach_idle_since_tick = 1
        r.approach(game, ctrl, ENTITY)
        assert r._approach_idle_since_tick == -1

    def test_records_settle_tick_on_first_idle_tick(self):
        game, ctrl = _game(tick=5, idle=True), _ctrl()
        r = _routine()
        assert r.approach(game, ctrl, ENTITY) is False
        assert r._approach_idle_since_tick == 5

    def test_ready_one_tick_after_settling(self):
        ctrl = _ctrl()
        r = _routine()

        game = _game(tick=5, idle=True)
        assert r.approach(game, ctrl, ENTITY) is False  # records settle tick

        game = _game(tick=6, idle=True)
        assert r.approach(game, ctrl, ENTITY) is True   # settle complete

    def test_buffer_resets_to_fresh_after_becoming_ready(self):
        """Once `approach` returns True it clears its buffer so a subsequent
        approach (e.g. the next entity) starts its own settle cycle."""
        ctrl = _ctrl()
        r = _routine()

        r.approach(_game(tick=5, idle=True), ctrl, ENTITY)
        assert r.approach(_game(tick=6, idle=True), ctrl, ENTITY) is True
        assert r._approach_idle_since_tick == -1


# ---------------------------------------------------------------------------
# verified_menu_click — confirm-then-click / abandon / dismiss-and-retry
# ---------------------------------------------------------------------------

class TestVerifiedMenuClick:
    def test_confirmed_when_entry_present_and_clicked(self):
        game = MagicMock()
        ctrl = MagicMock()
        ctrl.click_menu_entry.return_value = True

        result = _routine().verified_menu_click(game, ctrl, "Attack", "Goblin")

        assert result is MenuClick.CONFIRMED
        ctrl.click_menu_entry.assert_called_once_with(game, "Attack", "Goblin")
        ctrl.dismiss_menu.assert_not_called()

    def test_abandoned_when_menu_closed_without_match(self):
        game = MagicMock()
        game.menu_open.return_value = False
        ctrl = MagicMock()
        ctrl.click_menu_entry.return_value = False

        result = _routine().verified_menu_click(game, ctrl, "Attack", "Goblin")

        assert result is MenuClick.ABANDONED
        ctrl.dismiss_menu.assert_not_called()

    def test_pending_and_dismisses_when_menu_open_without_match(self):
        """Right-click menus don't time out — a menu open without the row we
        need has to be actively dismissed or the routine would stall forever."""
        game = MagicMock()
        game.menu_open.return_value = True
        ctrl = MagicMock()
        ctrl.click_menu_entry.return_value = False

        result = _routine().verified_menu_click(game, ctrl, "Take", "Bones")

        assert result is MenuClick.PENDING
        ctrl.dismiss_menu.assert_called_once_with(game)
