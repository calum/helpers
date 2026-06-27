"""
Unit tests for BridgeInputBackend — the transport that routes mouse/keyboard
primitives through the live BridgeConnection as mouseEvent/keyEvent
messages, instead of OS-level SendInput.

The BridgeConnection itself is mocked — these tests assert on the JSON-able
dict payloads passed to `connection.send()`, matching what
InputEventDispatcher.java (buildMouseEvents/buildKeyEvent) expects.

Run with:
    python -m pytest scripts/gamebridge/tests/test_bridge_input.py -v
"""
from unittest.mock import MagicMock, call, patch

from scripts.gamebridge.input import bridge_input
from scripts.gamebridge.input.bridge_input import (
    BUTTON_LEFT,
    BUTTON_RIGHT,
    BridgeInputBackend,
    _vk_for,
)


def _backend():
    return BridgeInputBackend(MagicMock())


# ---------------------------------------------------------------------------
# get_position / move_to
# ---------------------------------------------------------------------------

class TestPosition:
    def test_initial_position_is_origin(self):
        backend = _backend()
        assert backend.get_position() == (0.0, 0.0)

    def test_move_to_updates_position(self):
        backend = _backend()
        backend.move_to(10, 20)
        assert backend.get_position() == (10, 20)

    def test_move_to_sends_move_event(self):
        backend = _backend()
        backend.move_to(10.4, 20.6)
        backend._connection.send.assert_called_once_with({
            "type": "mouseEvent", "action": "move", "x": 10, "y": 21,
        })


# ---------------------------------------------------------------------------
# click_left / click_right
# ---------------------------------------------------------------------------

class TestClick:
    def test_click_left_sends_press_then_release_with_button1(self):
        backend = _backend()
        with patch("scripts.gamebridge.input.bridge_input.time"):
            backend.click_left()

        assert backend._connection.send.call_args_list == [
            call({"type": "mouseEvent", "action": "press", "x": 0, "y": 0, "button": BUTTON_LEFT, "clickCount": 1}),
            call({"type": "mouseEvent", "action": "release", "x": 0, "y": 0, "button": BUTTON_LEFT, "clickCount": 1}),
        ]

    def test_click_right_sends_press_then_release_with_button3(self):
        backend = _backend()
        with patch("scripts.gamebridge.input.bridge_input.time"):
            backend.click_right()

        assert backend._connection.send.call_args_list == [
            call({"type": "mouseEvent", "action": "press", "x": 0, "y": 0, "button": BUTTON_RIGHT, "clickCount": 1}),
            call({"type": "mouseEvent", "action": "release", "x": 0, "y": 0, "button": BUTTON_RIGHT, "clickCount": 1}),
        ]

    def test_click_with_coordinates_moves_first(self):
        backend = _backend()
        with patch("scripts.gamebridge.input.bridge_input.time"):
            backend.click_left(50, 60)

        assert backend.get_position() == (50, 60)
        move_call, press_call, release_call = backend._connection.send.call_args_list
        assert move_call == call({"type": "mouseEvent", "action": "move", "x": 50, "y": 60})
        assert press_call.args[0]["x"] == 50
        assert press_call.args[0]["y"] == 60
        assert release_call.args[0]["x"] == 50
        assert release_call.args[0]["y"] == 60

    def test_click_without_coordinates_does_not_move(self):
        backend = _backend()
        with patch("scripts.gamebridge.input.bridge_input.time"):
            backend.click_left()

        assert all(c.args[0]["action"] != "move" for c in backend._connection.send.call_args_list)

    def test_held_button_is_cleared_after_a_click(self):
        backend = _backend()
        with patch("scripts.gamebridge.input.bridge_input.time"):
            backend.click_left()

        assert backend._held_button is None


# ---------------------------------------------------------------------------
# button_down / button_up / move_to drag (item 2)
# ---------------------------------------------------------------------------

