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
 * Projectile travel-time tables, ported verbatim from AUTOZUK's
 * {@code MONSTER_PROJECTILE_HIT_TICKS} (research/AUTOZUK/index.html:446-452).
 * Each entry is distance-indexed (1-based, clamped beyond table length); the
 * value is the tick a hitsplat lands if the attack was thrown on tick 1.
 * Melee attacks always resolve with delay 1.
 */
final class ProjectileHitTicks
{
	private static final int[] BAT = {2, 2, 2, 3, 3};
	private static final int[] RANGER = {3, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 6, 6, 6, 6};
	private static final int[] MAGER = {2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 6};
	private static final int[] BLOB_RANGE = {2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 5, 5, 5, 5, 6, 6};
	private static final int[] BLOB_MAGE = {2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 6};

	private ProjectileHitTicks()
	{
	}

	/**
	 * @param type the attacking mob's type
	 * @param resolvedStyle the style this attack will land as (post secondary-melee/blob resolution)
	 * @param distance Chebyshev distance from the player to the mob's projectile origin tile
	 * @return ticks from firing to hitsplat landing
	 */
	static int delayFor(MobType type, AttackStyle resolvedStyle, int distance)
	{
		if (resolvedStyle == AttackStyle.MELEE)
		{
			return 1;
		}

		switch (type)
		{
			case BAT:
				return delayFromHitTickList(BAT, distance);
			case RANGER:
				return delayFromHitTickList(RANGER, distance);
			case MAGER:
				return delayFromHitTickList(MAGER, distance);
			case BLOB:
				return delayFromHitTickList(resolvedStyle == AttackStyle.RANGE ? BLOB_RANGE : BLOB_MAGE, distance);
			default:
				return 1;
		}
	}

	static int delayFromHitTickList(int[] list, int distance)
	{
		int d = Math.max(1, distance);
		int hitTick = list[Math.min(d, list.length) - 1];
		return hitTick - 1;
	}
}
