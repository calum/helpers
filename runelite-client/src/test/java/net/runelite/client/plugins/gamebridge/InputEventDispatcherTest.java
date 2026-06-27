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
import java.awt.event.InputEvent;
import java.awt.event.KeyEvent;
import java.awt.event.KeyListener;
import java.awt.event.MouseEvent;
import java.awt.event.MouseListener;
import java.awt.event.MouseMotionListener;
import java.awt.event.MouseWheelEvent;
import java.awt.event.MouseWheelListener;
import java.util.HashMap;
import java.util.Map;
import net.runelite.api.Client;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import org.mockito.junit.MockitoJUnitRunner;

/**
 * Dispatches synthetic {@link MouseEvent}/{@link KeyEvent}s onto a real
 * {@link Canvas} (no peer/display needed for listener dispatch) and asserts
 * on what the registered listeners actually receive — this is the same
 * mechanism the real game's input listeners are hooked up through.
 */
@RunWith(MockitoJUnitRunner.class)
public class InputEventDispatcherTest
{
	@Mock
	private Client client;

	@Mock
	private MouseListener mouseListener;

	@Mock
	private MouseMotionListener mouseMotionListener;

	@Mock
	private MouseWheelListener mouseWheelListener;

	@Mock
	private KeyListener keyListener;

	private Canvas canvas;
	private InputEventDispatcher dispatcher;

	@Before
	public void setUp()
	{
		canvas = new Canvas();
		canvas.addMouseListener(mouseListener);
		canvas.addMouseMotionListener(mouseMotionListener);
		canvas.addMouseWheelListener(mouseWheelListener);
		canvas.addKeyListener(keyListener);
		when(client.getCanvas()).thenReturn(canvas);
		dispatcher = new InputEventDispatcher(client);
	}

	// ------------------------------------------------------------------ //
	// Mouse events
	// ------------------------------------------------------------------ //

	@Test
	public void mousePressDispatchesMousePressedWithButtonAndPosition()
	{
		dispatcher.dispatchMouseEvent(mouseMsg("press", 100, 200, MouseEvent.BUTTON1));

		ArgumentCaptor<MouseEvent> captor = ArgumentCaptor.forClass(MouseEvent.class);
		verify(mouseListener).mousePressed(captor.capture());
		MouseEvent event = captor.getValue();
		assertEquals(100, event.getX());
		assertEquals(200, event.getY());
		assertEquals(MouseEvent.BUTTON1, event.getButton());
		assertEquals(InputEvent.BUTTON1_DOWN_MASK, event.getModifiersEx());
	}

	@Test
	public void mouseMoveDispatchesMouseMovedWithNoButton()
	{
		dispatcher.dispatchMouseEvent(mouseMsg("move", 50, 60, null));

		ArgumentCaptor<MouseEvent> captor = ArgumentCaptor.forClass(MouseEvent.class);
		verify(mouseMotionListener).mouseMoved(captor.capture());
		MouseEvent event = captor.getValue();
		assertEquals(50, event.getX());
		assertEquals(60, event.getY());
		assertEquals(MouseEvent.NOBUTTON, event.getButton());
	}

	@Test
	public void mouseReleaseAlsoFiresSyntheticClickEvent()
	{
		dispatcher.dispatchMouseEvent(mouseMsg("release", 10, 20, MouseEvent.BUTTON3));

		ArgumentCaptor<MouseEvent> released = ArgumentCaptor.forClass(MouseEvent.class);
		ArgumentCaptor<MouseEvent> clicked = ArgumentCaptor.forClass(MouseEvent.class);
		verify(mouseListener).mouseReleased(released.capture());
		verify(mouseListener).mouseClicked(clicked.capture());

		assertEquals(MouseEvent.BUTTON3, released.getValue().getButton());
		assertEquals(MouseEvent.BUTTON3, clicked.getValue().getButton());
		assertEquals(10, clicked.getValue().getX());
		assertEquals(20, clicked.getValue().getY());
	}

	@Test
	public void mouseEventMissingCoordinatesIsNotDispatched()
	{
		Map<String, Object> msg = new HashMap<>();
		msg.put("type", "mouseEvent");
		msg.put("action", "move");
		dispatcher.dispatchMouseEvent(msg);

		verifyNoInteractions(mouseListener, mouseMotionListener);
	}

