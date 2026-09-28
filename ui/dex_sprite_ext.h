// UI-side extensions of the sprite player, beside the frozen dex_sprite.h seam (not part of it).
// Include it after dex_sprite.h. It doesn't include that header itself: tools/tests builds the player
// against a generated copy of dex_sprite.h, and two copies of the seam must never meet in one unit.
#pragma once
#include <lvgl.h>

// Switch the character with motion.md's crossfade at the anchor: 2 cross frames x 80 ms, the
// outgoing character's last frame fading 2/3 -> 1/3 -> gone over the incoming one (smooth frames;
// pixel art swaps at once). dex_set_character() stays an instant, bit-exact swap.
void dex_set_character_crossfade(dex_character_t character);

// Test introspection: the outgoing character's opacity during a crossfade; LV_OPA_TRANSP when none
// is running.
lv_opa_t dex_debug_crossfade_opa(void);
