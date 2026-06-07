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

import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;
import org.junit.BeforeClass;
import org.junit.Test;

import java.io.IOException;
import java.lang.reflect.Type;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.Assert.*;

/**
 * Contract tests for the GameBridge wire format.
 *
 * Loads scripts/gamebridge/tests/contract.json — the same file that the
 * Python test_contract.py tests against — and validates that all field names
 * and types match what the Java plugin serialises.
 *
 * Rule: when you change the plugin's JSON output, update contract.json first.
 * Both this suite and the Python suite will then fail until the other side
 * catches up.
 */
public class ContractTest
{
	private static Map<String, Object> CONTRACT;

	// ------------------------------------------------------------------ //
	// Load the shared contract file
	// ------------------------------------------------------------------ //

	@BeforeClass
	public static void loadContract() throws IOException
	{
		Path path = findContractFile();
		String json = new String(Files.readAllBytes(path), StandardCharsets.UTF_8);
		Type mapType = new TypeToken<Map<String, Object>>(){}.getType();
		CONTRACT = new Gson().fromJson(json, mapType);
		assertNotNull("contract.json parsed to null", CONTRACT);
	}

	private static Path findContractFile() throws IOException
	{
		// Gradle may run tests from the subproject root or the repo root.
		for (String candidate : new String[]{
			"scripts/gamebridge/tests/contract.json",
			"../scripts/gamebridge/tests/contract.json",
		})
		{
			Path p = Paths.get(candidate);
			if (Files.exists(p))
			{
				return p;
			}
		}
		throw new IOException(
			"contract.json not found. Searched: scripts/gamebridge/tests/ and " +
			"../scripts/gamebridge/tests/ relative to working dir: " +
			Paths.get("").toAbsolutePath()
		);
	}

	// ------------------------------------------------------------------ //
	// Top-level fields
	// ------------------------------------------------------------------ //

	@Test
	public void topLevelTickPresent()
	{
		assertTrue("tick missing", CONTRACT.containsKey("tick"));
		assertIsNumber("tick", CONTRACT.get("tick"));
	}

	@Test
	public void topLevelPlayerPresent()
	{
		assertIsMap("player", CONTRACT.get("player"));
	}

	@Test
	public void topLevelCameraPresent()
	{
		assertIsMap("camera", CONTRACT.get("camera"));
	}

	@Test
	public void topLevelNpcsPresent()
	{
		assertIsList("npcs", CONTRACT.get("npcs"));
	}

	@Test
	public void topLevelPlayersPresent()
	{
		assertIsList("players", CONTRACT.get("players"));
	}

	@Test
	public void topLevelObjectsPresent()
	{
		assertIsList("objects", CONTRACT.get("objects"));
	}

	@Test
	public void topLevelGroundItemsPresent()
	{
		assertIsList("groundItems", CONTRACT.get("groundItems"));
	}

	@Test
	public void topLevelWidgetsPresent()
	{
		assertTrue("widgets missing", CONTRACT.containsKey("widgets"));
	}

	@Test
	public void topLevelInterfacesPresent()
	{
		assertIsList("interfaces", CONTRACT.get("interfaces"));
	}

	@Test
	public void topLevelInventoryPresent()
	{
		assertIsList("inventory", CONTRACT.get("inventory"));
	}

	@Test
	public void topLevelEquipmentPresent()
	{
		assertTrue("equipment missing", CONTRACT.containsKey("equipment"));
	}

	@Test
	public void topLevelEventsPresent()
	{
		assertIsList("events", CONTRACT.get("events"));
	}

	// ------------------------------------------------------------------ //
	// Player fields — matches buildPlayerMap() in GameBridgePlugin
	// ------------------------------------------------------------------ //

	@Test
	public void playerHasAllFields()
	{
		Map<?, ?> player = map("player");
		assertHasFields(player, "player", "name", "worldX", "worldY", "plane", "animation", "hp", "prayer");
	}

	@Test
	public void playerWorldCoordsAreNumbers()
	{
		Map<?, ?> player = map("player");
		assertIsNumber("player.worldX", player.get("worldX"));
		assertIsNumber("player.worldY", player.get("worldY"));
		assertIsNumber("player.plane",  player.get("plane"));
	}

