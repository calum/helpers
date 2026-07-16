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
 * {@code gridX = regionX-17}, {@code gridY = 46-regionY}).
 *
 * <p>These are <b>not</b> AUTOZUK's raw {@code PILLAR_LOCS} - AUTOZUK is a
 * from-scratch offline simulator whose internal grid was never calibrated
 * against real {@code WorldPoint}s. The one field-validated pillar position
 * data in this repo is {@code research/inferno-scouter}'s {@code PillarSlot}
 * enum ({@code InfernoScouterPlugin.java:1134-1136}: {@code WEST(0,9)},
 * {@code NORTH(17,7)}, {@code SOUTH(10,23)}), calibrated against real
 * {@code GameObject} positions using its own offset
 * ({@code InfernoScouterPlugin.java:827-828}: {@code scoutX = regionX-18},
 * {@code scoutY = 47-regionY}). Converting those validated values into this
 * package's grid frame requires solving both offsets:
 * {@code gridX = scoutX+1}, {@code gridY = scoutY-1} - giving
 * {@code WEST(1,8)}, {@code NORTH(18,6)}, {@code SOUTH(11,22)} below. Using
 * AUTOZUK's raw values directly (as a previous version of this enum did)
 * put every y-coordinate 2 tiles too far south, wrongly blocking LOS through
 * real, walkable tiles just past each pillar's true southern edge.
 */
enum PillarSlot
{
	WEST(1, 8),
	NORTH(18, 6),
	SOUTH(11, 22);

	static final int SIZE = 3;

	final int x;
	final int y;

	PillarSlot(int x, int y)
	{
		this.x = x;
		this.y = y;
	}
}
