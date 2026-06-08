"""
Predicts an entity's future canvas position from its last-known position and
EntityTracker-derived canvas velocity.

GameBridge delivers one snapshot per game tick (~600 ms) — by the time a
human-paced wind_mouse animation reaches a moving NPC's last-seen canvasX/
canvasY, the entity has likely moved on. MovingTarget bridges that gap:
combine a snapshot's canvas position + per-tick canvas velocity (see
state.entity_tracker.EntityTracker) with the wall-clock instant ("as_of",
typically time.monotonic()) the snapshot was taken at, and predict(at_time)
extrapolates to any later wall-clock instant.

predict() converts elapsed wall-clock seconds to elapsed game ticks via
TICK_DURATION_S — an approximation (the real tick length isn't perfectly
constant; see human/interruptions.py's InterruptionScheduler.TICK_DURATION_S
and the inline 600ms conversion in routines/examples/iron_mining.py for the
same constant duplicated elsewhere) — then scales the per-tick velocity by
that many ticks.

When canvas_velocity is None (EntityTracker has no data yet — first sighting,
the entity was off-screen, or its identity just reset), predict() degrades to
returning the static canvas_pos: an entity with unknown velocity is treated as
stationary rather than guessed at.

This module is deliberately decoupled from EntityTracker — it only needs a
canvas position, an optional per-tick velocity, and a timestamp, all supplied
by the caller. See PLAN.md "Phase 4" for how an EntityTracker instance and
MovingTarget end up wired into GameController.click_entity et al.; the other
half of "Phase 3" is input.mouse.wind_mouse_to_prediction, a WindMouse variant
built around predict().
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

Vector = Tuple[float, float]

# Approximate game-tick duration in seconds. Matches the constant duplicated
# in human/interruptions.py (InterruptionScheduler.TICK_DURATION_S) and the
# inline 600ms conversion in routines/examples/iron_mining.py.
TICK_DURATION_S = 0.6


@dataclass(frozen=True)
class MovingTarget:
    """A snapshot of an entity's canvas position plus enough information to
    extrapolate it forward in time.

    ``canvas_pos`` / ``as_of`` describe "now": where the entity was on screen,
    and the wall-clock instant (``time.monotonic()``) it was observed there.
    ``canvas_velocity`` is in pixels/tick (see ``EntityTracker.*_velocity``,
    space="canvas") — ``None`` means no velocity data is available, and
    ``predict`` then treats the entity as stationary.

    Example::

        target = MovingTarget.from_entity(
            goblin, tracker.npc_velocity(goblin, "canvas"), time.monotonic())
        dest_x, dest_y = target.predict(time.monotonic() + 1.2)
    """

    canvas_pos: Vector
    canvas_velocity: Optional[Vector]
    as_of: float

    @classmethod
    def from_entity(cls, entity: dict, canvas_velocity: Optional[Vector], as_of: float) -> "MovingTarget":
        """Build from an on-screen entity dict (must have numeric canvasX/canvasY)."""
        return cls(
            canvas_pos=(entity["canvasX"], entity["canvasY"]),
            canvas_velocity=canvas_velocity,
            as_of=as_of,
        )

    def predict(self, at_time: float) -> Vector:
        """Estimated canvas position at wall-clock instant ``at_time``."""
        if self.canvas_velocity is None:
            return self.canvas_pos

        elapsed_ticks = (at_time - self.as_of) / TICK_DURATION_S
        vx, vy = self.canvas_velocity
        x, y = self.canvas_pos
        return (x + vx * elapsed_ticks, y + vy * elapsed_ticks)
