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

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import org.junit.Test;

public class LosEngineTest
{
	@Test
	public void blockedTileBlocksLineOfSight()
	{
		LosEngine engine = new LosEngine();
		engine.setBlocked(5, 5, true);

		// Straight vertical line from (5,3) to (5,7) passes through the blocked tile (5,5).
		assertFalse(engine.hasLineOfSight(5, 3, 5, 7, 1, 15, true));
	}

	@Test
	public void losOpensImmediatelyWhenPillarTileIsCleared()
	{
		LosEngine engine = new LosEngine();
		engine.setBlocked(5, 5, true);
		assertFalse(engine.hasLineOfSight(5, 3, 5, 7, 1, 15, true));

		// Simulates a pillar collapsing: its footprint tile is cleared, LOS opens the same tick.
		engine.setBlocked(5, 5, false);
		assertTrue(engine.hasLineOfSight(5, 3, 5, 7, 1, 15, true));
	}

	@Test
	public void raycastOpenWhenNothingBlocked()
	{
		LosEngine engine = new LosEngine();
		assertTrue(engine.raycast(0, 0, 3, 1));
	}

	@Test
	public void raycastBlockedByDiagonalCornerClipTileOnXMajorAxis()
	{
		LosEngine engine = new LosEngine();
		// Neither straight-step tile (1,0) nor (2,0) is blocked, only the diagonal-clip corner (2,1).
		engine.setBlocked(2, 1, true);

		assertFalse(engine.raycast(0, 0, 3, 1));
	}

	@Test
	public void raycastBlockedByDiagonalCornerClipTileOnYMajorAxis()
	{
		LosEngine engine = new LosEngine();
		// Symmetric case with axes swapped: corner-clip tile is (1,2).
		engine.setBlocked(1, 2, true);

		assertFalse(engine.raycast(0, 0, 1, 3));
	}

	@Test
	public void meleeRangeIsAdjacentOnCardinalDirectionsOnly()
	{
		Footprint mob = new Footprint(5, 5, 1);

		assertTrue(LosEngine.isWithinMeleeRange(mob, 5, 6)); // north
		assertTrue(LosEngine.isWithinMeleeRange(mob, 6, 5)); // east
		assertFalse(LosEngine.isWithinMeleeRange(mob, 6, 6)); // diagonal - not melee adjacent
		assertFalse(LosEngine.isWithinMeleeRange(mob, 5, 7)); // two tiles away
	}

	@Test
	public void secondaryMeleeRangeIncludesDiagonals()
	{
		Footprint mob = new Footprint(5, 5, 1);

		assertTrue(LosEngine.isWithinSecondaryMeleeRange(mob, 6, 6)); // diagonal - secondary melee applies
		assertFalse(LosEngine.isWithinSecondaryMeleeRange(mob, 7, 7)); // two tiles away - edge case
	}

	@Test
	public void mobHasLosUsesMeleeAdjacencyWhenRangeIsOne()
	{
		LosEngine engine = new LosEngine();
		MobDef melee = MobDef.of(MobType.MELEE);
		Footprint mob = new Footprint(5, 5, melee.size);

		assertTrue(engine.mobHasLos(melee, mob, 5 + melee.size, 5));
		assertFalse(engine.mobHasLos(melee, mob, 5 + melee.size + 1, 5));
	}

	@Test
	public void footprintBlockedWhenAnyCoveredTileIsBlocked()
	{
		LosEngine engine = new LosEngine();
		// 3x3 footprint at (10,10) covers x in [10,12], y in [8,10] (same
		// convention as PillarTracker.applyTo).
		engine.setBlocked(12, 8, true);

		assertTrue(engine.footprintBlocked(10, 10, 3));
	}

	@Test
	public void footprintNotBlockedWhenAllCoveredTilesAreClear()
	{
		LosEngine engine = new LosEngine();

		assertFalse(engine.footprintBlocked(10, 10, 3));
	}
}
