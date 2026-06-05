# Game Bridge — Python Developer Guide

The **Game Bridge** RuneLite plugin embeds a TCP server inside the game client. Once per game tick (≈600 ms) it serialises a snapshot of the local player, camera, nearby NPCs and world objects, plus a delta list of events that occurred since the last tick, and broadcasts a single JSON line to every connected TCP client.

---

## Quick start

```python
import socket, json

sock = socket.create_connection(('127.0.0.1', 7070))
buf = ''
while True:
    data = sock.recv(65536)
    if not data:
        break
    buf += data.decode()
    while '\n' in buf:
        line, buf = buf.split('\n', 1)
        if line.strip():
            msg = json.loads(line)
            print(f"Tick {msg['tick']}: player at ({msg['player']['worldX']}, {msg['player']['worldY']})")
```

Enable the **Game Bridge** plugin in the RuneLite Plugins panel before connecting.

---

## Protocol

| Property | Value |
|---|---|
| Transport | TCP, localhost only (127.0.0.1) |
| Default port | 7070 (configurable in plugin settings) |
| Framing | Newline-delimited JSON — one JSON object per line |
| Rate | One message per game tick (~600 ms, ~1.67 msg/s) |
| Direction | Server → client only; the plugin never reads from the socket |
| Init message | When `exposeInventory` is enabled, every tick message contains top-level `inventory` and `equipment` arrays with the current container state. A newly-connected client therefore receives a full inventory and equipment snapshot on its very first tick — there is no special init handshake. |

---

## Top-level message structure

```json
{
  "tick":      12345,
  "player":    { ... },
  "camera":    { ... },
  "npcs":      [ ... ],
  "objects":   [ ... ],
  "widgets":   [ ... ],
  "inventory": [ ... ],
  "equipment": [ ... ],
  "events":    [ ... ]
}
```

| Field | Always present | Controlled by config key |
|---|---|---|
| `tick` | yes | — |
| `player` | yes (absent before login) | — |
| `camera` | yes | `exposeCamera` (default on) |
| `npcs` | yes | `exposeNpcs` (default on) |
| `objects` | yes | `exposeObjects` (default on) |
| `widgets` | no | `exposeWidgets` (default **off**) |
| `inventory` | no | `exposeInventory` (default on) |
| `equipment` | no | `exposeInventory` (default on) |
| `events` | yes (may be `[]`) | — |

---

## Player

```json
{
  "name":        "Zezima",
  "worldX":      3221,
  "worldY":      3218,
  "plane":       0,
  "animation":   808,
  "hp":          99,
  "prayer":      85
}
```

| Field | Type | Notes |
|---|---|---|
| `name` | string | RSN of the local player |
| `worldX` / `worldY` | int | RuneScape world-tile coordinates |
| `plane` | int | 0 = ground level, 1–3 = above ground (e.g. upstairs) |
| `animation` | int | Current animation ID; `-1` = idle |
| `hp` | int | Current (boosted) Hitpoints level |
| `prayer` | int | Current (boosted) Prayer level |

---

## Camera

```json
{
  "yaw":   1024,
  "pitch": 256,
  "x":     6582,
  "y":     218,
  "z":     6532,
  "baseX": 12800,
  "baseY": 12800
}
```

| Field | Type | Notes |
|---|---|---|
| `yaw` | int | 0–2047 CCW from North; 0 = north, 512 = west, 1024 = south, 1536 = east |
| `pitch` | int | 0–2047; higher values = more overhead (top-down) view. UP increases pitch; DOWN decreases it (more horizontal, sees further). |
| `x` / `y` / `z` | int | Camera position in local (scene-relative) coordinates. 1 tile = 128 units. |
| `baseX` / `baseY` | int | World tile coordinates of the south-west corner of the loaded scene. Use these to convert camera `x`/`y` to world tile coords: `world_tile_x = baseX + camera.x / 128`. |

### Pointing the camera at a world tile

```python
import math

def required_yaw(px, py, tx, ty):
    """Approximate RS camera yaw (0-2047, CCW from North) needed to face tile (tx, ty) from (px, py)."""
    dx = tx - px
    dy = ty - py
    return int(math.atan2(-dx, dy) / (2 * math.pi) * 2048 + 2048) % 2048

def yaw_delta(current_yaw, target_yaw):
    """Signed rotation delta. Positive = clockwise, negative = counter-clockwise."""
    delta = (target_yaw - current_yaw + 2048) % 2048
    return delta - 2048 if delta > 1024 else delta
```

---

## NPCs

