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
package net.runelite.client.plugins.gamebridge;

import java.util.Arrays;
import java.util.Collections;
import java.util.Map;
import net.runelite.api.Client;
import net.runelite.api.GameObject;
import net.runelite.api.ItemComposition;
import net.runelite.api.NPC;
import net.runelite.api.ObjectComposition;
import net.runelite.api.Player;
import net.runelite.api.Scene;
import net.runelite.api.Tile;
import net.runelite.api.TileItem;
import net.runelite.api.coords.WorldPoint;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.mockito.Mock;
import static org.mockito.Mockito.when;
import org.mockito.junit.MockitoJUnitRunner;

@RunWith(MockitoJUnitRunner.class)
public class TickMessageBuilderTest
{
	@Mock
	private Client client;

	@Mock
	private GameBridgeConfig config;

	@Mock
	private Player localPlayer;

	private TickMessageBuilder builder;

	@Before
	public void setUp()
	{
		builder = new TickMessageBuilder(client, config, new HullFilter(), new HullFilter());
		when(client.getLocalPlayer()).thenReturn(localPlayer);
		when(localPlayer.getWorldLocation()).thenReturn(new WorldPoint(3200, 3200, 0));
	}

	// ------------------------------------------------------------------ //
	// NPCs
	// ------------------------------------------------------------------ //

	@Test
	public void npcMatchByNameSelectsNearest()
	{
		NPC far = mockNpc(3106, 1, "Cow", new WorldPoint(3210, 3200, 0));
		NPC near = mockNpc(3106, 2, "Cow", new WorldPoint(3201, 3200, 0));
		when(client.getNpcs()).thenReturn(Arrays.asList(far, near));

		Map<String, Object> result = builder.findNearest("sub1", "npc", null, "cow");

		assertEquals("sub1", result.get("subId"));
		assertEquals(true, result.get("found"));
		assertEquals(2, result.get("index"));
		assertEquals(3201, result.get("worldX"));
		assertEquals(3200, result.get("worldY"));
	}

	@Test
	public void npcMatchById()
	{
		NPC goblin = mockNpc(101, 5, "Goblin", new WorldPoint(3205, 3200, 0));
		NPC guard = mockNpc(102, 6, "Guard", new WorldPoint(3201, 3200, 0));
		when(client.getNpcs()).thenReturn(Arrays.asList(goblin, guard));

		Map<String, Object> result = builder.findNearest("sub1", "npc", 101, null);

		assertEquals(true, result.get("found"));
		assertEquals(101, result.get("id"));
		assertEquals(5, result.get("index"));
	}

	@Test
	public void npcNoMatchReturnsFoundFalse()
	{
		NPC goblin = mockNpc(101, 5, "Goblin", new WorldPoint(3205, 3200, 0));
		when(client.getNpcs()).thenReturn(Collections.singletonList(goblin));

		Map<String, Object> result = builder.findNearest("sub1", "npc", null, "Nonexistent");

		assertEquals("sub1", result.get("subId"));
		assertEquals(false, result.get("found"));
		assertFalse("not-found result should not include entity fields", result.containsKey("id"));
	}

	private NPC mockNpc(int id, int index, String name, WorldPoint location)
	{
		NPC npc = org.mockito.Mockito.mock(NPC.class);
		when(npc.getId()).thenReturn(id);
		when(npc.getIndex()).thenReturn(index);
		when(npc.getName()).thenReturn(name);
		when(npc.getWorldLocation()).thenReturn(location);
		when(npc.getConvexHull()).thenReturn(null);
		when(npc.getLocalLocation()).thenReturn(null);
		return npc;
	}

	// ------------------------------------------------------------------ //
	// Objects
	// ------------------------------------------------------------------ //

	@Test
	public void objectMatchByNameIteratesTiles()
	{
		GameObject fishingSpot = org.mockito.Mockito.mock(GameObject.class);
		when(fishingSpot.getId()).thenReturn(1497);
		when(fishingSpot.getWorldLocation()).thenReturn(new WorldPoint(3205, 3200, 0));
		when(fishingSpot.getConvexHull()).thenReturn(null);
		when(fishingSpot.getLocalLocation()).thenReturn(null);

		ObjectComposition comp = org.mockito.Mockito.mock(ObjectComposition.class);
		when(comp.getName()).thenReturn("Fishing spot");
		when(comp.getImpostorIds()).thenReturn(null);
		when(client.getObjectDefinition(1497)).thenReturn(comp);

		Tile tile = org.mockito.Mockito.mock(Tile.class);
		when(tile.getGameObjects()).thenReturn(new GameObject[]{fishingSpot});

		setUpScene(tile);

		Map<String, Object> result = builder.findNearest("fish_spot", "object", null, "fishing spot");

		assertEquals("fish_spot", result.get("subId"));
		assertEquals(true, result.get("found"));
		assertEquals(1497, result.get("id"));
		assertEquals("Fishing spot", result.get("name"));
		assertEquals("game", result.get("category"));
		assertEquals(3205, result.get("worldX"));
		assertEquals(3200, result.get("worldY"));
	}

