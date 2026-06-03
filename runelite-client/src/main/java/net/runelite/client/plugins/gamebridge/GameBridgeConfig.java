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

import net.runelite.client.config.Config;
import net.runelite.client.config.ConfigGroup;
import net.runelite.client.config.ConfigItem;

@ConfigGroup("gamebridge")
public interface GameBridgeConfig extends Config
{
	@ConfigItem(
		keyName = "port",
		name = "Port",
		description = "TCP port the bridge listens on. Restart the plugin to apply a change.",
		position = 0
	)
	default int port()
	{
		return 7070;
	}

	@ConfigItem(
		keyName = "exposeNpcs",
		name = "Expose NPCs",
		description = "Include nearby NPCs in each tick message.",
		position = 1
	)
	default boolean exposeNpcs()
	{
		return true;
	}

	@ConfigItem(
		keyName = "exposeObjects",
		name = "Expose objects",
		description = "Include nearby scene objects in each tick message.",
		position = 2
	)
	default boolean exposeObjects()
	{
		return true;
	}

	@ConfigItem(
		keyName = "exposeInventory",
		name = "Expose inventory",
		description = "Include item container change events (inventory, bank, etc.).",
		position = 3
	)
	default boolean exposeInventory()
	{
		return true;
	}

	@ConfigItem(
		keyName = "exposeVarbits",
		name = "Expose varbits",
		description = "Include varbit/varplayer change events. Useful for tracking state used by other plugins (e.g. Giant's Foundry).",
		position = 4
	)
	default boolean exposeVarbits()
	{
		return true;
	}

	@ConfigItem(
		keyName = "exposeCamera",
		name = "Expose camera",
		description = "Include camera yaw, pitch, and position in each tick message.",
		position = 5
	)
	default boolean exposeCamera()
	{
		return true;
	}

	@ConfigItem(
		keyName = "hullFilter",
		name = "Hull filter",
		description = "Comma-separated object/NPC IDs or names that receive convex hull data. "
			+ "Empty = all visible entities get hulls. "
			+ "Example: 1276,Goblin,Oak tree,3106",
		position = 6
	)
	default String hullFilter()
	{
		return "";
	}

	@ConfigItem(
		keyName = "objectFilter",
		name = "Object filter",
		description = "Comma-separated object IDs or names to include in tick messages. "
			+ "Empty = no objects sent (use 'Send all named objects' or 'Debug: all objects' instead). "
			+ "Example: Iron rocks,Oak tree,1276",
		position = 7
	)
	default String objectFilter()
	{
		return "";
	}

	@ConfigItem(
		keyName = "sendAllNamedObjects",
		name = "Send all named objects",
		description = "Include every object whose name is not 'null' or 'unknown', regardless of the object filter. "
			+ "Broader than the filter but avoids unnamed/decorative objects.",
		position = 8
	)
	default boolean sendAllNamedObjects()
	{
		return false;
	}

	@ConfigItem(
		keyName = "debugAllObjects",
		name = "Debug: send all objects",
		description = "Include every tile object in every tick message. "
			+ "WARNING: can cause lag on large scenes. For development only.",
		position = 9
	)
	default boolean debugAllObjects()
	{
		return false;
	}

	@ConfigItem(
		keyName = "exposeWidgets",
		name = "Expose widgets",
		description = "Include visible UI widget slots (inventory, bank, equipment) with their screen bounds in each tick message.",
		position = 10
	)
	default boolean exposeWidgets()
	{
		return false;
	}
}