```json
{
  "id":          3106,
  "name":        "Cow",
  "worldX":      3225,
  "worldY":      3215,
  "plane":       0,
  "animation":   -1,
  "combatLevel": 2,
  "onScreen":    true,
  "canvasX":     412,
  "canvasY":     380,
  "hull":        [[400,370],[420,370],[420,390],[400,390]]
}
```

| Field | Notes |
|---|---|
| `onScreen` | `true` when the NPC has a visible convex hull in the current frame |
| `canvasX` / `canvasY` | Centre of the hull bounding box in screen pixels; `null` when off-screen |
| `hull` | Array of `[x, y]` screen-pixel pairs forming the clickable polygon; `null` when off-screen or excluded by the hull filter |

---

## Objects

Same shape as NPCs minus `combatLevel` and `animation`. Object names are impostor-resolved: a door that changes appearance based on a varbit shows its current name (e.g. `"Door"` not `"null"`).

Each object entry now includes a `category` field:

```json
{
  "id":       1276,
  "name":     "Oak tree",
  "category": "game",
  "worldX":   3225,
  "worldY":   3215,
  "plane":    0,
  "onScreen": true,
  "canvasX":  350,
  "canvasY":  290,
  "hull":     [[340,280],[360,280],[360,300],[340,300]]
}
```

| `category` value | RuneScape type | Examples |
|---|---|---|
| `"game"` | `GameObject` | Trees, rocks, furnaces, anvils |
| `"wall"` | `WallObject` | Doors, gates, fences |
| `"ground"` | `GroundObject` | Floor tiles, rugs |
| `"decorative"` | `DecorativeObject` | Cosmetic scenery |

### Object filtering

By default the `objects` array is **empty** to avoid the performance penalty of serialising every tile object on every tick. Use the plugin config to control what is included:

| Config key | Default | Effect |
|---|---|---|
| `objectFilter` | `""` | Comma-separated IDs/names (same format as hull filter). Only matching objects are included. |
| `sendAllNamedObjects` | `false` | Include any object whose resolved name is not `"null"` or `"unknown"`, in addition to filter matches. |
| `debugAllObjects` | `false` | Include every object unconditionally. ⚠ Can cause lag on large scenes — development only. |

The three rules are evaluated in priority order: `debugAllObjects` → filter match → `sendAllNamedObjects`.

```python
# Example: only care about iron rocks and the mine cart deposit box
# Set objectFilter = "Iron rocks,Mine cart" in the plugin config panel.
iron = state.nearest_object("Iron rocks")
cart = state.nearest_object("Mine cart")
```

---

## Widgets

When `exposeWidgets` is enabled the tick message includes a `widgets` array with visible UI slot data. This is useful for knowing the screen coordinates of specific inventory slots, bank slots, or equipment slots.

```json
{
  "groupId":  149,
  "childId":  0,
  "itemId":   995,
  "quantity": 1000,
  "bounds":   { "x": 560, "y": 210, "width": 32, "height": 32 },
  "text":     ""
}
```

| Field | Notes |
|---|---|
| `groupId` | Widget group ID. Known groups: `149` = Inventory, `12` = Bank, `387` = Equipment, `192` = Deposit box |
| `childId` | Slot index within the group's dynamic children |
| `itemId` | Item ID; `-1` if the slot is empty |
| `quantity` | Stack size |
| `bounds` | Screen-pixel rectangle of the slot (top-left origin, excludes window chrome) |
| `text` | Widget text, omitted when empty |

Only groups `149`, `12`, `387`, and `192` are serialised. Only non-hidden children are included.

```python
# Click the first inventory slot that holds a specific item
def click_inventory_item(ctrl, game, item_id):
    for w in game.widgets:
        if w["groupId"] == 149 and w["itemId"] == item_id:
            b = w["bounds"]
            cx = b["x"] + b["width"] // 2
            cy = b["y"] + b["height"] // 2
            ctrl.click_at(cx, cy)
            return True
    return False
```

---

## Inventory and Equipment snapshots

When `exposeInventory` is enabled, every tick message contains `inventory` and `equipment` as top-level arrays — polled snapshots of container 93 (inventory) and container 94 (worn equipment):

```json
[
  { "slot": 0, "itemId": 440, "qty": 1 },
  { "slot": 1, "itemId": -1,  "qty": 0 },
  ...
]
```

| Field | Notes |
|---|---|
| `slot` | Zero-based slot index |
| `itemId` | Item ID; `-1` = slot explicitly cleared; `0` = slot never occupied (also treated as empty) |
| `qty` | Stack size; `0` for empty slots |

These are **full snapshots on every tick** — not diffs. The `container` events in `events[]` are delta notifications of changes and use the same slot format. Both mechanisms are active when `exposeInventory` is on.

