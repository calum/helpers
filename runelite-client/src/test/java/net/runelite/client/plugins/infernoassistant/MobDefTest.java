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

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import org.junit.Test;

public class MobDefTest
{
	@Test
	public void everyMobTypeHasAMobDef()
	{
		for (MobType type : MobType.values())
		{
			assertEquals(type, MobDef.of(type).type);
		}
	}

	@Test
	public void magerMatchesPortedConstants()
	{
		MobDef mager = MobDef.of(MobType.MAGER);
		assertEquals(4, mager.size);
		assertEquals(220, mager.hp);
		assertEquals(4, mager.atkSpeed);
		assertEquals(15, mager.range);
		assertEquals(AttackStyle.MAGIC, mager.style);
		assertTrue(mager.hasFlicker);
		assertFalse(mager.hasDig);
		assertFalse(mager.isBlob);
	}

	@Test
	public void meleeMatchesPortedConstants()
	{
		MobDef melee = MobDef.of(MobType.MELEE);
		assertEquals(4, melee.size);
		assertEquals(75, melee.hp);
		assertEquals(1, melee.range);
		assertEquals(AttackStyle.MELEE, melee.style);
		assertTrue(melee.hasDig);
	}

	@Test
	public void blobIsFlaggedAsBlobWithThreeTickAttackSpeed()
	{
		MobDef blob = MobDef.of(MobType.BLOB);
		assertTrue(blob.isBlob);
		assertEquals(3, blob.atkSpeed);
	}

	@Test
	public void batMatchesPortedConstants()
	{
		MobDef bat = MobDef.of(MobType.BAT);
		assertEquals(2, bat.size);
		assertEquals(25, bat.hp);
		assertEquals(3, bat.atkSpeed);
		assertEquals(4, bat.range);
		assertEquals(AttackStyle.RANGE, bat.style);
	}

	@Test
	public void nibblerMatchesPortedConstants()
	{
		MobDef nibbler = MobDef.of(MobType.NIBBLER);
		assertEquals(1, nibbler.size);
		assertEquals(10, nibbler.hp);
		assertEquals(1, nibbler.range);
		assertEquals(AttackStyle.MELEE, nibbler.style);
	}
}
