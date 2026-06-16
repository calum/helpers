"""
InteractionRoutine — shared helpers for routines that click on game entities.

Two gating patterns recur across every routine that interacts with the
world (mining, fighting, looting, banking — see iron_mining.py and
melee_fighter.py):

1. **Approach** — before clicking an entity, bring it on screen, steer the
   camera clear of occluding UI panels, and wait for the player to stop
   moving. A one-tick settle buffer ensures the click lands once the
   walk/camera-pan has visually resolved rather than mid-motion (firing the
   instant `player_idle()` flips true can still land while the camera is
   still panning).

2. **Verify before you click** — right-click an entity, read the context
   menu back to confirm the option you actually want is present (a blind
   left-click can land on a tile or another entity in a crowd), then click
   that exact row. Right-click menus don't time out, so one that opens
   without the wanted row has to be dismissed explicitly or the routine
   would sit there forever.

`InteractionRoutine` factors both into reusable, tick-driven helpers so
individual routines describe *what* to interact with, not *how* to wait
for the game to be ready. Subclass it instead of `Routine` to use them.
"""
from __future__ import annotations

import logging
from enum import Enum, auto
from typing import Callable, Optional, TYPE_CHECKING

from .base import Routine
from ..input.keyboard import Key
from ..widget_ids import Inventory

if TYPE_CHECKING:
    from ..state.game_state import GameState
    from ..controller.controller import GameController

log = logging.getLogger(__name__)

OCCLUSION_NUDGE_YAW = 128.0  # ~1/16 turn — enough to shift an entity's canvas position out from behind a fixed UI panel


class MenuClick(Enum):
    """Outcome of one tick's attempt to confirm-and-click a context menu row."""

    CONFIRMED = auto()  # the row was present and clicked — gesture complete
    ABANDONED = auto()  # menu closed without the row — give up, retarget fresh
    PENDING = auto()    # menu still open without the row — dismissed, keep waiting


class DropMode(Enum):
    """How `InteractionRoutine.drop_item` performs its drop gesture."""

    SHIFT_CLICK = auto()  # hold Shift, left-click — RuneLite's shift-click default is "Drop"; one tick, nothing to verify
    RIGHT_CLICK = auto()  # right-click, verify a "Drop" entry in the menu, then click it — spans ticks


