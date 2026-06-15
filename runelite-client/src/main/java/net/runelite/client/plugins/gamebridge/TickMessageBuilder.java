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

import java.awt.Rectangle;
import java.awt.Shape;
import java.awt.geom.PathIterator;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import net.runelite.api.Actor;
import net.runelite.api.Client;
import net.runelite.api.DecorativeObject;
import net.runelite.api.GameObject;
import net.runelite.api.GroundObject;
import net.runelite.api.HashTable;
import net.runelite.api.Item;
import net.runelite.api.ItemComposition;
import net.runelite.api.ItemContainer;
import net.runelite.api.MenuEntry;
import net.runelite.api.NPC;
import net.runelite.api.ObjectComposition;
import net.runelite.api.Perspective;
import net.runelite.api.Player;
import net.runelite.api.Point;
import net.runelite.api.Skill;
import net.runelite.api.Tile;
import net.runelite.api.TileItem;
import net.runelite.api.TileObject;
import net.runelite.api.WallObject;
import net.runelite.api.WidgetNode;
import net.runelite.api.coords.LocalPoint;
import net.runelite.api.coords.WorldPoint;
import net.runelite.api.widgets.Widget;

/**
 * Assembles the per-tick JSON message from live game state.
 * Receives accumulated event lists from the plugin and merges them into the
 * outgoing message; does not itself subscribe to any events.
 */
class TickMessageBuilder
{
	// 149 = Inventory, 12 = Bank, 387 = Equipment (Wornitems), 192 = Deposit box
	private static final int[] WIDGET_GROUPS = {149, 12, 387, 192};

	private final Client client;
	private final GameBridgeConfig config;
	private final HullFilter hullFilter;
	private final HullFilter objectFilter;

	TickMessageBuilder(Client client, GameBridgeConfig config, HullFilter hullFilter, HullFilter objectFilter)
	{
		this.client = client;
		this.config = config;
		this.hullFilter = hullFilter;
		this.objectFilter = objectFilter;
	}

	Map<String, Object> build(List<Map<String, Object>> pendingEvents, Map<String, int[]> pendingVarbits)
	{
		Map<String, Object> msg = new LinkedHashMap<>();
		msg.put("type", "tick");
		msg.put("tick", client.getTickCount());

		Player local = client.getLocalPlayer();
		if (local != null)
		{
			msg.put("player", buildPlayerMap(local));
		}

		if (config.exposeCamera())
		{
			msg.put("camera", buildCameraMap());
		}

		if (config.exposeNpcs())
		{
			List<Map<String, Object>> npcList = new ArrayList<>();
			for (NPC npc : client.getNpcs())
			{
				Map<String, Object> m = serializeActor(npc, npc.getId(), npc.getName());
				// Composition id (npc.getId()) is shared by every instance of an NPC type
				// (e.g. all "Goblin"s); index is the unique per-instance identifier needed
				// to track a specific NPC across ticks (e.g. "did the one I attacked die?").
				m.put("index", npc.getIndex());
				npcList.add(m);
			}
			msg.put("npcs", npcList);
		}

		if (config.exposePlayers())
		{
			msg.put("players", buildPlayersList());
		}

		if (config.exposeObjects())
		{
			msg.put("objects", buildObjectsList());
		}

		if (config.exposeGroundItems())
		{
			msg.put("groundItems", buildGroundItemsList());
		}

		if (config.exposeWidgets())
		{
			msg.put("widgets", buildWidgetsList());
		}

		if (config.exposeInterfaces())
		{
			msg.put("interfaces", buildInterfacesList());
		}

		if (config.exposeMenu())
		{
			msg.put("menu", buildMenuMap());
		}

		// 93 = inventory (INV), 94 = worn equipment (WORN)
		if (config.exposeInventory())
		{
			msg.put("inventory", buildItemContainerList(93));
			msg.put("equipment", buildItemContainerList(94));
		}

		// Merge pending events and flushed varbits into a single list
		List<Map<String, Object>> events = new ArrayList<>(pendingEvents);
		for (int[] v : pendingVarbits.values())
		{
			Map<String, Object> e = new LinkedHashMap<>();
			e.put("type", "varbit");
			e.put("varpId", v[0]);
			e.put("varbitId", v[1]);
			e.put("value", v[2]);
			events.add(e);
		}
		msg.put("events", events);

		return msg;
	}

