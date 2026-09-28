// Motion from docs/design/final/motion.md (+ reading.md), as pure logic: no LVGL objects, so the
// sim tests can drive it with a fake clock. charm_ui.cpp draws what these models say.
#pragma once
#include <stdint.h>
#include <vector>

namespace motion {

constexpr uint32_t TICK_MS = 40;         // 25 fps
constexpr uint32_t ENTER_MS = 180;       // content line: fade 0 -> 100 %, rise 8 -> 0 px, ease-out
constexpr uint32_t ENTER_RISE_PX = 8;
constexpr uint32_t STAGGER_MS = 40;      // between lines, top to bottom
constexpr uint32_t RAIL_ENTER_MS = 120;  // rail actions enter last, fade only
constexpr uint32_t EXIT_MS = 120;        // all content fades out, ease-in, no movement
constexpr uint32_t TAP_MS = 80;          // tap feedback: 70 % for 80 ms, then the exit
constexpr uint8_t TAP_OPA = 179;         // 70 %
constexpr uint32_t WORKING_DOT_MS = 400; // "…" steps 1 / 2 / 3 dots

// Delay before content line `i` (0-based) starts entering, when the previous content exits first.
inline uint32_t enter_delay(int i, bool after_exit) { return (after_exit ? EXIT_MS : 0) + STAGGER_MS * (uint32_t)i; }

// ---------------------------------------------------------------- listening fuse
// The separator's accent segment grows left -> right over the listen limit (the contract's 25 s,
// not the render's 30 s), redrawn every 250 ms, with no numerals.
constexpr uint32_t FUSE_MS = 25000;
constexpr uint32_t FUSE_STEP_MS = 250;
constexpr uint32_t FUSE_FADE_MS = 200;
// Accent length in px (0..span) after `elapsed` ms, quantized to the 250 ms redraw.
int fuse_px(uint32_t elapsed_ms, int span_px);

// ---------------------------------------------------------------- money hold
constexpr uint32_t HOLD_MS = 2000;
constexpr int HOLD_STEPS = 20;           // 100 ms each
constexpr uint32_t DRAIN_MS = 300;       // early release drains in 3 linear steps
constexpr int DRAIN_STEPS = 3;
constexpr uint32_t FULL_HOLD_MS = 120;   // full frame held before the hand-off

// The bag fill shown on screen: linear 0 -> 1 over hold_ms in 20 steps while held, and a 3-step
// drain after an early release. It only draws; HoldTracker (ui_hold.h) decides what gets sent.
struct BagFill {
    bool holding = false;
    uint32_t hold_ms = HOLD_MS;
    uint32_t since = 0;       // press time, or drain start
    float drain_from = 0;     // fill at release
    bool draining = false;

    void press(uint32_t now, uint32_t hold) {
        holding = true;
        draining = false;
        hold_ms = hold ? hold : HOLD_MS;
        since = now;
    }
    // Early release (or abandoned hold): drain from wherever the fill stood.
    void release(uint32_t now) {
        if (!holding) return;
        drain_from = level(now);
        holding = false;
        draining = drain_from > 0;
        since = now;
    }
    void clear() { holding = draining = false; drain_from = 0; }
    float level(uint32_t now) const;  // stepped 0..1 as drawn
};

// ---------------------------------------------------------------- voice stream (Listening)
struct Pt {
    float x, y;
};
// Cubic Bézier (−6, 322) → (90, 196) → (420, 190) → hand: edge to the cupped hand, over his head.
Pt stream_point(float t, Pt hand);

constexpr uint32_t STREAM_TRANSIT_MS = 900;  // edge to hand
constexpr uint32_t STREAM_SAMPLE_MS = 80;    // mic amplitude sampled this often
constexpr uint32_t STREAM_FIRST_MS = 120;    // first capsule leaves 120 ms after the press
constexpr uint32_t STREAM_SILENCE_MS = 1200; // then the stream drains
constexpr float STREAM_THRESHOLD = 0.08f;

struct Capsule {
    uint32_t born;   // ms
    float len;       // fraction of the path, 0.04 .. 0.12
    float width;     // px at the edge, 4 .. 10
};

struct VoiceStream {
    std::vector<Capsule> caps;
    bool active = false;       // spawning allowed (mic capturing)
    uint32_t start = 0;        // button down
    uint32_t next_sample = 0;
    uint32_t last_voice = 0;   // last above-threshold sample
    bool voice = false;        // voice present (not yet 1.2 s of silence)

    void begin(uint32_t now) {
        caps.clear();
        active = true;
        start = now;
        next_sample = now + STREAM_FIRST_MS;
        voice = false;
    }
    // Release: no new capsules; the ones in flight finish their transit.
    void end() { active = false; voice = false; }
    // Advance to `now` with the latest mic level; spawns and retires capsules.
    void update(uint32_t now, float level);
    // Head position (0..1 along the path) of a capsule at `now`.
    static float head(const Capsule &c, uint32_t now) {
        return (float)(now - c.born) / (float)STREAM_TRANSIT_MS;
    }
    bool empty() const { return caps.empty(); }
};

// ---------------------------------------------------------------- reading scroll column
// Snap targets: the lead's lines (lead_lh apart, while inside the lead) and the detail's line grid
// (detail_top + k * lh). Returns the nearest target to `y`, clamped to [0, max_scroll].
int snap_scroll(int y, int lead_lh, int lead_lines, int detail_top, int lh, int max_scroll);
// The separator thumb: len = max(24, span * view / total), x = x0 + (span - len) * off / (total - view).
// Returns false (no thumb) when the column fits.
bool scroll_thumb(int offset, int total, int view, int x0, int span, int *x, int *len);

}  // namespace motion
