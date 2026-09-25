// PLACEHOLDER Dex: a gray box labeled with pose + outfit. The design sprint replaces this file's
// internals with the pixel sprite; the API in dex_sprite.h stays.
#include "dex_sprite.h"
#include <stdio.h>
#include <string.h>

namespace {

constexpr lv_coord_t FULL_W = 168, FULL_H = 224;
constexpr lv_coord_t MINI_W = 76, MINI_H = 76;
constexpr uint32_t FRAME_MS = 250;  // placeholder animation step
constexpr int FRAMES = 4;

const char *const POSE_NAMES[DEX_POSE_COUNT] = {
    "idle", "listening", "working", "attention", "done", "speaking", "asleep", "offline", "error",
};
const char *const OUTFIT_NAMES[DEX_OUTFIT_COUNT] = {
    "default", "gameday", "reading", "food", "code", "cat",
};

lv_obj_t *box;
lv_obj_t *label;
lv_obj_t *beat;  // a small square that steps each frame: proof the animation clock runs
dex_pose_t pose = DEX_POSE_IDLE;
dex_outfit_t outfit = DEX_OUTFIT_DEFAULT;
dex_size_t size = DEX_SIZE_FULL;
int frame = -1;

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

void place() {
    if (!box) return;
    if (size == DEX_SIZE_FULL) {
        lv_obj_set_size(box, FULL_W, FULL_H);
        lv_obj_align(box, LV_ALIGN_TOP_MID, 0, 92);
    } else {
        lv_obj_set_size(box, MINI_W, MINI_H);
        lv_obj_align(box, LV_ALIGN_TOP_RIGHT, -8, 6);
    }
    relabel();
}

}  // namespace

void dex_create(lv_obj_t *parent) {
    pose = DEX_POSE_IDLE;
    outfit = DEX_OUTFIT_DEFAULT;
    size = DEX_SIZE_FULL;
    frame = -1;
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
    place();
}

void dex_set_pose(dex_pose_t p) {
    if (p >= DEX_POSE_COUNT || p == pose) return;
    pose = p;
    relabel();
}

void dex_set_outfit(dex_outfit_t o) {
    if (o >= DEX_OUTFIT_COUNT || o == outfit) return;
    outfit = o;
    relabel();
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
    if (!beat) return;
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