	// -------------------------------------------------------------------------
	// Left-click action text
	// -------------------------------------------------------------------------

	/**
	 * The text describing the default (left-click) action under the cursor right
	 * now, e.g. {@code "Walk here"} or {@code "Attack Goblin (level-2)"}.
	 * <p>
	 * Mirrors {@code MouseHighlightOverlay}: {@code Client.getMenuEntries()}
	 * returns entries in reverse display order, so the last element is the
	 * top/default entry — the one that would fire on a plain left-click.
	 *
	 * @return {@code "option target"} (or just {@code "option"} if there's no
	 *         target), or {@code ""} if no menu entry is available.
	 */
	String currentTooltip()
	{
		MenuEntry[] menuEntries = client.getMenuEntries();
		if (menuEntries.length == 0)
		{
			return "";
		}

		MenuEntry entry = menuEntries[menuEntries.length - 1];
		String option = entry.getOption();
		String target = entry.getTarget();

		if (option == null)
		{
			option = "";
		}
		if (target == null || target.isEmpty())
		{
			return option;
		}
		return option + " " + target;
	}

	// -------------------------------------------------------------------------
	// Live clickbox subscriptions (findNearest)
	// -------------------------------------------------------------------------

	/**
	 * Finds the entity of the given {@code kind} nearest to the local player
	 * that matches {@code id}/{@code name}, and serializes it the same way as
	 * the per-tick lists (so hull/canvas fields are identical).
	 *
	 * @return {@code {"subId": subId, "found": true, ...entity fields}} or
	 *         {@code {"subId": subId, "found": false}} if nothing matches.
	 */
	Map<String, Object> findNearest(String subId, String kind, Integer id, String name)
	{
		Map<String, Object> result = new LinkedHashMap<>();
		result.put("subId", subId);

		Map<String, Object> match;
		switch (kind)
		{
			case "npc":
				match = findNearestNpc(id, name);
				break;
			case "player":
				match = findNearestPlayer(id, name);
				break;
			case "object":
				match = findNearestObject(id, name);
				break;
			case "groundItem":
				match = findNearestGroundItem(id, name);
				break;
			default:
				match = null;
				break;
		}

		if (match != null)
		{
			result.put("found", true);
			result.putAll(match);
		}
		else
		{
			result.put("found", false);
		}
		return result;
	}

	private Map<String, Object> findNearestNpc(Integer filterId, String filterName)
	{
		WorldPoint origin = playerLocation();
		NPC best = null;
		int bestDist = Integer.MAX_VALUE;
		for (NPC npc : client.getNpcs())
		{
			if (npc == null)
			{
				continue;
			}
			if (!matchesIdOrName(npc.getId(), npc.getName(), filterId, filterName))
			{
				continue;
			}
			int dist = manhattanDistance(origin, npc.getWorldLocation());
			if (dist < bestDist)
			{
				bestDist = dist;
				best = npc;
			}
		}
		if (best == null)
		{
			return null;
		}
		Map<String, Object> m = serializeActor(best, best.getId(), best.getName());
		m.put("index", best.getIndex());
		return m;
	}

	private Map<String, Object> findNearestPlayer(Integer filterId, String filterName)
	{
		WorldPoint origin = playerLocation();
		Player best = null;
		int bestDist = Integer.MAX_VALUE;
		for (Player player : client.getPlayers())
		{
			if (player == null || player.getName() == null)
			{
				continue;
			}
			if (!matchesIdOrName(player.getId(), player.getName(), filterId, filterName))
			{
				continue;
			}
			int dist = manhattanDistance(origin, player.getWorldLocation());
			if (dist < bestDist)
			{
				bestDist = dist;
				best = player;
			}
		}
		if (best == null)
		{
			return null;
		}
		return serializeActor(best, best.getId(), best.getName());
	}

