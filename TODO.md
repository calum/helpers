# The next improvements due to be made to the system

Please ensure you have read and fully understand CLAUDE.md, GAMEBRIDGE.md, RIPER-5.md, and ARCHITECTURE.md before starting on any of these pieces of work.

The following work items are in priority order.

## Camera Movement

The routines still try to click outside the game client, as if they are trying to click objects too far out of view.

We need to create the idea of a 'Field of view' and map that onto our 'Minimap'. Objects that fall outside of the field of view will require a camera adjustment. We should aim to centre the object into the field of view using the human emulated controller class. 

Usually a player will adjust the 'field of view' with either a middle-mouse-hold and drag, or using the arrow keys on their keyboard. I think the arrow keys are enough for the time being so lets support that first.

We should use the arrow keys to rotate the camera until the game state shows our goal object/npc/interactable as being close to the centre of our field of view (within a tolerance and with randomness by the humanised controller).


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