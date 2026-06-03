# The next improvements due to be made to the system

Please ensure you have read and fully understand CLAUDE.md, GAMEBRIDGE.md, RIPER-5.md, and ARCHITECTURE.md before starting on any of these pieces of work.

The following work items are in priority order.

## Camera Movement

The routines still try to click outside the game client, as if they are trying to click objects too far out of view.

We need to create the idea of a 'Field of view' and map that onto our 'Minimap'. Objects that fall outside of the field of view will require a camera adjustment. We should aim to centre the object into the field of view using the human emulated controller class. 

Usually a player will adjust the 'field of view' with either a middle-mouse-hold and drag, or using the arrow keys on their keyboard. I think the arrow keys are enough for the time being so lets support that first.

We should use the arrow keys to rotate the camera until the game state shows our goal object/npc/interactable as being close to the centre of our field of view (within a tolerance and with randomness by the humanised controller).

## Game world movement

We need to follow the RIPER-5 model to work out how to manage movement around the world and navigating obsticals in our way. This is necessary for banking items or moving between objectives during a routine.

The free resource [Explv's Map](https://explv.github.io/?centreX=2916&centreY=3315&centreZ=0&zoom=7) is probably going to be the route we take.

This map service is built with https://github.com/itsdax/Runescape-Web-Walker-Engine.

The following resources are useful:

* https://github.com/itsdax/Runescape-Web-Walker-Engine
* https://admin.dax.cloud/index 

As a beginner solution, we could have some predifined routes for each routine based on pre-calculated paths.

## More Human Behaviour

We need more human behaviour. It's much more important to seem human than it is to play optimally. I'd rather the routines worked 50% the speed if it means looking more human-like.

This means that each time I start the script, the human model should pick, using a truely random source like the weather prediction for the day, an emotional starting point.

Examples:
* Sad 
* Excited
* Bored
* Distracted

Other scenarios that make sense to incorporate, somehow:
* Human models is recieving messages on discord or whatsapp and is more distracted for a few minutes.
* Human model gets a knock at the door.
* Human model needs to go to the toilet, but before they do they are more rushed and then return more relaxed.
* Starting on a cold day with cold hands that take 10-20 minutes to warm up.
* Reading the wiki or watching a youtube video.

There are so many things we can incorporate into the human model to make it more realistic.

A stretch goal here would be to call off to an LLM when chat messages are coming in from other players that may be directed at the human model. These should not be encouraged to continue a conversation, but to be polite and respond with the context of what the controller is currently doing in the current routine.

## More Routines

We should add more routines for some various activities.

These should cover some unique functions:

* Fighting/Interacting with a moving NPC
* Long AFK tasks which encourage more AFK play style
* Faster paced content like ZMI runecrafting that requires more concentration and accurate clicks but also freely allows for AFK breaks. This means we will need a "cannot take break here unless it's marked as an urgent break" where the breaks are queued until after an important step of the routine but an urgent break can still occur and will likely lead to death in-game.