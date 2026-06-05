"""
Gold mining routine — subclass of IronMiningRoutine.

Inherits all state logic (find_ore → mining → walk_to_bank → deposit).
Only the ore name differs.
"""
from __future__ import annotations

from .iron_mining import IronMiningRoutine


class GoldMiningRoutine(IronMiningRoutine):
    """Mine gold ore rocks, bank when full, repeat."""

    ORE_NAME = "Gold rocks"