	@Test
	public void mouseEventUnknownActionIsNotDispatched()
	{
		dispatcher.dispatchMouseEvent(mouseMsg("scroll", 1, 1, null));

		verifyNoInteractions(mouseListener, mouseMotionListener);
	}

	@Test
	public void fractionalCoordinatesAreRoundedNotTruncated()
	{
		Map<String, Object> msg = mouseMsg("move", null, null, null);
		msg.put("x", 3.9);
		msg.put("y", -3.6);
		dispatcher.dispatchMouseEvent(msg);

		ArgumentCaptor<MouseEvent> captor = ArgumentCaptor.forClass(MouseEvent.class);
		verify(mouseMotionListener).mouseMoved(captor.capture());
		assertEquals(4, captor.getValue().getX());
		assertEquals(-4, captor.getValue().getY());
	}

	// ------------------------------------------------------------------ //
	// Click-and-drag (item 2)
	// ------------------------------------------------------------------ //

	@Test
	public void dragActionDispatchesMouseDraggedWithButtonDownMask()
	{
		dispatcher.dispatchMouseEvent(mouseMsg("press", 0, 0, MouseEvent.BUTTON1));
		dispatcher.dispatchMouseEvent(mouseMsg("drag", 15, 25, MouseEvent.BUTTON1));

		ArgumentCaptor<MouseEvent> captor = ArgumentCaptor.forClass(MouseEvent.class);
		verify(mouseMotionListener).mouseDragged(captor.capture());
		MouseEvent event = captor.getValue();
		assertEquals(15, event.getX());
		assertEquals(25, event.getY());
		assertEquals(InputEvent.BUTTON1_DOWN_MASK, event.getModifiersEx());
	}

	// ------------------------------------------------------------------ //
	// Double-click clickCount (item 3)
	// ------------------------------------------------------------------ //

	@Test
	public void explicitClickCountIsPropagatedToPressReleaseAndClicked()
	{
		Map<String, Object> press = mouseMsg("press", 5, 5, MouseEvent.BUTTON1);
		press.put("clickCount", 2);
		dispatcher.dispatchMouseEvent(press);

		Map<String, Object> release = mouseMsg("release", 5, 5, MouseEvent.BUTTON1);
		release.put("clickCount", 2);
		dispatcher.dispatchMouseEvent(release);

		ArgumentCaptor<MouseEvent> pressed = ArgumentCaptor.forClass(MouseEvent.class);
		ArgumentCaptor<MouseEvent> released = ArgumentCaptor.forClass(MouseEvent.class);
		ArgumentCaptor<MouseEvent> clicked = ArgumentCaptor.forClass(MouseEvent.class);
		verify(mouseListener).mousePressed(pressed.capture());
		verify(mouseListener).mouseReleased(released.capture());
		verify(mouseListener).mouseClicked(clicked.capture());

		assertEquals(2, pressed.getValue().getClickCount());
		assertEquals(2, released.getValue().getClickCount());
		assertEquals(2, clicked.getValue().getClickCount());
	}

	@Test
	public void absentClickCountDefaultsToOne()
	{
		dispatcher.dispatchMouseEvent(mouseMsg("press", 5, 5, MouseEvent.BUTTON1));

		ArgumentCaptor<MouseEvent> captor = ArgumentCaptor.forClass(MouseEvent.class);
		verify(mouseListener).mousePressed(captor.capture());
		assertEquals(1, captor.getValue().getClickCount());
	}

	// ------------------------------------------------------------------ //
	// Modifier-state tracking (item 4)
	// ------------------------------------------------------------------ //

	// KeyEvent *delivery* to a KeyListener can't be observed here (see the
	// class-level comment on the key-event tests below) — but a held
	// modifier key feeds into the *same* accumulated state used to compute
	// a subsequent mouse event's modifiers (see InputEventDispatcher.
	// dispatchMouseEvent: currentModifiers = heldKeyModifiers | heldButtonMask),
	// and mouse delivery IS observable headlessly. Verifying through a mouse
	// press is therefore an equally valid (and the only testable) way to
	// confirm dispatchKeyEvent's modifier-bit bookkeeping actually ran.