	// ------------------------------------------------------------------ //
	// Camera fields — matches buildCameraMap() in GameBridgePlugin
	// ------------------------------------------------------------------ //

	@Test
	public void cameraHasAllFields()
	{
		assertHasFields(map("camera"), "camera", "yaw", "pitch", "x", "y", "z");
	}

	// ------------------------------------------------------------------ //
	// NPC fields — matches serializeActor() in GameBridgePlugin
	// ------------------------------------------------------------------ //

	@Test
	public void npcEntriesHaveAllFields()
	{
		List<?> npcs = list("npcs");
		assertFalse("npcs array must not be empty", npcs.isEmpty());
		for (Object n : npcs)
		{
			Map<?, ?> npc = castMap("npc entry", n);
			assertHasFields(npc, "npc",
				"id", "index", "name", "worldX", "worldY", "plane",
				"animation", "combatLevel",
				"onScreen", "canvasX", "canvasY", "hull",
				"minimapX", "minimapY");
		}
	}

	@Test
	public void npcIndexIsUniquePerEntry()
	{
		// index is the per-instance identifier (unlike id, which is the shared
		// composition id) — the contract's two NPC entries must have distinct indices.
		List<?> npcs = list("npcs");
		Set<Object> indices = npcs.stream()
			.map(n -> castMap("npc", n).get("index"))
			.collect(Collectors.toSet());
		assertEquals("npc indices must be unique", npcs.size(), indices.size());
	}

	// ------------------------------------------------------------------ //
	// Player fields — matches buildPlayersList()/serializeActor() in TickMessageBuilder
	// ------------------------------------------------------------------ //

	@Test
	public void playerEntriesHaveAllFields()
	{
		List<?> players = list("players");
		assertFalse("players array must not be empty", players.isEmpty());
		for (Object p : players)
		{
			Map<?, ?> player = castMap("player entry", p);
			assertHasFields(player, "player entry",
				"id", "name", "worldX", "worldY", "plane",
				"animation", "combatLevel",
				"onScreen", "canvasX", "canvasY", "hull",
				"minimapX", "minimapY");
		}
	}

	@Test
	public void onScreenPlayerHasHullAndCanvas()
	{
		for (Object p : list("players"))
		{
			Map<?, ?> player = castMap("player", p);
			boolean onScreen = Boolean.TRUE.equals(player.get("onScreen"));
			if (onScreen)
			{
				assertNotNull("on-screen player must have hull",    player.get("hull"));
				assertNotNull("on-screen player must have canvasX", player.get("canvasX"));
				assertNotNull("on-screen player must have canvasY", player.get("canvasY"));
			}
			else
			{
				assertNull("off-screen player hull must be null",    player.get("hull"));
				assertNull("off-screen player canvasX must be null", player.get("canvasX"));
			}
		}
	}

	// ------------------------------------------------------------------ //
	// Ground item fields — matches serializeGroundItem() in TickMessageBuilder
	// ------------------------------------------------------------------ //

	@Test
	public void groundItemEntriesHaveAllFields()
	{
		List<?> items = list("groundItems");
		assertFalse("groundItems array must not be empty", items.isEmpty());
		for (Object i : items)
		{
			Map<?, ?> item = castMap("ground item entry", i);
			assertHasFields(item, "ground item",
				"id", "name", "quantity", "worldX", "worldY", "plane",
				"onScreen", "canvasX", "canvasY", "hull",
				"minimapX", "minimapY");
		}
	}

	@Test
	public void onScreenGroundItemHasHullAndCanvas()
	{
		for (Object i : list("groundItems"))
		{
			Map<?, ?> item = castMap("ground item", i);
			boolean onScreen = Boolean.TRUE.equals(item.get("onScreen"));
			if (onScreen)
			{
				assertNotNull("on-screen ground item must have hull",    item.get("hull"));
				assertNotNull("on-screen ground item must have canvasX", item.get("canvasX"));
				assertNotNull("on-screen ground item must have canvasY", item.get("canvasY"));
			}
			else
			{
				assertNull("off-screen ground item hull must be null",    item.get("hull"));
				assertNull("off-screen ground item canvasX must be null", item.get("canvasX"));
			}
		}
	}