class TestDrag:
    def test_button_down_sends_press_and_holds_button(self):
        backend = _backend()
        backend.button_down(BUTTON_LEFT)

        backend._connection.send.assert_called_once_with(
            {"type": "mouseEvent", "action": "press", "x": 0, "y": 0, "button": BUTTON_LEFT, "clickCount": 1})
        assert backend._held_button == BUTTON_LEFT

    def test_button_up_sends_release_and_clears_held_button(self):
        backend = _backend()
        backend.button_down(BUTTON_LEFT)
        backend.button_up(BUTTON_LEFT)

        assert backend._connection.send.call_args_list[-1] == call(
            {"type": "mouseEvent", "action": "release", "x": 0, "y": 0, "button": BUTTON_LEFT, "clickCount": 1})
        assert backend._held_button is None

    def test_button_up_with_mismatched_button_does_not_clear_held_button(self):
        backend = _backend()
        backend.button_down(BUTTON_LEFT)
        backend.button_up(BUTTON_RIGHT)

        assert backend._held_button == BUTTON_LEFT

    def test_move_to_sends_move_when_no_button_held(self):
        backend = _backend()
        backend.move_to(10, 20)

        backend._connection.send.assert_called_once_with(
            {"type": "mouseEvent", "action": "move", "x": 10, "y": 20})

    def test_move_to_sends_drag_with_button_while_held(self):
        backend = _backend()
        backend.button_down(BUTTON_LEFT)
        backend.move_to(10, 20)

        assert backend._connection.send.call_args_list[-1] == call(
            {"type": "mouseEvent", "action": "drag", "x": 10, "y": 20, "button": BUTTON_LEFT})

    def test_move_to_reverts_to_move_after_button_up(self):
        backend = _backend()
        backend.button_down(BUTTON_LEFT)
        backend.button_up(BUTTON_LEFT)
        backend.move_to(10, 20)

        assert backend._connection.send.call_args_list[-1] == call(
            {"type": "mouseEvent", "action": "move", "x": 10, "y": 20})


# ---------------------------------------------------------------------------
# clickCount / double-click tracking (item 3)
# ---------------------------------------------------------------------------

class TestClickCount:
    def test_second_click_at_same_spot_within_window_is_clickcount_2(self):
        backend = _backend()
        with patch.object(bridge_input.time, "sleep"):
            backend.click_left(10, 10)
            backend.click_left(10, 10)

        press_calls = [c for c in backend._connection.send.call_args_list if c.args[0]["action"] == "press"]
        assert press_calls[0].args[0]["clickCount"] == 1
        assert press_calls[1].args[0]["clickCount"] == 2

    def test_third_click_within_window_increments_to_3(self):
        backend = _backend()
        with patch.object(bridge_input.time, "sleep"):
            backend.click_left(10, 10)
            backend.click_left(10, 10)
            backend.click_left(10, 10)

        press_calls = [c for c in backend._connection.send.call_args_list if c.args[0]["action"] == "press"]
        assert press_calls[2].args[0]["clickCount"] == 3

    def test_click_after_double_click_window_elapses_resets_to_1(self):
        backend = _backend()
        # 3 monotonic() calls total: store after click 1, check + store for
        # click 2. A >500ms gap between the first store and click 2's check
        # must reset clickCount to 1 despite same position/button.
        with patch.object(bridge_input.time, "sleep"), \
                patch.object(bridge_input.time, "monotonic", side_effect=[0.0, 1.0, 1.0]):
            backend.click_left(10, 10)
            backend.click_left(10, 10)

        press_calls = [c for c in backend._connection.send.call_args_list if c.args[0]["action"] == "press"]
        assert press_calls[1].args[0]["clickCount"] == 1

    def test_click_at_different_position_resets_to_1(self):
        backend = _backend()
        with patch.object(bridge_input.time, "sleep"):
            backend.click_left(10, 10)
            backend.click_left(200, 200)

        press_calls = [c for c in backend._connection.send.call_args_list if c.args[0]["action"] == "press"]
        assert press_calls[1].args[0]["clickCount"] == 1

    def test_click_with_different_button_resets_to_1(self):
        backend = _backend()
        with patch.object(bridge_input.time, "sleep"):
            backend.click_left(10, 10)
            backend.click_right(10, 10)

        press_calls = [c for c in backend._connection.send.call_args_list if c.args[0]["action"] == "press"]
        assert press_calls[1].args[0]["clickCount"] == 1


