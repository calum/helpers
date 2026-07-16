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

import com.google.inject.Provides;
import java.io.File;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.EnumSet;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import javax.inject.Inject;
import lombok.extern.slf4j.Slf4j;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.NPC;
import net.runelite.api.Player;
import net.runelite.api.Prayer;
import net.runelite.api.coords.WorldPoint;
import net.runelite.api.events.GameStateChanged;
import net.runelite.api.events.GameTick;
import net.runelite.api.events.NpcDespawned;
import net.runelite.api.events.NpcSpawned;
import net.runelite.client.RuneLite;
import net.runelite.client.config.ConfigManager;
import net.runelite.client.eventbus.Subscribe;
import net.runelite.client.events.ConfigChanged;
import net.runelite.client.plugins.Plugin;
import net.runelite.client.plugins.PluginDescriptor;
import net.runelite.client.ui.overlay.OverlayManager;

/**
 * Live protection-prayer helper for the Inferno. See DESIGN.md and README.md
 * in this package for the full design and scope.
 */
@PluginDescriptor(
	name = "Inferno Assistant",
	description = "Recommends which protection prayer to hold in the Inferno, with a short predictive queue",
	tags = {"inferno", "prayer", "pve", "overlay"},
	enabledByDefault = false
)
@Slf4j
public class InfernoAssistantPlugin extends Plugin
{
	@Inject
	private Client client;

	@Inject
	private OverlayManager overlayManager;

	@Inject
	private InfernoAssistantOverlay overlay;

	@Inject
	private InfernoLosOverlay losOverlay;

	@Inject
	private InfernoAssistantConfig config;

	private static final File DEBUG_LOG_FILE = new File(RuneLite.LOGS_DIR, "inferno-assistant-debug.log");

	private final Map<Integer, NpcThreatState> npcStates = new HashMap<>();
	private final LosEngine losEngine = new LosEngine();
	private final PillarTracker pillarTracker = new PillarTracker();
	private final ThreatPredictor threatPredictor = new ThreatPredictor();
	private final InfernoAssistantDebugLogger debugLogger = new InfernoAssistantDebugLogger();

	private Map<Integer, ConflictResolution> currentQueue = Map.of();
	private Map<Long, EnumSet<AttackStyle>> currentLosTiles = Map.of();

	@Provides
	InfernoAssistantConfig provideConfig(ConfigManager configManager)
	{
		return configManager.getConfig(InfernoAssistantConfig.class);
	}

	@Override
	protected void startUp() throws Exception
	{
		overlayManager.add(overlay);
		overlayManager.add(losOverlay);
		if (config.debugLogging())
		{
			debugLogger.open(DEBUG_LOG_FILE);
		}
	}

	@Override
	protected void shutDown() throws Exception
	{
		overlayManager.remove(overlay);
		overlayManager.remove(losOverlay);
		npcStates.clear();
		currentQueue = Map.of();
		currentLosTiles = Map.of();
		debugLogger.close();
	}

	@Subscribe
	public void onConfigChanged(ConfigChanged event)
	{
		if (!"infernoassistant".equals(event.getGroup()) || !"debugLogging".equals(event.getKey()))
		{
			return;
		}
		if (config.debugLogging())
		{
			debugLogger.open(DEBUG_LOG_FILE);
		}
		else
		{
			debugLogger.close();
		}
	}

	@Subscribe
	public void onGameStateChanged(GameStateChanged event)
	{
		if (event.getGameState() != GameState.LOGGED_IN)
		{
			npcStates.clear();
			currentQueue = Map.of();
			currentLosTiles = Map.of();
		}
	}

	@Subscribe
	public void onNpcSpawned(NpcSpawned event)
	{
		NPC npc = event.getNpc();

		if (!isInInferno())
		{
			debugLogger.log("onNpcSpawned: ignoring npc index=%d id=%d name=%s - not in inferno region",
				npc.getIndex(), npc.getId(), npc.getName());
			return;
		}

		MobType type = typeFor(npc);
		if (type == null)
		{
			debugLogger.log("onNpcSpawned: no MobType match for npc index=%d id=%d name=%s",
				npc.getIndex(), npc.getId(), npc.getName());
			return;
		}

		WorldPoint worldPoint = npc.getWorldLocation();
		if (worldPoint == null)
		{
			debugLogger.log("onNpcSpawned: npc index=%d type=%s has null world location", npc.getIndex(), type);
			return;
		}

		MobDef def = MobDef.of(type);
		Footprint footprint = GridConstants.footprintFor(worldPoint, def.size);
		npcStates.put(npc.getIndex(), new NpcThreatState(npc.getIndex(), type, footprint));
		debugLogger.log("onNpcSpawned: tracking npc index=%d type=%s footprint=(%d,%d,%d)",
			npc.getIndex(), type, footprint.x, footprint.y, footprint.size);
	}

	@Subscribe
	public void onNpcDespawned(NpcDespawned event)
	{
		NpcThreatState removed = npcStates.remove(event.getNpc().getIndex());
		if (removed != null)
		{
			debugLogger.log("onNpcDespawned: stopped tracking npc index=%d type=%s",
				event.getNpc().getIndex(), removed.mobType);
		}
	}