	@Test
	public void shiftHeldThenMousePressCarriesShiftModifier()
	{
		dispatcher.dispatchKeyEvent(keyMsg("press", KeyEvent.VK_SHIFT, null));
		dispatcher.dispatchMouseEvent(mouseMsg("press", 0, 0, MouseEvent.BUTTON1));

		ArgumentCaptor<MouseEvent> captor = ArgumentCaptor.forClass(MouseEvent.class);
		verify(mouseListener).mousePressed(captor.capture());
		assertEquals(
			InputEvent.SHIFT_DOWN_MASK | InputEvent.BUTTON1_DOWN_MASK,
			captor.getValue().getModifiersEx());
	}

	@Test
	public void releasingShiftClearsModifierForSubsequentMousePress()
	{
		dispatcher.dispatchKeyEvent(keyMsg("press", KeyEvent.VK_SHIFT, null));
		dispatcher.dispatchKeyEvent(keyMsg("release", KeyEvent.VK_SHIFT, null));
		dispatcher.dispatchMouseEvent(mouseMsg("press", 0, 0, MouseEvent.BUTTON1));

		ArgumentCaptor<MouseEvent> captor = ArgumentCaptor.forClass(MouseEvent.class);
		verify(mouseListener).mousePressed(captor.capture());
		assertEquals(InputEvent.BUTTON1_DOWN_MASK, captor.getValue().getModifiersEx());
	}

	@Test
	public void leftAndRightMouseButtonsBothHeldAccumulateModifiers()
	{
		dispatcher.dispatchMouseEvent(mouseMsg("press", 0, 0, MouseEvent.BUTTON1));
		dispatcher.dispatchMouseEvent(mouseMsg("press", 0, 0, MouseEvent.BUTTON3));

		ArgumentCaptor<MouseEvent> captor = ArgumentCaptor.forClass(MouseEvent.class);
		verify(mouseListener, org.mockito.Mockito.times(2)).mousePressed(captor.capture());
		MouseEvent secondPress = captor.getAllValues().get(1);
		assertEquals(
			InputEvent.BUTTON1_DOWN_MASK | InputEvent.BUTTON3_DOWN_MASK,
			secondPress.getModifiersEx());
	}

	@Test
	public void resetClearsAccumulatedModifierState()
	{
		dispatcher.dispatchKeyEvent(keyMsg("press", KeyEvent.VK_SHIFT, null));
		dispatcher.dispatchMouseEvent(mouseMsg("press", 0, 0, MouseEvent.BUTTON1));
		dispatcher.dispatchMouseEvent(mouseMsg("release", 0, 0, MouseEvent.BUTTON1));

		dispatcher.reset();

		dispatcher.dispatchMouseEvent(mouseMsg("press", 0, 0, MouseEvent.BUTTON3));

		ArgumentCaptor<MouseEvent> captor = ArgumentCaptor.forClass(MouseEvent.class);
		verify(mouseListener, org.mockito.Mockito.times(2)).mousePressed(captor.capture());
		MouseEvent secondPress = captor.getAllValues().get(1);
		assertEquals(InputEvent.BUTTON3_DOWN_MASK, secondPress.getModifiersEx());
	}

	// ------------------------------------------------------------------ //
	// Mouse wheel (item 5)
	// ------------------------------------------------------------------ //

	@Test
	public void wheelActionDispatchesMouseWheelEventWithRotation()
	{
		Map<String, Object> msg = new HashMap<>();
		msg.put("type", "mouseEvent");
		msg.put("action", "wheel");
		msg.put("x", 50);
		msg.put("y", 60);
		msg.put("rotation", -1);
		dispatcher.dispatchMouseEvent(msg);

		ArgumentCaptor<MouseWheelEvent> captor = ArgumentCaptor.forClass(MouseWheelEvent.class);
		verify(mouseWheelListener).mouseWheelMoved(captor.capture());
		assertEquals(-1, captor.getValue().getWheelRotation());
	}

