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

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * Per-tick conflict resolution, per DESIGN.md §6: at each tick offset, the
 * highest-{@code expectedDamage} style is recommended, and every other
 * conflicting style at that tick is surfaced as unmitigated rather than
 * dropped. Ties are resolved by first-encountered order in the input list
 * (i.e. stable, deterministic given a fixed NPC iteration order).
 */
final class ConflictResolver
{
	private ConflictResolver()
	{
	}

	static Map<Integer, ConflictResolution> resolve(List<ThreatPrediction> predictions, int queueLength)
	{
		Map<Integer, List<ThreatPrediction>> byTick = new TreeMap<>();
		List<ThreatPrediction> digWarnings = new ArrayList<>();
		List<ThreatPrediction> armedWarnings = new ArrayList<>();

		for (ThreatPrediction prediction : predictions)
		{
			if (prediction.meleerDigWarning)
			{
				digWarnings.add(prediction);
				continue;
			}
			if (prediction.armed)
			{
				armedWarnings.add(prediction);
				continue;
			}
			if (prediction.ticksUntilHit < 0 || prediction.ticksUntilHit > queueLength)
			{
				continue;
			}
			byTick.computeIfAbsent(prediction.ticksUntilHit, k -> new ArrayList<>()).add(prediction);
		}

		Map<Integer, ConflictResolution> result = new TreeMap<>();
		for (int tick = 0; tick <= queueLength; tick++)
		{
			List<ThreatPrediction> atTick = byTick.getOrDefault(tick, List.of());
			List<ThreatPrediction> digWarningsHere = tick == 0 ? digWarnings : List.of();
			List<ThreatPrediction> armedWarningsHere = tick == 0 ? armedWarnings : List.of();

			if (atTick.isEmpty() && digWarningsHere.isEmpty() && armedWarningsHere.isEmpty())
			{
				continue;
			}

			result.put(tick, resolveTick(atTick, digWarningsHere, armedWarningsHere));
		}
		return result;
	}

	private static ConflictResolution resolveTick(List<ThreatPrediction> atTick, List<ThreatPrediction> digWarnings,
		List<ThreatPrediction> armedWarnings)
	{
		if (atTick.isEmpty())
		{
			return new ConflictResolution(null, List.of(), digWarnings, armedWarnings);
		}

		ThreatPrediction highest = atTick.get(0);
		for (ThreatPrediction prediction : atTick)
		{
			if (prediction.expectedDamage > highest.expectedDamage)
			{
				highest = prediction;
			}
		}

		List<ThreatPrediction> unmitigated = new ArrayList<>();
		for (ThreatPrediction prediction : atTick)
		{
			if (prediction.style != highest.style)
			{
				unmitigated.add(prediction);
			}
		}

		return new ConflictResolution(highest.style, unmitigated, digWarnings, armedWarnings);
	}
}
