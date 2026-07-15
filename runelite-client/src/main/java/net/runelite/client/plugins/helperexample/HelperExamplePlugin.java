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
package net.runelite.client.plugins.helperexample;

import javax.inject.Inject;
import lombok.extern.slf4j.Slf4j;
import net.runelite.api.Client;
import net.runelite.api.ObjectComposition;
import net.runelite.api.events.GameObjectSpawned;
import net.runelite.client.eventbus.Subscribe;
import net.runelite.client.plugins.Plugin;
import net.runelite.client.plugins.PluginDescriptor;

/**
 * Minimal starter plugin: the reference example for writing new helper
 * plugins in this fork. Logs a message whenever a "Tree" game object spawns.
 * Copy this package as the starting point for a new helper.
 */
@PluginDescriptor(
	name = "Helper Example",
	description = "Reference example for helper plugins — logs Tree game object spawns",
	enabledByDefault = false
)
@Slf4j
public class HelperExamplePlugin extends Plugin
{
	private static final String TRACKED_OBJECT_NAME = "Tree";

	@Inject
	private Client client;

	@Subscribe
	public void onGameObjectSpawned(GameObjectSpawned event)
	{
		ObjectComposition comp = client.getObjectDefinition(event.getGameObject().getId());
		if (isTracked(comp.getName(), TRACKED_OBJECT_NAME))
		{
			log.info("{} spawned at {}", TRACKED_OBJECT_NAME, event.getGameObject().getWorldLocation());
		}
	}

	static boolean isTracked(String objectName, String target)
	{
		return objectName != null && objectName.equalsIgnoreCase(target);
	}
}
