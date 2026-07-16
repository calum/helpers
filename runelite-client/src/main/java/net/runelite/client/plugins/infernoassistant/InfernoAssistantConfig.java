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
package net.runelite.client.plugins.infernoassistant;

import java.awt.Color;
import net.runelite.client.config.Config;
import net.runelite.client.config.ConfigGroup;
import net.runelite.client.config.ConfigItem;

@ConfigGroup("infernoassistant")
public interface InfernoAssistantConfig extends Config
{
	@ConfigItem(
		position = 0,
		keyName = "showOverlay",
		name = "Show overlay",
		description = "Toggles the protection prayer recommendation overlay."
	)
	default boolean showOverlay()
	{
		return true;
	}

	@ConfigItem(
		position = 1,
		keyName = "queueLength",
		name = "Queue length",
		description = "How many ticks ahead the predictive queue looks. Also bounds how far ahead "
			+ "NPC movement is simulated to predict LOS before it's actually gained - raise this if "
			+ "wave-start spawn tiles are far enough away that closing to LOS takes longer than the "
			+ "queue."
	)
	default int queueLength()
	{
		return 15;
	}

	@ConfigItem(
		position = 2,
		keyName = "showUnmitigatedWarnings",
		name = "Show unmitigated warnings",
		description = "Shows a warning line when two NPCs threaten conflicting styles on the same tick."
	)
	default boolean showUnmitigatedWarnings()
	{
		return true;
	}

	@ConfigItem(
		position = 3,
		keyName = "mageColor",
		name = "Magic color",
		description = "Color used for Protect from Magic recommendations."
	)
	default Color mageColor()
	{
		return new Color(0x4F86E8);
	}

	@ConfigItem(
		position = 4,
		keyName = "rangeColor",
		name = "Range color",
		description = "Color used for Protect from Missiles recommendations."
	)
	default Color rangeColor()
	{
		return new Color(0x43A85B);
	}

	@ConfigItem(
		position = 5,
		keyName = "meleeColor",
		name = "Melee color",
		description = "Color used for Protect from Melee recommendations."
	)
	default Color meleeColor()
	{
		return new Color(0x3E434B);
	}

	@ConfigItem(
		position = 6,
		keyName = "debugLogging",
		name = "Debug logging",
		description = "Logs verbose per-tick threat-tracking state to <RuneLite dir>/logs/inferno-assistant-debug.log."
	)
	default boolean debugLogging()
	{
		return false;
	}
}