	@Subscribe
	public void onGameTick(GameTick event)
	{
		if (!isInInferno())
		{
			currentQueue = Map.of();
			currentLosTiles = Map.of();
			return;
		}

		pillarTracker.updateFromNpcs(client.getNpcs());
		pillarTracker.applyTo(losEngine);

		Player localPlayer = client.getLocalPlayer();
		if (localPlayer == null)
		{
			debugLogger.log("onGameTick: local player is null, skipping tick");
			return;
		}
		WorldPoint playerWorldPoint = localPlayer.getWorldLocation();
		if (playerWorldPoint == null)
		{
			debugLogger.log("onGameTick: player world location is null, skipping tick");
			return;
		}
		Footprint playerFootprint = GridConstants.footprintFor(playerWorldPoint, 1);

		refreshNpcFootprints();

		boolean protectMagic = client.isPrayerActive(Prayer.PROTECT_FROM_MAGIC);
		boolean protectMissiles = client.isPrayerActive(Prayer.PROTECT_FROM_MISSILES);
		boolean protectMelee = client.isPrayerActive(Prayer.PROTECT_FROM_MELEE);
		int queueLength = Math.max(0, config.queueLength());
		int tick = client.getTickCount();
		boolean allPillarsDown = Arrays.stream(PillarSlot.values()).noneMatch(pillarTracker::isAlive);

		debugLogger.log("onGameTick: tick=%d player=(%d,%d) trackedNpcs=%d protectMagic=%b protectMissiles=%b protectMelee=%b allPillarsDown=%b",
			tick, playerFootprint.x, playerFootprint.y, npcStates.size(), protectMagic, protectMissiles, protectMelee, allPillarsDown);

		List<ThreatPrediction> predictions = new ArrayList<>();
		for (NpcThreatState state : npcStates.values())
		{
			List<ThreatPrediction> npcPredictions = threatPredictor.advance(state, playerFootprint, losEngine,
				protectMagic, protectMissiles, protectMelee, tick, queueLength, allPillarsDown);
			debugLogger.log("  npc index=%d type=%s footprint=(%d,%d,%d) hasLos=%b inRange=%b ticksSinceLastAttack=%d blobPhase=%s predictions=%d",
				state.npcIndex, state.mobType, state.footprint.x, state.footprint.y, state.footprint.size,
				state.hasLos, state.inRange, state.ticksSinceLastAttack, state.blobPhase, npcPredictions.size());
			for (ThreatPrediction prediction : npcPredictions)
			{
				debugLogger.log("    prediction npc=%d type=%s ticksUntilHit=%d style=%s expectedDamage=%d uncertain=%b meleerDigWarning=%b armed=%b",
					prediction.npcIndex, prediction.mobType, prediction.ticksUntilHit, prediction.style,
					prediction.expectedDamage, prediction.uncertain, prediction.meleerDigWarning, prediction.armed);
			}
			predictions.addAll(npcPredictions);
		}

		currentQueue = ConflictResolver.resolve(predictions, queueLength);
		currentLosTiles = LosTileCalculator.computeLosTiles(npcStates.values(), losEngine);
		debugLogger.log("onGameTick: resolved queue entries=%d losTiles=%d", currentQueue.size(), currentLosTiles.size());
	}

	private void refreshNpcFootprints()
	{
		for (NPC npc : client.getNpcs())
		{
			if (npc == null)
			{
				continue;
			}
			NpcThreatState state = npcStates.get(npc.getIndex());
			if (state == null)
			{
				continue;
			}
			WorldPoint worldPoint = npc.getWorldLocation();
			if (worldPoint == null)
			{
				continue;
			}
			state.footprint = GridConstants.footprintFor(worldPoint, MobDef.of(state.mobType).size);
		}
	}

	boolean isInInferno()
	{
		if (client.getGameState() != GameState.LOGGED_IN)
		{
			return false;
		}
		int[] regions = client.getMapRegions();
		if (regions == null)
		{
			return false;
		}
		for (int region : regions)
		{
			if (region == GridConstants.INFERNO_REGION_ID)
			{
				return true;
			}
		}
		return false;
	}

	Map<Integer, ConflictResolution> getCurrentQueue()
	{
		return currentQueue;
	}

	Map<Long, EnumSet<AttackStyle>> getCurrentLosTiles()
	{
		return currentLosTiles;
	}

	/**
	 * Name-match first (name may be null pre-load), ID fallback, ported from
	 * {@code InfernoScouterPlugin.typeFor}.
	 */
	private static MobType typeFor(NPC npc)
	{
		String name = npc.getName();
		if (name != null)
		{
			switch (name)
			{
				case "Jal-MejRah":
					return MobType.BAT;
				case "Jal-Ak":
					return MobType.BLOB;
				case "Jal-ImKot":
					return MobType.MELEE;
				case "Jal-Xil":
					return MobType.RANGER;
				case "Jal-Zek":
					return MobType.MAGER;
				case "Jal-Nib":
					return MobType.NIBBLER;
				default:
					break;
			}
		}

		switch (npc.getId())
		{
			case 7692:
				return MobType.BAT;
			case 7693:
				return MobType.BLOB;
			case 7697:
				return MobType.MELEE;
			case 7698:
			case 7702:
				return MobType.RANGER;
			case 7699:
			case 7703:
				return MobType.MAGER;
			default:
				return null;
		}
	}
}
