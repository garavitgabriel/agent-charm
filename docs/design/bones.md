---
title: Dex Charm — bones v1 (after round 1)
type: design-notes
created: 2026-09-25
updated: 2026-09-25
related: [../BRIEF.md, ../internal/design-sprint/canvas-prompts-r1.md]
tags: [design-sprint, bones]
---

# Bones — Dex Charm

**Status: v1 after round 1 (2026-09-25).** The draft was written before round 1, then revised with 4/4 critic failures and the owner's reactions. B10–B13 are new from round 1. This list goes into LOCKED for round 2.

## Hard structural rules

B1. **Character integrity (smooth Dex, locked 2026-09-25).** Dex is the smooth illustrated character
    from `character/smooth/` (flat tonal steps, one outline weight, no gradients), reused, not redrawn in
    a new style. Same proportions and palette on every screen. He never reads as a sticker pasted on the UI.
B2. **Type floor and scale.** At most 3 fixed text sizes per screen. Body text ≥ 18 px, nothing below
    16 px, secondary grey ≥ #BDBDBD. (Round 1: all four renders failed at 9–12 px.) All text is legible on true black at arm's length.
B3. **Two-second glance.** Each screen has one dominant element that answers "what is this?" in under
    two seconds. Test: a blurred thumbnail still shows the hierarchy.
B4. **Element budget.** Home has ≤ 3 elements besides Dex. Cards have ≤ 60 words and ≤ 3 actions.
B5. **Dex never disappears.** He is never hidden behind a card. The corner mini-Dex is allowed only for
    passive reading (e.g. a long answer). On active screens, B14 applies.
B6. **Money is unmistakable.** The money card looks different from the decision card at a glance. The
    confirm is a 2-second hold ring, never a tap target. The total is the largest text on the screen.
B7. **One accent, one meaning.** The accent colour means exactly one thing and never appears as
    decoration. No red dots, badges or counters anywhere.
B8. **Implementable.** Flat fills, strokes and sprites only. No blur, soft shadow, glass or large
    gradient. Colours stay distinct after RGB565 quantisation.
B9. **True black owns the screen.** Most of the screen area is #000. Cards are the exception, not
    the background.

B10. **No clock. Dex is the hero of Home.** No clock, time display or hero numerals on Home or any surface (the owner, 2026-09-25: "i dont want anymore clock styles"). Dex fills ≥45% of Home's height, with at most one status line. Test: it must not read as a watch face.
B11. **Dex acts every state.** Each surface has its own pose (idle, listening, thinking, asking, waiting-on-hold, done, asleep, offline). No pose is reused across two states, and Dex stays in one fixed anchor zone that content never overlaps.
B12. **Money is the loudest screen.** The hold instruction is at headline size next to the control. The hold control is dominant and ours, not a thin ring (Dex himself may be the progress indicator).
B14. **Dex works the active screens.** On Listening, Decision, Money and Done, Dex is part of the
     interaction, not decoration beside it. He holds up the question, carries the bag, becomes the hold
     progress, ticks the box. Test: remove Dex and the screen loses meaning, not just charm.
     (The owner, r2: "when activating it should leverage what we can".)
B13. **Night-safe brightness.** No large white/cream areas. Brightest elements are small, and a dim palette exists for the bedroom.

## Kill list (v1)

- Chat bubbles or chat-widget layouts for Dex's answers. They make him look like a 2018 chatbot.
- Tracked micro-caps eyebrow labels on every block.
- Glassmorphism, glows and gradients, which the device can't render.
- Notification badges, red dots, streak counters.
- Equal-width tab bars and dot pagers with no primary element.
- Sparkle/✨ "AI" iconography.
- Pixel-art fonts or pixel-art UI. (Pixel style retired with the smooth-Dex decision.)
- The renderer's own brand palette (Claude orange-on-cream). Caught by the owner in 24-6IPL.
- Symmetric Siri/Voice-Memos waveform bars. 4/4 critics.
- Apple Watch activity-ring / Apple Pay hold ring copied as the money confirm. 4/4 critics.
- Equal-weight ✓ / ✗ / ⏰ icon-only action row (iOS call/alarm template).
- One sprite pose resized across screens ("sticker Dex").
- Any clock or watch-face composition: a big time, a time as hero, digits Dex leans on. The owner's hard no.
- A giant numeral leading screens where no number matters (e.g. "212").
- Grey cards on AMOLED. True black is the container.
- Hairline Didone or thin display serifs, which bloom in glare.
- Decoration pagers (Roman numerals, dot pagers).

## Keeps

- **The copy voice.** 4/4 critics named words as the keep: "Nothing needs you", headline-first lines ("Light day."), question + stated default ("Pause the side project? / Default: yes, Sunday.").
- **13-RABK money card.** the owner's keep.
- **1-CTRL answer card and decision card.** the owner's keeps ("clean", "don't hate it").
