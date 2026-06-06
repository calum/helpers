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
import com.google.inject.Provides;
import java.awt.Rectangle;
import java.awt.Shape;
import java.awt.geom.PathIterator;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import javax.inject.Inject;
import lombok.extern.slf4j.Slf4j;
import net.runelite.api.Actor;
import net.runelite.api.Client;
import net.runelite.api.DecorativeObject;
import net.runelite.api.GameObject;
import net.runelite.api.GroundObject;
import net.runelite.api.HashTable;
import net.runelite.api.Item;
import net.runelite.api.ItemContainer;
import net.runelite.api.NPC;
import net.runelite.api.ObjectComposition;
import net.runelite.api.Perspective;
import net.runelite.api.Player;
import net.runelite.api.Point;
import net.runelite.api.Skill;
import net.runelite.api.Tile;
import net.runelite.api.TileObject;
import net.runelite.api.WallObject;
import net.runelite.api.WidgetNode;
import net.runelite.api.coords.LocalPoint;
import net.runelite.api.coords.WorldPoint;
import net.runelite.api.widgets.Widget;
import net.runelite.api.events.AnimationChanged;
import net.runelite.api.events.ChatMessage;
import net.runelite.api.events.GameTick;
import net.runelite.api.events.InteractingChanged;
import net.runelite.api.events.ItemContainerChanged;
import net.runelite.api.events.StatChanged;
import net.runelite.api.events.VarbitChanged;
import net.runelite.client.config.ConfigManager;
import net.runelite.client.eventbus.Subscribe;
import net.runelite.client.events.ConfigChanged;
import net.runelite.client.plugins.Plugin;
import net.runelite.client.plugins.PluginDescriptor;

@Slf4j
@PluginDescriptor(
	name = "Game Bridge",
	description = "Streams game state as newline-delimited JSON over a local TCP socket for external tooling",
	enabledByDefault = false
)
public class GameBridgePlugin extends Plugin
{
	@Inject
	private Client client;

	@Inject
	private GameBridgeConfig config;

	@Inject
	private Gson gson;

	// Widget groups serialised when exposeWidgets is on.
	// 149 = Inventory, 12 = Bank, 387 = Equipment (Wornitems), 192 = Deposit box
	private static final int[] WIDGET_GROUPS = {149, 12, 387, 192};

	private final BridgeServer server = new BridgeServer();
	private final HullFilter hullFilter = new HullFilter();
	private final HullFilter objectFilter = new HullFilter();

	// Accumulated between ticks; flushed in onGameTick
	private final List<Map<String, Object>> pendingEvents = new ArrayList<>();
	// key = "varpId,varbitId"; last write within a tick wins
	private final Map<String, int[]> pendingVarbits = new LinkedHashMap<>();

	@Provides
	GameBridgeConfig provideConfig(ConfigManager configManager)
	{
		return configManager.getConfig(GameBridgeConfig.class);
	}

	@Override
	protected void startUp() throws Exception
	{
		hullFilter.parse(config.hullFilter());
		objectFilter.parse(config.objectFilter());
		server.start(config.port());
	}

	@Override
	protected void shutDown()
	{
		server.stop();
		pendingEvents.clear();
		pendingVarbits.clear();
	}

	@Subscribe
	public void onConfigChanged(ConfigChanged event)
	{
		if (!"gamebridge".equals(event.getGroup()))
		{
			return;
		}
		if ("hullFilter".equals(event.getKey()))
		{
			hullFilter.parse(config.hullFilter());
		}
		else if ("objectFilter".equals(event.getKey()))
		{
			objectFilter.parse(config.objectFilter());
		}
	}

	@Subscribe
	public void onStatChanged(StatChanged event)
	{
		Map<String, Object> e = new LinkedHashMap<>();
		e.put("type", "xp");
		e.put("skill", event.getSkill().name());
		e.put("xp", event.getXp());
		e.put("level", event.getLevel());
		e.put("boostedLevel", event.getBoostedLevel());
		pendingEvents.add(e);
	}

	@Subscribe
	public void onAnimationChanged(AnimationChanged event)
	{
		Actor actor = event.getActor();
		Map<String, Object> e = new LinkedHashMap<>();
		e.put("type", "animation");
		e.put("actor", actor == client.getLocalPlayer() ? "player" : actor.getName());
		e.put("animId", actor.getAnimation());
		pendingEvents.add(e);
	}

