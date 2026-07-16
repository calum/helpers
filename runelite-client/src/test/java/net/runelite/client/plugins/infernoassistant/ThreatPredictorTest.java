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
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import org.junit.Test;

public class ThreatPredictorTest
{
	@Test
	public void attackTimerSchedulesHitAtCorrectOffsetWhenEligible()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState ranger = new NpcThreatState(1, MobType.RANGER, new Footprint(10, 15, 3));
		ranger.ticksSinceLastAttack = 3; // atkSpeed(4) - 1, becomes eligible after increment

		// lookaheadTicks=3 isolates a single scheduled attack (next cycle at t=4 falls outside).
		List<ThreatPrediction> predictions = predictor.advance(ranger, player, engine, false, false, false, 0, 3);

		assertEquals(1, predictions.size());
		ThreatPrediction prediction = predictions.get(0);
		assertEquals(AttackStyle.RANGE, prediction.style);
		assertEquals(2, prediction.ticksUntilHit); // distance 5 -> ranger table delay = 2
		assertEquals(0, ranger.ticksSinceLastAttack);
	}

	@Test
	public void attackTimerNotResetWhenOutOfLosOrRange()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState ranger = new NpcThreatState(1, MobType.RANGER, new Footprint(10, 40, 3)); // distance 30 > range 15
		ranger.ticksSinceLastAttack = 2; // atkSpeed(4) - 2, not yet cooldown-expired after increment

		// lookaheadTicks=0 isolates the cooldown/armed logic from the movement-based
		// prediction path (covered separately below), which needs a non-zero lookahead.
		List<ThreatPrediction> predictions = predictor.advance(ranger, player, engine, false, false, false, 0, 0);

		assertTrue(predictions.isEmpty());
		assertEquals(3, ranger.ticksSinceLastAttack);
	}

	@Test
	public void armedWarningSurfacedWhenCooldownExpiredButNoLosOrRange()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState ranger = new NpcThreatState(1, MobType.RANGER, new Footprint(10, 40, 3)); // distance 30 > range 15
		ranger.ticksSinceLastAttack = 3; // reaches atkSpeed(4) after increment, but still out of range

		List<ThreatPrediction> predictions = predictor.advance(ranger, player, engine, false, false, false, 0, 0);

		assertEquals(1, predictions.size());
		ThreatPrediction warning = predictions.get(0);
		assertTrue(warning.armed);
		assertEquals(AttackStyle.RANGE, warning.style);
		assertEquals(4, ranger.ticksSinceLastAttack); // not reset - no actual attack occurred
	}

	@Test
	public void armedWarningNotSurfacedWhenCooldownNotYetExpired()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState ranger = new NpcThreatState(1, MobType.RANGER, new Footprint(10, 40, 3));
		ranger.ticksSinceLastAttack = 0;

		List<ThreatPrediction> predictions = predictor.advance(ranger, player, engine, false, false, false, 0, 0);

		assertTrue(predictions.isEmpty());
	}

	@Test
	public void blobResolvesStyleFromPrayerHeldAtScanTickNotFireTick()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState blob = new NpcThreatState(1, MobType.BLOB, new Footprint(10, 15, 3));

		// Scan tick: protect-magic held -> reactive rule resolves to RANGE.
		predictor.advance(blob, player, engine, true, false, false, 0, 6);
		// Prayer changes mid-scan; must not affect the already-resolved style.
		predictor.advance(blob, player, engine, false, false, false, 1, 6);
		List<ThreatPrediction> predictions = predictor.advance(blob, player, engine, false, true, false, 2, 6);

		assertEquals(1, predictions.size());
		assertEquals(AttackStyle.RANGE, predictions.get(0).style);
	}

	@Test
	public void blobResolvesToMagicWhenNoRelevantPrayerHeldAtScanTick()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState blob = new NpcThreatState(1, MobType.BLOB, new Footprint(10, 15, 3));

		predictor.advance(blob, player, engine, false, false, false, 0, 6);
		predictor.advance(blob, player, engine, false, false, false, 1, 6);
		List<ThreatPrediction> predictions = predictor.advance(blob, player, engine, false, false, false, 2, 6);

		assertEquals(1, predictions.size());
		assertEquals(AttackStyle.MAGIC, predictions.get(0).style);
	}

	@Test
	public void magerFlickerTellFiresOneTickBeforeScheduledAttack()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState mager = new NpcThreatState(1, MobType.MAGER, new Footprint(10, 15, 4));
		mager.ticksSinceLastAttack = 2; // atkSpeed(4) - 1 after increment -> the flicker tell tick

		predictor.advance(mager, player, engine, false, false, false, 0, 6);

		assertTrue(mager.magerFlickerTell);
	}

	@Test
	public void meleerDigWarningSurfacedOnceCounterCrossesThreshold()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState meleer = new NpcThreatState(1, MobType.MELEE, new Footprint(10, 40, 4)); // never in melee range

		List<ThreatPrediction> predictions = null;
		for (int tick = 0; tick < 38; tick++)
		{
			predictions = predictor.advance(meleer, player, engine, false, false, false, tick, 6);
		}

		boolean sawWarning = false;
		for (ThreatPrediction prediction : predictions)
		{
			sawWarning |= prediction.meleerDigWarning;
		}
		assertTrue(sawWarning);
	}

	@Test
	public void movementPredictionEmittedForOutOfRangeNpcClosingWithinLookahead()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		Footprint start = new Footprint(10, 30, 3); // distance 20 - outside ranger's range-15 LOS
		NpcThreatState ranger = new NpcThreatState(1, MobType.RANGER, start);
		MobDef def = MobDef.of(MobType.RANGER);
		int lookaheadTicks = 10;

		MovementSimulator.Projection expected = MovementSimulator.project(def, start, player, engine, lookaheadTicks);
		assertTrue("test setup expects the ranger to close into LOS within the lookahead", expected.ticks >= 0);
		int expectedDistance = Footprint.chebyshev(expected.footprint.x, expected.footprint.y, player.x, player.y);
		int expectedDelay = ProjectileHitTicks.delayFor(MobType.RANGER, AttackStyle.RANGE, expectedDistance);
		// ticksSinceLastAttack starts at 0 and is incremented once before the eta check.
		int futureTicksSinceLastAttack = 1 + expected.ticks;
		int expectedFireTick = futureTicksSinceLastAttack >= def.atkSpeed
			? expected.ticks
			: expected.ticks + (def.atkSpeed - futureTicksSinceLastAttack);

		List<ThreatPrediction> predictions = predictor.advance(ranger, player, engine, false, false, false, 0, lookaheadTicks);

		assertEquals(1, predictions.size());
		ThreatPrediction prediction = predictions.get(0);
		assertEquals(AttackStyle.RANGE, prediction.style);
		assertTrue(prediction.uncertain);
		assertFalse(prediction.armed);
		assertEquals(expectedFireTick + expectedDelay, prediction.ticksUntilHit);
	}

	@Test
	public void movementPredictionNotEmittedWhenUnreachableWithinLookahead()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState ranger = new NpcThreatState(1, MobType.RANGER, new Footprint(10, 30, 3)); // distance 20

		// lookaheadTicks=2 is nowhere near enough to close a 20-tile gap into range-15 LOS.
		List<ThreatPrediction> predictions = predictor.advance(ranger, player, engine, false, false, false, 0, 2);

		assertTrue(predictions.isEmpty());
	}

	@Test
	public void blobPreEngagementPredictsAttackViaMovementBeforeLos()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		Footprint start = new Footprint(10, 30, 3);
		NpcThreatState blob = new NpcThreatState(1, MobType.BLOB, start);
		MobDef def = MobDef.of(MobType.BLOB);
		int lookaheadTicks = 12;

		MovementSimulator.Projection expected = MovementSimulator.project(def, start, player, engine, lookaheadTicks);
		assertTrue("test setup expects the blob to close into LOS within the lookahead", expected.ticks >= 0);
		int expectedDistance = Footprint.chebyshev(expected.footprint.x, expected.footprint.y, player.x, player.y);
		AttackStyle expectedStyle = ThreatPredictor.resolveBlobStyle(true); // protectMagicHeld=true -> reacts with RANGE
		int expectedDelay = ProjectileHitTicks.delayFor(MobType.BLOB, expectedStyle, expectedDistance);
		int expectedFireTick = expected.ticks + def.atkSpeed;

		List<ThreatPrediction> predictions = predictor.advance(blob, player, engine, true, false, false, 0, lookaheadTicks);

		assertEquals(1, predictions.size());
		ThreatPrediction prediction = predictions.get(0);
		assertEquals(expectedStyle, prediction.style);
		assertTrue(prediction.uncertain);
		assertEquals(expectedFireTick + expectedDelay, prediction.ticksUntilHit);
		// The real scan/fire phase machine hasn't started yet - still pre-engagement.
		assertEquals(BlobPhase.NONE, blob.blobPhase);
	}

	@Test
	public void isEligibleToAttackRequiresLosRangeAndCooldownExpired()
	{
		MobDef ranger = MobDef.of(MobType.RANGER);
		NpcThreatState state = new NpcThreatState(1, MobType.RANGER, new Footprint(0, 0, 3));
		state.hasLos = true;
		state.inRange = true;
		state.ticksSinceLastAttack = 4;
		assertTrue(ThreatPredictor.isEligibleToAttack(state, ranger));

		state.ticksSinceLastAttack = 3;
		assertFalse(ThreatPredictor.isEligibleToAttack(state, ranger));

		state.ticksSinceLastAttack = 4;
		state.hasLos = false;
		assertFalse(ThreatPredictor.isEligibleToAttack(state, ranger));
	}

	@Test
	public void resolveBlobStyleReactsToHeldPrayer()
	{
		assertEquals(AttackStyle.RANGE, ThreatPredictor.resolveBlobStyle(true));
		assertEquals(AttackStyle.MAGIC, ThreatPredictor.resolveBlobStyle(false));
	}

	@Test
	public void secondaryMeleeAppliesOnlyForMagerRangerBlobWhenAdjacent()
	{
		MobDef ranger = MobDef.of(MobType.RANGER);
		MobDef nibbler = MobDef.of(MobType.NIBBLER);
		Footprint mob = new Footprint(5, 5, 1);
		Footprint adjacentPlayer = new Footprint(6, 6, 1);
		Footprint farPlayer = new Footprint(10, 10, 1);

		assertTrue(ThreatPredictor.secondaryMeleeApplies(ranger, mob, adjacentPlayer));
		assertFalse(ThreatPredictor.secondaryMeleeApplies(ranger, mob, farPlayer));
		assertFalse(ThreatPredictor.secondaryMeleeApplies(nibbler, mob, adjacentPlayer));
	}

	@Test
	public void meleerDigThresholdBoundary()
	{
		assertFalse(ThreatPredictor.meleerDigThresholdReached(-37));
		assertTrue(ThreatPredictor.meleerDigThresholdReached(-38));
		assertTrue(ThreatPredictor.meleerDigThresholdReached(-50));
	}

	/**
	 * Nibblers exclusively attack pillars until all three are destroyed - they
	 * pose no threat to the player before then (per
	 * research/INFERNO_MECHANICS.md), so {@code advance} must suppress every
	 * nibbler prediction/armed-warning, and skip updating hasLos/inRange, while
	 * any pillar is still alive.
	 */
	@Test
	public void nibblerProducesNothingWhilePillarsAlive()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState nibbler = new NpcThreatState(1, MobType.NIBBLER, new Footprint(10, 11, 1)); // melee-adjacent
		nibbler.ticksSinceLastAttack = 10;

		List<ThreatPrediction> predictions = predictor.advance(nibbler, player, engine,
			false, false, false, 0, 6, false);

		assertTrue(predictions.isEmpty());
		assertFalse(nibbler.hasLos);
		assertFalse(nibbler.inRange);
	}

	@Test
	public void nibblerResumesNormalPredictionOnceAllPillarsDown()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState nibbler = new NpcThreatState(1, MobType.NIBBLER, new Footprint(10, 11, 1)); // melee-adjacent
		nibbler.ticksSinceLastAttack = 3; // atkSpeed(4) - 1, becomes eligible after increment

		// lookaheadTicks=1 isolates a single scheduled attack (next cycle at t=4 falls outside).
		List<ThreatPrediction> predictions = predictor.advance(nibbler, player, engine,
			false, false, false, 0, 1, true);

		assertTrue(nibbler.hasLos);
		assertTrue(nibbler.inRange);
		assertEquals(1, predictions.size());
		assertEquals(AttackStyle.MELEE, predictions.get(0).style);
	}

	@Test
	public void allPillarsDownDefaultsToTrueForTheThreeArgOverload()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState nibbler = new NpcThreatState(1, MobType.NIBBLER, new Footprint(10, 11, 1));
		nibbler.ticksSinceLastAttack = 3;

		// The pre-existing 8-arg overload (used by callers that don't know about
		// pillar state) must not silently suppress nibblers.
		List<ThreatPrediction> predictions = predictor.advance(nibbler, player, engine,
			false, false, false, 0, 1);

		assertEquals(1, predictions.size());
	}
}
