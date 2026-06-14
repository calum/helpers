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
import com.google.gson.JsonSyntaxException;
import com.google.gson.reflect.TypeToken;
import com.google.inject.Provides;
import java.lang.reflect.Type;
import java.util.ArrayList;
import java.util.HashMap;
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
import net.runelite.api.events.ClientTick;
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
	private static final int MAX_SUBSCRIPTIONS_PER_CLIENT = 20;
	private static final int MAX_INCOMING_PER_TICK = 50;
	private static final int DEFAULT_TTL_TICKS = 10;
	private static final Type INCOMING_MESSAGE_TYPE = new TypeToken<Map<String, Object>>(){}.getType();

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

	// Live clickbox subscriptions, keyed per-connection
	private final Map<BridgeServer.ClientEntry, Map<String, Subscription>> subscriptions = new HashMap<>();

	private TickMessageBuilder tickBuilder;

	/**
	 * A Python-registered interest in the nearest entity matching {@code kind}/{@code id}/{@code name}.
	 * Renewed by re-sending {@code subscribe} with the same {@code subId}; expires after
	 * {@code ttlTicks} game ticks without renewal.
	 */
	private static final class Subscription
	{
		final String subId;
		final String kind;
		final String name;
		final Integer id;
		int ttlTicks;

		Subscription(String subId, String kind, String name, Integer id, int ttlTicks)
		{
			this.subId = subId;
			this.kind = kind;
			this.name = name;
			this.id = id;
			this.ttlTicks = ttlTicks;
		}
	}

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
		subscriptions.clear();
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
		tickSubscriptionTtls();
		pruneDisconnectedSubscriptions();
	}

	// -------------------------------------------------------------------------
	// Live clickbox subscriptions
	// -------------------------------------------------------------------------

	@Subscribe
	public void onClientTick(ClientTick event)
	{
		for (BridgeServer.ClientEntry entry : server.activeClients())
		{
			processIncoming(entry);

			Map<String, Subscription> subs = subscriptions.get(entry);
			if (subs == null || subs.isEmpty())
			{
				continue;
			}

			List<Map<String, Object>> entities = new ArrayList<>(subs.size());
			for (Subscription sub : subs.values())
			{
				entities.add(tickBuilder.findNearest(sub.subId, sub.kind, sub.id, sub.name));
			}

			Map<String, Object> msg = new LinkedHashMap<>();
			msg.put("type", "hullUpdate");
			msg.put("clientTick", client.getGameCycle());
			msg.put("entities", entities);
			server.sendTo(entry, gson.toJson(msg));
		}
	}

	private void processIncoming(BridgeServer.ClientEntry entry)
	{
		for (String line : server.drainIncoming(entry, MAX_INCOMING_PER_TICK))
		{
			Map<String, Object> msg;
			try
			{
				msg = gson.fromJson(line, INCOMING_MESSAGE_TYPE);
			}
			catch (JsonSyntaxException e)
			{
				log.warn("Game Bridge: malformed inbound message: {}", line, e);
				continue;
			}
			if (msg == null)
			{
				continue;
			}

			Object type = msg.get("type");
			if ("subscribe".equals(type))
			{
				handleSubscribe(entry, msg);
			}
			else if ("unsubscribe".equals(type))
			{
				handleUnsubscribe(entry, msg);
			}
		}
	}

	private void handleSubscribe(BridgeServer.ClientEntry entry, Map<String, Object> msg)
	{
		Object subId = msg.get("subId");
		Object kind = msg.get("kind");
		if (!(subId instanceof String) || !(kind instanceof String))
		{
			log.warn("Game Bridge: subscribe missing subId/kind: {}", msg);
			return;
		}

		String name = (String) msg.get("name");
		Integer id = toInteger(msg.get("id"));
		if (id == null && name == null)
		{
			log.warn("Game Bridge: subscribe requires at least one of id/name: {}", msg);
			return;
		}

		Integer ttl = toInteger(msg.get("ttlTicks"));
		int ttlTicks = ttl != null ? ttl : DEFAULT_TTL_TICKS;

		Map<String, Subscription> subs = subscriptions.computeIfAbsent(entry, e -> new LinkedHashMap<>());
		if (!subs.containsKey(subId) && subs.size() >= MAX_SUBSCRIPTIONS_PER_CLIENT)
		{
			log.warn("Game Bridge: subscription cap ({}) reached, ignoring subscribe for {}",
				MAX_SUBSCRIPTIONS_PER_CLIENT, subId);
			return;
		}

		subs.put((String) subId, new Subscription((String) subId, (String) kind, name, id, ttlTicks));
	}

	private void handleUnsubscribe(BridgeServer.ClientEntry entry, Map<String, Object> msg)
	{
		Object subId = msg.get("subId");
		if (!(subId instanceof String))
		{
			return;
		}
		Map<String, Subscription> subs = subscriptions.get(entry);
		if (subs != null)
		{
			subs.remove(subId);
		}
	}

	private static Integer toInteger(Object value)
	{
		return value instanceof Number ? ((Number) value).intValue() : null;
	}

	private void tickSubscriptionTtls()
	{
		for (Map<String, Subscription> subs : subscriptions.values())
		{
			subs.values().removeIf(sub -> --sub.ttlTicks <= 0);
		}
	}

	private void pruneDisconnectedSubscriptions()
	{
		subscriptions.keySet().retainAll(server.activeClients());
	}
}
