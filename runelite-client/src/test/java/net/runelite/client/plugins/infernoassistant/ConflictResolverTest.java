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
import java.util.Map;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import org.junit.Test;

public class ConflictResolverTest
{
	@Test
	public void singleStyleTickRecommendsItWithNoUnmitigated()
	{
		ThreatPrediction bat = ThreatPrediction.attack(1, MobType.BAT, 2, AttackStyle.RANGE, 5, false);

		Map<Integer, ConflictResolution> result = ConflictResolver.resolve(List.of(bat), 6);

		ConflictResolution resolution = result.get(2);
		assertEquals(AttackStyle.RANGE, resolution.recommendedStyle);
		assertTrue(resolution.unmitigated.isEmpty());
	}

	@Test
	public void mixedStyleTickPicksHigherExpectedDamageAndSurfacesTheRest()
	{
		ThreatPrediction mager = ThreatPrediction.attack(1, MobType.MAGER, 3, AttackStyle.MAGIC, 25, false);
		ThreatPrediction bat = ThreatPrediction.attack(2, MobType.BAT, 3, AttackStyle.RANGE, 5, false);

		Map<Integer, ConflictResolution> result = ConflictResolver.resolve(List.of(bat, mager), 6);

		ConflictResolution resolution = result.get(3);
		assertEquals(AttackStyle.MAGIC, resolution.recommendedStyle);
		assertEquals(1, resolution.unmitigated.size());
		assertEquals(AttackStyle.RANGE, resolution.unmitigated.get(0).style);
	}

	@Test
	public void tiedExpectedDamagePicksFirstEncounteredDeterministically()
	{
		ThreatPrediction first = ThreatPrediction.attack(1, MobType.RANGER, 1, AttackStyle.RANGE, 20, false);
		ThreatPrediction second = ThreatPrediction.attack(2, MobType.MAGER, 1, AttackStyle.MAGIC, 20, false);

		Map<Integer, ConflictResolution> result = ConflictResolver.resolve(List.of(first, second), 6);

		ConflictResolution resolution = result.get(1);
		assertEquals(AttackStyle.RANGE, resolution.recommendedStyle);
		assertEquals(1, resolution.unmitigated.size());
		assertEquals(AttackStyle.MAGIC, resolution.unmitigated.get(0).style);
	}

	@Test
	public void threeWayConflictRecommendsOneAndSurfacesOtherTwo()
	{
		ThreatPrediction mager = ThreatPrediction.attack(1, MobType.MAGER, 0, AttackStyle.MAGIC, 25, false);
		ThreatPrediction ranger = ThreatPrediction.attack(2, MobType.RANGER, 0, AttackStyle.RANGE, 40, false);
		ThreatPrediction meleer = ThreatPrediction.attack(3, MobType.MELEE, 0, AttackStyle.MELEE, 45, false);

		Map<Integer, ConflictResolution> result = ConflictResolver.resolve(List.of(mager, ranger, meleer), 6);

		ConflictResolution resolution = result.get(0);
		assertEquals(AttackStyle.MELEE, resolution.recommendedStyle);
		assertEquals(2, resolution.unmitigated.size());
	}

	@Test
	public void emptyPredictionListProducesNoTickEntries()
	{
		Map<Integer, ConflictResolution> result = ConflictResolver.resolve(List.of(), 6);

		assertTrue(result.isEmpty());
	}

	@Test
	public void tickWithNoPredictionsHasNoMapEntry()
	{
		ThreatPrediction bat = ThreatPrediction.attack(1, MobType.BAT, 2, AttackStyle.RANGE, 5, false);

		Map<Integer, ConflictResolution> result = ConflictResolver.resolve(List.of(bat), 6);

		assertFalse(result.containsKey(3));
		assertNull(result.get(3));
	}

	@Test
	public void armedWarningSurfacedAtTickZeroWithNoRecommendedStyle()
	{
		ThreatPrediction armed = ThreatPrediction.armedWarning(1, MobType.BAT, AttackStyle.RANGE, 5);

		Map<Integer, ConflictResolution> result = ConflictResolver.resolve(List.of(armed), 6);

		ConflictResolution resolution = result.get(0);
		assertNull(resolution.recommendedStyle);
		assertEquals(1, resolution.armedWarnings.size());
		assertEquals(AttackStyle.RANGE, resolution.armedWarnings.get(0).style);
	}

	@Test
	public void armedWarningDoesNotSuppressActualAttackAtSameTick()
	{
		ThreatPrediction armed = ThreatPrediction.armedWarning(1, MobType.BAT, AttackStyle.RANGE, 5);
		ThreatPrediction attack = ThreatPrediction.attack(2, MobType.MAGER, 0, AttackStyle.MAGIC, 25, false);

		Map<Integer, ConflictResolution> result = ConflictResolver.resolve(List.of(armed, attack), 6);

		ConflictResolution resolution = result.get(0);
		assertEquals(AttackStyle.MAGIC, resolution.recommendedStyle);
		assertEquals(1, resolution.armedWarnings.size());
	}
}
