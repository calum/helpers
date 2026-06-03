"""
In-memory model of the RuneScape game world.

Updated from tick messages delivered by the GameBridge plugin.
Read-only from outside; write only via update().
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class GameState:
    tick: int = 0

    # Top-level tick fields
    player: dict = field(default_factory=dict)
    camera: dict = field(default_factory=dict)
    npcs: List[dict] = field(default_factory=list)
    objects: List[dict] = field(default_factory=list)

    # Derived from container events
    inventory: List[dict] = field(default_factory=list)
    equipment: List[dict] = field(default_factory=list)

    # Derived from xp events
    xp: Dict[str, int] = field(default_factory=dict)
    levels: Dict[str, int] = field(default_factory=dict)
    boosted_levels: Dict[str, int] = field(default_factory=dict)

    # Derived from varbit events  {"varpId:varbitId": value}
    varbits: Dict[str, int] = field(default_factory=dict)

    # Rolling chat log (capped)
    chat_log: List[dict] = field(default_factory=list)

    # Current interacting-with target name, or None
    interacting_with: Optional[str] = None

    _prev_animation: int = field(default=-1, repr=False)
    _CHAT_LOG_CAP: int = field(default=200, init=False, repr=False)

    # ------------------------------------------------------------------ #
    # Core update
    # ------------------------------------------------------------------ #

    def update(self, msg: dict) -> None:
        """Apply a raw tick message from the GameBridge stream."""
        self.tick = msg["tick"]

        if "player" in msg:
            self._prev_animation = self.player.get("animation", -1)
            self.player = msg["player"]

        if "camera" in msg:
            self.camera = msg["camera"]

        if "npcs" in msg:
            self.npcs = msg["npcs"]

        if "objects" in msg:
            self.objects = msg["objects"]

        for event in msg.get("events", []):
            self._apply_event(event)

    def _apply_event(self, event: dict) -> None:
        t = event["type"]

        if t == "xp":
            skill = event["skill"]
            self.xp[skill] = event["xp"]
            self.levels[skill] = event["level"]
            self.boosted_levels[skill] = event["boostedLevel"]

        elif t == "container":
            cid = event["containerId"]
            if cid == 93:
                self.inventory = event["items"]
            elif cid == 95:
                self.equipment = event["items"]

        elif t == "varbit":
            key = f"{event['varpId']}:{event['varbitId']}"
            self.varbits[key] = event["value"]

        elif t == "chat":
            self.chat_log.append(event)
            if len(self.chat_log) > self._CHAT_LOG_CAP:
                self.chat_log.pop(0)

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
        return sum(1 for s in self.inventory if s["itemId"] == -1)

    def inventory_used_slots(self) -> int:
        return 28 - self.inventory_free_slots()

    def inventory_full(self) -> bool:
        return self.inventory_free_slots() == 0

    def inventory_has_item(self, item_id: int) -> bool:
        return any(s["itemId"] == item_id for s in self.inventory)

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

    # ------------------------------------------------------------------ #
    # Objects
    # ------------------------------------------------------------------ #

    def objects_named(self, name: str) -> List[dict]:
        return [o for o in self.objects if o.get("name", "").lower() == name.lower()]

    def nearest_object(self, name: str) -> Optional[dict]:
        px, py = self.player_pos
        return min(
            self.objects_named(name),
            key=lambda o: abs(o["worldX"] - px) + abs(o["worldY"] - py),
            default=None,
        )

    def player_near(self, entity: dict, tiles: int = 1) -> bool:
        px, py = self.player_pos
        return (abs(entity["worldX"] - px) + abs(entity["worldY"] - py)) <= tiles

    def distance_to(self, entity: dict) -> int:
        px, py = self.player_pos
        return abs(entity["worldX"] - px) + abs(entity["worldY"] - py)

    # ------------------------------------------------------------------ #
    # Camera
    # ------------------------------------------------------------------ #

    def camera_yaw_to(self, entity: dict) -> int:
        """Approximate RS yaw (0-2047) needed to face an entity."""
        px, py = self.player_pos
        dx = entity["worldX"] - px
        dy = entity["worldY"] - py
        return int(math.atan2(dx, dy) / (2 * math.pi) * 2048 + 2048) % 2048

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
