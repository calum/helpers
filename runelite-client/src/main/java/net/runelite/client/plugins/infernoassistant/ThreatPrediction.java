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

/**
 * A single predicted upcoming event for one NPC, per DESIGN.md §5. One of:
 * a predicted attack ({@link #style} set, {@link #ticksUntilHit} the tick
 * offset the hit lands - this includes movement-projected attacks from an
 * NPC that doesn't have LOS yet, see {@link MovementSimulator}, always
 * marked {@link #uncertain}); a meleer "about to dig and relocate" warning
 * ({@link #meleerDigWarning} true, no style/timing since dig completion
 * isn't deterministic); or an "armed" warning ({@link #armed} true) for an
 * NPC whose attack timer has already expired but which currently lacks
 * LOS/range and isn't predicted to gain it within the lookahead window -
 * since such an NPC fires the instant it does gain LOS, this is a fallback
 * warning for when movement projection can't say when that will be.
 */
final class ThreatPrediction
{
	final int npcIndex;
	final MobType mobType;
	final int ticksUntilHit;
	final AttackStyle style;
	final int expectedDamage;
	final boolean uncertain;
	final boolean meleerDigWarning;
	final boolean armed;

	private ThreatPrediction(int npcIndex, MobType mobType, int ticksUntilHit, AttackStyle style,
		int expectedDamage, boolean uncertain, boolean meleerDigWarning, boolean armed)
	{
		this.npcIndex = npcIndex;
		this.mobType = mobType;
		this.ticksUntilHit = ticksUntilHit;
		this.style = style;
		this.expectedDamage = expectedDamage;
		this.uncertain = uncertain;
		this.meleerDigWarning = meleerDigWarning;
		this.armed = armed;
	}

	static ThreatPrediction attack(int npcIndex, MobType mobType, int ticksUntilHit, AttackStyle style,
		int expectedDamage, boolean uncertain)
	{
		return new ThreatPrediction(npcIndex, mobType, ticksUntilHit, style, expectedDamage, uncertain, false, false);
	}

	static ThreatPrediction meleerDigWarning(int npcIndex)
	{
		return new ThreatPrediction(npcIndex, MobType.MELEE, -1, null, 0, true, true, false);
	}

	static ThreatPrediction armedWarning(int npcIndex, MobType mobType, AttackStyle style, int expectedDamage)
	{
		return new ThreatPrediction(npcIndex, mobType, -1, style, expectedDamage, true, false, true);
	}
}
