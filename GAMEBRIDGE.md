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
  "type":        "tick",
  "tick":        12345,
  "player":      { ... },
  "camera":      { ... },
  "npcs":        [ ... ],
  "players":     [ ... ],
  "objects":     [ ... ],
  "groundItems": [ ... ],
  "widgets":     [ ... ],
  "interfaces":  [ ... ],
  "menu":        { ... },
  "inventory":   [ ... ],
  "equipment":   [ ... ],
  "events":      [ ... ]
}
```

| Field | Always present | Controlled by config key |
|---|---|---|
| `type` | yes | — always `"tick"` for this message |
| `tick` | yes | — |
| `player` | yes (absent before login) | — |
| `camera` | yes | `exposeCamera` (default on) |
| `npcs` | yes | `exposeNpcs` (default on) |
| `players` | yes | `exposePlayers` (default on) |
| `objects` | yes | `exposeObjects` (default on) |
| `groundItems` | yes | `exposeGroundItems` (default on) |
| `widgets` | no | `exposeWidgets` (default **off**) |
| `interfaces` | no | `exposeInterfaces` (default **on**) |
| `menu` | no | `exposeMenu` (default **on**) |
| `inventory` | no | `exposeInventory` (default on) |
| `equipment` | no | `exposeInventory` (default on) |
| `events` | yes (may be `[]`) | — |

A connected client may also receive `"type": "hullUpdate"` messages — see
[Live clickbox subscriptions](#live-clickbox-subscriptions) below. Discriminate
on the top-level `type` field to tell the two apart.

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
  "index":       14271,
  "name":        "Cow",
  "worldX":      3225,
  "worldY":      3215,
  "plane":       0,
  "animation":   -1,
  "combatLevel": 2,
  "onScreen":    true,
  "canvasX":     412,
  "canvasY":     380,
  "hull":        [[400,370],[420,370],[420,390],[400,390]],
  "minimapX":    642,
  "minimapY":    83
}
```

| Field | Notes |
|---|---|
| `id` | NPC composition/definition ID — **shared** by every instance of the same NPC type (e.g. all "Goblin"s have the same `id`) |
| `index` | Per-instance world index — **unique** to this specific NPC; use it to track one individual across ticks (e.g. "did the Goblin I attacked die?"). May be reused by a different NPC after this one despawns, so only rely on it across short windows. |
| `onScreen` | `true` when the NPC has a visible convex hull in the current frame |
| `canvasX` / `canvasY` | Vertex-average centroid of the convex hull in screen pixels — guaranteed to fall *inside* the polygon (unlike the bounding-box centre, which can land outside a skewed hull); `null` when off-screen |
| `hull` | Array of `[x, y]` screen-pixel pairs forming the clickable polygon; `null` when off-screen or excluded by the hull filter |
| `minimapX` / `minimapY` | Canvas pixel coordinates of this entity on the minimap; `null` when the entity is beyond minimap range |

---

## Players

Other nearby players (the local player is described separately in the top-level
`player` object, never included here). Same shape as NPCs, minus the
composition/instance `id`/`index` split — a player's `id` is already a unique
per-instance world index.

```json
{
  "id":          17,
  "name":        "Hans",
  "worldX":      3224,
  "worldY":      3216,
  "plane":       0,
  "animation":   -1,
  "combatLevel": 5,
  "onScreen":    true,
  "canvasX":     430,
  "canvasY":     360,
  "hull":        [[420,350],[440,350],[440,370],[420,370]],
  "minimapX":    645,
  "minimapY":    80
}
```

| Field | Notes |
|---|---|
| `id` | Unique per-instance world index for this player |
| `onScreen` / `canvasX` / `canvasY` / `hull` / `minimapX` / `minimapY` | Same semantics as NPCs |

Use `GameState.players` / `GameState.entity_near_other_player(entity, tiles)` to
e.g. avoid picking combat targets that another player is already standing next to.

Controlled by `exposePlayers` (default on).

---

## Objects

Same shape as NPCs minus `combatLevel` and `animation`. Object names are impostor-resolved: a door that changes appearance based on a varbit shows its current name (e.g. `"Door"` not `"null"`).

Each object entry now includes a `category` field:

```json
{
  "id":        1276,
  "name":      "Oak tree",
  "category":  "game",
  "worldX":    3225,
  "worldY":    3215,
  "plane":     0,
  "onScreen":  true,
  "canvasX":   350,
  "canvasY":   290,
  "hull":      [[340,280],[360,280],[360,300],[340,300]],
  "minimapX":  638,
  "minimapY":  84
}
```

`minimapX` / `minimapY` are the canvas pixel coordinates of the object on the minimap. Both are `null` when the object is beyond the minimap's view distance (~20 tiles from the player).

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

## Ground items

