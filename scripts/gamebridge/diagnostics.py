"""
Pure entity-inspection helpers backing the dashboard's Testing tab.

Each ``describe_*`` function takes the live controller/game state plus a
resolved entity and returns a short, human-readable string summarising what it
did or found. They have no Qt dependency, so they're unit-testable in
isolation and reusable from any future testing surface (dashboard, CLI, etc).

To add a new check: write a ``describe_*`` function here, then register it in
``GameBridgeWindow._TEST_ACTIONS`` in dashboard.py.
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from .state import interfaces as iface_registry

if TYPE_CHECKING:
    from .controller.controller import GameController
    from .state.game_state import GameState


def find_entity(game: "GameState", name: str) -> Optional[dict]:
    """Resolve a free-text name to the nearest matching object or NPC.

    Objects are checked first since most routines target rocks/trees/banks;
    falls back to NPCs for names that only match a creature.
    """
    return game.nearest_object(name) or game.nearest_npc(name)


def describe_move_into_view(ctrl: "GameController", game: "GameState", entity: dict) -> str:
    """Run bring_entity_on_screen and describe the outcome."""
    name = entity.get("name", "?")
    if entity.get("onScreen"):
        return f"'{name}' is already on screen — nothing to do."
    if ctrl.bring_entity_on_screen(entity, game):
        return f"'{name}' is in view (inside the FOV trapezoid)."
    return f"Adjusting the camera to bring '{name}' into view — check again next tick."


def describe_move_towards(ctrl: "GameController", entity: dict) -> str:
    """Click the entity directly and describe whether the click was issued."""
    name = entity.get("name", "?")
    if not entity.get("onScreen"):
        return f"'{name}' is off screen — click_entity would be a no-op. Try 'Move into view' first."
    ctrl.click_entity(entity)
    return f"Clicked '{name}' to move towards / interact with it."


def describe_click_minimap(ctrl: "GameController", game: "GameState", entity: dict) -> str:
    """Click the entity's minimap position and describe whether it was possible."""
    name = entity.get("name", "?")
    if ctrl.click_minimap_entity(entity, game):
        return f"Clicked the minimap to walk towards '{name}' (won't re-click until the walk settles)."
    return f"'{name}' has no minimap coordinates — it's beyond the ~20-tile minimap radius."


def describe_is_occluded(game: "GameState", entity: dict) -> str:
    """Test the entity's canvas position against the live UI panel list,
    naming the specific panel found in the way — its registered name, group
    id and bounds — rather than a bare yes/no. When the result looks wrong
    (an entity reported occluded in open space, say), that's exactly what's
    needed to tell whether a real panel is sitting there or a registry entry
    whose bounds/group don't mean what we think (see `state.interfaces` and
    `GameState.occluding_widget_at`).

    Only groups registered with ``occludes=True`` ever match — and every
    such entry carries a name — so the label is always `name (G<id>:<child>)`,
    never a bare id.
    """
    name = entity.get("name", "?")
    cx, cy = entity.get("canvasX"), entity.get("canvasY")
    if cx is None or cy is None:
        return f"'{name}' has no canvas position (off screen) — cannot test occlusion."

    widget = game.occluding_widget_at(cx, cy)
    if widget is None:
        return f"'{name}' at canvas ({cx:.0f}, {cy:.0f}) is clear of any UI panel."

    gid = widget.get("groupId", "?")
    cid = widget.get("childId", "?")
    label = f"{iface_registry.name_for(gid)} (G{gid}:{cid})"
    b = widget.get("bounds") or {}
    bounds = (
        f"({b['x']}, {b['y']}) {b['width']}×{b['height']}"
        if b else "no bounds reported"
    )
    return (
        f"'{name}' at canvas ({cx:.0f}, {cy:.0f}) is occluded by "
        f"{label} — bounds {bounds}."
    )


def describe_is_on_screen(entity: dict) -> str:
    """Report the entity's onScreen flag as reported by the Java plugin."""
    name = entity.get("name", "?")
    return f"'{name}' is {'on screen' if entity.get('onScreen') else 'off screen'}."


def describe_is_on_minimap(entity: dict) -> str:
    """Report whether the entity has minimap coordinates this tick."""
    name = entity.get("name", "?")
    on_minimap = entity.get("minimapX") is not None and entity.get("minimapY") is not None
    return f"'{name}' is {'visible' if on_minimap else 'not visible'} on the minimap."
