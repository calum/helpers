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
 * Line-of-sight engine ported from AUTOZUK's blocked-tile-bitmap + raycast
 * approach (research/AUTOZUK/index.html:490-505). Pure grid-coordinate math,
 * no RuneLite API dependency - the blocked bitmap is populated by callers
 * (e.g. {@link PillarTracker}) from live pillar state.
 */
final class LosEngine
{
	private final boolean[] blocked = new boolean[GridConstants.GRID_SIZE * GridConstants.GRID_SIZE];

	void setBlocked(int x, int y, boolean isBlocked)
	{
		blocked[index(x, y)] = isBlocked;
	}

	void clear()
	{
		java.util.Arrays.fill(blocked, false);
	}

	boolean isBlocked(int x, int y)
	{
		return blocked[index(x, y)];
	}

	/**
	 * Whether any tile of a {@code size x size} footprint at ({@code x}, {@code y})
	 * (same SW-corner convention as {@link Footprint}) is blocked. Used by
	 * {@link MovementSimulator} to test candidate move destinations.
	 */
	boolean footprintBlocked(int x, int y, int size)
	{
		for (int fx = x; fx < x + size; fx++)
		{
			for (int fy = y - size + 1; fy <= y; fy++)
			{
				if (isBlocked(fx, fy))
				{
					return true;
				}
			}
		}
		return false;
	}

	private static int index(int x, int y)
	{
		return (x << 6) | y;
	}

	/**
	 * Ported from AUTOZUK's {@code hasLineOfSight} (index.html:490-497).
	 */
	boolean hasLineOfSight(int x1, int y1, int x2, int y2, int s, int r, boolean isNpc)
	{
		if (isBlocked(x1, y1) || isBlocked(x2, y2))
		{
			return false;
		}
		if (Footprint.collisionMath(x1, y1, s, x2, y2, 1))
		{
			return false;
		}
		if (r == 1)
		{
			int dx = x2 - x1;
			int dy = y2 - y1;
			return (dx < s && dx >= 0 && (dy == 1 || dy == -s)) || (dy > -s && dy <= 0 && (dx == -1 || dx == s));
		}
		if (isNpc)
		{
			int tx = Math.max(x1, Math.min(x1 + s - 1, x2));
			int ty = Math.max(y1 - s + 1, Math.min(y1, y2));
			return hasLineOfSight(x2, y2, tx, ty, 1, r, false);
		}
		if (Math.abs(x2 - x1) > r || Math.abs(y2 - y1) > r)
		{
			return false;
		}
		return raycast(x1, y1, x2, y2);
	}

	/**
	 * 16.16 fixed-point Bresenham walk, ported from AUTOZUK's {@code raycast}
	 * (index.html:499-505). At every step this checks both the tile the ray
	 * enters, and the tile it visually clips through when crossing a
	 * diagonal boundary on the minor axis - the OSRS projectile-clip rule.
	 * Both axis-major branches must preserve that second check.
	 */
	boolean raycast(int x1, int y1, int x2, int y2)
	{
		int dx = x2 - x1;
		int dy = y2 - y1;
		int dxAbs = Math.abs(dx);
		int dyAbs = Math.abs(dy);
		if (dxAbs == 0 && dyAbs == 0)
		{
			return true;
		}

		if (dxAbs > dyAbs)
		{
			int xInc = dx > 0 ? 1 : -1;
			int slope = (dy << 16) / dxAbs;
			int y = (y1 << 16) + 0x8000;
			if (dy < 0)
			{
				y -= 1;
			}
			int xTile = x1;
			while (xTile != x2)
			{
				xTile += xInc;
				int yTile = y >>> 16;
				if (isBlocked(xTile, yTile))
				{
					return false;
				}
				y += slope;
				int ny = y >>> 16;
				if (ny != yTile && isBlocked(xTile, ny))
				{
					return false;
				}
			}
		}
		else
		{
			int yInc = dy > 0 ? 1 : -1;
			int slope = (dx << 16) / dyAbs;
			int x = (x1 << 16) + 0x8000;
			if (dx < 0)
			{
				x -= 1;
			}
			int yTile = y1;
			while (yTile != y2)
			{
				yTile += yInc;
				int xTile = x >>> 16;
				if (isBlocked(xTile, yTile))
				{
					return false;
				}
				x += slope;
				int nx = x >>> 16;
				if (nx != xTile && isBlocked(nx, yTile))
				{
					return false;
				}
			}
		}

		return true;
	}

	/**
	 * Closed-form melee adjacency check - ported from AUTOZUK's
	 * {@code isWithinMeleeRange} (index.html:508), identical to the
	 * {@code r===1} branch of {@code hasLineOfSight}.
	 */
	static boolean isWithinMeleeRange(Footprint mob, int tx, int ty)
	{
		int dx = tx - mob.x;
		int dy = ty - mob.y;
		int s = mob.size;
		return (dx < s && dx >= 0 && (dy == 1 || dy == -s)) || (dy > -s && dy <= 0 && (dx == -1 || dx == s));
	}

	/**
	 * Secondary-melee adjacency (includes diagonals), ported from AUTOZUK's
	 * {@code isWithinSecondaryMeleeRange} (index.html:509-511).
	 */
	static boolean isWithinSecondaryMeleeRange(Footprint mob, int tx, int ty)
	{
		int[] closest = Footprint.closestTileTo(mob, tx, ty);
		return Footprint.chebyshev(tx, ty, closest[0], closest[1]) == 1;
	}

	/**
	 * Ported from AUTOZUK's {@code mobHasLOS} (index.html:506).
	 */
	boolean mobHasLos(MobDef def, Footprint mob, int tx, int ty)
	{
		if (def.range == 1)
		{
			return isWithinMeleeRange(mob, tx, ty);
		}
		return hasLineOfSight(mob.x, mob.y, tx, ty, mob.size, def.range, true);
	}
}