class InteractionRoutine(Routine):
    """Routine base class adding `approach`, `verified_menu_click`, and
    `click_live`/`right_click_live`."""

    # subId for live clickbox subscriptions (see click_live/right_click_live
    # below). A routine's state machine only ever has one click in flight per
    # tick, so every click site in a routine instance can safely share this
    # one subId — re-subscribing just renews/retargets it.
    LIVE_HULL_SUB_ID = "click_target"

    # Fields copied from a hullUpdate entity onto the per-tick entity dict —
    # everything click_entity/right_click_entity actually look at.
    _LIVE_HULL_FIELDS = ("onScreen", "canvasX", "canvasY", "hull", "worldX", "worldY", "plane")

    def __init__(self) -> None:
        super().__init__()
        self._approach_idle_since_tick: int = -1
        self._drop_target: Optional[dict] = None
        self._drop_queue: list[dict] = []
        self._drop_pending: Optional[dict] = None
        self._drop_skipped: set = set()

    # ------------------------------------------------------------------
    # Approach
    # ------------------------------------------------------------------

    def approach(self, game: "GameState", ctrl: "GameController", entity: dict) -> bool:
        """
        Drive the camera/movement gating needed before interacting with
        `entity`. Call once per tick while approaching it; returns True on
        the single tick it's safe to click — on screen, unoccluded, and the
        player idle for a full settle tick — and resets its internal buffer
        so the next approach starts fresh. Returns False on every other
        tick, so callers can simply:

            if not self.approach(game, ctrl, entity):
                return None
            ctrl.click_entity(entity)
        """
        name = entity.get("name", "entity")

        if not ctrl.bring_entity_on_screen(entity, game):
            log.debug("%s not visible — adjusting camera", name)
            self._approach_idle_since_tick = -1
            return False

        if entity.get("onScreen") and game.is_occluded(entity["canvasX"], entity["canvasY"]):
            # `bring_entity_on_screen`/`rotate_camera_to` both bail out as
            # soon as `onScreen` is true — exactly the state we're in here,
            # so calling either is a no-op and the entity sits behind the
            # panel forever. UI panels live at fixed canvas positions, so
            # rotating the camera is what actually moves the entity's
            # projected position out from behind one.
            log.debug("%s is hidden behind a UI panel — nudging camera clear", name)
            ctrl.rotate_camera(Key.RIGHT, OCCLUSION_NUDGE_YAW)
            self._approach_idle_since_tick = -1
            return False

        if not game.player_idle():
            self._approach_idle_since_tick = -1
            return False

        if self._approach_idle_since_tick == -1:
            self._approach_idle_since_tick = game.tick
            return False

        self._approach_idle_since_tick = -1
        return True

    # ------------------------------------------------------------------
    # Verify before you click
    # ------------------------------------------------------------------

    def verified_menu_click(
        self,
        game: "GameState",
        ctrl: "GameController",
        verb: str,
        target_name: Optional[str],
    ) -> MenuClick:
        """
        Attempt to confirm-and-click a "`verb` `target_name`" row in an
        already-open right-click context menu (the gesture must have been
        started with `ctrl.right_click_entity(...)` beforehand). Call once
        per tick while the gesture is pending — it never blocks:

        - CONFIRMED: the row was there and got clicked — gesture done.
        - ABANDONED: the menu closed without the row — give up and retry
          with a fresh target next tick.
        - PENDING: the menu is still open without the row — it has been
          dismissed (menus don't time out) so the gesture can be retried
          once it closes.
        """
        if ctrl.click_menu_entry(game, verb, target_name):
            return MenuClick.CONFIRMED

        if not game.menu_open():
            log.debug("Menu closed without a %s %s entry — retrying", verb, target_name)
            return MenuClick.ABANDONED

        log.debug("Menu open without a %s %s entry — dismissing it", verb, target_name)
        ctrl.dismiss_menu(game)
        return MenuClick.PENDING

    # ------------------------------------------------------------------
    # Live clickbox subscriptions
    # ------------------------------------------------------------------
    #
    # The per-tick `entity` dict's canvasX/canvasY/hull can be up to ~600ms
    # stale by the time a click lands — long enough for a moving NPC/object
    # or a panning camera to drift off the clicked point. `click_live`/
    # `right_click_live` (re)subscribe for `entity` and, if a fresher
    # hullUpdate (~20ms cadence) has already arrived for it, click that
    # position instead. See GAMEBRIDGE.md "Live clickbox subscriptions".

    def _with_live_hull(self, ctrl: "GameController", entity: dict) -> dict:
        """Return `entity` with onScreen/canvas/hull fields refreshed from the
        latest LIVE_HULL_SUB_ID hullUpdate, if one has arrived for this same
        entity. Falls back to `entity` unchanged if no update has arrived yet,
        or the update is for a different (just-subscribed-to) entity — both
        normal on the first click after retargeting.
        """
        update = ctrl.hull_update(self.LIVE_HULL_SUB_ID)
        if not update or not update.get("found"):
            return entity

        if (update.get("name") or "").lower() != (entity.get("name") or "").lower():
            return entity

        live = dict(entity)
        for field in self._LIVE_HULL_FIELDS:
            if field in update:
                live[field] = update[field]
        return live

    def _verify_tooltip_and_act(
        self,
        ctrl: "GameController",
        live: dict,
        verify_tooltip: bool,
        act: Callable[[dict], None],
    ) -> bool:
        """Shared body of `click_live`/`right_click_live`: log the current
        tooltip, optionally verify `live["name"]` appears in it, and either
        perform `act(live)` (the click) or move the mouse towards `live`
        instead so the next call gets a fresher tooltip to check.

        If `verify_tooltip` is False, or `live` has no `name`, the tooltip is
        still logged but the check is skipped — some entities (e.g. tiles
        with no left-click action) never produce a tooltip that contains
        their name.

        Returns True if `act(live)` ran (the click fired), False if the
        mouse was moved instead — callers must not assume the click happened
        just because this was called.
        """
        tooltip = ctrl.tooltip()
        age = ctrl.tooltip_age()
        age_str = f"{age * 1000:.0f}ms" if isinstance(age, (int, float)) else age
        log.debug("Tooltip before click: %r (age=%s)", tooltip, age_str)

        name = live.get("name")
        if verify_tooltip and name and name.lower() not in tooltip.lower():
            log.debug(
                "%r not found in tooltip %r — moving mouse instead of clicking",
                name, tooltip,
            )
            ctrl.move_to_entity(live)
            return False

        act(live)
        return True

    def click_live(self, ctrl: "GameController", entity: dict, kind: str, verify_tooltip: bool = True) -> bool:
        """Subscribe to `entity` for live hull updates, then left-click it
        using the freshest available canvas position — and keep tracking
        those live updates while the cursor is moving towards it (see
        `GameController._plan_live_click`).

        `kind` is one of "npc"/"object"/"player"/"groundItem" — see
        `GameController.subscribe_to`.

        Before clicking, the current `ctrl.tooltip()` is logged at debug
        level and, if `verify_tooltip` is True (the default) and `entity` has
        a `name`, checked to contain that name — confirming the cursor is
        actually hovering this entity rather than scenery/another entity in
        front of it. If the name isn't found, the click is skipped and the
        mouse is moved towards `entity` instead, so a later call (once the
        tooltip catches up) can verify and click. Pass `verify_tooltip=False`
        for entities with no meaningful left-click tooltip (e.g. some tiles).

        Returns True if the click fired, False if the mouse was moved instead
        — callers that gate a state transition on "the click landed" must
        check this rather than assuming success.
        """
        ctrl.subscribe_to(self.LIVE_HULL_SUB_ID, kind, name=entity.get("name"), id=entity.get("id"))
        live = self._with_live_hull(ctrl, entity)
        return self._verify_tooltip_and_act(
            ctrl, live, verify_tooltip,
            lambda e: ctrl.click_entity(e, sub_id=self.LIVE_HULL_SUB_ID),
        )

    def right_click_live(self, ctrl: "GameController", entity: dict, kind: str, verify_tooltip: bool = True) -> bool:
        """Subscribe to `entity` for live hull updates, then right-click it
        using the freshest available canvas position — and keep tracking
        those live updates while the cursor is moving towards it (see
        `GameController._plan_live_click`).

        `kind` is one of "npc"/"object"/"player"/"groundItem" — see
        `GameController.subscribe_to`.

        Same tooltip logging/verification as `click_live` — see its
        docstring for details, the `verify_tooltip` flag, and the meaning of
        the returned bool.
        """
        ctrl.subscribe_to(self.LIVE_HULL_SUB_ID, kind, name=entity.get("name"), id=entity.get("id"))
        live = self._with_live_hull(ctrl, entity)
        return self._verify_tooltip_and_act(
            ctrl, live, verify_tooltip,
            lambda e: ctrl.right_click_entity(e, sub_id=self.LIVE_HULL_SUB_ID),
        )

    # ------------------------------------------------------------------
    # Dropping inventory items
    # ------------------------------------------------------------------

    def drop_item(
        self,
        game: "GameState",
        ctrl: "GameController",
        item_ids,
        mode: DropMode = DropMode.SHIFT_CLICK,
        group_id: int = Inventory.GROUP,
    ) -> bool:
        """
        Drop one inventory item whose `itemId` is in `item_ids`. Call once
        per tick from a "dropping" state:

            def dropping(self, game, ctrl):
                if self.drop_item(game, ctrl, self.DROP_ITEM_IDS):
                    return None
                return "find_spot"

        Returns True while there's still a matching item (stay in the
        current state and call again next tick), False once nothing matching
        `item_ids` remains in the inventory (the caller should transition
        away).

        - `DropMode.SHIFT_CLICK` (default): RuneLite's default left-click
          action while Shift is held is "Drop". A real player holds Shift
          down for an entire drop sequence rather than tapping it before
          every click, so this holds Shift (`ctrl.hold_key`) on the first
          matching item and only releases it (`ctrl.release_key`) once
          nothing is left to drop — every item in between is a plain
          `ctrl.click_widget`, no menu to verify.
        - `DropMode.RIGHT_CLICK`: right-click the item, verify a "Drop" entry
          is actually in the context menu (`verified_menu_click`), then click
          it — the same "verify before you click" gesture as picking up loot,
          spanning multiple ticks per item.
        """
        widget = next(
            (w for w in game.widgets if w.get("groupId") == group_id and w.get("itemId") in item_ids),
            None,
        )

        if mode is DropMode.SHIFT_CLICK:
            if widget is None:
                ctrl.release_key(Key.SHIFT)
                return False

            ctrl.hold_key(Key.SHIFT)
            ctrl.click_widget(widget)
            return True

        if self._drop_target is not None:
            outcome = self.verified_menu_click(game, ctrl, "Drop", None)

            if outcome is not MenuClick.PENDING:
                self._drop_target = None

            return True

        if widget is None:
            return False

        ctrl.right_click_widget(widget)
        self._drop_target = widget
        return True

    def drop_items_shift_click(
        self,
        game: "GameState",
        ctrl: "GameController",
        item_ids,
        group_id: int = Inventory.GROUP,
        verify_tooltip: bool = False,
    ) -> bool:
        """
        Shift-drop every inventory item whose `itemId` is in `item_ids`.

        By default (`verify_tooltip=False`) this is fire-and-forget: the
        first tick it sees any matching widgets it queues them all, holds
        Shift once, and clicks each queued widget one time. If any items
        remain on a later tick, the method rebuilds the queue and retries
        them again.

        If `verify_tooltip` is True, each queued item is handled across two
        calls instead: the mouse is moved to the slot (without clicking),
        then on the following call `ctrl.tooltip()` is logged at debug level
        and checked for "drop" — only then is the item actually clicked. A
        slot whose tooltip never says "Drop" (e.g. its left-click action is
        "Wear"/"Wield"/"Read" for that item) is skipped rather than
        mis-clicked, and excluded from the queue for the rest of this drop
        sequence.

        Returns True while there are still matching items to clear and the
        caller should remain in the drop state, False once no matching item
        remains (or all have been skipped) and Shift can be released.
        """
        if not self._drop_queue and self._drop_pending is None:
            self._drop_queue = [
                w for w in game.widgets
                if w.get("groupId") == group_id
                and w.get("itemId") in item_ids
                and w.get("childId") not in self._drop_skipped
            ]

        if not self._drop_queue and self._drop_pending is None:
            ctrl.release_key(Key.SHIFT)
            self._drop_skipped.clear()
            return False

        ctrl.hold_key(Key.SHIFT)

        if not verify_tooltip:
            for widget in self._drop_queue:
                ctrl.click_widget(widget)
            self._drop_queue = []
            return True

        if self._drop_pending is not None:
            widget = self._drop_pending
            self._drop_pending = None
            tooltip = ctrl.tooltip()
            log.debug("Tooltip before drop click: %r", tooltip)
            if "drop" in tooltip.lower():
                ctrl.click_widget(widget)
            else:
                log.debug(
                    "'drop' not found in tooltip %r — skipping slot %d",
                    tooltip, widget.get("childId", -1),
                )
                self._drop_skipped.add(widget.get("childId"))
            return True

        widget = self._drop_queue.pop(0)
        ctrl.move_to_widget(widget)
        self._drop_pending = widget
        return True
