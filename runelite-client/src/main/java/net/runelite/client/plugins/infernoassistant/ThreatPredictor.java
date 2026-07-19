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
		state.hadLosLastTick = state.hasLos;
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
			advanceBlob(state, def, player, losEngine, protectMagicHeld, protectMissilesHeld, lookaheadTicks, predictions);
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

		boolean secondaryMelee = secondaryMeleeApplies(def, state.footprint, player);
		boolean uncertain = secondaryMelee || def.hasFlicker;

		// A mob whose cooldown has already expired fires the instant it gains
		// LOS - there is no separate 1-tick "target acquisition" delay on top
		// of that, confirmed by direct observation (an armed NPC attacks the
		// same tick the player walks into its LOS, not the tick after).
		int t = isEligibleToAttack(state, def) ? 0 : def.atkSpeed - state.ticksSinceLastAttack;
		boolean firstIteration = true;
		while (t <= lookaheadTicks)
		{
			out.add(ThreatPrediction.attack(state.npcIndex, def.type, t, def.style, def.maxHit, uncertain));
			if (firstIteration && t == 0)
			{
				state.ticksSinceLastAttack = 0;
			}
			firstIteration = false;
			t += def.atkSpeed;
		}
	}

	/**
	 * Ported from AUTOZUK's {@code hlMobAttack} blob branch (index.html:909-913):
	 * a scan resolves <b>immediately</b> either the instant LOS is freshly
	 * gained, or whenever the post-fire cooldown ({@link BlobPhase#SCAN_WAIT})
	 * counts down to 0 - there is no multi-tick delay before the first scan
	 * of a fresh engagement, only between a fire and the next scan. Once
	 * resolved, the blob counts down {@code def.atkSpeed} ticks to the fire
	 * itself, emitting an updated prediction every tick of that countdown so
	 * the queue doesn't go blank mid-cycle.
	 */
	private void advanceBlob(NpcThreatState state, MobDef def, Footprint player, LosEngine losEngine,
		boolean protectMagicHeld, boolean protectMissilesHeld, int lookaheadTicks, List<ThreatPrediction> out)
	{
		boolean freshLosGain = state.hasLos && !state.hadLosLastTick;

		if (!state.hasLos && state.blobPhase != BlobPhase.FIRE)
		{
			// No LOS, and not already mid a locked-in fire countdown from an earlier
			// scan (a blob that scanned and then lost LOS still fires blind, per
			// AUTOZUK - matches the "hold-recommendation only" approximation already
			// documented for this plugin).
			state.blobPhase = BlobPhase.NONE;
			predictIncomingAttack(state, def, resolveBlobStyle(protectMagicHeld, protectMissilesHeld), def.atkSpeed,
				player, losEngine, lookaheadTicks, out);
			return;
		}

		boolean scanResolvesNow = freshLosGain
			|| (state.blobPhase == BlobPhase.SCAN_WAIT && --state.blobPhaseTicksRemaining <= 0);

		if (scanResolvesNow)
		{
			state.blobResolvedStyle = resolveBlobStyle(protectMagicHeld, protectMissilesHeld);
			state.blobPhase = BlobPhase.FIRE;
			state.blobPhaseTicksRemaining = def.atkSpeed;
		}
		else if (state.blobPhase == BlobPhase.FIRE)
		{
			state.blobPhaseTicksRemaining--;
		}

		if (state.blobPhase == BlobPhase.FIRE)
		{
			boolean secondaryMelee = secondaryMeleeApplies(def, state.footprint, player);
			out.add(ThreatPrediction.attack(state.npcIndex, def.type, state.blobPhaseTicksRemaining,
				state.blobResolvedStyle, def.maxHit, secondaryMelee));

			if (state.blobPhaseTicksRemaining <= 0)
			{
				state.blobPhase = BlobPhase.SCAN_WAIT;
				state.blobPhaseTicksRemaining = def.atkSpeed;
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
			// If the mob's cooldown will have already expired by the tick it's
			// projected to walk into LOS (eta), it fires that same tick - matching
			// the same no-extra-delay rule applied in advanceStandard for the
			// confirmed-LOS case.
			int futureTicksSinceLastAttack = state.ticksSinceLastAttack + eta;
			fireTick = futureTicksSinceLastAttack >= def.atkSpeed
				? eta
				: eta + (def.atkSpeed - futureTicksSinceLastAttack);
		}

		if (fireTick > lookaheadTicks)
		{
			return;
		}

		out.add(ThreatPrediction.attack(state.npcIndex, def.type, fireTick, style, def.maxHit, true));
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

	/**
	 * Reactive blob style resolution ported from AUTOZUK's {@code calcSimDamage}
	 * (index.html:1211-1220): whichever style Protect from Magic does *not*
	 * block, evaluated using the prayer held at the scan tick. If neither
	 * Protect from Magic nor Protect from Missiles is held (e.g. Protect from
	 * Melee, or no prayer) at that tick, per the wiki the blob's attack style
	 * is effectively random - reported as {@link AttackStyle#UNKNOWN}.
	 */
	static AttackStyle resolveBlobStyle(boolean protectMagicHeld, boolean protectMissilesHeld)
	{
		if (protectMagicHeld && !protectMissilesHeld)
		{
			return AttackStyle.RANGE;
		}
		if (protectMissilesHeld && !protectMagicHeld)
		{
			return AttackStyle.MAGIC;
		}
		return AttackStyle.UNKNOWN;
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
