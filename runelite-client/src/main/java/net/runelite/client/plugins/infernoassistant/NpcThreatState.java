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
 * Mutable per-NPC live threat-tracking state, per DESIGN.md §4. Owned by
 * {@link InfernoAssistantPlugin}, advanced each tick by {@link ThreatPredictor}.
 */
final class NpcThreatState
{
	final int npcIndex;
	final MobType mobType;
	Footprint footprint;

	int ticksSinceLastAttack;
	boolean hasLos;
	boolean hadLosLastTick;
	boolean inRange;

	BlobPhase blobPhase = BlobPhase.NONE;
	int blobPhaseTicksRemaining;
	AttackStyle blobResolvedStyle;

	boolean magerFlickerTell;

	int meleerDigCounter;

	NpcThreatState(int npcIndex, MobType mobType, Footprint footprint)
	{
		this.npcIndex = npcIndex;
		this.mobType = mobType;
		this.footprint = footprint;
	}
}
