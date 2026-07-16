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

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import org.junit.Test;

public class FootprintTest
{
	@Test
	public void collisionMathDetectsOverlappingFootprints()
	{
		assertTrue(Footprint.collisionMath(0, 0, 2, 1, 1, 2));
	}

	@Test
	public void collisionMathDetectsAdjacentNonOverlappingFootprints()
	{
		// A 1x1 at (2,0) is directly east of a 2x2 SW-anchored at (0,0) - not overlapping.
		assertFalse(Footprint.collisionMath(0, 0, 2, 2, 0, 1));
	}

	@Test
	public void collisionMathDetectsDisjointFootprints()
	{
		assertFalse(Footprint.collisionMath(0, 0, 1, 10, 10, 1));
	}

	@Test
	public void closestTileToClampsOnAllFourSidesOfFootprint()
	{
		Footprint mob = new Footprint(5, 5, 3); // occupies x:5-7, y:3-5

		assertArrayEquals(new int[] {5, 5}, Footprint.closestTileTo(mob, 0, 10));   // west+north of footprint
		assertArrayEquals(new int[] {7, 5}, Footprint.closestTileTo(mob, 20, 10));  // east+north
		assertArrayEquals(new int[] {5, 3}, Footprint.closestTileTo(mob, 0, 0));    // west+south
		assertArrayEquals(new int[] {7, 3}, Footprint.closestTileTo(mob, 20, 0));   // east+south
		assertArrayEquals(new int[] {6, 4}, Footprint.closestTileTo(mob, 6, 4));    // inside footprint
	}

	@Test
	public void chebyshevIsSymmetricForAxisAlignedDelta()
	{
		assertEquals(5, Footprint.chebyshev(0, 0, 5, 0));
		assertEquals(5, Footprint.chebyshev(5, 0, 0, 0));
	}

	@Test
	public void chebyshevUsesMaxOfDeltasForDiagonal()
	{
		assertEquals(4, Footprint.chebyshev(0, 0, 3, 4));
	}
}
