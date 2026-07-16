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

import java.util.List;

/**
 * The resolved recommendation for a single tick offset in the lookahead
 * window, per DESIGN.md §6. {@code recommendedStyle} is {@code null} when
 * there are no predicted attacks at this tick. {@code unmitigated} holds
 * every predicted attack whose style differs from the recommendation -
 * never dropped, always surfaced.
 */
final class ConflictResolution
{
	final AttackStyle recommendedStyle;
	final List<ThreatPrediction> unmitigated;
	final List<ThreatPrediction> meleerDigWarnings;
	final List<ThreatPrediction> armedWarnings;

	ConflictResolution(AttackStyle recommendedStyle, List<ThreatPrediction> unmitigated,
		List<ThreatPrediction> meleerDigWarnings, List<ThreatPrediction> armedWarnings)
	{
		this.recommendedStyle = recommendedStyle;
		this.unmitigated = unmitigated;
		this.meleerDigWarnings = meleerDigWarnings;
		this.armedWarnings = armedWarnings;
	}
}
