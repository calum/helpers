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
import static org.junit.Assert.assertTrue;
import org.junit.Test;

public class MovementSimulatorTest
{
	@Test
	public void stepMovesDiagonallyTowardTargetWhenClear()
	{
		LosEngine engine = new LosEngine();
		Footprint mob = new Footprint(5, 5, 1);
		Footprint target = new Footprint(10, 10, 1);

		Footprint next = MovementSimulator.step(mob, target, engine);

		assertEquals(6, next.x);
		assertEquals(6, next.y);
	}

	@Test
	public void stepFallsBackToAxisOnlyWhenDiagonalIsBlocked()
	{
		LosEngine engine = new LosEngine();
		// Mob at (5,5) chasing target at (10,10) would diagonal-step to (6,6);
		// block that destination so it must fall back to an axis-only step.
		engine.setBlocked(6, 6, true);
		Footprint mob = new Footprint(5, 5, 1);
		Footprint target = new Footprint(10, 10, 1);

		Footprint next = MovementSimulator.step(mob, target, engine);

		assertTrue((next.x == 6 && next.y == 5) || (next.x == 5 && next.y == 6));
	}

	@Test
	public void stepStaysPutWhenFullyBlocked()
	{
		LosEngine engine = new LosEngine();
		engine.setBlocked(6, 6, true);
		engine.setBlocked(6, 5, true);
		engine.setBlocked(5, 6, true);
		Footprint mob = new Footprint(5, 5, 1);
		Footprint target = new Footprint(10, 10, 1);

		Footprint next = MovementSimulator.step(mob, target, engine);

		assertEquals(5, next.x);
		assertEquals(5, next.y);
	}

	@Test
	public void stepClampsToArenaBounds()
	{
		LosEngine engine = new LosEngine();
		Footprint mob = new Footprint(GridConstants.ARENA_X_MIN, GridConstants.ARENA_Y_MIN, 1);
		Footprint target = new Footprint(GridConstants.ARENA_X_MIN - 5, GridConstants.ARENA_Y_MIN - 5, 1);

		Footprint next = MovementSimulator.step(mob, target, engine);

		assertEquals(GridConstants.ARENA_X_MIN, next.x);
		assertEquals(GridConstants.ARENA_Y_MIN, next.y);
	}

	@Test
	public void ticksUntilLosReachesTargetWithinLookaheadOnClearPath()
	{
		LosEngine engine = new LosEngine();
		MobDef ranger = MobDef.of(MobType.RANGER);
		Footprint mob = new Footprint(20, 20, ranger.size);
		Footprint target = new Footprint(10, 10, 1);

		int ticks = MovementSimulator.ticksUntilLos(ranger, mob, target, engine, 20);

		assertTrue(ticks >= 0 && ticks <= 20);
	}

	@Test
	public void ticksUntilLosReturnsNegativeOneWhenUnreachableWithinMaxTicks()
	{
		LosEngine engine = new LosEngine();
		MobDef ranger = MobDef.of(MobType.RANGER);
		Footprint mob = new Footprint(20, 20, ranger.size);
		Footprint target = new Footprint(10, 10, 1);

		// A ranger closing one tile per tick from 10 tiles away needs more
		// than a single tick to reach its range-15 LOS in the worst case
		// bootstrap tick, but definitely can't within 0 additional ticks.
		int ticks = MovementSimulator.ticksUntilLos(ranger, mob, target, engine, 0);

		assertEquals(-1, ticks);
	}
}
