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
        g.update(self._make_container_msg(95, slots))
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