```python
# Read current inventory from the top-level snapshot
inv = msg["inventory"]          # list of {"slot", "itemId", "qty"}
equip = msg["equipment"]        # worn items in the same format
```

---

## Events

`events` is a delta log containing only things that changed during this tick. Each entry has a `type` field.

### `xp` — experience gained

```json
{ "type": "xp", "skill": "WOODCUTTING", "xp": 1204050, "level": 70, "boostedLevel": 70 }
```

`skill` is the Java enum name (all caps). Full list:
`ATTACK`, `DEFENCE`, `STRENGTH`, `HITPOINTS`, `RANGED`, `PRAYER`, `MAGIC`, `COOKING`,
`WOODCUTTING`, `FLETCHING`, `FISHING`, `FIREMAKING`, `CRAFTING`, `SMITHING`, `MINING`,
`HERBLORE`, `AGILITY`, `THIEVING`, `SLAYER`, `FARMING`, `RUNECRAFT`, `HUNTER`, `CONSTRUCTION`.

### `animation` — animation change

```json
{ "type": "animation", "actor": "player", "animId": 879 }
```

`actor` is `"player"` for the local player, otherwise the actor's name string (for NPCs and other players).

### `container` — item container change

```json
{
  "type":        "container",
  "containerId": 93,
  "items": [
    { "slot": 0, "itemId": 995,  "qty": 1000 },
    { "slot": 1, "itemId": -1,   "qty": 0    }
  ]
}
```

The **full** container is sent on every change (not a diff). `itemId = -1` means the slot is empty. Fired when the `exposeInventory` config is enabled.

Common container IDs:

| ID | Container |
|---|---|
| 93 | Inventory |
| 94 | Equipment (worn items) |
| 95 | Bank |

### `varbit` — varbit or varplayer change

```json
{ "type": "varbit", "varpId": 2, "varbitId": 9178, "value": 2 }
```

For varplayer changes `varbitId` is `-1`. For varbit changes `varpId` is the parent varp.
Only the **final** value for each `(varpId, varbitId)` pair is emitted if the value changes multiple times in one tick.

This is the low-level signal that drives other plugins' state machines (Giant's Foundry, Blast Furnace, etc.). Expose varbit IDs relevant to an activity and you can replicate that plugin's logic in Python without depending on the plugin directly.

### `chat` — chat message

```json
{ "type": "chat", "msgType": "GAMEMESSAGE", "name": "", "message": "You chop some logs." }
```

Common `msgType` values: `GAMEMESSAGE`, `PUBLICCHAT`, `PRIVATECHAT`, `FRIENDSCHAT`, `CLAN_CHAT`, `CONSOLE`, `TRADE`, `SPAM`.

### `interacting` — player target changed

```json
{ "type": "interacting", "target": "Goblin" }
```

Fires when the local player starts or stops interacting with an actor. `target` is `null` when the player stops interacting.

---

## Hull filter

By default every visible entity has its convex hull polygon included. On a busy scene this can be a large payload.

Set the **Hull filter** plugin config field to a comma-separated list of IDs or names:

```
1276,Oak tree,Goblin,3106
```

Matching rules:
- Tokens that parse as integers are matched against the entity's numeric ID
- All other tokens are matched **case-insensitively** against the entity's resolved name
- Both NPC and object entries are filtered by the same list
- An **empty** filter (the default) returns hulls for every visible entity

When an entity is excluded by the filter, `hull` is `null` but all other fields (`onScreen`, `canvasX/Y`, `worldX/Y`) are still present.

---

## Canvas coordinates and clicking

`canvasX/Y` is the screen-pixel centre of the entity's bounding box — useful for direct mouse automation if you know the game window's screen origin:

```python
import pyautogui  # pip install pyautogui

def click_entity(game_window_x, game_window_y, entity):
    if not entity['onScreen']:
        return False
    pyautogui.click(game_window_x + entity['canvasX'],
                    game_window_y + entity['canvasY'])
    return True
```

`hull` gives the full clickable polygon for precise hit-testing:

```python
from shapely.geometry import Point, Polygon  # pip install shapely

def hull_contains(entity, screen_x, screen_y):
    if not entity.get('hull'):
        return False
    return Polygon(entity['hull']).contains(Point(screen_x, screen_y))
```

---

## Building a game state model