	private Map<String, Object> findNearestObject(Integer filterId, String filterName)
	{
		WorldPoint origin = playerLocation();
		NearestObject nearest = new NearestObject();

		Tile[][][] tiles = client.getScene().getTiles();
		int plane = client.getPlane();
		for (Tile[] row : tiles[plane])
		{
			for (Tile tile : row)
			{
				if (tile == null)
				{
					continue;
				}
				for (GameObject go : tile.getGameObjects())
				{
					if (go != null)
					{
						considerObject(go, "game", filterId, filterName, origin, nearest);
					}
				}
				WallObject wall = tile.getWallObject();
				if (wall != null)
				{
					considerObject(wall, "wall", filterId, filterName, origin, nearest);
				}
				GroundObject ground = tile.getGroundObject();
				if (ground != null)
				{
					considerObject(ground, "ground", filterId, filterName, origin, nearest);
				}
				DecorativeObject deco = tile.getDecorativeObject();
				if (deco != null)
				{
					considerObject(deco, "decorative", filterId, filterName, origin, nearest);
				}
			}
		}

		if (nearest.obj == null)
		{
			return null;
		}
		return serializeTileObject(nearest.obj, nearest.name, nearest.category);
	}

	private void considerObject(TileObject obj, String category, Integer filterId, String filterName,
		WorldPoint origin, NearestObject nearest)
	{
		int id = obj.getId();
		String name = resolveName(id);
		if (!matchesIdOrName(id, name, filterId, filterName))
		{
			return;
		}
		int dist = manhattanDistance(origin, obj.getWorldLocation());
		if (dist < nearest.dist)
		{
			nearest.dist = dist;
			nearest.obj = obj;
			nearest.name = name;
			nearest.category = category;
		}
	}

	private static final class NearestObject
	{
		TileObject obj;
		String name;
		String category;
		int dist = Integer.MAX_VALUE;
	}

	private Map<String, Object> findNearestGroundItem(Integer filterId, String filterName)
	{
		WorldPoint origin = playerLocation();
		Tile bestTile = null;
		TileItem bestItem = null;
		int bestDist = Integer.MAX_VALUE;

		Tile[][][] tiles = client.getScene().getTiles();
		int plane = client.getPlane();
		for (Tile[] row : tiles[plane])
		{
			for (Tile tile : row)
			{
				if (tile == null)
				{
					continue;
				}
				List<TileItem> groundItems = tile.getGroundItems();
				if (groundItems == null)
				{
					continue;
				}
				for (TileItem item : groundItems)
				{
					if (item == null)
					{
						continue;
					}
					String name = resolveItemName(item.getId());
					if (!matchesIdOrName(item.getId(), name, filterId, filterName))
					{
						continue;
					}
					int dist = manhattanDistance(origin, tile.getWorldLocation());
					if (dist < bestDist)
					{
						bestDist = dist;
						bestTile = tile;
						bestItem = item;
					}
				}
			}
		}

		if (bestItem == null)
		{
			return null;
		}
		return serializeGroundItem(bestTile, bestItem);
	}

	private WorldPoint playerLocation()
	{
		Player local = client.getLocalPlayer();
		return local != null ? local.getWorldLocation() : new WorldPoint(0, 0, 0);
	}

	private static int manhattanDistance(WorldPoint a, WorldPoint b)
	{
		return Math.abs(a.getX() - b.getX()) + Math.abs(a.getY() - b.getY());
	}

	/**
	 * AND semantics when both {@code filterId} and {@code filterName} are given;
	 * name comparison is case-insensitive. At least one of the two must be
	 * non-null for a match.
	 */
	static boolean matchesIdOrName(int entityId, String entityName, Integer filterId, String filterName)
	{
		if (filterId == null && filterName == null)
		{
			return false;
		}
		if (filterId != null && entityId != filterId)
		{
			return false;
		}
		if (filterName != null && (entityName == null || !entityName.equalsIgnoreCase(filterName)))
		{
			return false;
		}
		return true;
	}

