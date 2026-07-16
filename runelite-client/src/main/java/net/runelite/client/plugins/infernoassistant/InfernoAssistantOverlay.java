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
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.util.List;
import java.util.Map;
import javax.inject.Inject;
import net.runelite.api.gameval.SpriteID;
import net.runelite.client.game.SpriteManager;
import net.runelite.client.ui.overlay.OverlayPanel;
import net.runelite.client.ui.overlay.OverlayPosition;
import net.runelite.client.ui.overlay.components.ComponentOrientation;
import net.runelite.client.ui.overlay.components.ImageComponent;
import net.runelite.client.ui.overlay.components.LineComponent;
import net.runelite.client.ui.overlay.components.PanelComponent;
import net.runelite.client.ui.overlay.components.TitleComponent;

/**
 * Single info-box overlay per DESIGN.md §7: current tick's recommendation
 * (plus a conflict line when applicable), then a lookahead queue of up to
 * {@code queueLength} ticks. Prayer recommendations are shown as the actual
 * protection prayer icon rather than text (icon-only, per design decision).
 */
class InfernoAssistantOverlay extends OverlayPanel
{
	private final InfernoAssistantPlugin plugin;
	private final InfernoAssistantConfig config;

	private BufferedImage magicIcon;
	private BufferedImage rangeIcon;
	private BufferedImage meleeIcon;

	@Inject
	private InfernoAssistantOverlay(InfernoAssistantPlugin plugin, InfernoAssistantConfig config,
		SpriteManager spriteManager)
	{
		super(plugin);
		this.plugin = plugin;
		this.config = config;
		setPosition(OverlayPosition.TOP_LEFT);

		spriteManager.getSpriteAsync(SpriteID.Prayeron.PROTECT_FROM_MAGIC, 0, image -> magicIcon = image);
		spriteManager.getSpriteAsync(SpriteID.Prayeron.PROTECT_FROM_MISSILES, 0, image -> rangeIcon = image);
		spriteManager.getSpriteAsync(SpriteID.Prayeron.PROTECT_FROM_MELEE, 0, image -> meleeIcon = image);
	}

	@Override
	public Dimension render(Graphics2D graphics)
	{
		if (!config.showOverlay() || !plugin.isInInferno())
		{
			return null;
		}

		Map<Integer, ConflictResolution> queue = plugin.getCurrentQueue();
		ConflictResolution current = queue.get(0);

		renderTitle(current, queue);

		if (current != null)
		{
			if (config.showUnmitigatedWarnings() && !current.unmitigated.isEmpty())
			{
				panelComponent.getChildren().add(LineComponent.builder()
					.left(unmitigatedText(current.unmitigated))
					.leftColor(Color.ORANGE)
					.build());
			}
			if (!current.meleerDigWarnings.isEmpty())
			{
				panelComponent.getChildren().add(LineComponent.builder()
					.left("Meleer may relocate soon")
					.leftColor(Color.ORANGE)
					.build());
			}
			for (ThreatPrediction armed : current.armedWarnings)
			{
				panelComponent.getChildren().add(LineComponent.builder()
					.left(armed.mobType + " armed (no LOS)")
					.leftColor(colorFor(armed.style))
					.build());
			}
		}

		int queueLength = Math.max(0, config.queueLength());
		for (int tick = 1; tick <= queueLength; tick++)
		{
			ConflictResolution resolution = queue.get(tick);
			if (resolution == null)
			{
				continue;
			}

			panelComponent.getChildren().add(queueRow(tick, resolution));
		}

		return super.render(graphics);
	}