# ---------------------------------------------------------------------------
# scroll (item 5)
# ---------------------------------------------------------------------------

class TestScroll:
    def test_scroll_sends_wheel_event_at_current_position(self):
        backend = _backend()
        backend.move_to(10, 20)
        backend._connection.send.reset_mock()

        backend.scroll(-1)

        backend._connection.send.assert_called_once_with(
            {"type": "mouseEvent", "action": "wheel", "x": 10, "y": 20, "rotation": -1})


# ---------------------------------------------------------------------------
# press_key / key_down / key_up
# ---------------------------------------------------------------------------

class TestKeyPress:
    def test_press_key_named_sends_press_then_release_with_vk_code(self):
        backend = _backend()
        with patch("scripts.gamebridge.input.bridge_input.time"):
            backend.press_key("escape", hold_ms=80.0)

        assert backend._connection.send.call_args_list == [
            call({"type": "keyEvent", "action": "press", "keyCode": 0x1B}),
            call({"type": "keyEvent", "action": "release", "keyCode": 0x1B}),
        ]

    def test_press_key_holds_for_requested_duration(self):
        backend = _backend()
        with patch("scripts.gamebridge.input.bridge_input.time") as mock_time:
            backend.press_key("escape", hold_ms=80.0)

        mock_time.sleep.assert_called_once_with(0.08)

    def test_press_key_lowercase_letter_no_shift_wrap(self):
        backend = _backend()
        with patch("scripts.gamebridge.input.bridge_input.time"):
            backend.press_key("a")

        assert backend._connection.send.call_args_list == [
            call({"type": "keyEvent", "action": "press", "keyCode": ord("A")}),
            call({"type": "keyEvent", "action": "release", "keyCode": ord("A")}),
        ]

    def test_press_key_uppercase_letter_wraps_in_shift(self):
        backend = _backend()
        with patch("scripts.gamebridge.input.bridge_input.time"):
            backend.press_key("A")

        assert backend._connection.send.call_args_list == [
            call({"type": "keyEvent", "action": "press", "keyCode": 0x10}),
            call({"type": "keyEvent", "action": "press", "keyCode": ord("A")}),
            call({"type": "keyEvent", "action": "release", "keyCode": ord("A")}),
            call({"type": "keyEvent", "action": "release", "keyCode": 0x10}),
        ]

    def test_press_key_unresolvable_key_noops(self):
        backend = _backend()
        with patch("scripts.gamebridge.input.bridge_input.time"):
            backend.press_key("")

        backend._connection.send.assert_not_called()

    def test_key_down_sends_press_only(self):
        backend = _backend()
        backend.key_down("shift")
        backend._connection.send.assert_called_once_with(
            {"type": "keyEvent", "action": "press", "keyCode": 0x10})

    def test_key_up_sends_release_only(self):
        backend = _backend()
        backend.key_up("shift")
        backend._connection.send.assert_called_once_with(
            {"type": "keyEvent", "action": "release", "keyCode": 0x10})

    def test_key_down_unresolvable_key_noops(self):
        backend = _backend()
        backend.key_down("")
        backend._connection.send.assert_not_called()


# ---------------------------------------------------------------------------
# _vk_for
# ---------------------------------------------------------------------------

class TestVkFor:
    def test_named_key_resolves(self):
        assert _vk_for("left") == 0x25
        assert _vk_for("LEFT") == 0x25

    def test_single_lowercase_letter_resolves_to_uppercase_ord(self):
        assert _vk_for("a") == ord("A")

    def test_single_uppercase_letter_resolves_to_same_ord(self):
        assert _vk_for("A") == ord("A")

    def test_digit_resolves(self):
        assert _vk_for("5") == ord("5")

    def test_empty_string_returns_none(self):
        assert _vk_for("") is None

    def test_unresolvable_multi_char_string_returns_none(self):
        assert _vk_for("notakey") is None