Item drops lying on the ground — e.g. monster loot, dropped items, resource
spawns. Same shape as objects, plus a `quantity` field; no `category`.

```json
{
  "id":        526,
  "name":      "Bones",
  "quantity":  1,
  "worldX":    3225,
  "worldY":    3215,
  "plane":     0,
  "onScreen":  true,
  "canvasX":   412,
  "canvasY":   395,
  "hull":      [[402,388],[422,388],[422,402],[402,402]],
  "minimapX":  642,
  "minimapY":  83
}
```

| Field | Notes |
|---|---|
| `name` | Resolved via `client.getItemDefinition(id)`; `"unknown"` if not resolvable |
| `quantity` | Stack size of this drop |
| `onScreen` / `canvasX` / `canvasY` / `hull` / `minimapX` / `minimapY` | Same semantics as objects — `hull` here is the tile's canvas polygon (`Perspective.getCanvasTilePoly`), gated by the same `hullFilter` |

```python
# Loot whatever lands on a tile after killing something there
for item in state.ground_items_at(corpse_x, corpse_y):
    if item["onScreen"]:
        ctrl.click_entity(item)
```

Controlled by `exposeGroundItems` (default on).

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

## Interfaces

When `exposeInterfaces` is enabled (default **on**) the tick message includes an `interfaces` array containing every visible, non-hidden widget from every currently-active interface group. This is a superset of `widgets` and replaces it for most use cases.

```json
{
  "groupId":  161,
  "childId":  0,
  "itemId":   -1,
  "quantity": 0,
  "bounds":   { "x": 1631, "y": 767, "width": 190, "height": 261 },
  "text":     ""
}
```

| Field | Notes |
|---|---|
| `groupId` | Interface (widget group) ID — determined dynamically from all currently-loaded groups |
| `childId` | Child slot index within the group; for dynamic children (item slots) this is the slot's own index |
| `itemId` | Item ID held in this slot; `-1` if none |
| `quantity` | Stack size; `0` if empty |
| `bounds` | Screen-pixel rectangle: top-left origin, width/height in pixels. Only widgets with `width > 0` and `height > 0` are included. |
| `text` | Widget text label; empty string if none |

Only non-hidden widgets with a positive-area bounding box are included. The list is rebuilt every tick from `Client.getComponentTable()` so it automatically reflects whatever interfaces are open (inventory, bank, minimap, prayer book, quest journal, etc.) without any plugin configuration.

### UI occlusion detection

Use the `interfaces` list to test whether a game entity's click target is hidden behind a UI panel before issuing a click:

```python
def is_occluded(canvas_x, canvas_y, interfaces):
    """Return True if (canvas_x, canvas_y) falls inside any active UI widget."""
    for w in interfaces:
        b = w["bounds"]
        if b["x"] <= canvas_x < b["x"] + b["width"] and \
           b["y"] <= canvas_y < b["y"] + b["height"]:
            return True
    return False

# Before clicking an entity:
if entity["onScreen"] and not is_occluded(entity["canvasX"], entity["canvasY"], msg["interfaces"]):
    ctrl.click_at(entity["canvasX"], entity["canvasY"])
```

### Minimap clicking via interfaces

The minimap draw area appears in `interfaces` just like any other panel. To walk to a distant object via the minimap, use its `minimapX`/`minimapY` coordinates:

```python
def click_minimap(ctrl, game_window_x, game_window_y, entity):
    """Click the minimap at the entity's minimap position to walk towards it."""
    if entity.get("minimapX") is None:
        return False  # entity is beyond minimap range
    ctrl.click_at(game_window_x + entity["minimapX"],
                  game_window_y + entity["minimapY"])
    return True
```

---

## Context menu (right-click menu)

When `exposeMenu` is enabled (default **on**) the tick message includes a `menu` object describing the native right-click context menu — the "minimenu" the game draws when you right-click an entity. This is **not** a widget/interface; it's drawn directly by the client and exposed via dedicated `Client` API (`isMenuOpen`, `getMenuEntries`, `getMenuX/Y/Width/Height`).

This lets you verify a menu's contents *before* clicking — e.g. right-click a Goblin, confirm an `"Attack Goblin (level-2)"` entry exists, then click that exact row. This is far more reliable than blind left-clicking, especially for moving targets or entities partially obscured by scenery (trees, rocks, other players).

```json
{
  "open": true,
  "x": 480, "y": 360, "width": 140, "height": 64,
  "entries": [
    {
      "option": "Attack",
      "target": "Goblin (level-2)",
      "identifier": 21,
      "type": 9,
      "bounds": { "x": 480, "y": 379, "width": 140, "height": 15 }
    },
    {
      "option": "Examine",
      "target": "Goblin (level-2)",
      "identifier": 21,
      "type": 25,
      "bounds": { "x": 480, "y": 394, "width": 140, "height": 15 }
    },
    {
      "option": "Cancel",
      "target": "",
      "identifier": 0,
      "type": 36,
      "bounds": { "x": 480, "y": 409, "width": 140, "height": 15 }
    }
  ]
}
```