	// -------------------------------------------------------------------------
	// Top-level section builders
	// -------------------------------------------------------------------------

	private Map<String, Object> buildPlayerMap(Player player)
	{
		Map<String, Object> m = new LinkedHashMap<>();
		WorldPoint wp = player.getWorldLocation();
		m.put("name", player.getName());
		m.put("worldX", wp.getX());
		m.put("worldY", wp.getY());
		m.put("plane", wp.getPlane());
		m.put("animation", player.getAnimation());
		m.put("hp", client.getBoostedSkillLevel(Skill.HITPOINTS));
		m.put("prayer", client.getBoostedSkillLevel(Skill.PRAYER));
		return m;
	}

	private Map<String, Object> buildCameraMap()
	{
		Map<String, Object> m = new LinkedHashMap<>();
		m.put("yaw", client.getCameraYaw());
		m.put("pitch", client.getCameraPitch());
		m.put("x", client.getCameraX());
		m.put("y", client.getCameraY());
		m.put("z", client.getCameraZ());
		m.put("baseX", client.getBaseX());
		m.put("baseY", client.getBaseY());
		return m;
	}

	private List<Map<String, Object>> buildPlayersList()
	{
		List<Map<String, Object>> list = new ArrayList<>();
		Player local = client.getLocalPlayer();
		for (Player player : client.getPlayers())
		{
			if (player == null || player == local || player.getName() == null)
			{
				continue;
			}
			list.add(serializeActor(player, player.getId(), player.getName()));
		}
		return list;
	}

	private List<Map<String, Object>> buildGroundItemsList()
	{
		List<Map<String, Object>> list = new ArrayList<>();
		Tile[][][] tiles = client.getScene().getTiles();
		int plane = client.getPlane();
		for (Tile[] row : tiles[plane])
		{
			for (Tile tile : row)
			{
				if (tile == null)
				{
					continue;
				}
				List<TileItem> groundItems = tile.getGroundItems();
				if (groundItems == null)
				{
					continue;
				}
				for (TileItem item : groundItems)
				{
					if (item != null)
					{
						list.add(serializeGroundItem(tile, item));
					}
				}
			}
		}
		return list;
	}

	private List<Map<String, Object>> buildObjectsList()
	{
		List<Map<String, Object>> list = new ArrayList<>();
		Tile[][][] tiles = client.getScene().getTiles();
		int plane = client.getPlane();
		for (Tile[] row : tiles[plane])
		{
			for (Tile tile : row)
			{
				if (tile == null)
				{
					continue;
				}
				for (GameObject go : tile.getGameObjects())
				{
					if (go != null)
					{
						addObjectIfIncluded(list, go, "game");
					}
				}
				WallObject wall = tile.getWallObject();
				if (wall != null)
				{
					addObjectIfIncluded(list, wall, "wall");
				}
				GroundObject ground = tile.getGroundObject();
				if (ground != null)
				{
					addObjectIfIncluded(list, ground, "ground");
				}
				DecorativeObject deco = tile.getDecorativeObject();
				if (deco != null)
				{
					addObjectIfIncluded(list, deco, "decorative");
				}
			}
		}
		return list;
	}

	private void addObjectIfIncluded(List<Map<String, Object>> list, TileObject obj, String category)
	{
		int id = obj.getId();
		String name = resolveName(id);
		if (shouldIncludeObject(id, name))
		{
			list.add(serializeTileObject(obj, name, category));
		}
	}

	private boolean shouldIncludeObject(int id, String name)
	{
		if (config.debugAllObjects())
		{
			return true;
		}
		if (!objectFilter.isEmpty() && objectFilter.matches(id, name))
		{
			return true;
		}
		if (config.sendAllNamedObjects())
		{
			return name != null && !name.equals("null") && !name.equals("unknown");
		}
		return false;
	}

