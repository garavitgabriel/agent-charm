// GENERATED — do not edit. Dex sprite frames for ui/dex_sprite.cpp.
// Regenerate: cd tools && uv run charm-assets sprites manifest.json
// Sources (relative to tools/):
//   manifest.json (sha256 920e25ae18b4381b)
//   76 frame PNGs (sha256 269614e28b7f516a)
//   coach/manifest.json (sha256 559ec9de9ec4fbd2)
//   43 coach frame PNGs (sha256 aeff9178086b9d58)

#pragma once
#include <stdint.h>
#include <lvgl.h>

// Smooth Dex: 20 pose/outfit animations drawn, 70 borrowed from the default outfit; 75 unique frames (78 uses).
// Coach: 10 pose/outfit animations drawn, 50 borrowed from coach's default outfit, 42 frames.
// Opaque RGB565 (little-endian) on #000, one LZ4 block each: 86,016 bytes a frame decoded, 1,165,822 bytes compressed in all.
#define CHARM_SPRITE_SMOOTH 1
#define CHARM_SPRITE_INDEXED_BPP 0
#define CHARM_SPRITE_CELL_W 192
#define CHARM_SPRITE_CELL_H 224
// The cell pixel on Dex's hip, and where the hip lands on screen. Dex is never scaled.
#define CHARM_SPRITE_ANCHOR_X 76
#define CHARM_SPRITE_ANCHOR_Y 161
#define CHARM_SPRITE_SCREEN_ANCHOR_X 236
#define CHARM_SPRITE_SCREEN_ANCHOR_Y 379
// Top-left of the unscaled 76x76 head-and-shoulders crop DEX_SIZE_MINI shows, cell px.
#define CHARM_SPRITE_MINI_X 38
#define CHARM_SPRITE_MINI_Y 20
#define CHARM_SPRITE_CHARACTERS 2  // dex, coach
#define CHARM_SPRITE_POSES 15
#define CHARM_SPRITE_OUTFITS 6
#define CHARM_SPRITE_POINTS 2  // hand, bag
#define CHARM_SPRITE_IMAGES 117
#define CHARM_SPRITE_NO_IMG 0xFFFF
#define CHARM_SPRITE_NO_POSE 0xFF

// Motion (docs/design/final/motion.md, via the manifest).
#define CHARM_SPRITE_TICK_MS 40
#define CHARM_SPRITE_BLINK_HALF_MS 60
#define CHARM_SPRITE_BLINK_CLOSED_MS 90
#define CHARM_SPRITE_BLINK_EVERY_MIN_MS 3000
#define CHARM_SPRITE_BLINK_EVERY_MAX_MS 6000
#define CHARM_SPRITE_BLINK_DOUBLE_EVERY 5
#define CHARM_SPRITE_BLINK_DOUBLE_GAP_MS 150
#define CHARM_SPRITE_SIP_EVERY_MIN_MS 20000
#define CHARM_SPRITE_SIP_EVERY_MAX_MS 40000
enum { CHARM_BREATH_NONE, CHARM_BREATH_DAY, CHARM_BREATH_NIGHT };

struct charm_sprite_img_t {
    const uint8_t *lz4;  // one LZ4 block: CELL_W x CELL_H RGB565 pixels
    uint32_t size;
    uint32_t fnv;        // FNV-1a over the decoded 16-bit pixels
    int16_t points[CHARM_SPRITE_POINTS][4];  // x, y, w, h in cell px; w == 0: none
};

struct charm_sprite_frame_t {
    uint16_t img;  // index into charm_sprite_imgs
    uint16_t ms;
};

struct charm_sprite_clip_t {
    const charm_sprite_frame_t *frames;  // nullptr: none
    uint8_t count;
};

struct charm_sprite_anim_t {
    const charm_sprite_frame_t *frames;  // nullptr when this pose/outfit has no art
    uint8_t count;
    uint8_t loop_from;       // frames[loop_from..count) loop; a single last frame holds
    const uint16_t (*blink)[2];  // per frame: half, closed; nullptr: no blinks
    charm_sprite_clip_t sip;     // one-shot every SIP_EVERY ms (idle only)
    charm_sprite_clip_t exit;    // plays first when the pose changes to exit_to
    uint8_t exit_to;             // dex_pose_t, or CHARM_SPRITE_NO_POSE
    uint8_t breath;              // CHARM_BREATH_*
};

// Breathing: whole-sprite y offset steps (0, -1, -2, -2, -1, 0 px) and their ms.
extern const uint16_t charm_sprite_breath[3][6];
extern const charm_sprite_img_t charm_sprite_imgs[CHARM_SPRITE_IMAGES];
// [character][pose][outfit] in dex_character_t / dex_pose_t / dex_outfit_t order:
//   characters: dex, coach
//   poses:      idle, listening, working, attention, done, speaking, asleep, offline, error, ask_yes, offer_bag, lift_bag, lookout, paper, show_phone
//   outfits:    default, gameday, reading, food, code, cat
// A character never borrows another's frames: no art is {nullptr, 0, ...}.
extern const charm_sprite_anim_t charm_sprite_anims[CHARM_SPRITE_CHARACTERS][CHARM_SPRITE_POSES][CHARM_SPRITE_OUTFITS];
