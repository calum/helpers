"""
Cross-tick identity & velocity tracking for NPCs, players, and objects.

GameState.update() replaces the npcs/players/objects lists wholesale every
tick — there is no notion of "the same entity as last tick" beyond the raw
JSON. EntityTracker fills that gap: fed a GameState snapshot once per tick,
it remembers each entity's previous sample (by a stable identity key) and
exposes the resulting per-tick velocity.

Identity keys (see GAMEBRIDGE.md):
    - NPCs    -> `index` (per-instance world index; unique but may be reused
                 by a different NPC shortly after the original despawns)
    - Players -> `id` (already a unique per-instance world index)
    - Objects -> `(id, worldX, worldY)` composite. Objects have no per-instance
                 index — only a shared composition `id` — but they're
                 stationary scenery, so id+position is a stable identity. This
                 also does the right thing when an object is replaced in place
                 (e.g. a tree chopped down to a stump): different `id`, same
                 tile -> a new tracked entity, not a continuation of the old one.

Velocity units are **per tick**, not per second — ticks are this codebase's
natural unit of game time (~600ms, but not perfectly constant), so the tracker
stays independent of any assumed tick duration:
    - world space:  tiles/tick  (dx, dy) of worldX/worldY
    - canvas space: pixels/tick (dx, dy) of canvasX/canvasY

Velocity is a simple two-sample delta — the most recent sighting minus the
one before it — divided by the tick gap between them. No smoothing or longer
history: the simplest thing that's correct. Velocity is `None` until an
entity has been seen on two consecutive trips through `update()`, and any gap
(the entity missing from a tick's list — despawn, or reuse of its identity key
by a different instance) drops its history and starts tracking fresh, per the
GAMEBRIDGE.md guidance that instance indices "may be reused... only rely on
[them] across short windows". Canvas velocity additionally requires both
samples to be on-screen (`canvasX`/`canvasY` not `None`).

This module deliberately does not hook into DecisionEngine, GameController, or
the dashboard — see PLAN.md Phase 3 (`MovingTarget`) and Phase 4 (wiring into
click_entity/move_to_entity/right_click_entity) for how this data eventually
gets consumed and who ends up owning/feeding an EntityTracker instance.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .game_state import GameState

Vector = Tuple[float, float]
Space = str  # "world" or "canvas"


def npc_key(npc: dict) -> int:
    """Stable identity key for an NPC: its per-instance world `index`."""
    return npc["index"]


def player_key(player: dict) -> int:
    """Stable identity key for a player: its per-instance world `id`."""
    return player["id"]


def object_key(obj: dict) -> Tuple[int, int, int]:
    """Stable identity key for an object: composition `id` + world tile.

    Objects carry no per-instance index, but they don't move — id+position
    is stable for as long as that exact object instance exists, and changes
    the moment it's replaced by something else at the same tile.
    """
    return (obj["id"], obj["worldX"], obj["worldY"])


@dataclass(frozen=True)
class _Sample:
    tick: int
    world_pos: Tuple[int, int]
    canvas_pos: Optional[Tuple[float, float]]


@dataclass(frozen=True)
class _Track:
    current: _Sample
    previous: Optional[_Sample]


def _sample_from(entity: dict, tick: int) -> _Sample:
    cx, cy = entity.get("canvasX"), entity.get("canvasY")
    canvas_pos = (cx, cy) if cx is not None and cy is not None else None
    return _Sample(
        tick=tick,
        world_pos=(entity["worldX"], entity["worldY"]),
        canvas_pos=canvas_pos,
    )


def _velocity(track: Optional[_Track], space: Space) -> Optional[Vector]:
    if track is None or track.previous is None:
        return None

    current, previous = track.current, track.previous
    dt = current.tick - previous.tick
    if dt <= 0:
        return None

    if space == "world":
        cur_pos, prev_pos = current.world_pos, previous.world_pos
    elif space == "canvas":
        if current.canvas_pos is None or previous.canvas_pos is None:
            return None
        cur_pos, prev_pos = current.canvas_pos, previous.canvas_pos
    else:
        raise ValueError(f"unknown space: {space!r}")

    return ((cur_pos[0] - prev_pos[0]) / dt, (cur_pos[1] - prev_pos[1]) / dt)


class EntityTracker:
    """Tracks individual NPCs, players, and objects across ticks.

    Usage::

        tracker = EntityTracker()
        tracker.update(game_state)   # once per tick, with the latest snapshot

        goblin = game_state.nearest_npc("Goblin")
        v = tracker.npc_velocity(goblin)            # tiles/tick, world space
        v = tracker.npc_velocity(goblin, "canvas")  # pixels/tick, screen space

        # Or, for a caller that doesn't know/care which kind of entity it has
        # (e.g. GameController.click_entity, which accepts npcs, players,
        # objects and ground items interchangeably):
        v = tracker.velocity(goblin, "canvas")
    """

    def __init__(self) -> None:
        self._npcs: Dict[int, _Track] = {}
        self._players: Dict[int, _Track] = {}
        self._objects: Dict[Tuple[int, int, int], _Track] = {}

    def update(self, game_state: GameState) -> None:
        """Ingest a new snapshot. Call once per tick with the latest GameState."""
        self._npcs = self._rebuild(self._npcs, game_state.npcs, game_state.tick, npc_key)
        self._players = self._rebuild(self._players, game_state.players, game_state.tick, player_key)
        self._objects = self._rebuild(self._objects, game_state.objects, game_state.tick, object_key)

    @staticmethod
    def _rebuild(old_tracks, entities, tick, key_fn):
        new_tracks = {}
        for entity in entities:
            key = key_fn(entity)
            sample = _sample_from(entity, tick)
            old_track = old_tracks.get(key)
            previous = old_track.current if old_track is not None else None
            new_tracks[key] = _Track(current=sample, previous=previous)
        return new_tracks

    def npc_velocity(self, npc: dict, space: Space = "world") -> Optional[Vector]:
        return _velocity(self._npcs.get(npc_key(npc)), space)

    def player_velocity(self, player: dict, space: Space = "world") -> Optional[Vector]:
        return _velocity(self._players.get(player_key(player)), space)

    def object_velocity(self, obj: dict, space: Space = "world") -> Optional[Vector]:
        return _velocity(self._objects.get(object_key(obj)), space)

    def velocity(self, entity: dict, space: Space = "world") -> Optional[Vector]:
        """Look up velocity for an entity of unknown kind (npc/player/object/
        ground item), routing to the right typed lookup above.

        GAMEBRIDGE.md's field tables give each kind exactly one identifying
        field the others lack: NPCs alone have `index`, objects alone have
        `category`, ground items alone have `quantity` — whatever's left over
        has the player shape (`id`, `combatLevel`, `animation`, no `index`).

        Ground items aren't tracked at all — they're stationary drops, like
        objects, but don't get a tracking slot of their own (extending this
        module to a fourth identity scheme for them would be unwarranted: see
        PLAN.md "Phase 4"). Returning `None` is not a degradation here — it's
        the same "treat as static" answer MovingTarget already gives a
        velocity-less entity, and a stationary item is, in fact, static.
        """
        if "index" in entity:
            return self.npc_velocity(entity, space)
        if "category" in entity:
            return self.object_velocity(entity, space)
        if "quantity" in entity:
            return None
        return self.player_velocity(entity, space)
