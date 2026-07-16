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
 * A tile footprint on the arena grid: SW-corner tile ({@code x}, {@code y})
 * plus a {@code size x size} extent growing north and east, matching
 * AUTOZUK's mob/pillar footprint convention.
 */
final class Footprint
{
	final int x;
	final int y;
	final int size;

	Footprint(int x, int y, int size)
	{
		this.x = x;
		this.y = y;
		this.size = size;
	}

	/**
	 * Whether two footprints overlap. Ported from AUTOZUK's {@code collisionMath}.
	 */
	static boolean collisionMath(int x, int y, int s, int x2, int y2, int s2)
	{
		return !(x > x2 + s2 - 1 || x + s - 1 < x2 || y - s + 1 > y2 || y < y2 - s2 + 1);
	}

	/**
	 * The tile on {@code mob}'s footprint closest to ({@code tx}, {@code ty}).
	 * Ported from AUTOZUK's {@code closestTileTo}.
	 *
	 * @return a two-element array {@code {x, y}}
	 */
	static int[] closestTileTo(Footprint mob, int tx, int ty)
	{
		int x = Math.max(mob.x, Math.min(mob.x + mob.size - 1, tx));
		int y = Math.max(mob.y - mob.size + 1, Math.min(mob.y, ty));
		return new int[] {x, y};
	}

	static int chebyshev(int x1, int y1, int x2, int y2)
	{
		return Math.max(Math.abs(x2 - x1), Math.abs(y2 - y1));
	}
}
