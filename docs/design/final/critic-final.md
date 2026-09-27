---
title: Dex Charm — checklist critic on FINAL
type: design-review
created: 2026-09-27
updated: 2026-09-27
related: [../sprint-log.md]
tags: [design-sprint, final, critic]
---

# Checklist critic — FINAL · model: Sonnet (design-critic, blind, one image, checklist only)

| Bone | Verdict | Critic's reason | Chief verification against source (`final/src/`) |
|---|---|---|---|
| B1 | PASS | same proportions, palette everywhere | ✓ |
| B2 | FAIL | sub-16px footnotes (4,6,7,14) | **Misread.** The source uses only 18/24/32/40px. The critic read a 2936px sheet of 17 boards, so the footnotes looked small at sheet scale. The real finding is the dimmer grey on the footnote row (contrast, not size). |
| B3 | PARTIAL | Night (12) has no dominant element | Real: Night has no text (the renderer's choice). |
| B4 | PASS | Home: 2 elements | ✓ |
| B5 | PASS | never covered | ✓ |
| B6 | PASS | price biggest, distinct from decision | ✓ |
| B7 | PASS | single purple accent, all functional | ✓ |
| B8 | FAIL | gradient shading on the character | **Misread.** There are 0 gradient/filter/blur/opacity tokens in the source. It's flat tonal steps (2–3 per material), which read as shading when downscaled. |
| B9 | PARTIAL | agenda times read as clock-ish | Content times (9:30, 20:35) are allowed by B10's wording ("times inside content are fine"). Watch it anyway. |
| B10 | PARTIAL | schedule times as content | Same as B9. Home is clean. |
| B11 | FAIL | hand-to-head pose on 8 and 9; scale shifts on 1 and 12 | **Partly real.** Every screen uses one scale constant `S` (scale does not shift, although the seated night pose reads smaller). But 8 (handoff) and 9 (lookout) may *look* alike. Check by eye. |
| B12 | PARTIAL | hold copy smaller than headline; 6 vs 7 nearly identical at thumbnail | **Real.** The same finding as round 2. |
| B13 | PASS | Night genuinely dim | ✓ |
| B14 | PARTIAL | only Listening is essential | Real, and harsh. Money has Dex holding the bag, but the text carries the meaning. |

**Accent (critic):** A, purple. It's saturated enough without neon bloom, and it's already the system hue.

**Remaining tells:** (1) shading reads as generated at sheet scale; (2) 8 and 9 poses look alike; (3) Night reads as a placeholder (lone moon); (4) 6 → 7 is a prop plus word swap, not a progress state; (5) the dashed comet trail on Listening doesn't match the flat icon language.

**Process lesson (new):** give the final critic per-screen PNGs or a 2× crop. A 17-board sheet makes a blind critic misread type size and flat shading. Two of the three FAILs were resolution artefacts.
