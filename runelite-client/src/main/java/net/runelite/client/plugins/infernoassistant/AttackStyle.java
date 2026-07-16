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

import net.runelite.api.Prayer;

/**
 * The three protection-prayer-relevant damage styles, and their mapping to
 * the {@link Prayer} that blocks them.
 */
enum AttackStyle
{
	MAGIC(Prayer.PROTECT_FROM_MAGIC),
	RANGE(Prayer.PROTECT_FROM_MISSILES),
	MELEE(Prayer.PROTECT_FROM_MELEE);

	private final Prayer protectionPrayer;

	AttackStyle(Prayer protectionPrayer)
	{
		this.protectionPrayer = protectionPrayer;
	}

	Prayer protectionPrayer()
	{
		return protectionPrayer;
	}

	/**
	 * @param protectMagicHeld whether Protect from Magic is currently active
	 * @param protectMissilesHeld whether Protect from Missiles is currently active
	 * @param protectMeleeHeld whether Protect from Melee is currently active
	 * @return whether this style is blocked given the held protection prayers
	 */
	boolean isBlockedBy(boolean protectMagicHeld, boolean protectMissilesHeld, boolean protectMeleeHeld)
	{
		switch (this)
		{
			case MAGIC:
				return protectMagicHeld;
			case RANGE:
				return protectMissilesHeld;
			case MELEE:
				return protectMeleeHeld;
			default:
				throw new IllegalStateException("Unhandled AttackStyle: " + this);
		}
	}
}