	@Test
	public void objectNoMatchReturnsFoundFalse()
	{
		Tile tile = org.mockito.Mockito.mock(Tile.class);
		when(tile.getGameObjects()).thenReturn(new GameObject[0]);
		setUpScene(tile);

		Map<String, Object> result = builder.findNearest("missing", "object", 9999, null);

		assertEquals("missing", result.get("subId"));
		assertEquals(false, result.get("found"));
	}

	// ------------------------------------------------------------------ //
	// Ground items
	// ------------------------------------------------------------------ //

	@Test
	public void groundItemMatchByIdIteratesTiles()
	{
		TileItem bones = org.mockito.Mockito.mock(TileItem.class);
		when(bones.getId()).thenReturn(526);
		when(bones.getQuantity()).thenReturn(1);

		ItemComposition comp = org.mockito.Mockito.mock(ItemComposition.class);
		when(comp.getName()).thenReturn("Bones");
		when(client.getItemDefinition(526)).thenReturn(comp);

		Tile tile = org.mockito.Mockito.mock(Tile.class);
		when(tile.getGroundItems()).thenReturn(Collections.singletonList(bones));
		when(tile.getWorldLocation()).thenReturn(new WorldPoint(3225, 3215, 0));
		when(tile.getLocalLocation()).thenReturn(null);

		setUpScene(tile);

		Map<String, Object> result = builder.findNearest("bones", "groundItem", 526, null);

		assertEquals("bones", result.get("subId"));
		assertEquals(true, result.get("found"));
		assertEquals(526, result.get("id"));
		assertEquals("Bones", result.get("name"));
		assertEquals(1, result.get("quantity"));
		assertEquals(3225, result.get("worldX"));
		assertEquals(3215, result.get("worldY"));
	}

	@Test
	public void groundItemNoMatchReturnsFoundFalse()
	{
		Tile tile = org.mockito.Mockito.mock(Tile.class);
		when(tile.getGroundItems()).thenReturn(Collections.emptyList());
		setUpScene(tile);

		Map<String, Object> result = builder.findNearest("none", "groundItem", null, "Coins");

		assertEquals("none", result.get("subId"));
		assertEquals(false, result.get("found"));
	}

	private void setUpScene(Tile tile)
	{
		Scene scene = org.mockito.Mockito.mock(Scene.class);
		Tile[][][] tiles = new Tile[1][][];
		tiles[0] = new Tile[][]{{tile}};
		when(scene.getTiles()).thenReturn(tiles);
		when(client.getScene()).thenReturn(scene);
		when(client.getPlane()).thenReturn(0);
	}

	// ------------------------------------------------------------------ //
	// matchesIdOrName
	// ------------------------------------------------------------------ //

	@Test
	public void matchesIdOrNameRequiresAtLeastOneFilter()
	{
		assertFalse(TickMessageBuilder.matchesIdOrName(1, "Goblin", null, null));
	}

	@Test
	public void matchesIdOrNameById()
	{
		assertTrue(TickMessageBuilder.matchesIdOrName(1, "Goblin", 1, null));
		assertFalse(TickMessageBuilder.matchesIdOrName(1, "Goblin", 2, null));
	}

	@Test
	public void matchesIdOrNameByNameCaseInsensitive()
	{
		assertTrue(TickMessageBuilder.matchesIdOrName(1, "Goblin", null, "goblin"));
		assertTrue(TickMessageBuilder.matchesIdOrName(1, "Goblin", null, "GOBLIN"));
		assertFalse(TickMessageBuilder.matchesIdOrName(1, "Goblin", null, "Cow"));
	}

	@Test
	public void matchesIdOrNameRequiresBothWhenBothGiven()
	{
		assertTrue(TickMessageBuilder.matchesIdOrName(1, "Goblin", 1, "goblin"));
		assertFalse(TickMessageBuilder.matchesIdOrName(1, "Goblin", 1, "Cow"));
		assertFalse(TickMessageBuilder.matchesIdOrName(2, "Goblin", 1, "Goblin"));
	}
}
