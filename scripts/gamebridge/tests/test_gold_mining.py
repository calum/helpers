"""
Tests for GoldMiningRoutine.

The routine is a thin subclass of IronMiningRoutine — full state-machine
logic is covered by test_iron_mining.py.  These tests verify only that
ORE_NAME is correctly overridden and flows through to the state methods.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scripts.gamebridge.routines.examples.gold_mining import GoldMiningRoutine
from scripts.gamebridge.state.game_state import GameState


GOLD_ROCK_ON_SCREEN = {
    "id": 440,
    "name": "Gold rocks",
    "worldX": 3300,
    "worldY": 3280,
    "plane": 0,
    "onScreen": True,
    "canvasX": 400,
    "canvasY": 200,
    "hull": [[390, 190], [410, 190], [410, 210], [390, 210]],
}


def _empty_game(tick: int = 1) -> GameState:
    game = GameState()
    game.tick = tick
    game.player = {"worldX": 3300, "worldY": 3280, "plane": 0, "animation": -1}
    game.inventory = [{"slot": i, "itemId": -1, "qty": 0} for i in range(28)]
    game.objects = [GOLD_ROCK_ON_SCREEN]
    return game


class TestGoldMiningRoutine:
    def test_ore_name_is_gold_rocks(self):
        assert GoldMiningRoutine.ORE_NAME == "Gold rocks"

    def test_find_ore_clicks_gold_rock(self):
        """find_ore waits one settle tick then clicks the gold rock and transitions to mining."""
        ctrl = MagicMock()
        ctrl.bring_entity_on_screen.return_value = True

        r = GoldMiningRoutine()
        # Tick 1: records settle tick, no click yet
        result = r.find_ore(_empty_game(tick=1), ctrl)
        ctrl.click_entity.assert_not_called()
        assert result is None

        # Tick 2: settle complete — clicks and enters mining
        result = r.find_ore(_empty_game(tick=2), ctrl)
        ctrl.click_entity.assert_called_once_with(GOLD_ROCK_ON_SCREEN)
        assert result == "mining"

    def test_find_ore_ignores_iron_rock(self):
        """Gold routine must not click an Iron rocks object."""
        game = _empty_game()
        game.objects = [{**GOLD_ROCK_ON_SCREEN, "name": "Iron rocks"}]
        ctrl = MagicMock()
        result = GoldMiningRoutine().find_ore(game, ctrl)
        ctrl.click_entity.assert_not_called()
        assert result is None
