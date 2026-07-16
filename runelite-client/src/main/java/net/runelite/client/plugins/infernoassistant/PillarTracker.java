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
import java.util.EnumMap;
import java.util.EnumSet;
import java.util.Set;
import net.runelite.api.NPC;
import net.runelite.api.coords.WorldPoint;

/**
 * Live pillar alive/HP tracking, ported from
 * {@code InfernoScouterPlugin.alivePillars}/{@code pillarHpBySlot}/
 * {@code pillarSlotFor}/{@code pillarHpFor}/{@code updatePillarHpFromNpcs}.
 * Unlike the original, this uses a single unified coordinate offset
 * ({@link GridConstants#REGION_X_OFFSET}/{@link GridConstants#REGION_Y_OFFSET})
 * for both NPCs and game objects, fixing the 18/47-vs-17/46 offset
 * inconsistency in the original {@code pillarSlotFor(GameObject)}.
 */
final class PillarTracker
{
	private static final Set<Integer> PILLAR_NPC_IDS = Set.of(7709, 7710);
	private static final int DESTROYED_PILLAR_NPC_ID = 7710;

	private final EnumSet<PillarSlot> alivePillars = EnumSet.allOf(PillarSlot.class);
	private final EnumMap<PillarSlot, Integer> pillarHpBySlot = new EnumMap<>(PillarSlot.class);

	PillarTracker()
	{
		for (PillarSlot slot : PillarSlot.values())
		{
			pillarHpBySlot.put(slot, 99);
		}
	}

	void updateFromNpcs(Collection<NPC> npcs)
	{
		for (NPC npc : npcs)
		{
			if (npc == null || !PILLAR_NPC_IDS.contains(npc.getId()))
			{
				continue;
			}

			PillarSlot slot = slotFor(npc);
			if (slot == null)
			{
				continue;
			}

			int hp = hpFor(npc);
			if (hp < 0)
			{
				// Unknown health ratio - assume alive, don't overwrite the HP number.
				alivePillars.add(slot);
				continue;
			}

			if (hp > 0)
			{
				alivePillars.add(slot);
			}
			else
			{
				alivePillars.remove(slot);
			}
			pillarHpBySlot.put(slot, hp);
		}
	}

	/**
	 * Ported from {@code InfernoScouterPlugin.pillarSlotFor(NPC)}, using the
	 * containing-slot check first, then nearest-slot fallback.
	 */
	static PillarSlot slotFor(NPC npc)
	{
		WorldPoint worldPoint = npc.getWorldLocation();
		if (worldPoint == null)
		{
			return null;
		}

		int gridX = GridConstants.gridX(worldPoint);
		int gridY = GridConstants.gridY(worldPoint);

		PillarSlot containing = slotContaining(gridX, gridY);
		if (containing != null)
		{
			return containing;
		}
		return nearestSlot(gridX, gridY);
	}

	private static PillarSlot slotContaining(int gridX, int gridY)
	{
		for (PillarSlot slot : PillarSlot.values())
		{
			if (gridX >= slot.x && gridX < slot.x + PillarSlot.SIZE
				&& gridY <= slot.y && gridY > slot.y - PillarSlot.SIZE)
			{
				return slot;
			}
		}
		return null;
	}

	private static PillarSlot nearestSlot(int gridX, int gridY)
	{
		PillarSlot nearest = null;
		int nearestDistance = Integer.MAX_VALUE;
		for (PillarSlot slot : PillarSlot.values())
		{
			int centerX = slot.x + 1;
			int centerY = slot.y - 1;
			int dx = gridX - centerX;
			int dy = gridY - centerY;
			int distance = dx * dx + dy * dy;
			if (distance < nearestDistance)
			{
				nearest = slot;
				nearestDistance = distance;
			}
		}
		return nearestDistance <= 8 ? nearest : null;
	}

	/**
	 * Ported verbatim from {@code InfernoScouterPlugin.pillarHpFor}.
	 *
	 * @return -1 unknown (don't overwrite), 0 dead/destroyed, 1-99 HP percent
	 */
	static int hpFor(NPC npc)
	{
		if (npc.getId() == DESTROYED_PILLAR_NPC_ID || npc.isDead())
		{
			return 0;
		}

		int ratio = npc.getHealthRatio();
		int scale = npc.getHealthScale();
		if (ratio < 0 || scale <= 0)
		{
			return -1;
		}
		if (ratio <= 0)
		{
			return 0;
		}
		if (ratio >= scale)
		{
			return 99;
		}
		return Math.max(1, Math.min(98, Math.round((ratio * 100.0f) / scale)));
	}

	boolean isAlive(PillarSlot slot)
	{
		return alivePillars.contains(slot);
	}

	int hpPercent(PillarSlot slot)
	{
		return pillarHpBySlot.get(slot);
	}

	/**
	 * Marks each alive pillar's 3x3 footprint as blocked, and clears it for
	 * dead pillars - the moment a pillar dies, LOS through its tiles opens
	 * immediately, matching AUTOZUK's {@code removePillarCollision}.
	 */
	void applyTo(LosEngine engine)
	{
		for (PillarSlot slot : PillarSlot.values())
		{
			boolean alive = isAlive(slot);
			for (int x = slot.x; x < slot.x + PillarSlot.SIZE; x++)
			{
				for (int y = slot.y - PillarSlot.SIZE + 1; y <= slot.y; y++)
				{
					engine.setBlocked(x, y, alive);
				}
			}
		}
	}
}
