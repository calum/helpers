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

import net.runelite.api.coords.WorldPoint;

/**
 * Region-to-arena-grid coordinate conversion and static arena geometry, using
 * the SW-corner convention shared by every ported AUTOZUK footprint. This is
 * the single place {@link WorldPoint}s are converted to grid coordinates -
 * every other class in this package consumes grid coordinates only.
 */
final class GridConstants
{
	static final int INFERNO_REGION_ID = 9043;

	static final int REGION_X_OFFSET = 16;
	static final int REGION_Y_OFFSET = 47;

	static final int ARENA_X_MIN = 1;
	static final int ARENA_X_MAX = 29;
	static final int ARENA_Y_MIN = 1;
	static final int ARENA_Y_MAX = 30;

	// Blocked-tile bitmap is indexed (x << 6) | y, i.e. a 64x64 grid.
	static final int GRID_SIZE = 64;

	private GridConstants()
	{
	}

	static int gridX(WorldPoint worldPoint)
	{
		return worldPoint.getRegionX() - REGION_X_OFFSET;
	}

	static int gridY(WorldPoint worldPoint)
	{
		return REGION_Y_OFFSET - worldPoint.getRegionY();
	}

	static Footprint footprintFor(WorldPoint worldPoint, int size)
	{
		return new Footprint(gridX(worldPoint), gridY(worldPoint), size);
	}

	/**
	 * Inverse of {@link #gridX(WorldPoint)}/{@link #gridY(WorldPoint)} - only
	 * valid within {@link #INFERNO_REGION_ID}, same as the forward conversion.
	 */
	static WorldPoint worldPointFor(int gridX, int gridY, int plane)
	{
		int regionX = gridX + REGION_X_OFFSET;
		int regionY = REGION_Y_OFFSET - gridY;
		return WorldPoint.fromRegion(INFERNO_REGION_ID, regionX, regionY, plane);
	}
}
