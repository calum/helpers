# Inferno Assistant

Live protection-prayer helper for the Inferno. While fighting a wave, it
watches your position and every visible NPC in real time and tells you:

1. Which protection prayer to have active **right now**, kept up to date
   as you or the NPCs move.
2. A short predictive queue of upcoming prayer switches (up to 6 ticks
   ahead) with tick countdowns, so you can time switches in advance rather
   than reacting after a hit lands.
3. When two NPCs are about to attack on conflicting, overlapping ticks
   (e.g. a mager and a bat on the same tick), which one to protect against
   — prioritizing whichever attack hits harder — while still showing you
   the other attack as unmitigated so it's never silently hidden.

It only ever *displays* a recommendation; it does not press prayers for
you.

Status: **design only** — see [DESIGN.md](DESIGN.md) for the full
technical design. No plugin code exists yet.

## Config (planned)

- `showOverlay` — toggle the overlay on/off.
- `queueLength` — how many ticks ahead the predictive queue looks
  (default 6).
- `showUnmitigatedWarnings` — toggle the "other threat unmitigated"
  warning line.
- Per-style colors for magic/range/melee, matching the color-picker
  pattern used by Inferno Scouter's config.

## Known limitations (v1)

- Standard wave roster only (mager, ranger, meleer, blob, bat, nibbler) —
  no JalTok-Jad or Zuk boss-fight support.
- Hold-recommendation only — no tick-perfect prayer-flick timing.
- Overlay only — no audio/visual alert cues.

## Background

This design builds on mechanics reverse-engineered in
[`research/INFERNO_MECHANICS.md`](../../../../../../../../../research/INFERNO_MECHANICS.md)
and reuses NPC/pillar tracking already working in
`research/inferno-scouter`'s `InfernoScouterPlugin`.
