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

import java.util.List;
import net.runelite.api.NPC;
import net.runelite.api.coords.WorldPoint;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import org.junit.Before;
import org.junit.Test;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

public class PillarTrackerTest
{
	private PillarTracker tracker;
	private LosEngine engine;

	@Before
	public void setUp()
	{
		tracker = new PillarTracker();
		engine = new LosEngine();
	}

	@Test
	public void allPillarsAliveByDefault()
	{
		for (PillarSlot slot : PillarSlot.values())
		{
			assertTrue(tracker.isAlive(slot));
		}
	}

	@Test
	public void applyToBlocksSouthPillarFootprintAtItsTrueLocation()
	{
		tracker.applyTo(engine);

		// SOUTH (11,24), size 3 -> occupies x[11,13], y[22,24].
		assertTrue(engine.isBlocked(11, 22));
		assertTrue(engine.isBlocked(13, 24));
		assertTrue(engine.isBlocked(12, 23));

		// One tile north of the true footprint must be open - this is exactly
		// the tile a previous (backwards) coordinate fix wrongly blocked,
		// while wrongly leaving the real pillar's southern rows open. See
		// PillarSlot's javadoc for the corner-conversion reasoning.
		assertFalse(engine.isBlocked(11, 21));
		assertFalse(engine.isBlocked(11, 20));
	}

	@Test
	public void destroyedPillarNpcClearsItsFootprintTheSameTick()
	{
		tracker.applyTo(engine);
		assertTrue(engine.isBlocked(12, 23));

		NPC destroyedPillar = pillarNpc(7710, PillarSlot.SOUTH.x + 1, PillarSlot.SOUTH.y);
		tracker.updateFromNpcs(List.of(destroyedPillar));

		assertFalse(tracker.isAlive(PillarSlot.SOUTH));

		tracker.applyTo(engine);
		assertFalse(engine.isBlocked(12, 23));
	}

	@Test
	public void aliveHealthyPillarNpcKeepsSlotAlive()
	{
		NPC healthyPillar = pillarNpc(7709, PillarSlot.WEST.x + 1, PillarSlot.WEST.y);
		when(healthyPillar.isDead()).thenReturn(false);
		when(healthyPillar.getHealthRatio()).thenReturn(30);
		when(healthyPillar.getHealthScale()).thenReturn(30);

		tracker.updateFromNpcs(List.of(healthyPillar));

		assertTrue(tracker.isAlive(PillarSlot.WEST));
		assertTrue(tracker.hpPercent(PillarSlot.WEST) > 0);
	}

	@Test
	public void unknownHealthRatioDoesNotOverwriteTrackedHp()
	{
		NPC unknownHealth = pillarNpc(7709, PillarSlot.NORTH.x + 1, PillarSlot.NORTH.y);
		when(unknownHealth.isDead()).thenReturn(false);
		when(unknownHealth.getHealthRatio()).thenReturn(-1);
		when(unknownHealth.getHealthScale()).thenReturn(30);

		tracker.updateFromNpcs(List.of(unknownHealth));

		assertTrue(tracker.isAlive(PillarSlot.NORTH));
		assertTrue(tracker.hpPercent(PillarSlot.NORTH) > 0);
	}

	private static NPC pillarNpc(int id, int gridX, int gridY)
	{
		NPC npc = mock(NPC.class);
		when(npc.getId()).thenReturn(id);
		WorldPoint worldPoint = new WorldPoint(
			gridX + GridConstants.REGION_X_OFFSET,
			GridConstants.REGION_Y_OFFSET - gridY,
			0);
		when(npc.getWorldLocation()).thenReturn(worldPoint);
		return npc;
	}
}
