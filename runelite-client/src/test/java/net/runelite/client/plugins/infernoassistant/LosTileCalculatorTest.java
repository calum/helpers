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

import java.util.EnumSet;
import java.util.List;
import java.util.Map;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import org.junit.Test;

public class LosTileCalculatorTest
{
	@Test
	public void magerTagsUnblockedTileWithinRangeAsMagic()
	{
		LosEngine engine = new LosEngine();
		NpcThreatState mager = new NpcThreatState(1, MobType.MAGER, new Footprint(10, 15, 4));

		Map<Long, EnumSet<AttackStyle>> tiles = LosTileCalculator.computeLosTiles(List.of(mager), engine);

		EnumSet<AttackStyle> styles = tiles.get(LosTileCalculator.pack(10, 5));
		assertEquals(EnumSet.of(AttackStyle.MAGIC), styles);
	}

	@Test
	public void meleeOnlyTagsAdjacentRingNotDistantTiles()
	{
		LosEngine engine = new LosEngine();
		NpcThreatState meleer = new NpcThreatState(1, MobType.MELEE, new Footprint(10, 10, 4));

		Map<Long, EnumSet<AttackStyle>> tiles = LosTileCalculator.computeLosTiles(List.of(meleer), engine);

		assertEquals(EnumSet.of(AttackStyle.MELEE), tiles.get(LosTileCalculator.pack(10, 11)));
		assertFalse("tile 2 away from a melee-range-1 mob must not be tagged",
			tiles.containsKey(LosTileCalculator.pack(10, 13)));
	}

	@Test
	public void blockedTileOccludesLosToTilesBehindIt()
	{
		LosEngine engine = new LosEngine();
		engine.setBlocked(10, 10, true);
		NpcThreatState mager = new NpcThreatState(1, MobType.MAGER, new Footprint(10, 20, 4));

		Map<Long, EnumSet<AttackStyle>> tiles = LosTileCalculator.computeLosTiles(List.of(mager), engine);

		assertFalse("a blocked tile in the raycast path must prevent the tile beyond it from being tagged",
			tiles.containsKey(LosTileCalculator.pack(10, 5)));
	}

	@Test
	public void blobContributesNoTilesWhileNotInFirePhase()
	{
		LosEngine engine = new LosEngine();
		NpcThreatState blob = new NpcThreatState(1, MobType.BLOB, new Footprint(10, 15, 3));
		blob.blobPhase = BlobPhase.NONE;

		assertTrue(LosTileCalculator.computeLosTiles(List.of(blob), engine).isEmpty());

		blob.blobPhase = BlobPhase.SCAN;
		assertTrue(LosTileCalculator.computeLosTiles(List.of(blob), engine).isEmpty());
	}

	@Test
	public void blobInFirePhaseTagsTilesWithResolvedStyleNotPlaceholderStyle()
	{
		LosEngine engine = new LosEngine();
		NpcThreatState blob = new NpcThreatState(1, MobType.BLOB, new Footprint(10, 15, 3));
		blob.blobPhase = BlobPhase.FIRE;
		blob.blobResolvedStyle = AttackStyle.RANGE;

		Map<Long, EnumSet<AttackStyle>> tiles = LosTileCalculator.computeLosTiles(List.of(blob), engine);

		// MobDef.BLOB.style is a placeholder MAGIC - the resolved style must win.
		assertEquals(EnumSet.of(AttackStyle.RANGE), tiles.get(LosTileCalculator.pack(10, 5)));
	}

	@Test
	public void overlappingNpcsOfDifferentStylesProduceMixedTileEntry()
	{
		LosEngine engine = new LosEngine();
		NpcThreatState mager = new NpcThreatState(1, MobType.MAGER, new Footprint(10, 15, 4));
		NpcThreatState ranger = new NpcThreatState(2, MobType.RANGER, new Footprint(10, 15, 3));

		Map<Long, EnumSet<AttackStyle>> tiles = LosTileCalculator.computeLosTiles(List.of(mager, ranger), engine);

		assertEquals(EnumSet.of(AttackStyle.MAGIC, AttackStyle.RANGE), tiles.get(LosTileCalculator.pack(10, 5)));
	}

	@Test
	public void nibblerNeverContributesTilesRegardlessOfPhaseOrLos()
	{
		LosEngine engine = new LosEngine();
		NpcThreatState nibbler = new NpcThreatState(1, MobType.NIBBLER, new Footprint(10, 11, 1));

		assertTrue(LosTileCalculator.computeLosTiles(List.of(nibbler), engine).isEmpty());
	}
}