	@Test
	public void onScreenNpcHasHullAndCanvas()
	{
		for (Object n : list("npcs"))
		{
			Map<?, ?> npc = castMap("npc", n);
			boolean onScreen = Boolean.TRUE.equals(npc.get("onScreen"));
			if (onScreen)
			{
				assertNotNull("on-screen NPC must have hull",    npc.get("hull"));
				assertNotNull("on-screen NPC must have canvasX", npc.get("canvasX"));
				assertNotNull("on-screen NPC must have canvasY", npc.get("canvasY"));
			}
			else
			{
				assertNull("off-screen NPC hull must be null",    npc.get("hull"));
				assertNull("off-screen NPC canvasX must be null", npc.get("canvasX"));
			}
		}
	}

	@Test
	public void npcContractHasBothOnAndOffScreenEntries()
	{
		boolean hasOn  = false;
		boolean hasOff = false;
		for (Object n : list("npcs"))
		{
			boolean on = Boolean.TRUE.equals(castMap("npc", n).get("onScreen"));
			hasOn  |= on;
			hasOff |= !on;
		}
		assertTrue("contract must contain an on-screen NPC",  hasOn);
		assertTrue("contract must contain an off-screen NPC", hasOff);
	}

	// ------------------------------------------------------------------ //
	// Object fields — matches serializeTileObject() in GameBridgePlugin
	// ------------------------------------------------------------------ //

	@Test
	public void objectEntriesHaveAllFields()
	{
		List<?> objects = list("objects");
		assertFalse("objects array must not be empty", objects.isEmpty());
		for (Object o : objects)
		{
			Map<?, ?> obj = castMap("object entry", o);
			assertHasFields(obj, "object",
				"id", "name", "category",
				"worldX", "worldY", "plane",
				"onScreen", "canvasX", "canvasY", "hull",
				"minimapX", "minimapY");
		}
	}

	@Test
	public void allFourObjectCategoriesPresent()
	{
		Set<Object> categories = list("objects").stream()
			.map(o -> castMap("object", o).get("category"))
			.collect(Collectors.toSet());
		Set<String> expected = new HashSet<>(Arrays.asList("game", "wall", "ground", "decorative"));
		Set<String> missing = new HashSet<>(expected);
		missing.removeAll(categories);
		assertTrue("contract missing categories: " + missing, missing.isEmpty());
	}

	@Test
	public void objectCategoryValuesAreStrings()
	{
		for (Object o : list("objects"))
		{
			Object cat = castMap("object", o).get("category");
			assertTrue("category must be a String, got: " + cat, cat instanceof String);
		}
	}

	// ------------------------------------------------------------------ //
	// Widget fields — matches serializeWidget() in GameBridgePlugin
	// ------------------------------------------------------------------ //

	@Test
	public void widgetEntriesHaveAllFields()
	{
		for (Object w : list("widgets"))
		{
			Map<?, ?> widget = castMap("widget", w);
			assertHasFields(widget, "widget", "groupId", "childId", "itemId", "quantity", "bounds", "text");
			Map<?, ?> bounds = castMap("widget.bounds", widget.get("bounds"));
			assertHasFields(bounds, "widget.bounds", "x", "y", "width", "height");
		}
	}

	@Test
	public void widgetUsesQuantityNotQty()
	{
		// Widgets use "quantity"; item-slot arrays use "qty" — both are intentional
		for (Object w : list("widgets"))
		{
			Map<?, ?> widget = castMap("widget", w);
			assertTrue("widget must have 'quantity' key", widget.containsKey("quantity"));
			assertFalse("widget must NOT have 'qty' (that key is for item slots)", widget.containsKey("qty"));
		}
	}

	// ------------------------------------------------------------------ //
	// Interface fields — matches buildInterfacesList() in GameBridgePlugin
	// ------------------------------------------------------------------ //

