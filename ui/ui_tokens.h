// Design tokens from docs/design/final/tokens.md (+ reading/reading.md). The one place the UI's
// colours, type, zones and Dex geometry live. Values are the design's exact constants (build.py).
#pragma once
#include <stdint.h>
#include <lvgl.h>
#include "charm_assets_fonts.h"

namespace tok {

// ---- palette (hex) -------------------------------------------------------------------------
constexpr uint32_t BG = 0x000000;
constexpr uint32_t FG = 0xF2EFE9;      // primary text
constexpr uint32_t FG2 = 0xD6D3CC;     // secondary text (>= #BDBDBD)
constexpr uint32_t ON_ACC = 0x0B0A12;  // text on an accent fill
constexpr uint32_t LINE = 0x3B3A40;    // separator, upcoming tracker stop
constexpr uint32_t FLOOR = 0x141316;   // Dex's ground shadow
constexpr uint32_t LINE_N = 0x1C1B20;  // separator, night
constexpr uint32_t FLOOR_N = 0x0A0A0C;
constexpr uint32_t ACC = 0xF2C14E;     // the one accent: "you can act on this"
constexpr uint32_t ACC_D = 0xD19F2B;   // side plane (accent-owned props only)
constexpr uint32_t ACC_L = 0xF9DC94;   // highlight (accent-owned props only)
constexpr uint32_t ACC_N = 0x5E4A1C;   // the accent at night (reserved)
constexpr uint32_t INK = 0x1B1412;     // the character outline ink (bag fill edge)

// ---- type: Instrument Sans at the fixed sizes ------------------------------------------------
// System scale 18/24/32/40 (<= 3 per screen; 40 = the money total only).
inline const lv_font_t *f18r() { return &charm_font_i400_18; }  // secondary, FG2
inline const lv_font_t *f18m() { return &charm_font_i500_18; }  // merchant name, reading lead
inline const lv_font_t *f24m() { return &charm_font_i500_24; }  // rows, status lines
inline const lv_font_t *f24s() { return &charm_font_i600_24; }  // actions
inline const lv_font_t *f32m() { return &charm_font_i500_32; }  // headline
inline const lv_font_t *f32s() { return &charm_font_i600_32; }  // "Hold Dex to order", "Ordering…"
inline const lv_font_t *f40m() { return &charm_font_i500_40; }  // the money total

constexpr lv_coord_t LH18 = 21, LH24 = 28, LH32 = 38, LH40 = 47;  // round(size * 1.18)
constexpr lv_coord_t LH_ACTION = 28;
constexpr lv_coord_t LH_HOLD = 36;  // the money hold label's 32 px line height

// Reading detail scale (reading.md; detail view only): 18/22/26 at ~1.45, whole-line viewports.
struct ReadStep {
    const lv_font_t *text;   // 400, FG2
    const lv_font_t *leadin; // 600, FG (paragraph lead-ins)
    lv_coord_t lh;           // line height
    int lines;               // lines visible at rest
};
inline ReadStep read_step(int step) {  // 0 = S (18), 1 = M (22, default), 2 = L (26)
    switch (step) {
        case 0: return {&charm_font_i400_18, &charm_font_i600_18, 26, 6};
        case 2: return {&charm_font_i400_26, &charm_font_i600_26, 38, 4};
        default: return {&charm_font_i400_22, &charm_font_i600_22, 32, 5};
    }
}

// ---- spacing and zones ---------------------------------------------------------------------
constexpr lv_coord_t PAD = 24;                     // outer gutter; text blocks start at y = 24
constexpr lv_coord_t CONTENT_X = 24, CONTENT_Y = 24, CONTENT_W = 320, CONTENT_H = 166;
constexpr lv_coord_t CONTENT_BOTTOM = 190;         // nothing below this in the content zone
constexpr lv_coord_t SEP_Y = 206, SEP_X0 = 24, SEP_X1 = 344, SEP_W = 3;
constexpr lv_coord_t ANCHOR_Y = 209;               // anchor zone (0, 209, 368, 239)
constexpr lv_coord_t RAIL_X = 24, RAIL_W = 140, RAIL_MAX_W = 172;
constexpr lv_coord_t TOUCH = 56;                   // minimum touch target
constexpr lv_coord_t PILL_H = 56, PILL_R = 28;

// ---- Dex geometry (identical on every screen) ----------------------------------------------
constexpr lv_coord_t DEX_HIP_X = 236, DEX_HIP_Y = 379;
// The ground shadow (FLOOR / FLOOR_N) is baked into Dex's frames (cell 192x224, chief ruling).

// Overlay fallbacks, measured from the reference PNGs, for when dex_get_point_area() returns false.
constexpr lv_area_t BAG_PREVIEW = {205, 332, 267, 403};  // 06: the bag at his chest (the hold target)
constexpr lv_area_t BAG_LIFT = {272, 227, 333, 305};     // 07: the bag overhead, filling
constexpr lv_area_t HAND_CUP = {296, 296, 316, 316};     // 02: the cupped hand the stream lands in
constexpr lv_coord_t PLACARD_CX = 307, PLACARD_CY = 261; // 05: the "Yes" placard's face

}  // namespace tok
