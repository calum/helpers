"""
In-memory model of the RuneScape game world.

Updated from tick messages delivered by the GameBridge plugin.
Read-only from outside; write only via update().
"""
from __future__ import annotations

import copy
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import interfaces as iface_registry


@dataclass
class GameState:
    tick: int = 0

    # Top-level tick fields
    player: dict = field(default_factory=dict)
    camera: dict = field(default_factory=dict)
    npcs: List[dict] = field(default_factory=list)
    players: List[dict] = field(default_factory=list)
    objects: List[dict] = field(default_factory=list)
    ground_items: List[dict] = field(default_factory=list)

    # Derived from container events
    inventory: List[dict] = field(default_factory=list)
    equipment: List[dict] = field(default_factory=list)

    # Derived from xp events
    xp: Dict[str, int] = field(default_factory=dict)
    levels: Dict[str, int] = field(default_factory=dict)
    boosted_levels: Dict[str, int] = field(default_factory=dict)

    # Derived from varbit events  {"varpId:varbitId": value}
    varbits: Dict[str, int] = field(default_factory=dict)

    # Rolling chat log (capped at 200; deque evicts oldest automatically)
    chat_log: deque = field(default_factory=lambda: deque(maxlen=200))

    # Widget slots (populated when exposeWidgets is on)
    widgets: List[dict] = field(default_factory=list)

    # All active, non-hidden UI widgets from every loaded interface group.
    # Populated when exposeInterfaces is on (default true).
    # Use is_occluded() to test whether a canvas point is behind a UI panel.
    interfaces: List[dict] = field(default_factory=list)

    # Current interacting-with target name, or None
    interacting_with: Optional[str] = None

    # Last tick when we received an XP drop for each skill
    last_xp_tick: Dict[str, int] = field(default_factory=dict)

    _prev_animation: int = field(default=-1, repr=False)
    _prev_pos: Optional[tuple] = field(default=None, repr=False)

    # ------------------------------------------------------------------ #
    # Core update
    # ------------------------------------------------------------------ #

    def clone(self) -> "GameState":
        """Return a copy safe to publish as an immutable snapshot.

        update() replaces most container fields wholesale (a fresh list/dict
        each tick), so a shallow copy can share those references safely — the
        original keeps the old ones, the clone gets new ones on its next
        update(). The exception is the handful of fields _apply_event()
        mutates *in place* (xp/levels/boosted_levels/varbits/last_xp_tick/
        chat_log) — those need fresh copies, or updating the clone would also
        mutate the snapshot a concurrent reader still holds.

        Used by DecisionEngine.ingest() to publish each tick's GameState as a
        stable snapshot the routine-driver thread can read without it changing
        underneath it — see PLAN.md for the threading rationale.
        """
        new = copy.copy(self)
        new.xp = dict(self.xp)
        new.levels = dict(self.levels)
        new.boosted_levels = dict(self.boosted_levels)
        new.varbits = dict(self.varbits)
        new.last_xp_tick = dict(self.last_xp_tick)
        new.chat_log = deque(self.chat_log, maxlen=200)
        return new

    def update(self, msg: dict) -> None:
        """Apply a raw tick message from the GameBridge stream."""
        self.tick = msg["tick"]

        if "player" in msg:
            self._prev_animation = self.player.get("animation", -1)
            self._prev_pos = self.player_pos if self.player else None
            self.player = msg["player"]

        if "camera" in msg:
            self.camera = msg["camera"]

        if "npcs" in msg:
            self.npcs = msg["npcs"]

        if "players" in msg:
            self.players = msg["players"]

        if "objects" in msg:
            self.objects = msg["objects"]

        if "groundItems" in msg:
            self.ground_items = msg["groundItems"]

        if "widgets" in msg:
            self.widgets = msg["widgets"]

        if "interfaces" in msg:
            self.interfaces = msg["interfaces"]

        if "inventory" in msg:
            self.inventory = msg["inventory"]

        if "equipment" in msg:
            self.equipment = msg["equipment"]

        for event in msg.get("events", []):
            self._apply_event(event)

    def _apply_event(self, event: dict) -> None:
        t = event["type"]

        if t == "xp":
            skill = event["skill"]
            self.xp[skill] = event["xp"]
            self.levels[skill] = event["level"]
            self.boosted_levels[skill] = event["boostedLevel"]
            self.last_xp_tick[skill] = self.tick

        elif t == "container":
            cid = event["containerId"]
            if cid == 93:
                self.inventory = event["items"]
            elif cid == 94:  # Equipment (worn items); 95 is Bank
                self.equipment = event["items"]

        elif t == "varbit":
            key = f"{event['varpId']}:{event['varbitId']}"
            self.varbits[key] = event["value"]

        elif t == "chat":
            stamped = dict(event)
            stamped["_tick"] = self.tick
            self.chat_log.append(stamped)

        elif t == "interacting":
            self.interacting_with = event.get("target")

    # ------------------------------------------------------------------ #
    # Player
    # ------------------------------------------------------------------ #

    @property
    def player_pos(self) -> tuple[int, int]:
        return self.player.get("worldX", 0), self.player.get("worldY", 0)

    @property
    def plane(self) -> int:
        return self.player.get("plane", 0)

    def player_animating(self) -> bool:
        return self.player.get("animation", -1) != -1

    def animation_started(self) -> bool:
        """True on the first tick an animation begins."""
        return self._prev_animation == -1 and self.player_animating()

    def animation_ended(self) -> bool:
        """True on the first tick an animation ends."""
        return self._prev_animation != -1 and not self.player_animating()

    def player_moving(self) -> bool:
        """True if the player's world position changed since the last tick."""
        if self._prev_pos is None:
            return False
        return self.player_pos != self._prev_pos

    def player_idle(self) -> bool:
        """True only when the player has no animation AND did not move this tick.

        Requiring a stable tile prevents the double-click window where the
        animation briefly reads -1 before the server-queued walk has started.
        """
        return not self.player_animating() and not self.player_moving()

    def player_hp(self) -> int:
        return self.player.get("hp", 0)

    def player_prayer(self) -> int:
        return self.player.get("prayer", 0)

    # ------------------------------------------------------------------ #
    # Inventory
    # ------------------------------------------------------------------ #

    def inventory_count(self, item_id: int) -> int:
        return sum(s["qty"] for s in self.inventory if s["itemId"] == item_id)

    def inventory_free_slots(self) -> int:
        if not self.inventory:
            return 0
        # Empty slots arrive as itemId=-1 (explicitly cleared) or itemId=0 (never occupied).
        # Real items always have itemId >= 1.
        return sum(1 for s in self.inventory if s["itemId"] <= 0)

    def inventory_used_slots(self) -> int:
        if not self.inventory:
            return 0
        return 28 - self.inventory_free_slots()

    def inventory_full(self) -> bool:
        if not self.inventory:
            return False  # no data yet — don't assume full
        return self.inventory_free_slots() == 0

    def inventory_has_item(self, item_id: int) -> bool:
        return any(s["itemId"] == item_id for s in self.inventory)

    def inventory_empty(self) -> bool:
        if not self.inventory:
            return False  # no data yet — don't assume empty
        return self.inventory_free_slots() == 28

    # ------------------------------------------------------------------ #
    # Widgets
    # ------------------------------------------------------------------ #

    def find_widget(self, group_id: int, child_id: int) -> Optional[dict]:
        """Return the widget with the given groupId/childId, or None."""
        for w in self.widgets:
            if w.get("groupId") == group_id and w.get("childId") == child_id:
                return w
        return None

    # ------------------------------------------------------------------ #
    # Interfaces
    # ------------------------------------------------------------------ #

    def is_occluded(self, canvas_x: float, canvas_y: float) -> bool:
        """Return True if the canvas point lies inside any occluding UI widget.

        Call this before clicking an on-screen entity to avoid hitting a UI
        panel (bank, inventory, chatbox, etc.) instead of the entity.

        Only widgets whose group is explicitly registered as occluding in
        ``state/interfaces.py`` (``occludes(group_id)`` returns True) are
        checked — everything else (viewport/root containers, always-on chrome
        like orbs, xp counters, the minimap, ...) is ignored. The
        ``interfaces`` array dumps every loaded group indiscriminately, and
        most of it visually overlaps the canvas without actually blocking a
        click, so checking the full list (or even just excluding viewport
        roots) produced false "occluded" reports for entities sitting behind
        harmless chrome.

        Example::

            entity = game.nearest_object("Iron rocks")
            if entity and entity["onScreen"]:
                if not game.is_occluded(entity["canvasX"], entity["canvasY"]):
                    ctrl.click_entity(entity)
                else:
                    ctrl.bring_entity_on_screen(entity, game)
        """
        for w in self.interfaces:
            if not iface_registry.occludes(w.get("groupId", -1)):
                continue
            b = w.get("bounds")
            if not b:
                continue
            if (b["x"] <= canvas_x < b["x"] + b["width"] and
                    b["y"] <= canvas_y < b["y"] + b["height"]):
                return True
        return False

    def is_interface_open(self, name: str) -> bool:
        """Return True if any widget from the named interface group is active.

        ``name`` is looked up in the ``state/interfaces.py`` registry to find
        the group's numeric ID, then matched against the live ``interfaces``
        list. Returns False for unregistered names — register the group first
        (see that module's docstring for how).

        Example::

            if game.is_interface_open("silver_crafting"):
                ctrl.click_widget(gold_ring_slot)
            else:
                ctrl.click_entity(game.nearest_object("Furnace"))
        """
        group_id = iface_registry.group_id_for(name)
        if group_id is None:
            return False
        return any(w.get("groupId") == group_id for w in self.interfaces)

    def find_interface_widget(self, group_id: int, child_id: int) -> Optional[dict]:
        """Return the interface widget with the given groupId/childId, or None.

        Searches the full ``interfaces`` list (all active interface groups),
        unlike :meth:`find_widget` which only searches the limited
        ``exposeWidgets`` list.
        """
        for w in self.interfaces:
            if w.get("groupId") == group_id and w.get("childId") == child_id:
                return w
        return None

    def interfaces_for_group(self, group_id: int) -> List[dict]:
        """Return all interface widgets belonging to the given group ID."""
        return [w for w in self.interfaces if w.get("groupId") == group_id]

    # ------------------------------------------------------------------ #
    # NPCs
    # ------------------------------------------------------------------ #

    def npcs_named(self, name: str) -> List[dict]:
        return [n for n in self.npcs if n.get("name", "").lower() == name.lower()]

    def npcs_on_screen(self) -> List[dict]:
        return [n for n in self.npcs if n.get("onScreen")]

    def nearest_npc(self, name: str) -> Optional[dict]:
        px, py = self.player_pos
        return min(
            self.npcs_named(name),
            key=lambda n: abs(n["worldX"] - px) + abs(n["worldY"] - py),
            default=None,
        )

    def nearest_npc_on_screen(self, name: str) -> Optional[dict]:
        """Nearest NPC matching name that is currently on screen."""
        px, py = self.player_pos
        return min(
            (n for n in self.npcs_named(name) if n.get("onScreen")),
            key=lambda n: abs(n["worldX"] - px) + abs(n["worldY"] - py),
            default=None,
        )

    # ------------------------------------------------------------------ #
    # Objects
    # ------------------------------------------------------------------ #

    def objects_named(self, name: str) -> List[dict]:
        return [o for o in self.objects if o.get("name", "").lower() == name.lower()]

    def objects_on_screen(self) -> List[dict]:
        return [o for o in self.objects if o.get("onScreen")]

    def nearest_object(self, name: str) -> Optional[dict]:
        px, py = self.player_pos
        return min(
            self.objects_named(name),
            key=lambda o: abs(o["worldX"] - px) + abs(o["worldY"] - py),
            default=None,
        )

    def nearest_object_on_screen(self, name: str) -> Optional[dict]:
        """Nearest object matching name that is currently on screen."""
        px, py = self.player_pos
        return min(
            (o for o in self.objects_named(name) if o.get("onScreen")),
            key=lambda o: abs(o["worldX"] - px) + abs(o["worldY"] - py),
            default=None,
        )

    def player_near(self, entity: dict, tiles: int = 1) -> bool:
        px, py = self.player_pos
        return (abs(entity["worldX"] - px) + abs(entity["worldY"] - py)) <= tiles

    def distance_to(self, entity: dict) -> int:
        px, py = self.player_pos
        return abs(entity["worldX"] - px) + abs(entity["worldY"] - py)

    def distance_between(self, a: dict, b: dict) -> int:
        return abs(a["worldX"] - b["worldX"]) + abs(a["worldY"] - b["worldY"])

    # ------------------------------------------------------------------ #
    # Other players
    # ------------------------------------------------------------------ #

    def players_named(self, name: str) -> List[dict]:
        return [p for p in self.players if p.get("name", "").lower() == name.lower()]

    def entity_near_other_player(self, entity: dict, tiles: int = 1) -> bool:
        """True if any other player is within `tiles` of the given entity.

        Useful for picking combat targets that aren't already contested —
        e.g. skip an NPC standing next to another player who may be fighting it.
        """
        return any(self.distance_between(entity, p) <= tiles for p in self.players)

    # ------------------------------------------------------------------ #
    # Ground items
    # ------------------------------------------------------------------ #

    def ground_items_at(self, world_x: int, world_y: int) -> List[dict]:
        return [
            i for i in self.ground_items
            if i.get("worldX") == world_x and i.get("worldY") == world_y
        ]

    # ------------------------------------------------------------------ #
    # Camera
    # ------------------------------------------------------------------ #

    def camera_yaw_to(self, entity: dict) -> int:
        """Approximate RS yaw (0-2047) needed to face an entity."""
        px, py = self.player_pos
        dx = entity["worldX"] - px
        dy = entity["worldY"] - py
        return int(math.atan2(-dx, dy) / (2 * math.pi) * 2048 + 2048) % 2048

    # ------------------------------------------------------------------ #
    # Chat
    # ------------------------------------------------------------------ #

    def last_chat_matching(self, substring: str) -> Optional[dict]:
        for msg in reversed(self.chat_log):
            if substring.lower() in msg.get("message", "").lower():
                return msg
        return None

    def chat_since_tick(self, tick: int) -> List[dict]:
        """All chat messages received at or after a given tick."""
        return [m for m in self.chat_log if m.get("_tick", 0) >= tick]

    # ------------------------------------------------------------------ #
    # Varbits
    # ------------------------------------------------------------------ #

    def get_varbit(self, varp_id: int, varbit_id: int = -1) -> Optional[int]:
        return self.varbits.get(f"{varp_id}:{varbit_id}")
