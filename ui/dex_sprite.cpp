// Dex, played from the generated frame table in charm_assets_sprites.{h,cpp}
// (tools/: `uv run charm-assets sprites MANIFEST`). Two formats, whichever the table was generated in:
//
// * Smooth (CHARM_SPRITE_SMOOTH, the real Dex): opaque RGB565 frames pre-composited on #000, one LZ4
//   block each. The current frame is decoded into ONE reusable buffer (PSRAM on the device) and shown
//   unscaled with its hip on the design anchor. Motion follows docs/design/final/motion.md through
//   the table: per-frame ms with a loop point, blinks (random 3-6 s, every 5th double, never while
//   inhaling), the idle sip, the lift -> offer return clip, and breathing as a whole-sprite integer
//   px offset. Each frame carries its overlay points (hand, bag) for dex_get_point_area().
// * Indexed (pixel-art sheets, e.g. the tools/ dummy): each pose/outfit is a list of frames with
//   per-frame ms, zoomed by an integer scale into the full or mini box.
//
// A pose/outfit with no frames falls back to the gray placeholder box labeled with pose + outfit.
#include "dex_sprite.h"
#include "charm_assets_sprites.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if defined(ESP_PLATFORM)
#include <esp_heap_caps.h>
#endif

#ifndef CHARM_SPRITE_SMOOTH
#define CHARM_SPRITE_SMOOTH 0
#endif

static_assert(CHARM_SPRITE_POSES == DEX_POSE_COUNT, "charm_assets_sprites: pose table out of date");
static_assert(CHARM_SPRITE_OUTFITS == DEX_OUTFIT_COUNT, "charm_assets_sprites: outfit table out of date");

