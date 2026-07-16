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

import java.util.ArrayList;
import java.util.List;

/**
 * Pure per-tick threat prediction core (no RuneLite API dependency), per
 * DESIGN.md §5. Advances one {@link NpcThreatState} per call, applying the
 * ported AUTOZUK special mechanics (blob scan/fire, mager flicker, meleer
 * dig, secondary melee), and returns predicted events within the lookahead
 * window.
 */
final class ThreatPredictor
{
	List<ThreatPrediction> advance(NpcThreatState state, Footprint player, LosEngine losEngine,
		boolean protectMagicHeld, boolean protectMissilesHeld, boolean protectMeleeHeld,
		int currentTick, int lookaheadTicks)
	{
		return advance(state, player, losEngine, protectMagicHeld, protectMissilesHeld, protectMeleeHeld,
			currentTick, lookaheadTicks, true);
	}

	/**
	 * @param allPillarsDown nibblers exclusively attack pillars until all three are
	 * destroyed - per {@code research/INFERNO_MECHANICS.md}, they pose no threat to the
	 * player before then, so this suppresses all nibbler LOS/range/prediction output
	 * until it's {@code true}.
	 */
	List<ThreatPrediction> advance(NpcThreatState state, Footprint player, LosEngine losEngine,
		boolean protectMagicHeld, boolean protectMissilesHeld, boolean protectMeleeHeld,
		int currentTick, int lookaheadTicks, boolean allPillarsDown)
	{
		if (state.mobType == MobType.NIBBLER && !allPillarsDown)
		{
			return List.of();
		}

		MobDef def = MobDef.of(state.mobType);
		state.hasLos = losEngine.mobHasLos(def, state.footprint, player.x, player.y);
		state.inRange = def.range == 1
			? LosEngine.isWithinMeleeRange(state.footprint, player.x, player.y)
			: Footprint.chebyshev(state.footprint.x, state.footprint.y, player.x, player.y) <= def.range;

		List<ThreatPrediction> predictions = new ArrayList<>();

		if (def.hasDig)
		{
			handleMeleerDig(state, predictions);
		}

		if (def.isBlob)
		{
			advanceBlob(state, def, player, losEngine, protectMagicHeld, lookaheadTicks, predictions);
		}
		else
		{
			advanceStandard(state, def, player, losEngine, lookaheadTicks, predictions);
		}

		return predictions;
	}

	private void advanceStandard(NpcThreatState state, MobDef def, Footprint player, LosEngine losEngine,
		int lookaheadTicks, List<ThreatPrediction> out)
	{
		state.ticksSinceLastAttack++;

		if (def.hasFlicker)
		{
			state.magerFlickerTell = state.hasLos && state.ticksSinceLastAttack == def.atkSpeed - 1;
		}

		if (!state.hasLos || !state.inRange)
		{
			// Meleers already get a distinct "may relocate soon" warning via
			// handleMeleerDig - an armed-warning here would just be redundant.
			if (!def.hasDig && state.ticksSinceLastAttack >= def.atkSpeed)
			{
				out.add(ThreatPrediction.armedWarning(state.npcIndex, def.type, def.style, def.maxHit));
			}
			if (!state.hasLos)
			{
				predictIncomingAttack(state, def, def.style, def.atkSpeed, player, losEngine, lookaheadTicks, out);
			}
			return;
		}

		int distance = Footprint.chebyshev(state.footprint.x, state.footprint.y, player.x, player.y);
		boolean secondaryMelee = secondaryMeleeApplies(def, state.footprint, player);
		boolean uncertain = secondaryMelee || def.hasFlicker;

		int t = isEligibleToAttack(state, def) ? 0 : def.atkSpeed - state.ticksSinceLastAttack;
		boolean firstIteration = true;
		while (t <= lookaheadTicks)
		{
			int delay = ProjectileHitTicks.delayFor(def.type, def.style, distance);
			out.add(ThreatPrediction.attack(state.npcIndex, def.type, t + delay, def.style, def.maxHit, uncertain));
			if (firstIteration && t == 0)
			{
				state.ticksSinceLastAttack = 0;
			}
			firstIteration = false;
			t += def.atkSpeed;
		}
	}

