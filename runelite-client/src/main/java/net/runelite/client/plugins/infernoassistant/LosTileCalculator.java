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

import java.util.Collection;
import java.util.EnumSet;
import java.util.HashMap;
import java.util.Map;

/**
 * Pure per-tick LOS-tile computation (no RuneLite API dependency), for the
 * ground-tile threat overlay. For each live NPC that currently poses a
 * player-facing threat, marks every tile within its LOS/range with that
 * NPC's attack style, so the overlay can shade tiles by which style(s) can
 * currently reach them.
 */
final class LosTileCalculator
{
	private LosTileCalculator()
	{
	}

	/**
	 * @return grid tile (packed as {@code (gridX << 32) | gridY}) to the set of
	 * attack styles that currently have LOS/range to that tile
	 */
	static Map<Long, EnumSet<AttackStyle>> computeLosTiles(Collection<NpcThreatState> states, LosEngine losEngine)
	{
		Map<Long, EnumSet<AttackStyle>> result = new HashMap<>();
		for (NpcThreatState state : states)
		{
			if (state.mobType == MobType.NIBBLER)
			{
				// Nibblers exclusively threaten pillars, never the player - see
				// research/INFERNO_MECHANICS.md.
				continue;
			}

			MobDef def = MobDef.of(state.mobType);

			AttackStyle style;
			if (def.isBlob)
			{
				if (state.blobPhase != BlobPhase.FIRE)
				{
					// Only show blob LOS once it has scanned and committed to an
					// actual mage/range attack, per the design's blob scan/fire rule.
					continue;
				}
				style = state.blobResolvedStyle;
			}
			else
			{
				style = def.style;
			}

			addLosTiles(state.footprint, def, style, losEngine, result);
		}
		return result;
	}

	private static void addLosTiles(Footprint mob, MobDef def, AttackStyle style, LosEngine losEngine,
		Map<Long, EnumSet<AttackStyle>> result)
	{
		int xMin = Math.max(GridConstants.ARENA_X_MIN, mob.x - def.range);
		int xMax = Math.min(GridConstants.ARENA_X_MAX, mob.x + mob.size - 1 + def.range);
		int yMin = Math.max(GridConstants.ARENA_Y_MIN, mob.y - mob.size + 1 - def.range);
		int yMax = Math.min(GridConstants.ARENA_Y_MAX, mob.y + def.range);

		for (int tx = xMin; tx <= xMax; tx++)
		{
			for (int ty = yMin; ty <= yMax; ty++)
			{
				if (losEngine.mobHasLos(def, mob, tx, ty))
				{
					result.computeIfAbsent(pack(tx, ty), k -> EnumSet.noneOf(AttackStyle.class)).add(style);
				}
			}
		}
	}

	static long pack(int gridX, int gridY)
	{
		return (((long) gridX) << 32) | (gridY & 0xFFFFFFFFL);
	}

	static int unpackX(long packed)
	{
		return (int) (packed >> 32);
	}

	static int unpackY(long packed)
	{
		return (int) packed;
	}
}