	@Test
	public void interfaceEntriesHaveAllFields()
	{
		List<?> interfaces = list("interfaces");
		assertFalse("interfaces array must not be empty", interfaces.isEmpty());
		for (Object i : interfaces)
		{
			Map<?, ?> iface = castMap("interface entry", i);
			assertHasFields(iface, "interface", "groupId", "childId", "itemId", "quantity", "bounds", "text");
			Map<?, ?> bounds = castMap("interface.bounds", iface.get("bounds"));
			assertHasFields(bounds, "interface.bounds", "x", "y", "width", "height");
		}
	}

	@Test
	public void interfaceBoundsHavePositiveArea()
	{
		for (Object i : list("interfaces"))
		{
			Map<?, ?> bounds = castMap("interface.bounds", castMap("interface", i).get("bounds"));
			assertTrue("interface bounds width must be > 0",  ((Number) bounds.get("width")).intValue()  > 0);
			assertTrue("interface bounds height must be > 0", ((Number) bounds.get("height")).intValue() > 0);
		}
	}

	// ------------------------------------------------------------------ //
	// Minimap fields — minimapX / minimapY on NPC and object entries
	// ------------------------------------------------------------------ //

	@Test
	public void npcMinimapFieldsPresent()
	{
		for (Object n : list("npcs"))
		{
			Map<?, ?> npc = castMap("npc", n);
			assertTrue("npc must have minimapX key", npc.containsKey("minimapX"));
			assertTrue("npc must have minimapY key", npc.containsKey("minimapY"));
		}
	}

	@Test
	public void objectMinimapFieldsPresent()
	{
		for (Object o : list("objects"))
		{
			Map<?, ?> obj = castMap("object", o);
			assertTrue("object must have minimapX key", obj.containsKey("minimapX"));
			assertTrue("object must have minimapY key", obj.containsKey("minimapY"));
		}
	}

	// ------------------------------------------------------------------ //
	// Item slot fields — inventory / equipment / container items
	// ------------------------------------------------------------------ //

	@Test
	public void inventorySlotsHaveRequiredFields()
	{
		for (Object s : list("inventory"))
		{
			assertHasFields(castMap("inventory slot", s), "inventory slot", "slot", "itemId", "qty");
		}
	}

	@Test
	public void equipmentSlotsHaveRequiredFields()
	{
		for (Object s : list("equipment"))
		{
			assertHasFields(castMap("equipment slot", s), "equipment slot", "slot", "itemId", "qty");
		}
	}

	// ------------------------------------------------------------------ //
	// Events — all types present with correct fields
	// ------------------------------------------------------------------ //

	@Test
	public void allEventTypesPresent()
	{
		Set<Object> found = list("events").stream()
			.map(e -> castMap("event", e).get("type"))
			.collect(Collectors.toSet());
		for (String t : new String[]{"xp", "chat", "container", "animation", "varbit", "interacting"})
		{
			assertTrue("event type missing: " + t, found.contains(t));
		}
	}

	@Test
	public void xpEventFields()
	{
		Map<?, ?> ev = findEvent("xp");
		assertHasFields(ev, "xp event", "skill", "xp", "level", "boostedLevel");
	}

	@Test
	public void chatEventFields()
	{
		// msgType/name/message — NOT "type" which is the discriminator
		Map<?, ?> ev = findEvent("chat");
		assertHasFields(ev, "chat event", "msgType", "name", "message");
	}

	@Test
	public void containerEventFields()
	{
		Map<?, ?> ev = findEvent("container");
		assertHasFields(ev, "container event", "containerId", "items");
		List<?> items = (List<?>) ev.get("items");
		for (Object item : items)
		{
			assertHasFields(castMap("container item", item), "container item", "slot", "itemId", "qty");
		}
	}

	@Test
	public void animationEventFields()
	{
		Map<?, ?> ev = findEvent("animation");
		assertHasFields(ev, "animation event", "actor", "animId");
	}

	@Test
	public void varbitEventFields()
	{
		Map<?, ?> ev = findEvent("varbit");
		assertHasFields(ev, "varbit event", "varpId", "varbitId", "value");
	}

