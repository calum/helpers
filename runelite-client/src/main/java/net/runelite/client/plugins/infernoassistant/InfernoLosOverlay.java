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
import java.awt.Dimension;
import java.awt.Graphics2D;
import java.awt.Polygon;
import java.util.EnumSet;
import java.util.Map;
import javax.inject.Inject;
import net.runelite.api.Client;
import net.runelite.api.Perspective;
import net.runelite.api.Player;
import net.runelite.api.WorldView;
import net.runelite.api.coords.LocalPoint;
import net.runelite.api.coords.WorldPoint;
import net.runelite.client.ui.overlay.Overlay;
import net.runelite.client.ui.overlay.OverlayLayer;
import net.runelite.client.ui.overlay.OverlayPosition;

/**
 * Ground-tile "danger zone" overlay: shades tiles by which NPC attack
 * style(s) currently have line of sight to them, per {@link LosTileCalculator}.
 * Deliberately a plain borderless fill at low alpha - subtle threat shading,
 * not a replacement for the prayer-recommendation panel in
 * {@link InfernoAssistantOverlay}.
 */
class InfernoLosOverlay extends Overlay
{
	private final Client client;
	private final InfernoAssistantPlugin plugin;
	private final InfernoAssistantConfig config;

	@Inject
	private InfernoLosOverlay(Client client, InfernoAssistantPlugin plugin, InfernoAssistantConfig config)
	{
		this.client = client;
		this.plugin = plugin;
		this.config = config;
		setPosition(OverlayPosition.DYNAMIC);
		setLayer(OverlayLayer.ABOVE_SCENE);
		setPriority(PRIORITY_LOW);
	}

	@Override
	public Dimension render(Graphics2D graphics)
	{
		if (!config.showLosOverlay() || !plugin.isInInferno())
		{
			return null;
		}

		Map<Long, EnumSet<AttackStyle>> losTiles = plugin.getCurrentLosTiles();
		if (losTiles.isEmpty())
		{
			return null;
		}

		Player localPlayer = client.getLocalPlayer();
		if (localPlayer == null)
		{
			return null;
		}
		WorldView worldView = localPlayer.getWorldView();
		int plane = localPlayer.getWorldLocation().getPlane();
		int alpha = config.losOverlayAlpha();

		for (Map.Entry<Long, EnumSet<AttackStyle>> entry : losTiles.entrySet())
		{
			int gridX = LosTileCalculator.unpackX(entry.getKey());
			int gridY = LosTileCalculator.unpackY(entry.getKey());

			WorldPoint worldPoint = GridConstants.worldPointFor(gridX, gridY, plane);
			LocalPoint localPoint = LocalPoint.fromWorld(worldView, worldPoint);
			if (localPoint == null)
			{
				continue;
			}

			Polygon poly = Perspective.getCanvasTilePoly(client, localPoint);
			if (poly == null)
			{
				continue;
			}

			graphics.setColor(blend(entry.getValue(), alpha));
			graphics.fill(poly);
		}

		return null;
	}

	private Color blend(EnumSet<AttackStyle> styles, int alpha)
	{
		int r = 0;
		int g = 0;
		int b = 0;
		for (AttackStyle style : styles)
		{
			Color styleColor = colorFor(style);
			r += styleColor.getRed();
			g += styleColor.getGreen();
			b += styleColor.getBlue();
		}
		int count = styles.size();
		return new Color(r / count, g / count, b / count, alpha);
	}

	private Color colorFor(AttackStyle style)
	{
		switch (style)
		{
			case MAGIC:
				return config.mageColor();
			case RANGE:
				return config.rangeColor();
			case MELEE:
				return config.meleeColor();
			default:
				throw new IllegalStateException("Unhandled AttackStyle: " + style);
		}
	}
}
