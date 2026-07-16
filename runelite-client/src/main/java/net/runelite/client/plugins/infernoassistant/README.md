# Inferno Assistant

Live protection-prayer helper for the Inferno. While fighting a wave, it
watches your position and every visible NPC in real time and tells you:

1. Which protection prayer to have active **right now**, shown as the
   actual prayer icon, kept up to date as you or the NPCs move. If nothing
   is due this exact tick but an NPC is projected to close into LOS soon
   (e.g. at wave start, before anything has LOS yet), the nearest upcoming
   recommendation is shown instead of a blank "No threats".
2. A short predictive queue of upcoming prayer switches (default 15 ticks
   ahead, configurable) with tick countdowns, so you can time switches in
   advance rather than reacting after a hit lands. This queue is populated
   both from confirmed attack-cooldown timers and, for NPCs that don't have
   LOS yet, a movement simulation that projects when they'll walk into LOS.
3. When two NPCs are about to attack on conflicting, overlapping ticks
   (e.g. a mager and a bat on the same tick), which one to protect against
   — prioritizing whichever attack hits harder — while still showing you
   the other attack as unmitigated so it's never silently hidden.

It only ever *displays* a recommendation; it does not press prayers for
you.

See [DESIGN.md](DESIGN.md) for the full technical design.

## Config

- `showOverlay` — toggle the overlay on/off.
- `queueLength` — how many ticks ahead the predictive queue looks, and how
  far ahead NPC movement is simulated to predict LOS before it's actually
  gained (default 15).
- `showUnmitigatedWarnings` — toggle the "other threat unmitigated"
  warning line.
- Per-style colors for magic/range/melee, matching the color-picker
  pattern used by Inferno Scouter's config.

## Known limitations (v1)

- Standard wave roster only (mager, ranger, meleer, blob, bat, nibbler) —
  no JalTok-Jad or Zuk boss-fight support.
- Hold-recommendation only — no tick-perfect prayer-flick timing.
- Overlay only — no audio/visual alert cues.
- Movement-based LOS prediction uses a simplified greedy chase model (no
  mob-mob collision, no random jitter) - see `MovementSimulator`'s javadoc.
  It re-simulates from live NPC positions every tick, so it self-corrects
  quickly if reality diverges from the projection.

## Background

This design builds on mechanics reverse-engineered in
[`research/INFERNO_MECHANICS.md`](../../../../../../../../../research/INFERNO_MECHANICS.md)
and reuses NPC/pillar tracking already working in
`research/inferno-scouter`'s `InfernoScouterPlugin`.
