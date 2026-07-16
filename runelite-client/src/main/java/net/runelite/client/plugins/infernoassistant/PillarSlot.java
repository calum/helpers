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
 * The three Inferno pillar locations, in this package's SW-corner grid
 * convention ({@link GridConstants#gridX}/{@link GridConstants#gridY},
 * {@code gridX = regionX-17}, {@code gridY = 46-regionY}), where {@code y}
 * is the footprint's <b>south</b> edge (matching every other
 * {@link Footprint} in this package - see {@code Footprint}'s
 * {@code y - size + 1 .. y} span).
 *
 * <p>The one field-validated pillar position data in this repo is
 * {@code research/inferno-scouter}'s {@code PillarSlot} enum
 * ({@code InfernoScouterPlugin.java:1134-1136}: {@code WEST(0,9)},
 * {@code NORTH(17,7)}, {@code SOUTH(10,23)}), calibrated against real
 * {@code GameObject} positions using its own offset
 * ({@code InfernoScouterPlugin.java:827-828}: {@code scoutX = regionX-18},
 * {@code scoutY = 47-regionY}) - but that stored coordinate is the
 * footprint's <b>north</b> edge (NW-corner convention), not south. Converting
 * it to this package's south-edge convention needs two steps, not one: first
 * shift from north edge to south edge <i>within inferno-scouter's own
 * frame</i> (add {@code size-1}, since the footprint spans
 * {@code [northY, northY+size-1]}), then re-base the axis to this package's
 * frame ({@code gridY = scoutY-1}, since {@code gridY = 46-regionY} and
 * {@code scoutY = 47-regionY} differ only by that constant for any given
 * real tile):
 * <pre>
 *   southEdgeGridY = (northEdgeScoutY + size - 1) - 1
 * </pre>
 * Working this through for all three pillars ({@code (9+2-1)=10},
 * {@code (7+2-1)=8}, {@code (23+2-1)=24}) reproduces AUTOZUK's raw
 * {@code PILLAR_LOCS} (`research/AUTOZUK/index.html:372`:
 * {@code W:{x:1,y:10}}, {@code N:{x:18,y:8}}, {@code S:{x:11,y:24}})
 * exactly - two independent sources agreeing is strong corroboration.
 * A previous version of this enum applied only the axis re-basing and not
 * the north-to-south shift, landing on {@code WEST(1,8)}, {@code NORTH(18,6)},
 * {@code SOUTH(11,22)} - each pillar's blocked footprint 2 tiles too far
 * north, wrongly opening LOS through the real pillar's true southern rows
 * while wrongly blocking real open ground 2 tiles north of it. Don't
 * re-derive this a third time without re-checking both conversion steps.
 */
enum PillarSlot
{
	WEST(1, 10),
	NORTH(18, 8),
	SOUTH(11, 24);

	static final int SIZE = 3;

	final int x;
	final int y;

	PillarSlot(int x, int y)
	{
		this.x = x;
		this.y = y;
	}
}
