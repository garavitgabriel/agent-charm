// The Dex seam. Everything Dex looks like lives behind this header.
// dex_sprite.cpp plays the frame table generated into charm_assets_sprites.{h,cpp} by tools/
// (`charm-assets sprites MANIFEST`); a pose/outfit with no frames is a gray placeholder box
// labeled with pose + outfit. New art is a regenerate, never an API change.
#pragma once
#include <stdint.h>
#include <lvgl.h>

enum dex_pose_t {
    DEX_POSE_IDLE,
    DEX_POSE_LISTENING,
    DEX_POSE_WORKING,
    DEX_POSE_ATTENTION,
    DEX_POSE_DONE,
    DEX_POSE_SPEAKING,
    DEX_POSE_ASLEEP,
    DEX_POSE_OFFLINE,
    DEX_POSE_ERROR,      // design: "needs more" shrug, palms up
    // Design § 11.3 poses (added 2026-09-27; append-only so existing values keep their numbers).
    DEX_POSE_ASK_YES,    // Decision: holds up the "Yes" sign
    DEX_POSE_OFFER_BAG,  // Money preview: takeout bag at chest (the hold control)
    DEX_POSE_LIFT_BAG,   // Money mid-hold: on toes, bag overhead, filling
    DEX_POSE_LOOKOUT,    // Live tracker: arms folded, looks to the door, toe-tap
    DEX_POSE_PAPER,      // Pocket edition: holds the paper open
    DEX_POSE_SHOW_PHONE, // Job done: shows his phone
    DEX_POSE_COUNT
};

// Outfit/prop for Dex, one per protocol `mode.value`.
enum dex_outfit_t {
    DEX_OUTFIT_DEFAULT,
    DEX_OUTFIT_GAMEDAY,
    DEX_OUTFIT_READING,
    DEX_OUTFIT_FOOD,
    DEX_OUTFIT_CODE,
    DEX_OUTFIT_CAT,
    DEX_OUTFIT_COUNT
};

// Full body (Home and friends) or the mini head-and-shoulders in a corner while a card is open.
// DESIGN § 11.6: Dex is ALWAYS full body at the one anchor. MINI is kept for API stability only;
// the final UI must not use it.
enum dex_size_t { DEX_SIZE_FULL, DEX_SIZE_MINI };

// Points on Dex the UI draws overlays against (design § 11.7: the bag fill and the voice stream
// are LVGL overlays, never baked into sprites).
enum dex_point_t {
    DEX_POINT_HAND,  // the cupped hand the Listening voice stream lands in
    DEX_POINT_BAG,   // the takeout bag: the money hold control and the fill clip
    DEX_POINT_COUNT
};

// Create Dex once on `parent`. Dex persists across surfaces; the UI only moves and re-poses him.
void dex_create(lv_obj_t *parent);

void dex_set_pose(dex_pose_t pose);
void dex_set_outfit(dex_outfit_t outfit);
void dex_set_size(dex_size_t size);
void dex_set_hidden(bool hidden);

// Animation clock. Called from charm_ui_tick().
void dex_tick(uint32_t now_ms);

// Screen-space box of `which` for the CURRENT frame (it moves with the pose, e.g. bag at chest vs
// overhead). Returns false when the current frames carry no such metadata (placeholder art); the UI
// then falls back to fixed coordinates measured from the reference screens.
bool dex_get_point_area(dex_point_t which, lv_area_t *out);

dex_pose_t dex_get_pose(void);
dex_outfit_t dex_get_outfit(void);
dex_size_t dex_get_size(void);

const char *dex_pose_name(dex_pose_t pose);
const char *dex_outfit_name(dex_outfit_t outfit);
// Protocol mode string -> outfit. Returns false (and leaves *out) for an unknown mode.
bool dex_outfit_from_mode(const char *mode, dex_outfit_t *out);