	@Test
	public void interactingEventFields()
	{
		Map<?, ?> ev = findEvent("interacting");
		assertTrue("interacting event must have 'target' key", ev.containsKey("target"));
		// target may be null (no current interaction)
	}

	// ------------------------------------------------------------------ //
	// HullFilter integration — exercise the filter against contract data
	// ------------------------------------------------------------------ //

	@Test
	public void hullFilterMatchesContractNpcById()
	{
		Map<?, ?> npc = castMap("npc", list("npcs").get(0));
		int id = ((Number) npc.get("id")).intValue();
		HullFilter filter = new HullFilter();
		filter.parse(String.valueOf(id));
		assertTrue("filter should match contract NPC by id",
			filter.matches(id, (String) npc.get("name")));
	}

	@Test
	public void hullFilterMatchesContractNpcByName()
	{
		Map<?, ?> npc = castMap("npc", list("npcs").get(0));
		String name = (String) npc.get("name");
		HullFilter filter = new HullFilter();
		filter.parse(name);
		assertTrue("filter should match contract NPC by name",
			filter.matches(99999, name));
	}

	@Test
	public void hullFilterMatchesContractObjectByName()
	{
		Map<?, ?> obj = castMap("object", list("objects").get(0));
		String name = (String) obj.get("name");
		HullFilter filter = new HullFilter();
		filter.parse(name);
		assertTrue("filter should match contract object by name",
			filter.matches(99999, name));
	}

	@Test
	public void hullFilterExcludesUnrelatedEntry()
	{
		// Filter on first NPC ID — second NPC (different ID) must not match
		List<?> npcs = list("npcs");
		if (npcs.size() < 2)
		{
			return; // not enough data to test exclusion
		}
		int id1 = ((Number) castMap("npc", npcs.get(0)).get("id")).intValue();
		Map<?, ?> npc2 = castMap("npc", npcs.get(1));
		int id2 = ((Number) npc2.get("id")).intValue();
		if (id1 == id2)
		{
			return; // same ID — skip
		}
		HullFilter filter = new HullFilter();
		filter.parse(String.valueOf(id1));
		assertFalse("filter on id1 should NOT match npc2",
			filter.matches(id2, (String) npc2.get("name")));
	}

	@Test
	public void emptyHullFilterMatchesAnyContractEntry()
	{
		HullFilter filter = new HullFilter();
		for (Object n : list("npcs"))
		{
			Map<?, ?> npc = castMap("npc", n);
			int id = ((Number) npc.get("id")).intValue();
			assertTrue(filter.matches(id, (String) npc.get("name")));
		}
	}

	// ------------------------------------------------------------------ //
	// Helpers
	// ------------------------------------------------------------------ //

	@SuppressWarnings("unchecked")
	private static Map<String, Object> map(String key)
	{
		return (Map<String, Object>) CONTRACT.get(key);
	}

	@SuppressWarnings("unchecked")
	private static List<?> list(String key)
	{
		return (List<?>) CONTRACT.get(key);
	}

	@SuppressWarnings("unchecked")
	private static Map<String, Object> castMap(String label, Object o)
	{
		assertTrue(label + " must be a Map", o instanceof Map);
		return (Map<String, Object>) o;
	}

	private static void assertIsMap(String name, Object value)
	{
		assertTrue(name + " must be a Map", value instanceof Map);
	}

	private static void assertIsList(String name, Object value)
	{
		assertTrue(name + " must be a List", value instanceof List);
	}

	private static void assertIsNumber(String name, Object value)
	{
		assertTrue(name + " must be a Number", value instanceof Number);
	}

	private static void assertHasFields(Map<?, ?> map, String label, String... fields)
	{
		for (String field : fields)
		{
			assertTrue(label + " missing field '" + field + "'", map.containsKey(field));
		}
	}

	private static Map<?, ?> findEvent(String type)
	{
		return list("events").stream()
			.map(e -> (Map<?, ?>) e)
			.filter(e -> type.equals(e.get("type")))
			.findFirst()
			.orElseThrow(() -> new AssertionError(
				"No event of type '" + type + "' found in contract events array"));
	}
}
