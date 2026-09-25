// Dex, played from the generated frame table in charm_assets_sprites.{h,cpp}
// (tools/: `uv run charm-assets sprites MANIFEST`). Each pose/outfit is a list of frames with
// per-frame ms, stepped on the UI tick. Full and mini are the same frames at two integer scales;
// mini shows the head-and-shoulders region from CHARM_SPRITE_MINI_X/Y. A pose/outfit with no
// frames falls back to the gray placeholder box labeled with pose + outfit.
#include "dex_sprite.h"
#include "charm_assets_sprites.h"
#include <stdio.h>
#include <string.h>

static_assert(CHARM_SPRITE_POSES == DEX_POSE_COUNT, "charm_assets_sprites: pose table out of date");
static_assert(CHARM_SPRITE_OUTFITS == DEX_OUTFIT_COUNT, "charm_assets_sprites: outfit table out of date");

namespace {

constexpr lv_coord_t FULL_W = 168, FULL_H = 224;
constexpr lv_coord_t MINI_W = 76, MINI_H = 76;
constexpr uint32_t FRAME_MS = 250;  // placeholder animation step
constexpr int FRAMES = 4;
constexpr lv_coord_t CELL_W = CHARM_SPRITE_CELL_W, CELL_H = CHARM_SPRITE_CELL_H;
static_assert(CELL_W * CHARM_SPRITE_SCALE_FULL <= FULL_W && CELL_H * CHARM_SPRITE_SCALE_FULL <= FULL_H,
              "full-size sprite is bigger than the Dex box");

const char *const POSE_NAMES[DEX_POSE_COUNT] = {
    "idle", "listening", "working", "attention", "done", "speaking", "asleep", "offline", "error",
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
int frame = -1;  // placeholder beat step

const charm_sprite_anim_t *anim;  // nullptr: the placeholder is showing
uint8_t anim_frame;
uint32_t frame_since;  // when anim_frame came up
bool frame_clock_set;  // false until the first tick after a (re)start

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

// The sprite when the current pose/outfit has frames, the gray placeholder when it doesn't.
void restyle() {
    if (!box) return;
    const charm_sprite_anim_t *a = &charm_sprite_anims[pose][outfit];
    const charm_sprite_anim_t *want = a->count > 0 && a->frames ? a : nullptr;
    lv_obj_set_style_bg_opa(box, want ? LV_OPA_TRANSP : LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(box, want ? 0 : 1, 0);
    if (want) {
        lv_obj_add_flag(label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(beat, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(img, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_clear_flag(label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(beat, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(img, LV_OBJ_FLAG_HIDDEN);
    }
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

}  // namespace

void dex_create(lv_obj_t *parent) {
    pose = DEX_POSE_IDLE;
    outfit = DEX_OUTFIT_DEFAULT;
    size = DEX_SIZE_FULL;
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
    lv_img_set_antialias(img, false);  // pixel art: nearest-neighbor scaling
#if CHARM_SPRITE_INDEXED_BPP
    lv_img_set_src(img, &expanded);
    lv_img_set_pivot(img, 0, 0);  // after set_src, which recenters the pivot
#endif
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

void dex_set_hidden(bool hidden) {
    if (!box) return;
    if (hidden) lv_obj_add_flag(box, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_clear_flag(box, LV_OBJ_FLAG_HIDDEN);
}

void dex_tick(uint32_t now_ms) {
    if (!box) return;
    if (anim) {
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
        return;
    }
    int f = (int)((now_ms / FRAME_MS) % FRAMES);
    if (f == frame) return;
    frame = f;
    lv_obj_align(beat, LV_ALIGN_BOTTOM_LEFT, (lv_coord_t)(4 + f * 8), -4);
}

dex_pose_t dex_get_pose(void) { return pose; }
dex_outfit_t dex_get_outfit(void) { return outfit; }
dex_size_t dex_get_size(void) { return size; }

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
