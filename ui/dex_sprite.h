// The Dex seam. Everything Dex looks like lives behind this header.
// Today it is a gray placeholder box labeled with pose + outfit; the design sprint replaces only
// dex_sprite.cpp's internals (sprite sheets, frames, props) and keeps this API.
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
    DEX_POSE_ERROR,
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
enum dex_size_t { DEX_SIZE_FULL, DEX_SIZE_MINI };

// Create Dex once on `parent`. Dex persists across surfaces; the UI only moves and re-poses him.
void dex_create(lv_obj_t *parent);

void dex_set_pose(dex_pose_t pose);
void dex_set_outfit(dex_outfit_t outfit);
void dex_set_size(dex_size_t size);
void dex_set_hidden(bool hidden);

// Animation clock. Called from charm_ui_tick().
void dex_tick(uint32_t now_ms);

dex_pose_t dex_get_pose(void);
dex_outfit_t dex_get_outfit(void);
dex_size_t dex_get_size(void);

const char *dex_pose_name(dex_pose_t pose);
const char *dex_outfit_name(dex_outfit_t outfit);
// Protocol mode string -> outfit. Returns false (and leaves *out) for an unknown mode.
bool dex_outfit_from_mode(const char *mode, dex_outfit_t *out);
