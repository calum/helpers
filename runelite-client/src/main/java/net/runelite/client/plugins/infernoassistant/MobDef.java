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
 * Static per-type Inferno mob attack profile, ported from AUTOZUK's
 * {@code MOB_DEFS} (research/AUTOZUK/index.html:375-385). {@code maxHit} is
 * not part of AUTOZUK's table (which only scores prayer sequences, not
 * damage magnitude); it is an approximate published max hit used purely as
 * a relative ranking weight for conflict resolution (DESIGN.md §5/§6), not
 * a real accuracy/damage roll.
 */
enum MobDef
{
	MAGER(MobType.MAGER, 4, 220, 4, 15, AttackStyle.MAGIC, true, false, false, 25),
	RANGER(MobType.RANGER, 3, 125, 4, 15, AttackStyle.RANGE, false, false, false, 40),
	MELEE(MobType.MELEE, 4, 75, 4, 1, AttackStyle.MELEE, false, true, false, 45),
	BLOB(MobType.BLOB, 3, 40, 3, 15, AttackStyle.MAGIC, false, false, true, 20),
	BAT(MobType.BAT, 2, 25, 3, 4, AttackStyle.RANGE, false, false, false, 5),
	NIBBLER(MobType.NIBBLER, 1, 10, 4, 1, AttackStyle.MELEE, false, false, false, 1);

	final MobType type;
	final int size;
	final int hp;
	final int atkSpeed;
	final int range;
	final AttackStyle style;
	final boolean hasFlicker;
	final boolean hasDig;
	final boolean isBlob;
	final int maxHit;

	MobDef(MobType type, int size, int hp, int atkSpeed, int range, AttackStyle style,
		boolean hasFlicker, boolean hasDig, boolean isBlob, int maxHit)
	{
		this.type = type;
		this.size = size;
		this.hp = hp;
		this.atkSpeed = atkSpeed;
		this.range = range;
		this.style = style;
		this.hasFlicker = hasFlicker;
		this.hasDig = hasDig;
		this.isBlob = isBlob;
		this.maxHit = maxHit;
	}

	static MobDef of(MobType type)
	{
		for (MobDef def : values())
		{
			if (def.type == type)
			{
				return def;
			}
		}
		throw new IllegalArgumentException("No MobDef for " + type);
	}
}
