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

import net.runelite.client.config.Config;
import net.runelite.client.config.ConfigGroup;
import net.runelite.client.config.ConfigItem;

@ConfigGroup("objectlogger")
public interface ObjectLoggerConfig extends Config
{
	@ConfigItem(
		keyName = "logFile",
		name = "Log file path",
		description = "Path to write events to. Relative paths are placed inside ~/.runelite/",
		position = 0
	)
	default String logFile()
	{
		return "object-logger.log";
	}

	@ConfigItem(
		keyName = "trackedObjects",
		name = "Tracked objects",
		description = "Comma-separated object names to track (e.g. \"Tree,Oak tree\"). Empty = log everything.",
		position = 1
	)
	default String trackedObjects()
	{
		return "";
	}

	@ConfigItem(
		keyName = "logDespawns",
		name = "Log despawns",
		description = "Also log when tracked objects despawn.",
		position = 2
	)
	default boolean logDespawns()
	{
		return false;
	}

	@ConfigItem(
		keyName = "verboseLogging",
		name = "Verbose console logging",
		description = "Print every spawned object to the RuneLite console log, regardless of the tracked list.",
		position = 3
	)
	default boolean verboseLogging()
	{
		return false;
	}

	@ConfigItem(
		keyName = "chatMessages",
		name = "Show in game chat",
		description = "Send matched spawn/despawn events to your local game chat window.",
		position = 4
	)
	default boolean chatMessages()
	{
		return false;
	}
}
