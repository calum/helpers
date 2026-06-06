# The next improvements due to be made to the system

Please ensure you have read and fully understand CLAUDE.md, GAMEBRIDGE.md, RIPER-5.md, and ARCHITECTURE.md before starting on any of these pieces of work.

The following work items are in priority order.

## Camera Movement (PARTIALLY WORKING)

The routines still try to click outside the game client, as if they are trying to click objects too far out of view.

We need to create the idea of a 'Field of view' and map that onto our 'Minimap'. Objects that fall outside of the field of view will require a camera adjustment. We should aim to centre the object into the field of view using the human emulated controller class. 

Usually a player will adjust the 'field of view' with either a middle-mouse-hold and drag, or using the arrow keys on their keyboard. I think the arrow keys are enough for the time being so lets support that first.

We should use the arrow keys to rotate the camera until the game state shows our goal object/npc/interactable as being close to the centre of our field of view (within a tolerance and with randomness by the humanised controller).

Still to be implemented: We should zoom out by using the mouse scroll wheel to see more distance and click to interact with the object that is far away. We should avoid using up and down arrows when zooming out is an option.

## Minimap and interface detection (INFRASTRUCTURE DONE — needs wiring into routines)

### What is implemented

The Java plugin now sends two new pieces of data every tick:

- **`interfaces`** — every visible, non-hidden UI widget from every currently loaded interface group (minimap, inventory, prayer orbs, bank, etc.), each with its canvas-space bounding box (`x, y, width, height`). Discovered dynamically via `client.getComponentTable()` so it covers any interface that happens to be open with no hardcoding.
- **`minimapX` / `minimapY`** — canvas pixel coordinates of every NPC and object on the minimap, computed in Java via `Perspective.localToMinimap()`. `null` when the entity is beyond the ~20-tile minimap radius.

The Python layer has been updated to match:

- `game.interfaces` — list of all active interface widgets for the current tick.
- `game.is_occluded(canvas_x, canvas_y)` — returns `True` if a canvas point falls inside any active UI widget. Use this before clicking an entity.
- `game.find_interface_widget(group_id, child_id)` — look up a specific widget from the full interface list.
- `game.interfaces_for_group(group_id)` — all widgets for a given group.
- `ctrl.click_minimap_entity(entity)` — clicks the entity's precomputed minimap position to walk towards it. Returns `False` if the entity is too far from the player to appear on the minimap.

The dashboard has a new **Interfaces** tab showing the live interface list, and the Hull Debug "Show Interfaces" toggle now draws every active UI panel as a coloured overlay on the screenshot, colour-coded by group ID.

### What still needs to happen

**1. Guard all entity clicks with `is_occluded` in the existing routines.**

In `iron_mining.py` and `gold_mining.py`, the `find_ore` state calls `ctrl.click_entity(ore)` without checking whether the ore's canvas centre is hidden behind the minimap or inventory. The fix is straightforward:

```python
# in find_ore, before clicking:
if game.is_occluded(ore["canvasX"], ore["canvasY"]):
    ctrl.bring_entity_on_screen(ore, game)  # rotate camera to move the ore clear
    return None
ctrl.click_entity(ore)
```

**2. Add minimap-based walking when camera rotation is not enough.**

`bring_entity_on_screen` rotates the camera and adjusts pitch, but if the entity is genuinely too far away (e.g. the player is walking to the bank) the entity will never come on screen that way. The current banking states in both routines use hard-coded object clicks that fail silently when out of range. Replace or augment with:

```python
if not ctrl.bring_entity_on_screen(target, game):
    # camera adjusted but entity still not on screen next tick — try minimap
    ctrl.click_minimap_entity(target)
    return None
```

**3. Determine the correct group IDs for the minimap and inventory panels.**

Run the game with the dashboard open, look at the Interfaces tab, and note the `groupId` values for:
- The minimap draw area (needed if you want to avoid clicking the minimap when an entity is behind it)
- The inventory panel root (the large panel, not individual slots)
- The prayer/HP/run orbs

`is_occluded` already handles all of these automatically from the live data — no hardcoding needed — but knowing the group IDs is useful when you want to *interact* with a specific interface (e.g. clicking the minimap at a known world position to walk there).

**4. Test occlusion in practice.**

Stand next to an iron rock that is partially behind the minimap in the top-right corner, run the iron mining routine, and verify the routine either rotates the camera to expose the rock or walks via the minimap rather than clicking the UI chrome.


## Mouse movement

I noticed the mouse movement still seems robotic. I think that after clicking, the mouse should have a high probability to "drift". I noticed that when I play, I will click an iron rock and then move my mouse away slightly, almost to keep my reactions ready to go again. It's rare that I click and then stay stationary.

The second improvement is a "pre-emptive" movement. So for something like mining, we know that after a click, we would pre-emtpively move the mouse to the next thing, but not click it. 
e.g.
```
Click iron rock
move mouse to next closest iron rock
wait for mine
if it messes up, click original rock again
if it works, click closest iron rock (which may not be the one we pre-empted but thats okay)
```

## Game world movement

We need to follow the RIPER-5 model to work out how to manage movement around the world and navigating obsticals in our way. This is necessary for banking items or moving between objectives during a routine.

The free resource [Explv's Map](https://explv.github.io/?centreX=2916&centreY=3315&centreZ=0&zoom=7) is probably going to be the route we take.

This map service is built with https://github.com/itsdax/Runescape-Web-Walker-Engine.

The following resources are useful:

* https://github.com/itsdax/Runescape-Web-Walker-Engine
* https://admin.dax.cloud/index 

As a beginner solution, we could have some predifined routes for each routine based on pre-calculated paths.

## More Routines

We should add more routines for some various activities.

These should cover some unique functions:

* Fighting/Interacting with a moving NPC
* Long AFK tasks which encourage more AFK play style
* Faster paced content like ZMI runecrafting that requires more concentration and accurate clicks but also freely allows for AFK breaks. This means we will need a "cannot take break here unless it's marked as an urgent break" where the breaks are queued until after an important step of the routine but an urgent break can still occur and will likely lead to death in-game.