	private List<Map<String, Object>> buildWidgetsList()
	{
		List<Map<String, Object>> list = new ArrayList<>();
		for (int groupId : WIDGET_GROUPS)
		{
			for (int childId = 0; childId < 512; childId++)
			{
				Widget w = client.getWidget(groupId, childId);
				if (w == null)
				{
					break;
				}
				if (!w.isHidden())
				{
					list.add(serializeWidget(groupId, childId, w));
				}
				// Dynamic children (item slots, bank slots, etc.) live under container widgets
				// and are not reachable via the flat childId scan above.
				Widget[] dyn = w.getDynamicChildren();
				if (dyn != null)
				{
					for (Widget dynChild : dyn)
					{
						if (dynChild != null && !dynChild.isHidden())
						{
							list.add(serializeWidget(groupId, dynChild.getIndex(), dynChild));
						}
					}
				}
			}
		}
		return list;
	}

	private List<Map<String, Object>> buildInterfacesList()
	{
		List<Map<String, Object>> list = new ArrayList<>();
		HashTable<WidgetNode> componentTable = client.getComponentTable();
		for (WidgetNode node : componentTable)
		{
			int groupId = node.getId();
			for (int childId = 0; childId < 512; childId++)
			{
				Widget w = client.getWidget(groupId, childId);
				if (w == null)
				{
					break;
				}
				if (!w.isHidden())
				{
					Rectangle b = w.getBounds();
					if (b.width > 0 && b.height > 0)
					{
						list.add(serializeWidget(groupId, childId, w));
					}
				}
				Widget[] dynChildren = w.getDynamicChildren();
				if (dynChildren != null)
				{
					for (Widget dyn : dynChildren)
					{
						if (dyn != null && !dyn.isHidden())
						{
							Rectangle b = dyn.getBounds();
							if (b.width > 0 && b.height > 0)
							{
								list.add(serializeWidget(groupId, dyn.getIndex(), dyn));
							}
						}
					}
				}
			}
		}
		return list;
	}

	// Pixel layout of the native right-click menu, reverse-engineered in
	// InteractHighlightOverlay.hoveredMenuEntry: a 19px "Choose Option" header
	// followed by 15px-tall entry rows. Client.getMenuEntries() returns entries
	// in reverse display order (last element is the top/first row shown).
	private static final int MENU_HEADER_HEIGHT = 19;
	private static final int MENU_ENTRY_HEIGHT = 15;

	private Map<String, Object> buildMenuMap()
	{
		Map<String, Object> m = new LinkedHashMap<>();
		boolean open = client.isMenuOpen();
		m.put("open", open);
		if (!open)
		{
			m.put("entries", new ArrayList<>());
			return m;
		}

		int menuX = client.getMenuX();
		int menuY = client.getMenuY();
		int menuWidth = client.getMenuWidth();
		m.put("x", menuX);
		m.put("y", menuY);
		m.put("width", menuWidth);
		m.put("height", client.getMenuHeight());

		MenuEntry[] menuEntries = client.getMenuEntries();
		List<Map<String, Object>> entries = new ArrayList<>(menuEntries.length);
		for (int displayIndex = 0; displayIndex < menuEntries.length; displayIndex++)
		{
			MenuEntry entry = menuEntries[menuEntries.length - 1 - displayIndex];

			Map<String, Object> e = new LinkedHashMap<>();
			e.put("option", entry.getOption());
			e.put("target", entry.getTarget());
			e.put("identifier", entry.getIdentifier());
			e.put("type", entry.getType().getId());

			Map<String, Object> bounds = new LinkedHashMap<>();
			bounds.put("x", menuX);
			bounds.put("y", menuY + MENU_HEADER_HEIGHT + displayIndex * MENU_ENTRY_HEIGHT);
			bounds.put("width", menuWidth);
			bounds.put("height", MENU_ENTRY_HEIGHT);
			e.put("bounds", bounds);

			entries.add(e);
		}
		m.put("entries", entries);

		return m;
	}

