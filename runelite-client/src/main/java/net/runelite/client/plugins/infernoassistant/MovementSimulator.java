/*
 * Copyright (c) 2026, Calum
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * 1. Redistributions of source code must retain the above copyright notice, this
 *    list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright notice,
 *    this list of conditions and the following disclaimer in the documentation
 *    and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 * WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
 * DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
 * ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
 * (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 * LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
 * ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
 * SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */
package net.runelite.client.plugins.infernoassistant;

/**
 * Predicts when a currently-out-of-LOS NPC will walk into LOS of a target,
 * by simulating greedy chase-toward-target movement one tile per tick.
 * Ported from AUTOZUK's {@code moveMob}/{@code hlMoveMob}
 * (research/AUTOZUK/index.html:2134-2160, 859-884): no BFS pathfinding, just
 * a sign-step toward the target with a diagonal-then-axis fallback around
 * blocked footprints (pillars).
 *
 * <p>Deliberately omits AUTOZUK's mob-mob collision avoidance and random
 * lateral jitter near the target - this is an approximation used purely to
 * rank/time prayer recommendations (consistent with {@code expectedDamage}
 * elsewhere in this package being a static ranking constant, not a real
 * accuracy roll, per DESIGN.md &sect;5), and self-corrects every tick since
 * it's re-run from the NPC's live position on every {@code GameTick}.
 */
final class MovementSimulator
{
	private MovementSimulator()
	{
	}

	/**
	 * One greedy step of {@code mob}'s footprint toward {@code target}: tries
	 * the diagonal step first, falls back to axis-only steps if the diagonal
	 * destination is blocked, and stays in place if every option is blocked.
	 * Clamped to the arena bounds.
	 */
	static Footprint step(Footprint mob, Footprint target, LosEngine losEngine)
	{
		int dx = Integer.signum(target.x - mob.x);
		int dy = Integer.signum(target.y - mob.y);

		if (dx == 0 && dy == 0)
		{
			return mob;
		}

		if (dx != 0 && dy != 0)
		{
			Footprint diagonal = clamp(mob.x + dx, mob.y + dy, mob.size);
			if (!losEngine.footprintBlocked(diagonal.x, diagonal.y, diagonal.size))
			{
				return diagonal;
			}
		}

		if (dx != 0)
		{
			Footprint xOnly = clamp(mob.x + dx, mob.y, mob.size);
			if (!losEngine.footprintBlocked(xOnly.x, xOnly.y, xOnly.size))
			{
				return xOnly;
			}
		}

		if (dy != 0)
		{
			Footprint yOnly = clamp(mob.x, mob.y + dy, mob.size);
			if (!losEngine.footprintBlocked(yOnly.x, yOnly.y, yOnly.size))
			{
				return yOnly;
			}
		}

		return mob;
	}

	private static Footprint clamp(int x, int y, int size)
	{
		int clampedX = Math.max(GridConstants.ARENA_X_MIN, Math.min(GridConstants.ARENA_X_MAX - size + 1, x));
		int clampedY = Math.max(GridConstants.ARENA_Y_MIN + size - 1, Math.min(GridConstants.ARENA_Y_MAX, y));
		return new Footprint(clampedX, clampedY, size);
	}

	/**
	 * Simulates {@code mob} chasing {@code target} for up to {@code maxTicks}
	 * ticks, returning the tick count on which it first gains LOS, or
	 * {@code -1} if it doesn't within {@code maxTicks}.
	 */
	static int ticksUntilLos(MobDef def, Footprint mob, Footprint target, LosEngine losEngine, int maxTicks)
	{
		int ticks = project(def, mob, target, losEngine, maxTicks).ticks;
		return ticks;
	}

	/**
	 * Same as {@link #ticksUntilLos} but also returns the NPC's simulated
	 * footprint at the moment LOS is gained (or after {@code maxTicks} steps
	 * if LOS is never gained), for callers that need the projected distance.
	 */
	static Projection project(MobDef def, Footprint mob, Footprint target, LosEngine losEngine, int maxTicks)
	{
		Footprint current = mob;
		for (int t = 1; t <= maxTicks; t++)
		{
			current = step(current, target, losEngine);
			if (losEngine.mobHasLos(def, current, target.x, target.y))
			{
				return new Projection(t, current);
			}
		}
		return new Projection(-1, current);
	}

	static final class Projection
	{
		final int ticks;
		final Footprint footprint;

		private Projection(int ticks, Footprint footprint)
		{
			this.ticks = ticks;
			this.footprint = footprint;
		}
	}
}
