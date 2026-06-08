"""
Registry of known RuneScape interface (widget group) IDs.

The Java plugin's ``interfaces`` tick field (see
``GameBridgePlugin.buildInterfacesList``) is a flat dump of every visible
widget from every currently *loaded* interface group — viewport root
containers (``resizable_viewport``, ``fixed_viewport``, ...) whose background
spans the entire canvas, always-on chrome (orbs, xp counters, minimap,
world-map button, ...), AND real panels (bank, inventory, chatbox, ...) all
appear side by side with no flag distinguishing "this blocks clicks" from
"this is just decoration drawn on top of the game world". Treating the whole
list as occluding (or even just excluding the viewport roots) produces false
positives for every entity that happens to sit behind a piece of chrome.

This module gives the rest of the gamebridge code two things, keyed off the
same registry so the two concerns don't drift apart:

1. ``occludes(group_id)`` — whether a widget belonging to that group should
   count as blocking a click. This is a *whitelist*: only groups registered
   here with ``occludes=True`` (real panels — bank, inventory, chatbox, ...)
   are checked by ``GameState.is_occluded``; everything else (viewport roots,
   unregistered chrome) is ignored. Whitelisting is far more tractable than
   trying to enumerate every harmless chrome group that could appear.
2. ``group_id_for(name)`` / ``is_interface_open`` support — a friendly name
   for routine checks, e.g. ``game.is_interface_open("silver_crafting")``.

Adding a new interface
----------------------
1. Find the group's numeric ID. Two sources, both under ``runelite-api``:
   - ``src/main/java/net/runelite/api/gameval/InterfaceID.java`` —
     comprehensive, auto-generated ``NAME = <id>`` constants
     (e.g. ``BANKMAIN = 12``). Search here for anything not in the TOML.
   - ``src/main/interfaces/interfaces.toml`` — friendlier names for the
     ~150 groups RuneLite has hand-documented, including their interesting
     child widget IDs (e.g. ``[bank] id=12 container=1 ...``).
2. Add an entry below: ``<id>: InterfaceInfo("<short_name>", occludes=<bool>)``.
   - ``occludes=True`` (the default) for normal panels — bank, inventory,
     shops, dialog boxes, skilling interfaces, etc. — anything that visually
     sits on top of the game world and should block a click from reaching an
     entity behind it. ``occludes()`` already returns False for any
     unregistered group, so chrome you don't care about can simply be left
     out — only add an entry for it if you want a friendly ``name`` for
     ``is_interface_open``.
   - ``occludes=False`` for viewport/root containers and chrome you want a
     friendly name for but that should never block a click (see the entries
     below) — marking a real panel this way would let clicks pass straight
     through it onto the game world.
3. Pick a short, unique ``name`` — this is what routines pass to
   ``GameState.is_interface_open(name)``, e.g.::

       if game.is_interface_open("silver_crafting"):
           ctrl.click_widget(gold_ring_slot)
       else:
           ctrl.click_entity(game.nearest_object("Furnace"))
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class InterfaceInfo:
    name: str
    occludes: bool = True


INTERFACES: Dict[int, InterfaceInfo] = {
    # --- Viewport / root containers ------------------------------------
    # Always loaded; their background widgets span the full canvas, so they
    # must never be treated as occluding or every click would be blocked.
    548: InterfaceInfo("fixed_viewport", occludes=False),
    161: InterfaceInfo("resizable_viewport", occludes=False),
    164: InterfaceInfo("resizable_viewport_bottom_line", occludes=False),
    165: InterfaceInfo("fullscreen_container_tli", occludes=False),
    # Overlay container for floating xp-drop icons — its root widgets report
    # full-canvas layout bounds even though almost nothing is drawn there, so
    # (like the viewport roots above) it must never be treated as occluding —
    # or as a click target — or it would swallow every click into the world.
    122: InterfaceInfo("xp_drops", occludes=False),

    # --- Panels in active use by routines / diagnostics -----------------
    12: InterfaceInfo("bank"),
    149: InterfaceInfo("inventory"),
    387: InterfaceInfo("equipment"),
    162: InterfaceInfo("chatbox"),
    160: InterfaceInfo("minimap"),
    6: InterfaceInfo("silver_crafting"),
}


def info_for(group_id: int) -> Optional[InterfaceInfo]:
    """Return the registered InterfaceInfo for a group ID, or None if unknown."""
    return INTERFACES.get(group_id)


def occludes(group_id: int) -> bool:
    """Whether widgets belonging to this group should count toward is_occluded().

    Unknown (unregistered) groups default to False. The ``interfaces`` array
    is a dump of *every* loaded group — including always-on chrome (orbs, xp
    counters, world map button, ...) that visually overlaps the canvas but
    never actually blocks a click. Whitelisting known-occluding panels here
    (bank, inventory, chatbox, ...) is far more tractable than trying to
    blacklist every harmless chrome group, and avoids false "occluded" reports
    for entities that sit behind chrome rather than a real panel. Register a
    new panel below with ``occludes=True`` once you confirm it actually blocks
    clicks.
    """
    info = INTERFACES.get(group_id)
    return info.occludes if info is not None else False


def name_for(group_id: int) -> Optional[str]:
    """Return the registered short name for a group ID, or None if unknown."""
    info = INTERFACES.get(group_id)
    return info.name if info is not None else None


def group_id_for(name: str) -> Optional[int]:
    """Reverse lookup: short name -> group ID, or None if not registered."""
    for group_id, info in INTERFACES.items():
        if info.name == name:
            return group_id
    return None
