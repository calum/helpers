"""resolve_click — hit-test a canvas-space click against live game state.

Used by the session recorder to turn a raw (canvas_x, canvas_y) click position
into a description of *what* was under the cursor at that moment — the open
menu entry, UI widget, or game entity (NPC/object/player/ground item) — so a
recorded session reads as an annotated action log rather than a list of bare
pixel coordinates that would need to be manually cross-referenced against the
tick stream later.

Resolution order mirrors how a player actually targets something on screen:
1. An open right-click menu entry — most explicit, names the exact action
   ("Attack Goblin (level-2)", "Mine Iron rocks", "Walk here", ...).
2. A UI widget / interface slot — inventory, bank, equipment, minimap, etc.
3. A world entity's clickable hull — NPC, player, object, ground item.
4. Nothing matched — recorded as a bare viewport click (e.g. "walk here" on
   open ground when no menu appeared, which happens on a plain left-click).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..state.game_state import GameState


def _point_in_rect(x: float, y: float, bounds: dict) -> bool:
    return (bounds["x"] <= x < bounds["x"] + bounds["width"]
            and bounds["y"] <= y < bounds["y"] + bounds["height"])


def _point_in_polygon(x: float, y: float, polygon: list) -> bool:
    """Ray-casting point-in-polygon test (same algorithm as fov._point_in_polygon —
    duplicated rather than imported since that one is a module-private helper)."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


# (result "kind", GameState attribute) — checked in this order so a player
# standing on top of an object resolves to the player, not the tile beneath them.
_ENTITY_LISTS = (
    ("npc", "npcs"),
    ("player", "players"),
    ("object", "objects"),
    ("groundItem", "ground_items"),
)


def resolve_click(canvas_x: float, canvas_y: float, game: "GameState") -> dict:
    """Return a dict describing whatever was at (canvas_x, canvas_y) on this tick.

    Always returns a dict with at least "kind" and "summary" — never None — so
    every recorded click carries a self-describing annotation, even a miss
    (kind="viewport"). "summary" is a one-line human-readable description
    suitable for both the live recording-tab log and skimming the JSONL file.
    """
    menu = game.menu or {}
    if menu.get("open"):
        for index, entry in enumerate(menu.get("entries", [])):
            bounds = entry.get("bounds")
            if bounds and _point_in_rect(canvas_x, canvas_y, bounds):
                option = entry.get("option", "")
                target = entry.get("target", "")
                label = f"{option} {target}".strip()
                return {
                    "kind": "menuEntry",
                    "option": option,
                    "target": target,
                    "identifier": entry.get("identifier"),
                    "menuActionType": entry.get("type"),
                    "index": index,
                    "summary": f'menu entry "{label}"',
                }

    for w in game.interfaces:
        bounds = w.get("bounds")
        if bounds and _point_in_rect(canvas_x, canvas_y, bounds):
            item_id = w.get("itemId", -1)
            text = w.get("text", "")
            label = text or (f"item {item_id}" if item_id and item_id != -1 else "")
            return {
                "kind": "widget",
                "groupId": w.get("groupId"),
                "childId": w.get("childId"),
                "itemId": item_id,
                "quantity": w.get("quantity"),
                "text": text,
                "summary": f"widget G{w.get('groupId')}:{w.get('childId')}"
                           + (f' "{label}"' if label else ""),
            }

    for kind, attr in _ENTITY_LISTS:
        for entity in getattr(game, attr, []):
            hull = entity.get("hull")
            if hull and _point_in_polygon(canvas_x, canvas_y, hull):
                return {
                    "kind": kind,
                    "id": entity.get("id"),
                    "name": entity.get("name"),
                    "worldX": entity.get("worldX"),
                    "worldY": entity.get("worldY"),
                    "hull": hull,
                    "summary": f'{kind} "{entity.get("name")}" (id={entity.get("id")}) '
                               f'at world ({entity.get("worldX")}, {entity.get("worldY")})',
                }

    return {
        "kind": "viewport",
        "summary": f"empty viewport at canvas ({canvas_x:.0f}, {canvas_y:.0f})",
    }