```python
import socket, json, math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class GameState:
    tick: int = 0
    player: dict = field(default_factory=dict)
    camera: dict = field(default_factory=dict)
    npcs: List[dict] = field(default_factory=list)
    objects: List[dict] = field(default_factory=list)
    inventory: List[dict] = field(default_factory=list)
    equipment: List[dict] = field(default_factory=list)
    xp: Dict[str, int] = field(default_factory=dict)

    def update(self, msg: dict):
        self.tick = msg['tick']
        if 'player' in msg:
            self.player = msg['player']
        if 'camera' in msg:
            self.camera = msg['camera']
        if 'npcs' in msg:
            self.npcs = msg['npcs']
        if 'objects' in msg:
            self.objects = msg['objects']
        if 'inventory' in msg:
            self.inventory = msg['inventory']
        if 'equipment' in msg:
            self.equipment = msg['equipment']
        for event in msg.get('events', []):
            if event['type'] == 'xp':
                self.xp[event['skill']] = event['xp']
            elif event['type'] == 'container':
                if event['containerId'] == 93:
                    self.inventory = event['items']
                elif event['containerId'] == 94:   # Equipment (worn items)
                    self.equipment = event['items']

    # --- convenience queries ---

    def npcs_on_screen(self) -> List[dict]:
        return [n for n in self.npcs if n['onScreen']]

    def objects_named(self, name: str) -> List[dict]:
        return [o for o in self.objects if o['name'].lower() == name.lower()]

    def nearest_object(self, name: str) -> Optional[dict]:
        px, py = self.player.get('worldX', 0), self.player.get('worldY', 0)
        candidates = self.objects_named(name)
        return min(candidates, key=lambda o: abs(o['worldX'] - px) + abs(o['worldY'] - py), default=None)

    def required_camera_yaw(self, target: dict) -> int:
        px, py = self.player.get('worldX', 0), self.player.get('worldY', 0)
        dx, dy = target['worldX'] - px, target['worldY'] - py
        return int(math.atan2(dx, dy) / (2 * math.pi) * 2048 + 2048) % 2048

    def inventory_count(self, item_id: int) -> int:
        return sum(s['qty'] for s in self.inventory if s['itemId'] == item_id)


# --- main loop ---

state = GameState()
sock = socket.create_connection(('127.0.0.1', 7070))
buf = ''
while True:
    data = sock.recv(65536)
    if not data:
        break
    buf += data.decode()
    while '\n' in buf:
        line, buf = buf.split('\n', 1)
        if not line.strip():
            continue
        state.update(json.loads(line))

        oak = state.nearest_object('Oak tree')
        if oak and oak['onScreen']:
            print(f"Tick {state.tick}: oak on screen at canvas ({oak['canvasX']}, {oak['canvasY']})")
```

---

## Reconnection

The plugin does not attempt to re-connect dropped clients. Implement reconnection on the Python side:

```python
import time

def stream_with_reconnect(host='127.0.0.1', port=7070, retry_delay=5.0):
    """Yields parsed JSON messages, reconnecting automatically on disconnect."""
    while True:
        try:
            sock = socket.create_connection((host, port))
            buf = ''
            while True:
                data = sock.recv(65536)
                if not data:
                    raise ConnectionError('server closed connection')
                buf += data.decode()
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    if line.strip():
                        yield json.loads(line)
        except (OSError, ConnectionError) as exc:
            print(f'Bridge disconnected ({exc}), retrying in {retry_delay}s')
            time.sleep(retry_delay)
```

---

## Plugin config reference

| Config key | Type | Default | Effect |
|---|---|---|---|
| `port` | int | 7070 | Listening port; restart plugin to apply |
| `exposeNpcs` | bool | true | Include `npcs` array in tick messages |
| `exposeObjects` | bool | true | Include `objects` array in tick messages (see Object filtering) |
| `exposeInventory` | bool | true | Emit `container` events |
| `exposeVarbits` | bool | true | Emit `varbit` events |
| `exposeCamera` | bool | true | Include `camera` object in tick messages |
| `hullFilter` | string | `""` | Comma-separated IDs/names for hull inclusion; empty = all hulls |
| `objectFilter` | string | `""` | Comma-separated IDs/names to include in `objects`; empty = none |
| `sendAllNamedObjects` | bool | false | Also include objects with a real (non-null) name |
| `debugAllObjects` | bool | false | Include all objects unconditionally — dev/debug only |
| `exposeWidgets` | bool | false | Include `widgets` array (inventory/bank/equipment slot bounds) |

---

## Source files

| File | Purpose |
|---|---|
| `runelite-client/…/plugins/gamebridge/GameBridgePlugin.java` | Plugin entry point, event subscriptions, JSON serialisation |
| `runelite-client/…/plugins/gamebridge/GameBridgeConfig.java` | Config interface |
| `runelite-client/…/plugins/gamebridge/BridgeServer.java` | Embedded TCP server |
| `runelite-client/…/plugins/gamebridge/HullFilter.java` | ID/name filter for convex hull data |
