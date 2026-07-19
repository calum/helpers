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
		ranger.hasLos = true; // already had LOS last tick - not a fresh gain, so t=0 applies

		// lookaheadTicks=3 isolates a single scheduled attack (next cycle at t=4 falls outside).
		List<ThreatPrediction> predictions = predictor.advance(ranger, player, engine, false, false, false, 0, 3);

		assertEquals(1, predictions.size());
		ThreatPrediction prediction = predictions.get(0);
		assertEquals(AttackStyle.RANGE, prediction.style);
		// Already eligible and had LOS last tick, so it fires this very tick (t=0).
		assertEquals(0, prediction.ticksUntilHit);
		assertEquals(0, ranger.ticksSinceLastAttack);
	}

	@Test
	public void freshLosGainFiresImmediatelyWhenCooldownAlreadyExpired()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		// hasLos defaults to false, so this advance() call observes a fresh false->true
		// LOS gain with a long-stale, already-expired cooldown - a walked-into-view armed
		// NPC attacks the same tick, not the tick after.
		NpcThreatState ranger = new NpcThreatState(1, MobType.RANGER, new Footprint(10, 15, 3));
		ranger.ticksSinceLastAttack = 10; // far past atkSpeed(4) - cooldown already expired

		// lookaheadTicks=3 isolates a single scheduled attack (next cycle at t=4 falls outside).
		List<ThreatPrediction> predictions = predictor.advance(ranger, player, engine, false, false, false, 0, 3);

		assertEquals(1, predictions.size());
		ThreatPrediction prediction = predictions.get(0);
		// Fresh LOS gain with an already-expired cooldown fires this very tick (t=0).
		assertEquals(0, prediction.ticksUntilHit);
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
	public void blobReScanResolvesStyleFromPrayerHeldAtCooldownExpiryNotEarlier()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState blob = new NpcThreatState(1, MobType.BLOB, new Footprint(10, 15, 3));

		// Tick 0: fresh LOS gain resolves the first scan immediately (protect-magic held -> RANGE).
		predictor.advance(blob, player, engine, true, false, false, 0, 6);
		// Ticks 1-2: fire countdown continues (2, then 1 remaining).
		predictor.advance(blob, player, engine, false, false, false, 1, 6);
		predictor.advance(blob, player, engine, false, false, false, 2, 6);
		// Tick 3: fires (0 remaining), rolls into SCAN_WAIT.
		predictor.advance(blob, player, engine, false, false, false, 3, 6);
		// Ticks 4-5: SCAN_WAIT counting down - held prayer here must not affect the next scan.
		predictor.advance(blob, player, engine, false, true, false, 4, 6);
		predictor.advance(blob, player, engine, false, true, false, 5, 6);
		// Tick 6: cooldown expires - the re-scan resolves using *this* tick's prayer (protect-magic -> RANGE),
		// not the protect-missiles held during ticks 4-5 (which would wrongly resolve MAGIC if sampled early).
		List<ThreatPrediction> predictions = predictor.advance(blob, player, engine, true, false, false, 6, 6);

		assertEquals(1, predictions.size());
		assertEquals(AttackStyle.RANGE, predictions.get(0).style);
	}

	@Test
	public void blobResolvesToUnknownWhenNoRelevantPrayerHeldAtScanTick()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState blob = new NpcThreatState(1, MobType.BLOB, new Footprint(10, 15, 3));

		List<ThreatPrediction> predictions = predictor.advance(blob, player, engine, false, false, false, 0, 6);

		assertEquals(1, predictions.size());
		assertEquals(AttackStyle.UNKNOWN, predictions.get(0).style);
	}

	@Test
	public void freshLosGainResolvesBlobScanImmediatelyWithNoPriorWait()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState blob = new NpcThreatState(1, MobType.BLOB, new Footprint(10, 15, 3));
		MobDef def = MobDef.of(MobType.BLOB);

		List<ThreatPrediction> predictions = predictor.advance(blob, player, engine, true, false, false, 0, 6);

		assertEquals(1, predictions.size());
		assertEquals(def.atkSpeed, predictions.get(0).ticksUntilHit);
		assertEquals(BlobPhase.FIRE, blob.blobPhase);
	}

	@Test
	public void blobFireCountdownEmittedEveryTickUntilAttackBegins()
	{
		ThreatPredictor predictor = new ThreatPredictor();
		LosEngine engine = new LosEngine();
		Footprint player = new Footprint(10, 10, 1);
		NpcThreatState blob = new NpcThreatState(1, MobType.BLOB, new Footprint(10, 15, 3));

		List<ThreatPrediction> tick0 = predictor.advance(blob, player, engine, true, false, false, 0, 6);
		List<ThreatPrediction> tick1 = predictor.advance(blob, player, engine, true, false, false, 1, 6);
		List<ThreatPrediction> tick2 = predictor.advance(blob, player, engine, true, false, false, 2, 6);
		List<ThreatPrediction> tick3 = predictor.advance(blob, player, engine, true, false, false, 3, 6);
		List<ThreatPrediction> tick4 = predictor.advance(blob, player, engine, true, false, false, 4, 6);
		List<ThreatPrediction> tick5 = predictor.advance(blob, player, engine, true, false, false, 5, 6);
		List<ThreatPrediction> tick6 = predictor.advance(blob, player, engine, true, false, false, 6, 6);

		// Scan resolves immediately at tick 0, then counts down every tick to the fire at tick 3.
		assertEquals(3, tick0.get(0).ticksUntilHit);
		assertEquals(2, tick1.get(0).ticksUntilHit);
		assertEquals(1, tick2.get(0).ticksUntilHit);
		assertEquals(0, tick3.get(0).ticksUntilHit);
		// SCAN_WAIT ticks produce no prediction - the queue goes quiet until the next scan.
		assertTrue(tick4.isEmpty());
		assertTrue(tick5.isEmpty());
		// The cooldown expires at tick 6 (3 ticks after the tick-3 fire), resolving the next scan immediately.
		assertEquals(3, tick6.get(0).ticksUntilHit);
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
		// ticksSinceLastAttack starts at 0 and is incremented once before the eta check.
		int futureTicksSinceLastAttack = 1 + expected.ticks;
		// If the cooldown will have already expired by eta, it fires that same tick.
		int expectedFireTick = futureTicksSinceLastAttack >= def.atkSpeed
			? expected.ticks
			: expected.ticks + (def.atkSpeed - futureTicksSinceLastAttack);

		List<ThreatPrediction> predictions = predictor.advance(ranger, player, engine, false, false, false, 0, lookaheadTicks);

		assertEquals(1, predictions.size());
		ThreatPrediction prediction = predictions.get(0);
		assertEquals(AttackStyle.RANGE, prediction.style);
		assertTrue(prediction.uncertain);
		assertFalse(prediction.armed);
		assertEquals(expectedFireTick, prediction.ticksUntilHit);
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
		AttackStyle expectedStyle = ThreatPredictor.resolveBlobStyle(true, false); // protectMagicHeld=true -> reacts with RANGE
		int expectedFireTick = expected.ticks + def.atkSpeed;

		List<ThreatPrediction> predictions = predictor.advance(blob, player, engine, true, false, false, 0, lookaheadTicks);

		assertEquals(1, predictions.size());
		ThreatPrediction prediction = predictions.get(0);
		assertEquals(expectedStyle, prediction.style);
		assertTrue(prediction.uncertain);
		assertEquals(expectedFireTick, prediction.ticksUntilHit);
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
		assertEquals(AttackStyle.RANGE, ThreatPredictor.resolveBlobStyle(true, false));
		assertEquals(AttackStyle.MAGIC, ThreatPredictor.resolveBlobStyle(false, true));
		assertEquals(AttackStyle.UNKNOWN, ThreatPredictor.resolveBlobStyle(false, false));
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
