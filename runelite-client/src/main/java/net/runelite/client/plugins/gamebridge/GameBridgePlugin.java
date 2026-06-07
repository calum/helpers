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
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import javax.inject.Inject;
import lombok.extern.slf4j.Slf4j;
import net.runelite.api.Actor;
import net.runelite.api.Client;
import net.runelite.api.Item;
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

	private final BridgeServer server = new BridgeServer();
	private final HullFilter hullFilter = new HullFilter();
	private final HullFilter objectFilter = new HullFilter();

	// Accumulated between ticks; flushed in onGameTick
	private final List<Map<String, Object>> pendingEvents = new ArrayList<>();
	// key = "varpId,varbitId"; last write within a tick wins
	private final Map<String, int[]> pendingVarbits = new LinkedHashMap<>();

	private TickMessageBuilder tickBuilder;

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
		tickBuilder = new TickMessageBuilder(client, config, hullFilter, objectFilter);
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

	// -------------------------------------------------------------------------
	// Event accumulation — collected between ticks and flushed in onGameTick
	// -------------------------------------------------------------------------

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
		server.broadcast(gson.toJson(tickBuilder.build(pendingEvents, pendingVarbits)));
		pendingEvents.clear();
		pendingVarbits.clear();
	}
}