	/**
	 * Top title: the current tick's recommendation if there is one, otherwise
	 * the nearest upcoming recommendation in the queue (labelled with its
	 * countdown) so the overlay recommends a prayer before an NPC actually
	 * has LOS, rather than only once something is due this very tick.
	 */
	private void renderTitle(ConflictResolution current, Map<Integer, ConflictResolution> queue)
	{
		if (current != null && current.recommendedStyle != null)
		{
			BufferedImage icon = iconFor(current.recommendedStyle);
			if (icon != null)
			{
				panelComponent.getChildren().add(new ImageComponent(icon));
				return;
			}
			panelComponent.getChildren().add(TitleComponent.builder()
				.text(styleName(current.recommendedStyle))
				.color(colorFor(current.recommendedStyle))
				.build());
			return;
		}

		Map.Entry<Integer, ConflictResolution> next = nearestUpcoming(queue);
		if (next != null)
		{
			BufferedImage icon = iconFor(next.getValue().recommendedStyle);
			if (icon != null)
			{
				panelComponent.getChildren().add(iconRow("+" + next.getKey(), icon));
				return;
			}
			panelComponent.getChildren().add(TitleComponent.builder()
				.text("+" + next.getKey() + " " + styleName(next.getValue().recommendedStyle))
				.color(colorFor(next.getValue().recommendedStyle))
				.build());
			return;
		}

		panelComponent.getChildren().add(TitleComponent.builder()
			.text("No threats")
			.color(Color.WHITE)
			.build());
	}

	private static Map.Entry<Integer, ConflictResolution> nearestUpcoming(Map<Integer, ConflictResolution> queue)
	{
		Map.Entry<Integer, ConflictResolution> nearest = null;
		for (Map.Entry<Integer, ConflictResolution> entry : queue.entrySet())
		{
			if (entry.getKey() <= 0 || entry.getValue().recommendedStyle == null)
			{
				continue;
			}
			if (nearest == null || entry.getKey() < nearest.getKey())
			{
				nearest = entry;
			}
		}
		return nearest;
	}

	private PanelComponent queueRow(int tick, ConflictResolution resolution)
	{
		if (resolution.recommendedStyle == null)
		{
			return textRow("+" + tick, "no safe prayer", Color.RED);
		}

		BufferedImage icon = iconFor(resolution.recommendedStyle);
		if (icon == null)
		{
			boolean conflict = config.showUnmitigatedWarnings() && !resolution.unmitigated.isEmpty();
			String right = styleName(resolution.recommendedStyle) + (conflict ? " (conflict)" : "");
			return textRow("+" + tick, right, colorFor(resolution.recommendedStyle));
		}

		PanelComponent row = iconRow("+" + tick, icon);
		if (config.showUnmitigatedWarnings() && !resolution.unmitigated.isEmpty())
		{
			row.getChildren().add(LineComponent.builder()
				.left("!")
				.leftColor(Color.ORANGE)
				.build());
		}
		return row;
	}

	private PanelComponent textRow(String left, String right, Color rightColor)
	{
		PanelComponent row = new PanelComponent();
		row.setOrientation(ComponentOrientation.HORIZONTAL);
		row.setBackgroundColor(null);
		row.setBorder(new Rectangle());
		row.getChildren().add(LineComponent.builder()
			.left(left)
			.right(right)
			.rightColor(rightColor)
			.build());
		return row;
	}

	private PanelComponent iconRow(String left, BufferedImage icon)
	{
		PanelComponent row = new PanelComponent();
		row.setOrientation(ComponentOrientation.HORIZONTAL);
		row.setBackgroundColor(null);
		row.setBorder(new Rectangle());
		row.getChildren().add(LineComponent.builder()
			.left(left)
			.build());
		row.getChildren().add(new ImageComponent(icon));
		return row;
	}

	private BufferedImage iconFor(AttackStyle style)
	{
		switch (style)
		{
			case MAGIC:
				return magicIcon;
			case RANGE:
				return rangeIcon;
			case MELEE:
				return meleeIcon;
			default:
				throw new IllegalStateException("Unhandled AttackStyle: " + style);
		}
	}

	private String unmitigatedText(List<ThreatPrediction> unmitigated)
	{
		StringBuilder builder = new StringBuilder("(");
		for (int i = 0; i < unmitigated.size(); i++)
		{
			if (i > 0)
			{
				builder.append(", ");
			}
			ThreatPrediction prediction = unmitigated.get(i);
			builder.append(prediction.mobType).append(" unmitigated — ").append(prediction.expectedDamage).append(" dmg");
		}
		builder.append(")");
		return builder.toString();
	}

	private String styleName(AttackStyle style)
	{
		switch (style)
		{
			case MAGIC:
				return "Protect from Magic";
			case RANGE:
				return "Protect from Missiles";
			case MELEE:
				return "Protect from Melee";
			default:
				throw new IllegalStateException("Unhandled AttackStyle: " + style);
		}
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
