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

import java.awt.Canvas;
import java.awt.Component;
import java.awt.event.InputEvent;
import java.awt.event.KeyEvent;
import java.awt.event.MouseEvent;
import java.awt.event.MouseWheelEvent;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import lombok.extern.slf4j.Slf4j;
import net.runelite.api.Client;

/**
 * Translates inbound {@code mouseEvent}/{@code keyEvent} messages (see
 * {@link GameBridgePlugin#processIncoming}) into synthetic AWT events
 * dispatched directly onto the game's {@link Canvas} via
 * {@link Canvas#dispatchEvent}.
 *
 * This is how Python-side input (mouse/keyboard) can be injected straight
 * into the client without going through OS-level {@code SendInput} — see
 * GAMEBRIDGE.md, "Injecting input".
 *
 * Instance state ({@link #heldKeyModifiers}/{@link #heldButtonMask}) tracks
 * which modifier keys and mouse buttons are currently held, accumulated
 * across however many incoming messages this connection has sent — a single
 * message only ever carries its own action, not the full set of keys/buttons
 * still down from earlier messages, so {@code buildMouseEvents}/
 * {@code buildKeyEvent} need that accumulated state handed in explicitly to
 * report realistic {@code getModifiersEx()} values.
 */
@Slf4j
class InputEventDispatcher
{
	private static final int WHEEL_SCROLL_AMOUNT = 3;

	private final Client client;

	private int heldKeyModifiers;
	private int heldButtonMask;

	InputEventDispatcher(Client client)
	{
		this.client = client;
	}

	void dispatchMouseEvent(Map<String, Object> msg)
	{
		Canvas canvas = client.getCanvas();
		int eventId = mouseEventId(msg.get("action"));
		Integer buttonField = toInteger(msg.get("button"));
		int buttonBit = buttonField != null ? buttonDownMask(buttonField) : 0;

		// Press: the bit goes active before the event is built, so the press
		// event itself reports the button as down (matches real hardware).
		if (eventId == MouseEvent.MOUSE_PRESSED)
		{
			heldButtonMask |= buttonBit;
		}

		for (MouseEvent event : buildMouseEvents(canvas, msg, heldKeyModifiers | heldButtonMask))
		{
			canvas.dispatchEvent(event);
		}

		// Release: built using the still-held state above, only cleared after.
		if (eventId == MouseEvent.MOUSE_RELEASED)
		{
			heldButtonMask &= ~buttonBit;
		}
	}

	void dispatchKeyEvent(Map<String, Object> msg)
	{
		Canvas canvas = client.getCanvas();
		Object action = msg.get("action");
		Integer keyCode = toInteger(msg.get("keyCode"));
		int modifierBit = keyCode != null ? modifierMaskFor(keyCode) : 0;

		if ("press".equals(action) && modifierBit != 0)
		{
			heldKeyModifiers |= modifierBit;
		}

		KeyEvent event = buildKeyEvent(canvas, msg, heldKeyModifiers);
		if (event != null)
		{
			canvas.dispatchEvent(event);
		}

		if ("release".equals(action) && modifierBit != 0)
		{
			heldKeyModifiers &= ~modifierBit;
		}
	}

	/**
	 * Clears accumulated modifier-key/mouse-button state. Call when a client
	 * disconnects so a dropped connection mid-gesture can't leave a modifier
	 * "stuck" held for the next connection.
	 */
	void reset()
	{
		heldKeyModifiers = 0;
		heldButtonMask = 0;
	}

	/**
	 * Builds the AWT mouse event(s) for {@code msg}, or an empty list if the
	 * message is malformed. Split out from {@link #dispatchMouseEvent} so the
	 * construction logic (button/coordinate handling, the release -> clicked
	 * synthesis) can be unit tested without needing a real dispatch target.
	 * Kept static and pure — {@code currentModifiers} is the accumulated
	 * held-key/held-button state, owned and mutated only by the instance
	 * methods above.
	 */
	static List<MouseEvent> buildMouseEvents(Component source, Map<String, Object> msg, int currentModifiers)
	{
		if ("wheel".equals(msg.get("action")))
		{
			return buildWheelEvents(source, msg, currentModifiers);
		}

		int eventId = mouseEventId(msg.get("action"));
		Integer x = toInteger(msg.get("x"));
		Integer y = toInteger(msg.get("y"));
		if (eventId == -1 || x == null || y == null)
		{
			log.warn("Game Bridge: malformed mouseEvent: {}", msg);
			return Collections.emptyList();
		}

		Integer buttonField = toInteger(msg.get("button"));
		int button = buttonField != null ? buttonField : MouseEvent.NOBUTTON;
		int clickCount = clickCountFor(eventId, msg);

		MouseEvent primary = new MouseEvent(
			source, eventId, System.currentTimeMillis(), currentModifiers, x, y, clickCount, false, button);

		// Synthetic events bypass the platform's own press/release -> clicked
		// synthesis, so emit it ourselves: a release is always the tail of a
		// discrete click as far as Python's input layer is concerned (see
		// BridgeInputBackend.click_left/click_right).
		if (eventId != MouseEvent.MOUSE_RELEASED)
		{
			return Collections.singletonList(primary);
		}
		MouseEvent clicked = new MouseEvent(
			source, MouseEvent.MOUSE_CLICKED, System.currentTimeMillis(), 0, x, y, clickCount, false, button);
		return Arrays.asList(primary, clicked);
	}

