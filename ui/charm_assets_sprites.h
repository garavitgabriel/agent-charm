// GENERATED — do not edit. Dex sprite frames for ui/dex_sprite.cpp.
// Regenerate: cd tools && uv run charm-assets sprites fixtures/dummy/manifest.json
// Sources (relative to tools/):
//   fixtures/dummy/manifest.json (sha256 6923bb80472eee03)
//   fixtures/dummy/dummy-sheet.png (sha256 47b97cda83a546bb)

#pragma once
#include <stdint.h>
#include <lvgl.h>

// 4 pose/outfit animations drawn, 14 borrowed from the default outfit; 8 frames, 8 unique images.
// Format LV_IMG_CF_INDEXED_4BIT: 704 bytes a frame, 5632 bytes of pixel data in all.
// A full set (9 poses x 6 outfits x 4 frames) at this cell and palette: ~247 KiB.
#define CHARM_SPRITE_CELL_W 32
#define CHARM_SPRITE_CELL_H 40
#define CHARM_SPRITE_SCALE_FULL 5
#define CHARM_SPRITE_SCALE_MINI 4
// Top-left of the head-and-shoulders region the mini size shows, in cell pixels.
#define CHARM_SPRITE_MINI_X 6
#define CHARM_SPRITE_MINI_Y 2
#define CHARM_SPRITE_CF LV_IMG_CF_INDEXED_4BIT
#define CHARM_SPRITE_INDEXED_BPP 4  // 0 = true color + alpha
#define CHARM_SPRITE_POSES 15
#define CHARM_SPRITE_OUTFITS 6

struct charm_sprite_frame_t {
    const lv_img_dsc_t *img;
    uint16_t ms;
};

struct charm_sprite_anim_t {
    const charm_sprite_frame_t *frames;  // nullptr when this pose/outfit has no art
    uint8_t count;
};

// [pose][outfit] in dex_pose_t / dex_outfit_t order:
//   poses:   idle, listening, working, attention, done, speaking, asleep, offline, error, ask_yes, offer_bag, lift_bag, lookout, paper, show_phone
//   outfits: default, gameday, reading, food, code, cat
extern const charm_sprite_anim_t charm_sprite_anims[CHARM_SPRITE_POSES][CHARM_SPRITE_OUTFITS];
