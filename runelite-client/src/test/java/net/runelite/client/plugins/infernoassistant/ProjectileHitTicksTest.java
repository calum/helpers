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

import static org.junit.Assert.assertEquals;
import org.junit.Test;

public class ProjectileHitTicksTest
{
	@Test
	public void meleeStyleAlwaysHasDelayOfOne()
	{
		assertEquals(1, ProjectileHitTicks.delayFor(MobType.MAGER, AttackStyle.MELEE, 1));
		assertEquals(1, ProjectileHitTicks.delayFor(MobType.MAGER, AttackStyle.MELEE, 15));
	}

	@Test
	public void batTableMatchesKnownValues()
	{
		// bat: [2,2,2,3,3] (dist 1..5) -> delay = hitTick - 1
		assertEquals(1, ProjectileHitTicks.delayFor(MobType.BAT, AttackStyle.RANGE, 1));
		assertEquals(2, ProjectileHitTicks.delayFor(MobType.BAT, AttackStyle.RANGE, 4));
	}

	@Test
	public void rangerTableMatchesKnownValues()
	{
		// ranger: [3,3,3,3,3,4,4,4,4,5,5,5,6,6,6,6]
		assertEquals(2, ProjectileHitTicks.delayFor(MobType.RANGER, AttackStyle.RANGE, 1));
		assertEquals(3, ProjectileHitTicks.delayFor(MobType.RANGER, AttackStyle.RANGE, 6));
		assertEquals(5, ProjectileHitTicks.delayFor(MobType.RANGER, AttackStyle.RANGE, 13));
	}

	@Test
	public void magerTableMatchesKnownValues()
	{
		// mager: [2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,6]
		assertEquals(1, ProjectileHitTicks.delayFor(MobType.MAGER, AttackStyle.MAGIC, 1));
		assertEquals(5, ProjectileHitTicks.delayFor(MobType.MAGER, AttackStyle.MAGIC, 16));
	}

	@Test
	public void blobUsesRangeOrMageTableBasedOnResolvedStyle()
	{
		// blobRange: [2,2,2,3,3,3,3,4,4,4,5,...] vs blobMage: [2,2,2,3,3,3,3,4,4,4,4,5,...]
		assertEquals(4, ProjectileHitTicks.delayFor(MobType.BLOB, AttackStyle.RANGE, 11));
		assertEquals(3, ProjectileHitTicks.delayFor(MobType.BLOB, AttackStyle.MAGIC, 11));
		assertEquals(4, ProjectileHitTicks.delayFor(MobType.BLOB, AttackStyle.MAGIC, 12));
	}

	@Test
	public void distanceBeyondTableLengthClampsToLastEntry()
	{
		// bat table length 5, last entry 3 -> delay 2, for any distance >= 5
		assertEquals(2, ProjectileHitTicks.delayFor(MobType.BAT, AttackStyle.RANGE, 100));
	}

	@Test
	public void distanceIsClampedToAtLeastOne()
	{
		assertEquals(1, ProjectileHitTicks.delayFor(MobType.BAT, AttackStyle.RANGE, 0));
		assertEquals(1, ProjectileHitTicks.delayFor(MobType.BAT, AttackStyle.RANGE, -5));
	}
}