	private static List<MouseEvent> buildWheelEvents(Component source, Map<String, Object> msg, int currentModifiers)
	{
		Integer x = toInteger(msg.get("x"));
		Integer y = toInteger(msg.get("y"));
		Integer rotation = toInteger(msg.get("rotation"));
		if (x == null || y == null || rotation == null)
		{
			log.warn("Game Bridge: malformed mouseEvent: {}", msg);
			return Collections.emptyList();
		}

		MouseWheelEvent wheel = new MouseWheelEvent(
			source, MouseEvent.MOUSE_WHEEL, System.currentTimeMillis(), currentModifiers,
			x, y, 0, false, MouseWheelEvent.WHEEL_UNIT_SCROLL, WHEEL_SCROLL_AMOUNT, rotation);
		return Collections.singletonList(wheel);
	}

	private static int clickCountFor(int eventId, Map<String, Object> msg)
	{
		if (eventId != MouseEvent.MOUSE_PRESSED && eventId != MouseEvent.MOUSE_RELEASED)
		{
			return 0;
		}
		Integer clickCount = toInteger(msg.get("clickCount"));
		return clickCount != null ? clickCount : 1;
	}

	/**
	 * Builds the AWT key event for {@code msg}, or {@code null} if the
	 * message is malformed. Split out from {@link #dispatchKeyEvent} for the
	 * same reason as {@link #buildMouseEvents}.
	 */
	static KeyEvent buildKeyEvent(Component source, Map<String, Object> msg, int currentModifiers)
	{
		Object action = msg.get("action");
		int eventId;
		if ("press".equals(action))
		{
			eventId = KeyEvent.KEY_PRESSED;
		}
		else if ("release".equals(action))
		{
			eventId = KeyEvent.KEY_RELEASED;
		}
		else if ("type".equals(action))
		{
			eventId = KeyEvent.KEY_TYPED;
		}
		else
		{
			log.warn("Game Bridge: malformed keyEvent: {}", msg);
			return null;
		}

		char keyChar = keyCharOf(msg.get("keyChar"));
		Integer keyCode = toInteger(msg.get("keyCode"));

		if (eventId == KeyEvent.KEY_TYPED)
		{
			if (keyChar == KeyEvent.CHAR_UNDEFINED)
			{
				log.warn("Game Bridge: keyEvent 'type' missing keyChar: {}", msg);
				return null;
			}
		}
		else if (keyCode == null)
		{
			log.warn("Game Bridge: keyEvent missing keyCode: {}", msg);
			return null;
		}

		int vk = eventId == KeyEvent.KEY_TYPED ? KeyEvent.VK_UNDEFINED : keyCode;
		return new KeyEvent(source, eventId, System.currentTimeMillis(), currentModifiers, vk, keyChar);
	}

	private static int mouseEventId(Object action)
	{
		if ("move".equals(action))
		{
			return MouseEvent.MOUSE_MOVED;
		}
		if ("press".equals(action))
		{
			return MouseEvent.MOUSE_PRESSED;
		}
		if ("release".equals(action))
		{
			return MouseEvent.MOUSE_RELEASED;
		}
		if ("drag".equals(action))
		{
			return MouseEvent.MOUSE_DRAGGED;
		}
		return -1;
	}

	private static int buttonDownMask(int button)
	{
		switch (button)
		{
			case MouseEvent.BUTTON1:
				return InputEvent.BUTTON1_DOWN_MASK;
			case MouseEvent.BUTTON2:
				return InputEvent.BUTTON2_DOWN_MASK;
			case MouseEvent.BUTTON3:
				return InputEvent.BUTTON3_DOWN_MASK;
			default:
				return 0;
		}
	}

	private static int modifierMaskFor(int keyCode)
	{
		switch (keyCode)
		{
			case KeyEvent.VK_SHIFT:
				return InputEvent.SHIFT_DOWN_MASK;
			case KeyEvent.VK_CONTROL:
				return InputEvent.CTRL_DOWN_MASK;
			case KeyEvent.VK_ALT:
				return InputEvent.ALT_DOWN_MASK;
			default:
				return 0;
		}
	}

	private static char keyCharOf(Object value)
	{
		return value instanceof String && !((String) value).isEmpty()
			? ((String) value).charAt(0)
			: KeyEvent.CHAR_UNDEFINED;
	}

	private static Integer toInteger(Object value)
	{
		return value instanceof Number ? (int) Math.round(((Number) value).doubleValue()) : null;
	}
}
