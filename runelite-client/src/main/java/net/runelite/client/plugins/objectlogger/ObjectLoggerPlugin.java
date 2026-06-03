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
package net.runelite.client.plugins.objectlogger;

import com.google.inject.Provides;
import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.io.PrintWriter;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Arrays;
import java.util.Collections;
import java.util.Set;
import java.util.stream.Collectors;
import javax.inject.Inject;
import javax.inject.Named;
import lombok.extern.slf4j.Slf4j;
import net.runelite.api.ChatMessageType;
import net.runelite.api.Client;
import net.runelite.api.ObjectComposition;
import net.runelite.api.events.GameObjectDespawned;
import net.runelite.api.events.GameObjectSpawned;
import net.runelite.client.chat.ChatMessageBuilder;
import net.runelite.client.chat.ChatMessageManager;
import net.runelite.client.chat.QueuedMessage;
import net.runelite.client.config.ConfigManager;
import net.runelite.client.eventbus.Subscribe;
import net.runelite.client.events.ConfigChanged;
import net.runelite.client.plugins.Plugin;
import net.runelite.client.plugins.PluginDescriptor;

@Slf4j
@PluginDescriptor(
	name = "Object Logger",
	description = "Logs game object spawns (and optionally despawns) to a file",
	enabledByDefault = false
)
public class ObjectLoggerPlugin extends Plugin
{
	private static final DateTimeFormatter TIMESTAMP = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

	@Inject
	private Client client;

	@Inject
	private ObjectLoggerConfig config;

	@Inject
	private ChatMessageManager chatMessageManager;

	@Inject
	@Named("runeLiteDir")
	private File runeLiteDir;

	private PrintWriter writer;
	private Set<String> trackedNames = Collections.emptySet();

	@Provides
	ObjectLoggerConfig provideConfig(ConfigManager configManager)
	{
		return configManager.getConfig(ObjectLoggerConfig.class);
	}

	@Override
	protected void startUp()
	{
		openWriter();
		updateTrackedNames();
	}

	@Override
	protected void shutDown()
	{
		closeWriter();
	}

	@Subscribe
	public void onConfigChanged(ConfigChanged event)
	{
		if (!"objectlogger".equals(event.getGroup()))
		{
			return;
		}
		if ("logFile".equals(event.getKey()))
		{
			closeWriter();
			openWriter();
		}
		else if ("trackedObjects".equals(event.getKey()))
		{
			updateTrackedNames();
		}
	}

	@Subscribe
	public void onGameObjectSpawned(GameObjectSpawned event)
	{
		int id = event.getGameObject().getId();
		String name = resolveName(id);
		String location = event.getGameObject().getWorldLocation().toString();

		if (config.verboseLogging() || isTracked(name))
		{
			writeLine("SPAWN", id, name, location);
			sendChatMessage("SPAWN", name, id, location);
		}
	}

	@Subscribe
	public void onGameObjectDespawned(GameObjectDespawned event)
	{
		if (!config.logDespawns())
		{
			return;
		}
		int id = event.getGameObject().getId();
		String name = resolveName(id);
		String location = event.getGameObject().getWorldLocation().toString();

		if (config.verboseLogging() || isTracked(name))
		{
			writeLine("DESPAWN", id, name, location);
			sendChatMessage("DESPAWN", name, id, location);
		}
	}

	private String resolveName(int id)
	{
		ObjectComposition comp = client.getObjectDefinition(id);
		if (comp == null)
		{
			return "unknown";
		}
		// Follow impostor chain so varbit-dependent objects (e.g. doors) show their real name
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

	private boolean isTracked(String name)
	{
		return trackedNames.isEmpty() || trackedNames.contains(name.toLowerCase());
	}

	private void sendChatMessage(String eventType, String name, int id, String location)
	{
		if (!config.chatMessages())
		{
			return;
		}
		String message = new ChatMessageBuilder()
			.append("[ObjectLogger] ")
			.append(eventType)
			.append(" \"")
			.append(name)
			.append("\" id=")
			.append(String.valueOf(id))
			.append(" ")
			.append(location)
			.build();
		chatMessageManager.queue(QueuedMessage.builder()
			.type(ChatMessageType.GAMEMESSAGE)
			.runeLiteFormattedMessage(message)
			.build());
	}

	private void writeLine(String eventType, int id, String name, String location)
	{
		if (writer == null)
		{
			return;
		}
		writer.printf("[%s] %s id=%d name=\"%s\" location=%s%n",
			LocalDateTime.now().format(TIMESTAMP), eventType, id, name, location);
		writer.flush();
	}

	private void openWriter()
	{
		String path = config.logFile().trim();
		File file = new File(path);
		if (!file.isAbsolute())
		{
			file = new File(runeLiteDir, path);
		}
		try
		{
			File parent = file.getParentFile();
			if (parent != null)
			{
				parent.mkdirs();
			}
			writer = new PrintWriter(new FileWriter(file, true));
			log.info("Object Logger writing to {}", file.getAbsolutePath());
		}
		catch (IOException e)
		{
			log.error("Object Logger could not open {}", file.getAbsolutePath(), e);
			writer = null;
		}
	}

	private void closeWriter()
	{
		if (writer != null)
		{
			writer.close();
			writer = null;
		}
	}

	private void updateTrackedNames()
	{
		String raw = config.trackedObjects().trim();
		if (raw.isEmpty())
		{
			trackedNames = Collections.emptySet();
			return;
		}
		trackedNames = Arrays.stream(raw.split(","))
			.map(String::trim)
			.filter(s -> !s.isEmpty())
			.map(String::toLowerCase)
			.collect(Collectors.toSet());
	}
}