	@Test
	public void wheelActionMissingRotationIsNotDispatched()
	{
		Map<String, Object> msg = new HashMap<>();
		msg.put("type", "mouseEvent");
		msg.put("action", "wheel");
		msg.put("x", 50);
		msg.put("y", 60);
		dispatcher.dispatchMouseEvent(msg);

		verifyNoInteractions(mouseWheelListener);
	}

	// ------------------------------------------------------------------ //
	// Key events
	//
	// Key event *construction* (buildKeyEvent) is exercised directly rather
	// than through dispatchKeyEvent + a real KeyListener: in a headless test
	// JVM, Component.dispatchEvent silently swallows KeyEvents before they
	// reach any KeyListener (no keyboard focus subsystem is present), even
	// though the same dispatch works correctly in the real, focused client.
	// buildKeyEvent contains 100% of this class's key-event logic — dispatch
	// itself is a single unconditional canvas.dispatchEvent(event) call.
	// ------------------------------------------------------------------ //

	@Test
	public void keyPressBuildsKeyPressedWithKeyCode()
	{
		KeyEvent event = InputEventDispatcher.buildKeyEvent(canvas, keyMsg("press", KeyEvent.VK_LEFT, null), 0);

		assertEquals(KeyEvent.KEY_PRESSED, event.getID());
		assertEquals(KeyEvent.VK_LEFT, event.getKeyCode());
	}

	@Test
	public void keyReleaseBuildsKeyReleased()
	{
		KeyEvent event = InputEventDispatcher.buildKeyEvent(canvas, keyMsg("release", KeyEvent.VK_SHIFT, null), 0);

		assertEquals(KeyEvent.KEY_RELEASED, event.getID());
		assertEquals(KeyEvent.VK_SHIFT, event.getKeyCode());
	}

	@Test
	public void keyTypeBuildsKeyTypedWithKeyChar()
	{
		KeyEvent event = InputEventDispatcher.buildKeyEvent(canvas, keyMsg("type", null, "a"), 0);

		assertEquals(KeyEvent.KEY_TYPED, event.getID());
		assertEquals('a', event.getKeyChar());
	}

	@Test
	public void keyPressMissingKeyCodeBuildsNothing()
	{
		assertNull(InputEventDispatcher.buildKeyEvent(canvas, keyMsg("press", null, null), 0));
	}

	@Test
	public void keyTypeMissingKeyCharBuildsNothing()
	{
		assertNull(InputEventDispatcher.buildKeyEvent(canvas, keyMsg("type", null, null), 0));
	}

	@Test
	public void keyEventUnknownActionBuildsNothing()
	{
		assertNull(InputEventDispatcher.buildKeyEvent(canvas, keyMsg("hold", KeyEvent.VK_A, null), 0));
	}

	@Test
	public void dispatchKeyEventForwardsBuiltEventToCanvas()
	{
		// Smoke-tests the dispatch wiring itself (real canvas.dispatchEvent
		// call happens), independent of whether a KeyListener ever sees it.
		dispatcher.dispatchKeyEvent(keyMsg("press", KeyEvent.VK_A, null));
		dispatcher.dispatchKeyEvent(keyMsg("hold", KeyEvent.VK_A, null)); // malformed — must not throw
	}

	// ------------------------------------------------------------------ //
	// Helpers
	// ------------------------------------------------------------------ //

	private static Map<String, Object> mouseMsg(String action, Integer x, Integer y, Integer button)
	{
		Map<String, Object> msg = new HashMap<>();
		msg.put("type", "mouseEvent");
		msg.put("action", action);
		if (x != null)
		{
			msg.put("x", x);
		}
		if (y != null)
		{
			msg.put("y", y);
		}
		if (button != null)
		{
			msg.put("button", button);
		}
		return msg;
	}

	private static Map<String, Object> keyMsg(String action, Integer keyCode, String keyChar)
	{
		Map<String, Object> msg = new HashMap<>();
		msg.put("type", "keyEvent");
		msg.put("action", action);
		if (keyCode != null)
		{
			msg.put("keyCode", keyCode);
		}
		if (keyChar != null)
		{
			msg.put("keyChar", keyChar);
		}
		return msg;
	}
}