	private void advanceBlob(NpcThreatState state, MobDef def, Footprint player, LosEngine losEngine,
		boolean protectMagicHeld, int lookaheadTicks, List<ThreatPrediction> out)
	{
		if (!state.hasLos && state.blobPhase == BlobPhase.NONE)
		{
			predictIncomingAttack(state, def, resolveBlobStyle(protectMagicHeld), def.atkSpeed, player, losEngine,
				lookaheadTicks, out);
			return;
		}

		if (state.blobPhase == BlobPhase.NONE)
		{
			state.blobPhase = BlobPhase.SCAN;
			state.blobPhaseTicksRemaining = def.atkSpeed;
			state.blobResolvedStyle = resolveBlobStyle(protectMagicHeld);
		}

		state.blobPhaseTicksRemaining--;

		if (state.blobPhase == BlobPhase.SCAN && state.blobPhaseTicksRemaining <= 0)
		{
			int distance = Footprint.chebyshev(state.footprint.x, state.footprint.y, player.x, player.y);
			boolean secondaryMelee = secondaryMeleeApplies(def, state.footprint, player);
			int delay = ProjectileHitTicks.delayFor(def.type, state.blobResolvedStyle, distance);
			out.add(ThreatPrediction.attack(state.npcIndex, def.type, delay, state.blobResolvedStyle, def.maxHit, secondaryMelee));

			state.blobPhase = BlobPhase.FIRE;
			state.blobPhaseTicksRemaining = def.atkSpeed;
		}
		else if (state.blobPhase == BlobPhase.FIRE && state.blobPhaseTicksRemaining <= 0)
		{
			if (state.hasLos)
			{
				state.blobPhase = BlobPhase.SCAN;
				state.blobPhaseTicksRemaining = def.atkSpeed;
				state.blobResolvedStyle = resolveBlobStyle(protectMagicHeld);
			}
			else
			{
				state.blobPhase = BlobPhase.NONE;
			}
		}
	}

	/**
	 * Predicts an incoming attack for an NPC that doesn't currently have LOS,
	 * by simulating its greedy chase movement ({@link MovementSimulator})
	 * toward the player and projecting forward from the tick it's simulated
	 * to gain LOS. Always marked {@code uncertain} since the underlying
	 * movement model is an approximation (no mob-mob collision, no jitter -
	 * see {@link MovementSimulator}'s javadoc) that self-corrects every real
	 * tick rather than being guaranteed accurate in advance.
	 */
	private void predictIncomingAttack(NpcThreatState state, MobDef def, AttackStyle style, int scanTicks,
		Footprint player, LosEngine losEngine, int lookaheadTicks, List<ThreatPrediction> out)
	{
		MovementSimulator.Projection projection = MovementSimulator.project(def, state.footprint, player, losEngine, lookaheadTicks);
		if (projection.ticks < 0)
		{
			return;
		}

		int eta = projection.ticks;
		int fireTick;
		if (def.isBlob)
		{
			fireTick = eta + scanTicks;
		}
		else
		{
			int futureTicksSinceLastAttack = state.ticksSinceLastAttack + eta;
			fireTick = futureTicksSinceLastAttack >= def.atkSpeed
				? eta
				: eta + (def.atkSpeed - futureTicksSinceLastAttack);
		}

		if (fireTick > lookaheadTicks)
		{
			return;
		}

		int distance = Footprint.chebyshev(projection.footprint.x, projection.footprint.y, player.x, player.y);
		int delay = ProjectileHitTicks.delayFor(def.type, style, distance);
		out.add(ThreatPrediction.attack(state.npcIndex, def.type, fireTick + delay, style, def.maxHit, true));
	}

	private void handleMeleerDig(NpcThreatState state, List<ThreatPrediction> out)
	{
		if (state.hasLos)
		{
			state.meleerDigCounter = 0;
			return;
		}

		state.meleerDigCounter--;
		if (meleerDigThresholdReached(state.meleerDigCounter))
		{
			out.add(ThreatPrediction.meleerDigWarning(state.npcIndex));
		}
	}

	static boolean isEligibleToAttack(NpcThreatState state, MobDef def)
	{
		return state.hasLos && state.inRange && state.ticksSinceLastAttack >= def.atkSpeed;
	}

	static int projectileDelay(MobDef def, int distance)
	{
		return ProjectileHitTicks.delayFor(def.type, def.style, distance);
	}

	/**
	 * Reactive blob style resolution ported from AUTOZUK's {@code calcSimDamage}
	 * (index.html:1211-1220): whichever style Protect from Magic does *not*
	 * block, evaluated using the prayer held at the scan tick.
	 */
	static AttackStyle resolveBlobStyle(boolean protectMagicHeld)
	{
		return protectMagicHeld ? AttackStyle.RANGE : AttackStyle.MAGIC;
	}

	/**
	 * Ported from AUTOZUK's {@code canUseSecondaryMelee}/{@code isWithinSecondaryMeleeRange}
	 * (index.html:509-516): mager/ranger/blob only, footprint-adjacent
	 * (including diagonally).
	 */
	static boolean secondaryMeleeApplies(MobDef def, Footprint mob, Footprint player)
	{
		if (def.type != MobType.MAGER && def.type != MobType.RANGER && def.type != MobType.BLOB)
		{
			return false;
		}
		return LosEngine.isWithinSecondaryMeleeRange(mob, player.x, player.y);
	}

	/**
	 * Ported from AUTOZUK's meleer dig trigger threshold (index.html:870-871):
	 * a 10%/tick chance to dig starts once the no-LOS counter passes -38
	 * (guaranteed at -50). Used here as a single warning threshold rather
	 * than rolling the chance, since v1 only surfaces a warning.
	 */
	static boolean meleerDigThresholdReached(int meleerDigCounter)
	{
		return meleerDigCounter <= -38;
	}
}
