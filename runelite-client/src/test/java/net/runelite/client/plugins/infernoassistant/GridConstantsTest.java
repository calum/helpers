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
import static org.junit.Assert.assertEquals;
import org.junit.Test;

public class GridConstantsTest
{
	@Test
	public void gridXYMatchesKnownInfernoScouterCoordinate()
	{
		// regionX=17, regionY=46 is grid origin (0,0) per REGION_X_OFFSET/REGION_Y_OFFSET.
		WorldPoint worldPoint = new WorldPoint(GridConstants.REGION_X_OFFSET, GridConstants.REGION_Y_OFFSET, 0);

		assertEquals(0, GridConstants.gridX(worldPoint));
		assertEquals(0, GridConstants.gridY(worldPoint));
	}

	@Test
	public void gridXYOffsetsInExpectedDirections()
	{
		// regionX increases with gridX; regionY decreases with gridY (Y axis is flipped).
		WorldPoint worldPoint = new WorldPoint(GridConstants.REGION_X_OFFSET + 5, GridConstants.REGION_Y_OFFSET - 3, 0);

		assertEquals(5, GridConstants.gridX(worldPoint));
		assertEquals(3, GridConstants.gridY(worldPoint));
	}

	@Test
	public void footprintForUsesGridConversionAndGivenSize()
	{
		WorldPoint worldPoint = new WorldPoint(GridConstants.REGION_X_OFFSET + 2, GridConstants.REGION_Y_OFFSET - 4, 0);

		Footprint footprint = GridConstants.footprintFor(worldPoint, 3);

		assertEquals(2, footprint.x);
		assertEquals(4, footprint.y);
		assertEquals(3, footprint.size);
	}

	@Test
	public void pillarSlotsMatchRealGameObjectCalibrationConvertedToGridFrame()
	{
		// research/inferno-scouter's PillarSlot (InfernoScouterPlugin.java:1134-1136) is
		// calibrated against real GameObject positions: WEST(0,9), NORTH(17,7), SOUTH(10,23),
		// using scoutX=regionX-18, scoutY=47-regionY. Converting those real-world-validated
		// values into this package's grid frame (gridX=regionX-17, gridY=46-regionY) requires
		// gridX=scoutX+1, gridY=scoutY-1 - NOT AUTOZUK's raw PILLAR_LOCS (S:{x:11,y:24} etc,
		// research/AUTOZUK/index.html:372) taken as-is, which put every pillar 2 tiles too far
		// south and wrongly blocked LOS through real, walkable tiles past each pillar's true
		// southern edge (see PillarSlot's javadoc).
		assertEquals(1, PillarSlot.WEST.x);
		assertEquals(8, PillarSlot.WEST.y);
		assertEquals(18, PillarSlot.NORTH.x);
		assertEquals(6, PillarSlot.NORTH.y);
		assertEquals(11, PillarSlot.SOUTH.x);
		assertEquals(22, PillarSlot.SOUTH.y);
		assertEquals(3, PillarSlot.SIZE);
	}
}