| Field | Notes |
|---|---|
| `open` | Whether a right-click menu is currently open. When `false`, `entries` is an empty array and `x`/`y`/`width`/`height` are omitted. |
| `x`, `y`, `width`, `height` | Screen-pixel bounding box of the whole menu (canvas coordinates, top-left origin), only present while open. |
| `entries[].option` | The action verb shown (e.g. `"Attack"`, `"Walk here"`, `"Examine"`, `"Cancel"`). |
| `entries[].target` | The target name shown alongside the option, colour-tagged as in-game (e.g. `"Goblin (level-2)"`); empty string if the option has no target. |
| `entries[].identifier` | Identifier value for the target (mirrors `MenuEntry.getIdentifier()`). |
| `entries[].type` | Numeric menu action ID (mirrors `MenuEntry.getType().getId()` — see `MenuAction` in `runelite-api`). |
| `entries[].bounds` | Screen-pixel rectangle of that row — click its centre to select the entry. |

`entries` is already in **display (top-to-bottom) order** — the first element is the top-most row. (The underlying `Client.getMenuEntries()` array is reversed; the plugin un-reverses it and pre-computes each row's pixel bounds — `19px` "Choose Option" header + `15px` per row — so Python never has to know the layout constants.)

The engine drives routines one tick at a time and can't block waiting for the menu to open without freezing on stale data — so spread the gesture across ticks, the same "act, then verify next tick" shape `bring_entity_on_screen`/`click_minimap_entity` already use:

```python
# State machine spanning ticks: right-click, then verify + click the matching entry
def attack(self, game, ctrl):
    if not self._right_clicked:
        target = game.nearest_npc_on_screen("Goblin")
        if target is None:
            return None
        ctrl.right_click_entity(target)
        self._right_clicked = True
        return None

    if ctrl.click_menu_entry(game, "Attack", "Goblin"):
        self._right_clicked = False
        return "fighting"

    if not game.menu_open():
        self._right_clicked = False  # closed without a match — retry next time
    return None
```

`GameState.menu` always holds the latest `menu` object (`{"open": False, "entries": []}` when no menu is open). `GameState.menu_entry_matching(option_substr, target_substr=None)` returns the first entry whose `option`/`target` contain the given substrings (case-insensitive substring match), or `None`. `Controller.click_menu_entry(game_state, option_substr, target_substr=None)` looks up the same match and clicks the centre of its `bounds`, returning `True`/`False` to indicate whether a match was found and clicked — non-blocking, just like `click_entity`/`click_minimap_entity`.

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

`canvasX/Y` is the vertex-average centroid of the entity's convex hull, in screen pixels — useful for direct mouse automation if you know the game window's screen origin. It is computed from the hull polygon itself (not its bounding box), so for convex shapes it's mathematically guaranteed to land inside the polygon — unlike a bounding-box centre, which for a hull skewed by viewing angle can fall outside the visible shape entirely (causing both wrong click targets and false "occluded" reads when checked against UI panel bounds):

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

## Live clickbox subscriptions

The once-per-`GameTick` snapshot above (`canvasX`/`canvasY`/`hull`) is accurate
*at computation time* but goes stale by the time a routine reacts to it —
especially for moving NPCs/objects or while the camera is panning, making
clicks on moving targets inaccurate.

Live clickbox subscriptions let you register interest in a specific entity
(e.g. "the nearest Fishing spot") and receive **fresh clickbox updates** at
client-tick rate (~20 ms), much faster than the ~600 ms tick broadcast. A
routine can re-check the clickbox repeatedly while moving the mouse toward a
target.

This is a **complementary layer**, not a replacement for the per-tick
snapshot — use the tick message for general game state, and subscriptions
only for the specific entity/entities you're about to interact with.

### Subscribing

Send a `subscribe` message on the same TCP socket:

```json
{"type": "subscribe", "subId": "fish_spot", "kind": "object", "name": "Fishing spot", "id": null, "ttlTicks": 10}
```

| Field | Type | Notes |
|---|---|---|
| `type` | string | always `"subscribe"` |
| `subId` | string | client-chosen identifier; echoed back in `hullUpdate` |
| `kind` | string | one of `npc`, `object`, `player`, `groundItem` |
| `name` | string or `null` | case-insensitive name match |
| `id` | int or `null` | exact ID match |
| `ttlTicks` | int | subscription auto-expires after this many **game ticks** without renewal (default 10, ~6 s) |

At least one of `name`/`id` must be given. If both are given, both must match
(AND). If multiple entities match, the **nearest to the local player**
(Manhattan distance on `worldX`/`worldY`) is selected.

Re-sending `subscribe` with the same `subId` renews/overwrites the
subscription (including its `kind`/`name`/`id`/`ttlTicks`). There is no
notification when a subscription expires — it simply stops appearing in
`hullUpdate` messages.

**Cap**: at most 20 concurrent subscriptions per connection. Subscribes past
the cap are ignored (existing `subId`s can still be renewed).

### Unsubscribing

```json
{"type": "unsubscribe", "subId": "fish_spot"}
```

### `hullUpdate` messages

Once per `ClientTick` (~20 ms), while the connection has ≥1 active
subscription, the plugin pushes:

```json
{
  "type": "hullUpdate",
  "clientTick": 88123,
  "entities": [
    {
      "subId": "fish_spot",
      "found": true,
      "id": 1497,
      "name": "Fishing spot",
      "worldX": 3085,
      "worldY": 3231,
      "plane": 0,
      "onScreen": true,
      "canvasX": 512,
      "canvasY": 340,
      "hull": [[500, 330], [524, 330], [524, 350], [500, 350]]
    },
    {"subId": "missing_npc", "found": false}
  ]
}
```

If no matching entity is currently found, the entity is `{"subId": ..., "found": false}`
with no other fields. When `found` is `true`, the entity reuses the same
serialisation as the `npcs`/`players`/`objects`/`groundItems` arrays in the
tick message — it may contain extra fields (e.g. `combatLevel`, `category`,
`minimapX`/`minimapY`) beyond the ones shown above. Ignore unknown fields.

### Python usage

```python
ctrl.subscribe_to("fish_spot", "object", name="Fishing spot")

# Each loop iteration, poll the latest pushed clickbox:
update = ctrl.hull_update("fish_spot")
if update and update["found"] and update["onScreen"]:
    ctrl.click_at(update["canvasX"], update["canvasY"])

ctrl.unsubscribe("fish_spot")
```

`hull_update()` returns `None` until the first `hullUpdate` for that `subId`
has arrived, and after `unsubscribe`/TTL expiry it simply stops updating
(the last-seen value remains until overwritten).

> **Future work**: this ground-truth data is intended to eventually be
> blended with the client-side `MovingTarget.predict()` extrapolation
> (see `scripts/gamebridge/state/moving_target.py`) for smoother tracking
> between pushes — out of scope for now.

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
    players: List[dict] = field(default_factory=list)
    objects: List[dict] = field(default_factory=list)
    ground_items: List[dict] = field(default_factory=list)
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
        if 'players' in msg:
            self.players = msg['players']
        if 'objects' in msg:
            self.objects = msg['objects']
        if 'groundItems' in msg:
            self.ground_items = msg['groundItems']
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

    def ground_items_at(self, world_x: int, world_y: int) -> List[dict]:
        return [i for i in self.ground_items if i['worldX'] == world_x and i['worldY'] == world_y]

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
| `exposePlayers` | bool | true | Include `players` array (other nearby players) in tick messages |
| `exposeObjects` | bool | true | Include `objects` array in tick messages (see Object filtering) |
| `exposeGroundItems` | bool | true | Include `groundItems` array (item drops on the ground) in tick messages |
| `exposeInventory` | bool | true | Emit `container` events |
| `exposeVarbits` | bool | true | Emit `varbit` events |
| `exposeCamera` | bool | true | Include `camera` object in tick messages |
| `hullFilter` | string | `""` | Comma-separated IDs/names for hull inclusion; empty = all hulls |
| `objectFilter` | string | `""` | Comma-separated IDs/names to include in `objects`; empty = none |
| `sendAllNamedObjects` | bool | false | Also include objects with a real (non-null) name |
| `debugAllObjects` | bool | false | Include all objects unconditionally — dev/debug only |
| `exposeWidgets` | bool | false | Include `widgets` array (inventory/bank/equipment slot bounds) |
| `exposeInterfaces` | bool | true | Include `interfaces` array — all active, non-hidden widgets from every loaded interface group |
| `exposeMenu` | bool | true | Include `menu` object — open right-click context menu, entries with option/target text and clickable bounds |

---

## Source files

| File | Purpose |
|---|---|
| `runelite-client/…/plugins/gamebridge/GameBridgePlugin.java` | Plugin entry point, event subscriptions, JSON serialisation |
| `runelite-client/…/plugins/gamebridge/GameBridgeConfig.java` | Config interface |
| `runelite-client/…/plugins/gamebridge/BridgeServer.java` | Embedded TCP server |
| `runelite-client/…/plugins/gamebridge/HullFilter.java` | ID/name filter for convex hull data |
