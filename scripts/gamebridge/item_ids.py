"""
Item ID constants for GameBridge routines.

Organised by skill / activity. Import what you need:

    from scripts.gamebridge.item_ids import TIN_ORE, COPPER_ORE, BRONZE_BAR

Keeping IDs here means every routine references the same canonical value —
changing an ID (e.g. when a game update renumbers an item) is a one-line fix
rather than a search across every routine file.
"""

# ── Firemaking ─────────────────────────────────────────────────────────────────
TINDERBOX = 590
LOGS      = 1511

# ── Fishing & Cooking ──────────────────────────────────────────────────────────
RAW_SHRIMP    = 317
COOKED_SHRIMP = 315
RAW_ANCHOVIES = 321
ANCHOVIES     = 319
BURNT_FISH    = 7954  # generic — shared by burnt shrimp AND burnt anchovies

RAW_TROUT     = 335
COOKED_TROUT  = 333
RAW_SALMON    = 331
COOKED_SALMON = 329
BURNT_FISH_ROD = 343  # burnt trout, salmon, pike, etc. (distinct from BURNT_FISH = 7954)

# ── Mining ─────────────────────────────────────────────────────────────────────
TIN_ORE    = 438
COPPER_ORE = 436

# ── Smelting ───────────────────────────────────────────────────────────────────
BRONZE_BAR = 2349

# ── Smithing ───────────────────────────────────────────────────────────────────
BRONZE_HELM = 1155  # Bronze full helm