namespace {

constexpr lv_coord_t MINI_W = 76, MINI_H = 76;
constexpr uint32_t FRAME_MS = 250;  // placeholder animation step
constexpr int FRAMES = 4;
constexpr lv_coord_t CELL_W = CHARM_SPRITE_CELL_W, CELL_H = CHARM_SPRITE_CELL_H;

const char *const POSE_NAMES[DEX_POSE_COUNT] = {
    "idle", "listening", "working", "attention", "done", "speaking", "asleep", "offline", "error",
    "ask_yes", "offer_bag", "lift_bag", "lookout", "paper", "show_phone",
};
const char *const OUTFIT_NAMES[DEX_OUTFIT_COUNT] = {
    "default", "gameday", "reading", "food", "code", "cat",
};

lv_obj_t *box;
lv_obj_t *label;
lv_obj_t *beat;  // a small square that steps each frame: proof the animation clock runs
lv_obj_t *img;   // the sprite
dex_pose_t pose = DEX_POSE_IDLE;
dex_outfit_t outfit = DEX_OUTFIT_DEFAULT;
dex_size_t size = DEX_SIZE_FULL;
bool hidden = false;
int frame = -1;  // placeholder beat step

const charm_sprite_anim_t *anim;  // nullptr: the placeholder is showing
uint8_t anim_frame;
uint32_t frame_since;  // when anim_frame came up
bool frame_clock_set;  // false until the first tick after a (re)start

void relabel() {
    if (!label) return;
    char text[64];
    if (size == DEX_SIZE_FULL) {
        snprintf(text, sizeof text, "DEX\n%s\n%s", POSE_NAMES[pose], OUTFIT_NAMES[outfit]);
    } else {
        snprintf(text, sizeof text, "dex\n%s", POSE_NAMES[pose]);
    }
    lv_label_set_text(label, text);
}

// The gray placeholder box (on) or the sprite (off).
void show_placeholder(bool on) {
    lv_obj_set_style_bg_opa(box, on ? LV_OPA_COVER : LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(box, on ? 1 : 0, 0);
    if (on) {
        lv_obj_clear_flag(label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(beat, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(img, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(beat, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(img, LV_OBJ_FLAG_HIDDEN);
    }
}

void step_placeholder(uint32_t now_ms) {
    int f = (int)((now_ms / FRAME_MS) % FRAMES);
    if (f == frame) return;
    frame = f;
    lv_obj_align(beat, LV_ALIGN_BOTTOM_LEFT, (lv_coord_t)(4 + f * 8), -4);
}

#if CHARM_SPRITE_SMOOTH
// ---------------------------------------------------------------------------- smooth (RGB565 + LZ4)

static_assert(CHARM_SPRITE_POINTS == DEX_POINT_COUNT, "charm_assets_sprites: point table out of date");
static_assert(sizeof(lv_color_t) == 2, "smooth frames are RGB565");
// The cell's top-left on the parent: the hip anchor never moves and Dex is never scaled.
constexpr lv_coord_t CELL_X = CHARM_SPRITE_SCREEN_ANCHOR_X - CHARM_SPRITE_ANCHOR_X;
constexpr lv_coord_t CELL_Y = CHARM_SPRITE_SCREEN_ANCHOR_Y - CHARM_SPRITE_ANCHOR_Y;
constexpr uint32_t PIXEL_BYTES = (uint32_t)CELL_W * CELL_H * sizeof(lv_color_t);
constexpr lv_coord_t BREATH_DY[6] = {0, -1, -2, -2, -1, 0};  // rest, inhale x2, hold, exhale x2

lv_color_t *pixels;  // the one decode buffer: PSRAM on the device
lv_img_dsc_t shown = {{LV_IMG_CF_TRUE_COLOR, 0, 0, (uint32_t)CELL_W, (uint32_t)CELL_H}, PIXEL_BYTES, nullptr};
uint16_t shown_img = CHARM_SPRITE_NO_IMG;  // which image `pixels` holds
lv_coord_t shown_dy;                       // the whole-sprite breathing offset

// A one-shot clip over the main track: the idle sip, or the exit clip (lift -> offer) that plays
// before the next pose's animation starts.
enum class Clip : uint8_t { None, Sip, Exit };
Clip clip = Clip::None;
const charm_sprite_clip_t *clip_src;
uint8_t clip_frame;
uint32_t clip_since;
const charm_sprite_anim_t *after_exit;  // the animation the exit clip leads into

// Blink phases: 1 half, 2 closed, 3 half; for a double, 4 open gap, 5 half, 6 closed, 7 half.
uint8_t blink_phase;
uint32_t blink_since;
uint32_t next_blink;
uint32_t blink_count;
uint32_t next_sip;
uint32_t breath_epoch;
bool breath_epoch_set;
uint32_t rng;

uint32_t rand_between(uint32_t lo, uint32_t hi) {
    rng ^= rng << 13;
    rng ^= rng >> 17;
    rng ^= rng << 5;
    return lo + rng % (hi - lo + 1);
}

uint32_t next_blink_from(uint32_t now) {
    return now + rand_between(CHARM_SPRITE_BLINK_EVERY_MIN_MS, CHARM_SPRITE_BLINK_EVERY_MAX_MS);
}

uint32_t next_sip_from(uint32_t now) {
    return now + rand_between(CHARM_SPRITE_SIP_EVERY_MIN_MS, CHARM_SPRITE_SIP_EVERY_MAX_MS);
}

bool due(uint32_t now, uint32_t at) { return (int32_t)(now - at) >= 0; }

// One LZ4 block (no frame header) into exactly `cap` bytes. False on corrupt input.
bool lz4_decode(const uint8_t *ip, uint32_t n, uint8_t *dst, uint32_t cap) {
    const uint8_t *const iend = ip + n;
    uint8_t *op = dst;
    uint8_t *const oend = dst + cap;
    while (ip < iend) {
        const uint8_t token = *ip++;
        uint32_t lit = token >> 4;
        if (lit == 15) {
            uint8_t b;
            do {
                if (ip >= iend) return false;
                b = *ip++;
                lit += b;
            } while (b == 255);
        }
        if (lit > (uint32_t)(iend - ip) || lit > (uint32_t)(oend - op)) return false;
        memcpy(op, ip, lit);
        op += lit;
        ip += lit;
        if (ip >= iend) break;  // the last sequence is literals only
        if (iend - ip < 2) return false;
        const uint32_t off = (uint32_t)ip[0] | (uint32_t)ip[1] << 8;
        ip += 2;
        if (off == 0 || off > (uint32_t)(op - dst)) return false;
        uint32_t len = token & 15;
        if (len == 15) {
            uint8_t b;
            do {
                if (ip >= iend) return false;
                b = *ip++;
                len += b;
            } while (b == 255);
        }
        len += 4;
        if (len > (uint32_t)(oend - op)) return false;
        const uint8_t *m = op - off;
        if (off >= len) {
            memcpy(op, m, len);
            op += len;
        } else {
            while (len--) *op++ = *m++;  // overlapping: a repeating run
        }
    }
    return op == oend;
}

lv_color_t *alloc_pixels() {
#if defined(ESP_PLATFORM)
    void *p = heap_caps_malloc(PIXEL_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!p) p = heap_caps_malloc(PIXEL_BYTES, MALLOC_CAP_8BIT);
    return (lv_color_t *)p;
#else
    return (lv_color_t *)malloc(PIXEL_BYTES);
#endif
}

void show_image(uint16_t i) {
    if (i == shown_img || !pixels || i >= CHARM_SPRITE_IMAGES) return;
    const charm_sprite_img_t &im = charm_sprite_imgs[i];
    if (!lz4_decode(im.lz4, im.size, (uint8_t *)pixels, PIXEL_BYTES)) {
        LV_LOG_WARN("dex: frame %u does not decode", (unsigned)i);
        memset(pixels, 0, PIXEL_BYTES);  // black: never a half-drawn Dex
    }
    shown_img = i;
    lv_img_cache_invalidate_src(&shown);
    lv_obj_invalidate(img);
}

uint16_t current_image() {
    if (clip != Clip::None) return clip_src->frames[clip_frame].img;
    if (blink_phase && blink_phase != 4 && anim->blink) {
        const bool closed = blink_phase == 2 || blink_phase == 6;
        return anim->blink[anim_frame][closed ? 1 : 0];
    }
    return anim->frames[anim_frame].img;
}

// The breathing step (0..5) at `now`: rest, inhale -1, inhale -2, hold, exhale -1, exhale 0.
int breath_step(uint32_t now, const uint16_t *steps) {
    uint32_t cycle = 0;
    for (int i = 0; i < 6; i++) cycle += steps[i];
    if (!cycle) return 0;
    uint32_t t = (now - breath_epoch) % cycle;
    for (int i = 0; i < 6; i++) {
        if (t < steps[i]) return i;
        t -= steps[i];
    }
    return 0;
}

void set_offset(lv_coord_t dy) {
    if (dy == shown_dy) return;
    shown_dy = dy;
    lv_obj_set_y(img, size == DEX_SIZE_FULL ? dy : (lv_coord_t)(dy - CHARM_SPRITE_MINI_Y));
}

void start_clip(Clip kind, const charm_sprite_clip_t *src, uint32_t now) {
    clip = kind;
    clip_src = src;
    clip_frame = 0;
    clip_since = now;
}

void restyle() {
    if (!box) return;
    const charm_sprite_anim_t *a = &charm_sprite_anims[pose][outfit];
    const charm_sprite_anim_t *want = a->count > 0 && a->frames && pixels ? a : nullptr;
    show_placeholder(!want);
    relabel();
    if (!want) {
        anim = nullptr;
        clip = Clip::None;
        return;
    }
    // A borrowed outfit (the same frames) keeps playing where it was.
    if (anim && want->frames == anim->frames && clip != Clip::Exit) return;
    frame_clock_set = false;  // the next tick starts the new clocks
    blink_phase = 0;
    // Leaving through a return clip (lift_bag -> offer_bag goes back through the in-betweens).
    if (anim && anim->exit.frames && anim->exit_to == (uint8_t)pose && clip != Clip::Exit) {
        start_clip(Clip::Exit, &anim->exit, 0);
        after_exit = want;
        return;
    }
    clip = Clip::None;
    anim = want;
    anim_frame = 0;
    show_image(current_image());
}

void place() {
    if (!box) return;
    if (size == DEX_SIZE_FULL) {
        lv_obj_set_size(box, CELL_W, CELL_H);
        lv_obj_align(box, LV_ALIGN_TOP_LEFT, CELL_X, CELL_Y);  // also clears mini's TOP_RIGHT
        lv_obj_add_flag(box, LV_OBJ_FLAG_OVERFLOW_VISIBLE);  // breathing lifts Dex 2 px
        lv_obj_set_pos(img, 0, shown_dy);
    } else {
        // DESIGN § 11.6: the final UI never uses mini. Kept for main's card layout: the unscaled
        // head-and-shoulders crop, clipped to the corner box.
        lv_obj_set_size(box, MINI_W, MINI_H);
        lv_obj_align(box, LV_ALIGN_TOP_RIGHT, -8, 6);
        lv_obj_clear_flag(box, LV_OBJ_FLAG_OVERFLOW_VISIBLE);
        lv_obj_set_pos(img, -CHARM_SPRITE_MINI_X, (lv_coord_t)(shown_dy - CHARM_SPRITE_MINI_Y));
    }
    restyle();
}

void create_sprite() {
    if (!pixels) {
        pixels = alloc_pixels();
        if (pixels) memset(pixels, 0, PIXEL_BYTES);
    }
    shown.data = (const uint8_t *)pixels;
    shown_img = CHARM_SPRITE_NO_IMG;
    shown_dy = 0;
    clip = Clip::None;
    blink_phase = 0;
    blink_count = 0;
    breath_epoch_set = false;
    rng = 0x2545F491u;  // fixed seed: the sim's shots and checks are reproducible
    if (pixels) {
        lv_img_set_src(img, &shown);
        lv_img_set_pivot(img, 0, 0);
    }
}

void tick(uint32_t now) {
    if (!breath_epoch_set) {
        breath_epoch = now;
        breath_epoch_set = true;
    }
    if (!frame_clock_set) {
        frame_since = now;
        clip_since = now;
        next_blink = next_blink_from(now);
        next_sip = next_sip_from(now);
        frame_clock_set = true;
    }

    // The one-shot clip (sip or exit).
    while (clip != Clip::None && now - clip_since >= clip_src->frames[clip_frame].ms) {
        clip_since += clip_src->frames[clip_frame].ms;
        if (++clip_frame < clip_src->count) continue;
        if (clip == Clip::Exit) {
            anim = after_exit;
            anim_frame = 0;
            frame_since = clip_since;
        } else {
            next_sip = next_sip_from(now);
        }
        clip = Clip::None;
    }

    // The main track: frames loop from loop_from; a single last frame holds.
    if (clip != Clip::Exit) {
        uint32_t cycle = 0;
        for (int i = anim->loop_from; i < anim->count; i++) cycle += anim->frames[i].ms;
        if (anim_frame >= anim->loop_from && now - frame_since >= 2 * cycle) {
            frame_since = now - (now - frame_since) % cycle;  // after a stall, skip whole cycles
        }
        while (now - frame_since >= anim->frames[anim_frame].ms) {
            frame_since += anim->frames[anim_frame].ms;
            anim_frame = (uint8_t)(anim_frame + 1 < anim->count ? anim_frame + 1 : anim->loop_from);
        }
    }

    // Breathing: a whole-sprite offset (none while an exit clip swaps poses).
    const uint8_t breath = clip == Clip::Exit ? (uint8_t)CHARM_BREATH_NONE : anim->breath;
    const int step = breath_step(now, charm_sprite_breath[breath]);
    const bool inhaling = breath != CHARM_BREATH_NONE && (step == 1 || step == 2);
    set_offset(breath != CHARM_BREATH_NONE ? BREATH_DY[step] : 0);

    // Blinks: random 3-6 s apart, never while inhaling, every Nth one double.
    if (blink_phase) {
        static const uint16_t PHASE_MS[8] = {
            0, CHARM_SPRITE_BLINK_HALF_MS, CHARM_SPRITE_BLINK_CLOSED_MS, CHARM_SPRITE_BLINK_HALF_MS,
            CHARM_SPRITE_BLINK_DOUBLE_GAP_MS, CHARM_SPRITE_BLINK_HALF_MS, CHARM_SPRITE_BLINK_CLOSED_MS,
            CHARM_SPRITE_BLINK_HALF_MS,
        };
        const bool twice = CHARM_SPRITE_BLINK_DOUBLE_EVERY && blink_count % CHARM_SPRITE_BLINK_DOUBLE_EVERY == 0;
        while (blink_phase && now - blink_since >= PHASE_MS[blink_phase]) {
            blink_since += PHASE_MS[blink_phase];
            blink_phase = (uint8_t)((blink_phase == 3 && !twice) || blink_phase == 7 ? 0 : blink_phase + 1);
            if (!blink_phase) next_blink = next_blink_from(now);
        }
    } else if (due(now, next_blink)) {
        if (!anim->blink || clip != Clip::None) {
            next_blink = next_blink_from(now);
        } else if (!inhaling) {
            blink_phase = 1;
            blink_since = now;
            blink_count++;
        }
    }

    // The idle sip: a one-shot every 20-40 s, never mid-blink.
    if (clip == Clip::None && !blink_phase && anim->sip.frames && due(now, next_sip)) {
        start_clip(Clip::Sip, &anim->sip, now);
    }

    show_image(current_image());
}

bool point_area(dex_point_t which, lv_area_t *out) {
    if (!box || !anim || hidden || size != DEX_SIZE_FULL || shown_img >= CHARM_SPRITE_IMAGES) return false;
    const int16_t *p = charm_sprite_imgs[shown_img].points[which];
    if (p[2] <= 0 || p[3] <= 0) return false;
    lv_area_t parent;
    lv_obj_get_coords(lv_obj_get_parent(box), &parent);
    out->x1 = (lv_coord_t)(parent.x1 + CELL_X + p[0]);
    out->y1 = (lv_coord_t)(parent.y1 + CELL_Y + shown_dy + p[1]);
    out->x2 = (lv_coord_t)(out->x1 + p[2] - 1);
    out->y2 = (lv_coord_t)(out->y1 + p[3] - 1);
    return true;
}

#else
// ---------------------------------------------------------------------------- indexed (pixel art)

constexpr lv_coord_t FULL_W = 168, FULL_H = 224;
static_assert(CELL_W * CHARM_SPRITE_SCALE_FULL <= FULL_W && CELL_H * CHARM_SPRITE_SCALE_FULL <= FULL_H,
              "full-size sprite is bigger than the Dex box");

#if CHARM_SPRITE_INDEXED_BPP
// Indexed frames stay in flash; the current one is expanded here so LVGL can zoom it (8.3 only
// transforms images it can read whole).
uint8_t pixels[CELL_W * CELL_H * LV_IMG_PX_SIZE_ALPHA_BYTE];
lv_img_dsc_t expanded = {
    {LV_IMG_CF_TRUE_COLOR_ALPHA, 0, 0, (uint32_t)CELL_W, (uint32_t)CELL_H}, sizeof pixels, pixels,
};

void expand(const lv_img_dsc_t *src) {
    constexpr int BPP = CHARM_SPRITE_INDEXED_BPP;
    constexpr int COLORS = 1 << BPP;
    constexpr int ROW_BYTES = (CELL_W * BPP + 7) / 8;
    const lv_color32_t *pal = (const lv_color32_t *)src->data;
    const uint8_t *rows = src->data + COLORS * sizeof(lv_color32_t);
    lv_color_t colors[COLORS];
    for (int i = 0; i < COLORS; i++) colors[i] = lv_color_make(pal[i].ch.red, pal[i].ch.green, pal[i].ch.blue);
    uint8_t *out = pixels;
    for (int y = 0; y < CELL_H; y++) {
        const uint8_t *row = rows + y * ROW_BYTES;
        for (int x = 0; x < CELL_W; x++) {
            const int bit = x * BPP;
            const int index = (row[bit / 8] >> (8 - BPP - bit % 8)) & (COLORS - 1);
            memcpy(out, &colors[index], sizeof(lv_color_t));
            out[LV_IMG_PX_SIZE_ALPHA_BYTE - 1] = pal[index].ch.alpha;
            out += LV_IMG_PX_SIZE_ALPHA_BYTE;
        }
    }
}
#endif

void show_frame() {
    if (!img || !anim) return;
    const lv_img_dsc_t *src = anim->frames[anim_frame].img;
#if CHARM_SPRITE_INDEXED_BPP
    expand(src);
    lv_img_cache_invalidate_src(&expanded);
    lv_obj_invalidate(img);
#else
    lv_img_set_src(img, src);
    lv_img_set_pivot(img, 0, 0);  // set_src recenters the pivot
#endif
}

// The sprite when the current pose/outfit has frames, the gray placeholder when it doesn't.
void restyle() {
    if (!box) return;
    const charm_sprite_anim_t *a = &charm_sprite_anims[pose][outfit];
    const charm_sprite_anim_t *want = a->count > 0 && a->frames ? a : nullptr;
    show_placeholder(!want);
    if (want != anim) {
        anim = want;
        anim_frame = 0;
        frame_clock_set = false;
        show_frame();
    }
    relabel();
}

void place() {
    if (!box) return;
    // The sprite is zoomed around its top-left corner, so its position is where the scaled
    // image starts.
    int scale;
    if (size == DEX_SIZE_FULL) {
        lv_obj_set_size(box, FULL_W, FULL_H);
        lv_obj_align(box, LV_ALIGN_TOP_MID, 0, 92);
        scale = CHARM_SPRITE_SCALE_FULL;
        // Centered, feet on the bottom of the box.
        lv_obj_set_pos(img, (lv_coord_t)((FULL_W - CELL_W * scale) / 2), (lv_coord_t)(FULL_H - CELL_H * scale));
    } else {
        lv_obj_set_size(box, MINI_W, MINI_H);
        lv_obj_align(box, LV_ALIGN_TOP_RIGHT, -8, 6);
        scale = CHARM_SPRITE_SCALE_MINI;
        // The box clips everything outside the head-and-shoulders region.
        lv_obj_set_pos(img, (lv_coord_t)(-CHARM_SPRITE_MINI_X * scale), (lv_coord_t)(-CHARM_SPRITE_MINI_Y * scale));
    }
    lv_img_set_zoom(img, (uint16_t)(LV_IMG_ZOOM_NONE * scale));
    restyle();
}

void create_sprite() {
    lv_img_set_antialias(img, false);  // pixel art: nearest-neighbor scaling
#if CHARM_SPRITE_INDEXED_BPP
    lv_img_set_src(img, &expanded);
    lv_img_set_pivot(img, 0, 0);  // after set_src, which recenters the pivot
#endif
}

void tick(uint32_t now_ms) {
    if (!frame_clock_set) {
        frame_since = now_ms;
        frame_clock_set = true;
        return;
    }
    uint32_t cycle = 0;
    for (int i = 0; i < anim->count; i++) cycle += anim->frames[i].ms;
    uint32_t late = now_ms - frame_since;
    if (late >= cycle) frame_since = now_ms - late % cycle;  // after a stall, skip whole cycles
    const uint8_t was = anim_frame;
    while (now_ms - frame_since >= anim->frames[anim_frame].ms) {
        frame_since += anim->frames[anim_frame].ms;
        anim_frame = (uint8_t)((anim_frame + 1) % anim->count);
    }
    if (anim_frame != was) show_frame();
}

// Pixel-art frames carry no overlay points: the UI uses its fallback coordinates.
bool point_area(dex_point_t, lv_area_t *) { return false; }

#endif

}  // namespace

void dex_create(lv_obj_t *parent) {
    pose = DEX_POSE_IDLE;
    outfit = DEX_OUTFIT_DEFAULT;
    size = DEX_SIZE_FULL;
    hidden = false;
    frame = -1;
    anim = nullptr;
    box = lv_obj_create(parent);
    lv_obj_remove_style_all(box);
    lv_obj_set_style_bg_color(box, lv_color_hex(0x505050), 0);
    lv_obj_set_style_bg_opa(box, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(box, lv_color_hex(0x909090), 0);
    lv_obj_set_style_border_width(box, 1, 0);
    lv_obj_clear_flag(box, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_clear_flag(box, LV_OBJ_FLAG_SCROLLABLE);

    label = lv_label_create(box);
    lv_obj_set_style_text_color(label, lv_color_hex(0xE0E0E0), 0);
    lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_center(label);

    beat = lv_obj_create(box);
    lv_obj_remove_style_all(beat);
    lv_obj_set_size(beat, 6, 6);
    lv_obj_set_style_bg_color(beat, lv_color_hex(0xA0A0A0), 0);
    lv_obj_set_style_bg_opa(beat, LV_OPA_COVER, 0);
    lv_obj_align(beat, LV_ALIGN_BOTTOM_LEFT, 4, -4);

    img = lv_img_create(box);
    lv_obj_clear_flag(img, LV_OBJ_FLAG_CLICKABLE);
    create_sprite();
    place();
}

void dex_set_pose(dex_pose_t p) {
    if (p >= DEX_POSE_COUNT || p == pose) return;
    pose = p;
    restyle();
}

void dex_set_outfit(dex_outfit_t o) {
    if (o >= DEX_OUTFIT_COUNT || o == outfit) return;
    outfit = o;
    restyle();
}

void dex_set_size(dex_size_t s) {
    if (s == size) return;
    size = s;
    place();
}

void dex_set_hidden(bool h) {
    if (!box) return;
    hidden = h;
    if (h) lv_obj_add_flag(box, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_clear_flag(box, LV_OBJ_FLAG_HIDDEN);
}

void dex_tick(uint32_t now_ms) {
    if (!box) return;
    if (anim) {
        tick(now_ms);
        return;
    }
    step_placeholder(now_ms);
}

dex_pose_t dex_get_pose(void) { return pose; }
dex_outfit_t dex_get_outfit(void) { return outfit; }
dex_size_t dex_get_size(void) { return size; }

// Smooth frames: the current frame's box, moving with the pose and the breathing offset.
// Pixel art: false, and the UI falls back to coordinates measured from the reference screens.
bool dex_get_point_area(dex_point_t which, lv_area_t *out) {
    if (which >= DEX_POINT_COUNT || !out) return false;
    return point_area(which, out);
}

const char *dex_pose_name(dex_pose_t p) { return p < DEX_POSE_COUNT ? POSE_NAMES[p] : "?"; }
const char *dex_outfit_name(dex_outfit_t o) { return o < DEX_OUTFIT_COUNT ? OUTFIT_NAMES[o] : "?"; }

bool dex_outfit_from_mode(const char *mode, dex_outfit_t *out) {
    if (!mode) return false;
    for (int i = 0; i < DEX_OUTFIT_COUNT; i++) {
        if (strcmp(mode, OUTFIT_NAMES[i]) == 0) {
            *out = (dex_outfit_t)i;
            return true;
        }
    }
    return false;
}
