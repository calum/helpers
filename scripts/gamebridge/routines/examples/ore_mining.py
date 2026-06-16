"""
Ore mining routine — subclass of IronMiningRoutine.

Inherits all state logic (find_ore → mining → walk_to_bank → deposit).
Only the ore name differs.
"""
from __future__ import annotations

from .iron_mining import IronMiningRoutine


class OreMiningRoutine(IronMiningRoutine):
    """Mine ORE_NAME ore rocks, bank when full, repeat."""

    ORE_NAME = "Tin rocks"
