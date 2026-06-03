# Feedback from initial testing

## All objects causes slow down
Sending all objects is causing the game client to lag and jitter. We will have to restrict this to only send requested object IDs/names back, and also have a toggle to only send back objects which have a name as most of the objects had null for name.

##