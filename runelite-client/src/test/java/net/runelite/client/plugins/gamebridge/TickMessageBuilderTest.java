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
import net.runelite.api.MenuEntry;
import net.runelite.api.NPC;
import net.runelite.api.ObjectComposition;
import net.runelite.api.Player;
import net.runelite.api.Scene;
import net.runelite.api.Tile;
import net.runelite.api.TileItem;
import net.runelite.api.WorldView;
import net.runelite.api.coords.WorldPoint;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.mockito.ArgumentCaptor;
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
	// Camera
	// ------------------------------------------------------------------ //

	@Test
	public void cameraMapConvertsJau14ToLegacyJau11AndIncludesMinimapZoom()
	{
		// Client.getCameraYaw()/getCameraYawTarget()/getCameraPitch() return
		// JAU14 (0-16383/revolution); the wire format documents the older
		// JAU11 convention (0-2047/revolution) that Python consumers expect,
		// so the builder must divide raw values by 8 (16384/2048).
		when(config.exposeCamera()).thenReturn(true);
		when(client.getCameraYaw()).thenReturn(1500 * 8);
		when(client.getCameraYawTarget()).thenReturn(1024 * 8);
		when(client.getCameraPitch()).thenReturn(256 * 8);
		when(client.getCameraX()).thenReturn(6582);
		when(client.getCameraY()).thenReturn(218);
		when(client.getCameraZ()).thenReturn(6532);
		when(client.getBaseX()).thenReturn(12800);
		when(client.getBaseY()).thenReturn(12800);
		when(client.getMinimapZoom()).thenReturn(4.0);

		Map<String, Object> result = builder.build(Collections.emptyList(), Collections.emptyMap());

		@SuppressWarnings("unchecked")
		Map<String, Object> camera = (Map<String, Object>) result.get("camera");
		assertEquals(1500, camera.get("yaw"));
		assertEquals(1024, camera.get("yawTarget"));
		assertEquals(256, camera.get("pitch"));
		assertEquals(4.0, camera.get("minimapZoom"));
	}

	@Test
	public void cameraMapOmittedWhenExposeCameraDisabled()
	{
		when(config.exposeCamera()).thenReturn(false);

		Map<String, Object> result = builder.build(Collections.emptyList(), Collections.emptyMap());

		assertFalse("camera should be omitted when exposeCamera is off", result.containsKey("camera"));
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
	// findTile
	// ------------------------------------------------------------------ //

	@Test
	public void findTileReturnsFoundFalseWhenOutOfScene()
	{
		// WorldView's scene covers x in [3200, 3264); 3500 is outside it.
		WorldView wv = mockWorldView(0, 3200, 3200, 64, 64);
		when(client.findWorldViewFromWorldPoint(org.mockito.Mockito.any())).thenReturn(wv);

		Map<String, Object> result = builder.findTile("dodge", 3500, 3500, 0);

		assertEquals("dodge", result.get("subId"));
		assertEquals(false, result.get("found"));
		assertFalse("not-found result should not include tile fields", result.containsKey("worldX"));
	}

	@Test
	public void findTileReturnsFoundFalseWhenPlaneMismatch()
	{
		// LocalPoint.fromWorld returns null when wv.getPlane() != the requested plane,
		// even if the tile would otherwise be in-scene.
		WorldView wv = mockWorldView(1, 3200, 3200, 64, 64);
		when(client.findWorldViewFromWorldPoint(org.mockito.Mockito.any())).thenReturn(wv);

		Map<String, Object> result = builder.findTile("dodge", 3210, 3210, 0);

		assertEquals(false, result.get("found"));
	}

	@Test
	public void findTileDefaultsToClientPlaneWhenPlaneOmitted()
	{
		when(client.getPlane()).thenReturn(2);
		WorldView wv = mockWorldView(0, 3200, 3200, 64, 64);
		ArgumentCaptor<WorldPoint> captor = ArgumentCaptor.forClass(WorldPoint.class);
		when(client.findWorldViewFromWorldPoint(captor.capture())).thenReturn(wv);

		builder.findTile("dodge", 3210, 3210, null);

		assertEquals(2, captor.getValue().getPlane());
	}

	@Test
	public void findTileUsesExplicitPlaneOverClientPlane()
	{
		WorldView wv = mockWorldView(3, 3200, 3200, 64, 64);
		ArgumentCaptor<WorldPoint> captor = ArgumentCaptor.forClass(WorldPoint.class);
		when(client.findWorldViewFromWorldPoint(captor.capture())).thenReturn(wv);

		builder.findTile("dodge", 3210, 3210, 3);

		assertEquals(3, captor.getValue().getPlane());
	}

	private WorldView mockWorldView(int plane, int baseX, int baseY, int sizeX, int sizeY)
	{
		WorldView wv = org.mockito.Mockito.mock(WorldView.class);
		when(wv.getPlane()).thenReturn(plane);
		when(wv.getBaseX()).thenReturn(baseX);
		when(wv.getBaseY()).thenReturn(baseY);
		when(wv.getSizeX()).thenReturn(sizeX);
		when(wv.getSizeY()).thenReturn(sizeY);
		return wv;
	}

	// ------------------------------------------------------------------ //
	// currentTooltip
	// ------------------------------------------------------------------ //

	@Test
	public void currentTooltipCombinesOptionAndTarget()
	{
		MenuEntry attack = mockMenuEntry("Attack", "Goblin (level-2)");
		when(client.getMenuEntries()).thenReturn(new MenuEntry[]{attack});

		assertEquals("Attack Goblin (level-2)", builder.currentTooltip());
	}

	@Test
	public void currentTooltipUsesLastEntryAsDefaultAction()
	{
		// Client.getMenuEntries() is in reverse display order — the last
		// element is the top/default (left-click) entry.
		MenuEntry examine = mockMenuEntry("Examine", "Goblin (level-2)");
		MenuEntry attack = mockMenuEntry("Attack", "Goblin (level-2)");
		when(client.getMenuEntries()).thenReturn(new MenuEntry[]{examine, attack});

		assertEquals("Attack Goblin (level-2)", builder.currentTooltip());
	}

	@Test
	public void currentTooltipOmitsTargetWhenEmpty()
	{
		MenuEntry walkHere = mockMenuEntry("Walk here", "");
		when(client.getMenuEntries()).thenReturn(new MenuEntry[]{walkHere});

		assertEquals("Walk here", builder.currentTooltip());
	}

	@Test
	public void currentTooltipOmitsTargetWhenNull()
	{
		MenuEntry walkHere = mockMenuEntry("Walk here", null);
		when(client.getMenuEntries()).thenReturn(new MenuEntry[]{walkHere});

		assertEquals("Walk here", builder.currentTooltip());
	}

	@Test
	public void currentTooltipReturnsEmptyStringWhenNoMenuEntries()
	{
		when(client.getMenuEntries()).thenReturn(new MenuEntry[0]);

		assertEquals("", builder.currentTooltip());
	}

	private MenuEntry mockMenuEntry(String option, String target)
	{
		MenuEntry entry = org.mockito.Mockito.mock(MenuEntry.class);
		when(entry.getOption()).thenReturn(option);
		when(entry.getTarget()).thenReturn(target);
		return entry;
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
