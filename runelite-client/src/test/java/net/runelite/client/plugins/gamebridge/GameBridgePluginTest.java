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
import java.lang.reflect.Field;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import net.runelite.api.Client;
import net.runelite.api.events.ClientTick;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.mockito.Mock;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import org.mockito.junit.MockitoJUnitRunner;

/**
 * Exercises {@code GameBridgePlugin}'s subscribe/unsubscribe handling and its
 * wiring into the per-{@code ClientTick} {@code hullUpdate} dispatch, via the
 * public {@link GameBridgePlugin#onClientTick} entry point — {@code server}/
 * {@code tickBuilder} are swapped for mocks by reflection (the plugin is
 * normally constructed by Guice, which isn't available here).
 */
@RunWith(MockitoJUnitRunner.class)
public class GameBridgePluginTest
{
	@Mock
	private Client client;

	@Mock
	private BridgeServer server;

	@Mock
	private TickMessageBuilder tickBuilder;

	@Mock
	private BridgeServer.ClientEntry entry;

	private GameBridgePlugin plugin;

	@Before
	public void setUp() throws Exception
	{
		plugin = new GameBridgePlugin();
		setField("client", client);
		setField("server", server);
		setField("tickBuilder", tickBuilder);
		setField("gson", new Gson());

		when(server.activeClients()).thenReturn(Collections.singletonList(entry));
		when(tickBuilder.currentTooltip()).thenReturn("");
	}

	private void setField(String name, Object value) throws Exception
	{
		Field f = GameBridgePlugin.class.getDeclaredField(name);
		f.setAccessible(true);
		f.set(plugin, value);
	}

	private void drainOnce(String line) throws Exception
	{
		when(server.drainIncoming(entry, 50))
			.thenReturn(Collections.singletonList(line))
			.thenReturn(Collections.emptyList());
	}

	@Test
	public void tileSubscribeMissingWorldCoordsIsRejected() throws Exception
	{
		Map<String, Object> msg = new LinkedHashMap<>();
		msg.put("type", "subscribe");
		msg.put("subId", "dodge");
		msg.put("kind", "tile");
		drainOnce(new Gson().toJson(msg));

		plugin.onClientTick(new ClientTick());

		verify(tickBuilder, never()).findTile(any(), any(), any(), any());
		verify(server, never()).sendTo(eq(entry), any());
	}

	@Test
	public void tileSubscribeWithWorldCoordsIsAcceptedAndDispatched() throws Exception
	{
		Map<String, Object> msg = new LinkedHashMap<>();
		msg.put("type", "subscribe");
		msg.put("subId", "dodge");
		msg.put("kind", "tile");
		msg.put("worldX", 3210);
		msg.put("worldY", 3214);
		msg.put("plane", 0);
		drainOnce(new Gson().toJson(msg));

		Map<String, Object> tileResult = new LinkedHashMap<>();
		tileResult.put("subId", "dodge");
		tileResult.put("found", true);
		when(tickBuilder.findTile("dodge", 3210, 3214, 0)).thenReturn(tileResult);

		plugin.onClientTick(new ClientTick());

		verify(tickBuilder, times(1)).findTile("dodge", 3210, 3214, 0);
		verify(server).sendTo(eq(entry), contains("\"found\":true"));
	}

	@Test
	public void tileSubscribePlaneDefaultsToNullWhenOmitted() throws Exception
	{
		Map<String, Object> msg = new LinkedHashMap<>();
		msg.put("type", "subscribe");
		msg.put("subId", "dodge");
		msg.put("kind", "tile");
		msg.put("worldX", 3210);
		msg.put("worldY", 3214);
		drainOnce(new Gson().toJson(msg));

		when(tickBuilder.findTile("dodge", 3210, 3214, null)).thenReturn(Collections.singletonMap("subId", "dodge"));

		plugin.onClientTick(new ClientTick());

		verify(tickBuilder, times(1)).findTile("dodge", 3210, 3214, null);
	}

	@Test
	public void nonTileSubscribeStillRequiresIdOrName() throws Exception
	{
		Map<String, Object> msg = new LinkedHashMap<>();
		msg.put("type", "subscribe");
		msg.put("subId", "npc1");
		msg.put("kind", "npc");
		drainOnce(new Gson().toJson(msg));

		plugin.onClientTick(new ClientTick());

		verify(tickBuilder, never()).findNearest(any(), any(), any(), any());
		verify(server, never()).sendTo(eq(entry), any());
	}

	@Test
	public void unsubscribeRemovesActiveTileSubscription() throws Exception
	{
		Map<String, Object> sub = new LinkedHashMap<>();
		sub.put("type", "subscribe");
		sub.put("subId", "dodge");
		sub.put("kind", "tile");
		sub.put("worldX", 3210);
		sub.put("worldY", 3214);
		when(tickBuilder.findTile("dodge", 3210, 3214, null)).thenReturn(Collections.singletonMap("subId", "dodge"));
		when(server.drainIncoming(entry, 50)).thenReturn(Collections.singletonList(new Gson().toJson(sub)));
		plugin.onClientTick(new ClientTick());
		verify(tickBuilder, times(1)).findTile("dodge", 3210, 3214, null);

		Map<String, Object> unsub = new LinkedHashMap<>();
		unsub.put("type", "unsubscribe");
		unsub.put("subId", "dodge");
		when(server.drainIncoming(entry, 50)).thenReturn(Collections.singletonList(new Gson().toJson(unsub)));
		plugin.onClientTick(new ClientTick());

		when(server.drainIncoming(entry, 50)).thenReturn(Collections.emptyList());
		plugin.onClientTick(new ClientTick());

		verify(tickBuilder, times(1)).findTile(any(), any(), any(), any());
	}
}