	private List<Map<String, Object>> buildItemContainerList(int containerId)
	{
		ItemContainer container = client.getItemContainer(containerId);
		if (container == null)
		{
			return new ArrayList<>();
		}
		Item[] items = container.getItems();
		List<Map<String, Object>> slots = new ArrayList<>(items.length);
		for (int i = 0; i < items.length; i++)
		{
			Map<String, Object> slot = new LinkedHashMap<>();
			slot.put("slot", i);
			slot.put("itemId", items[i].getId());
			slot.put("qty", items[i].getQuantity());
			slots.add(slot);
		}
		return slots;
	}

	// -------------------------------------------------------------------------
	// Serialisation helpers
	// -------------------------------------------------------------------------

	private Map<String, Object> serializeActor(Actor actor, int id, String name)
	{
		Map<String, Object> m = new LinkedHashMap<>();
		m.put("id", id);
		m.put("name", name);
		WorldPoint wp = actor.getWorldLocation();
		m.put("worldX", wp.getX());
		m.put("worldY", wp.getY());
		m.put("plane", wp.getPlane());
		m.put("animation", actor.getAnimation());
		m.put("combatLevel", actor.getCombatLevel());
		applyHullFields(m, actor.getConvexHull(), id, name);
		int[] mp = minimapPoint(actor.getLocalLocation());
		m.put("minimapX", mp != null ? mp[0] : null);
		m.put("minimapY", mp != null ? mp[1] : null);
		return m;
	}

	private Map<String, Object> serializeTileObject(TileObject obj, String name, String category)
	{
		int id = obj.getId();
		Map<String, Object> m = new LinkedHashMap<>();
		m.put("id", id);
		m.put("name", name);
		m.put("category", category);
		WorldPoint wp = obj.getWorldLocation();
		m.put("worldX", wp.getX());
		m.put("worldY", wp.getY());
		m.put("plane", wp.getPlane());
		applyHullFields(m, getObjectHull(obj), id, name);
		int[] mp = minimapPoint(obj.getLocalLocation());
		m.put("minimapX", mp != null ? mp[0] : null);
		m.put("minimapY", mp != null ? mp[1] : null);
		return m;
	}

	private Map<String, Object> serializeGroundItem(Tile tile, TileItem item)
	{
		int id = item.getId();
		String name = resolveItemName(id);
		Map<String, Object> m = new LinkedHashMap<>();
		m.put("id", id);
		m.put("name", name);
		m.put("quantity", item.getQuantity());
		WorldPoint wp = tile.getWorldLocation();
		m.put("worldX", wp.getX());
		m.put("worldY", wp.getY());
		m.put("plane", wp.getPlane());
		LocalPoint lp = tile.getLocalLocation();
		applyHullFields(m, lp != null ? Perspective.getCanvasTilePoly(client, lp) : null, id, name);
		int[] mp = minimapPoint(lp);
		m.put("minimapX", mp != null ? mp[0] : null);
		m.put("minimapY", mp != null ? mp[1] : null);
		return m;
	}

	private Map<String, Object> serializeWidget(int groupId, int childId, Widget w)
	{
		Map<String, Object> m = new LinkedHashMap<>();
		m.put("groupId", groupId);
		m.put("childId", childId);
		m.put("itemId", w.getItemId());
		m.put("quantity", w.getItemQuantity());
		Rectangle bounds = w.getBounds();
		Map<String, Object> b = new LinkedHashMap<>();
		b.put("x", bounds.x);
		b.put("y", bounds.y);
		b.put("width", bounds.width);
		b.put("height", bounds.height);
		m.put("bounds", b);
		String text = w.getText();
		m.put("text", text != null ? text : "");
		return m;
	}