	@Subscribe
	public void onItemContainerChanged(ItemContainerChanged event)
	{
		if (!config.exposeInventory())
		{
			return;
		}
		Item[] items = event.getItemContainer().getItems();
		List<Map<String, Object>> slots = new ArrayList<>(items.length);
		for (int i = 0; i < items.length; i++)
		{
			Map<String, Object> slot = new LinkedHashMap<>();
			slot.put("slot", i);
			slot.put("itemId", items[i].getId());
			slot.put("qty", items[i].getQuantity());
			slots.add(slot);
		}
		Map<String, Object> e = new LinkedHashMap<>();
		e.put("type", "container");
		e.put("containerId", event.getContainerId());
		e.put("items", slots);
		pendingEvents.add(e);
	}

	@Subscribe
	public void onVarbitChanged(VarbitChanged event)
	{
		if (!config.exposeVarbits())
		{
			return;
		}
		// Overwrite any earlier change to the same varbit/varp this tick
		String key = event.getVarpId() + "," + event.getVarbitId();
		pendingVarbits.put(key, new int[]{event.getVarpId(), event.getVarbitId(), event.getValue()});
	}

	@Subscribe
	public void onChatMessage(ChatMessage event)
	{
		Map<String, Object> e = new LinkedHashMap<>();
		e.put("type", "chat");
		e.put("msgType", event.getType().name());
		e.put("name", event.getName());
		e.put("message", event.getMessage());
		pendingEvents.add(e);
	}

	@Subscribe
	public void onInteractingChanged(InteractingChanged event)
	{
		if (event.getSource() != client.getLocalPlayer())
		{
			return;
		}
		Map<String, Object> e = new LinkedHashMap<>();
		e.put("type", "interacting");
		Actor target = event.getTarget();
		e.put("target", target != null ? target.getName() : null);
		pendingEvents.add(e);
	}

	@Subscribe
	public void onGameTick(GameTick event)
	{
		server.activateNewClients();
		Map<String, Object> message = buildTickMessage();
		server.broadcast(gson.toJson(message));
		pendingEvents.clear();
		pendingVarbits.clear();
	}

	// -------------------------------------------------------------------------
	// Tick message assembly
	// -------------------------------------------------------------------------

	private Map<String, Object> buildTickMessage()
	{
		Map<String, Object> msg = new LinkedHashMap<>();
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
				npcList.add(serializeActor(npc, npc.getId(), npc.getName()));
			}
			msg.put("npcs", npcList);
		}

		if (config.exposeObjects())
		{
			msg.put("objects", buildObjectsList());
		}

		if (config.exposeWidgets())
		{
			msg.put("widgets", buildWidgetsList());
		}

		if (config.exposeInterfaces())
		{
			msg.put("interfaces", buildInterfacesList());
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
			m.put("canvasX", b.x + b.width / 2);
			m.put("canvasY", b.y + b.height / 2);
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

	// -------------------------------------------------------------------------
	// Minimap coordinate helper
	// -------------------------------------------------------------------------

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

	// -------------------------------------------------------------------------
	// Dynamic interface / widget enumeration
	// -------------------------------------------------------------------------

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
						list.add(serializeInterfaceWidget(groupId, childId, w));
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
								list.add(serializeInterfaceWidget(groupId, dyn.getIndex(), dyn));
							}
						}
					}
				}
			}
		}
		return list;
	}

	private Map<String, Object> serializeInterfaceWidget(int groupId, int childId, Widget w)
	{
		Map<String, Object> m = new LinkedHashMap<>();
		m.put("groupId", groupId);
		m.put("childId", childId);
		m.put("itemId", w.getItemId());
		m.put("quantity", w.getItemQuantity());
		Rectangle b = w.getBounds();
		Map<String, Object> bounds = new LinkedHashMap<>();
		bounds.put("x", b.x);
		bounds.put("y", b.y);
		bounds.put("width", b.width);
		bounds.put("height", b.height);
		m.put("bounds", bounds);
		String text = w.getText();
		m.put("text", text != null ? text : "");
		return m;
	}
}