	private void applyHullFields(Map<String, Object> m, Shape hull, int id, String name)
	{
		// hull != null is not sufficient: getConvexHull() returns a non-null Shape for
		// objects that are in the loaded scene tile array but projected outside the visible
		// canvas area (negative or > canvas dimensions). We must intersect with the
		// actual canvas viewport before declaring an entity "on screen".
		boolean onScreen = false;
		Rectangle b = null;
		if (hull != null)
		{
			b = hull.getBounds();
			Rectangle viewport = new Rectangle(0, 0,
				client.getCanvas().getWidth(), client.getCanvas().getHeight());
			onScreen = viewport.intersects(b);
		}
		m.put("onScreen", onScreen);
		if (onScreen)
		{
			// The hull's bounding-box centre can land outside the polygon
			// itself — convex hulls viewed at an angle are skewed
			// quadrilaterals, not axis-aligned rectangles, so their bbox
			// centre is frequently in empty space (or even over a UI panel
			// the visible shape doesn't actually overlap). The vertex
			// average of a convex polygon is always inside it — a convex
			// combination of the polygon's own points — so it's both a
			// reliable click target and a faithful point for occlusion checks.
			int[] centroid = hullCentroid(hull, b);
			m.put("canvasX", centroid[0]);
			m.put("canvasY", centroid[1]);
			m.put("hull", hullFilter.matches(id, name) ? hullPoints(hull) : null);
		}
		else
		{
			m.put("canvasX", null);
			m.put("canvasY", null);
			m.put("hull", null);
		}
	}

	private String resolveName(int id)
	{
		ObjectComposition comp = client.getObjectDefinition(id);
		if (comp == null)
		{
			return "unknown";
		}
		if (comp.getImpostorIds() != null)
		{
			ObjectComposition impostor = comp.getImpostor();
			if (impostor != null)
			{
				comp = impostor;
			}
		}
		String name = comp.getName();
		return name != null ? name : "unknown";
	}

	private String resolveItemName(int id)
	{
		ItemComposition comp = client.getItemDefinition(id);
		if (comp == null)
		{
			return "unknown";
		}
		String name = comp.getName();
		return name != null ? name : "unknown";
	}

	private Shape getObjectHull(TileObject obj)
	{
		if (obj instanceof GameObject)
		{
			return ((GameObject) obj).getConvexHull();
		}
		if (obj instanceof WallObject)
		{
			return ((WallObject) obj).getConvexHull();
		}
		if (obj instanceof GroundObject)
		{
			return ((GroundObject) obj).getConvexHull();
		}
		if (obj instanceof DecorativeObject)
		{
			return ((DecorativeObject) obj).getConvexHull();
		}
		return null;
	}

	private int[][] hullPoints(Shape hull)
	{
		List<int[]> points = new ArrayList<>();
		float[] coords = new float[6];
		PathIterator it = hull.getPathIterator(null);
		while (!it.isDone())
		{
			int type = it.currentSegment(coords);
			if (type == PathIterator.SEG_MOVETO || type == PathIterator.SEG_LINETO)
			{
				points.add(new int[]{(int) coords[0], (int) coords[1]});
			}
			it.next();
		}
		return points.toArray(new int[0][]);
	}

	private int[] hullCentroid(Shape hull, Rectangle bounds)
	{
		long sumX = 0;
		long sumY = 0;
		int count = 0;
		float[] coords = new float[6];
		PathIterator it = hull.getPathIterator(null);
		while (!it.isDone())
		{
			int type = it.currentSegment(coords);
			if (type == PathIterator.SEG_MOVETO || type == PathIterator.SEG_LINETO)
			{
				sumX += (int) coords[0];
				sumY += (int) coords[1];
				count++;
			}
			it.next();
		}

		if (count == 0)
		{
			return new int[]{bounds.x + bounds.width / 2, bounds.y + bounds.height / 2};
		}

		return new int[]{(int) (sumX / count), (int) (sumY / count)};
	}

	private int[] minimapPoint(LocalPoint lp)
	{
		if (lp == null)
		{
			return null;
		}
		Point p = Perspective.localToMinimap(client, lp);
		if (p == null)
		{
			return null;
		}
		return new int[]{p.getX(), p.getY()};
	}
}
