// Hold-to-confirm (contract, not placeholder). A continuous press of at least hold_ms fires exactly
// once and reports how long it was held. Releasing early cancels and fires nothing.
#pragma once
#include <stdint.h>

struct HoldTracker {
    uint32_t hold_ms = 0;
    bool active = false;  // finger down, counting
    bool fired = false;   // completed once; a tracker never fires twice
    uint32_t start_ms = 0;

    void reset(uint32_t hold) {
        hold_ms = hold;
        active = false;
        fired = false;
        start_ms = 0;
    }
    void press(uint32_t now_ms) {
        if (fired) return;
        active = true;
        start_ms = now_ms;
    }
    // Returns true (and sets *held_ms) only when this release completes the hold.
    bool release(uint32_t now_ms, uint32_t *held_ms) {
        if (!active) return false;
        active = false;
        const uint32_t held = now_ms - start_ms;
        if (held < hold_ms) return false;  // early release: cancel, send nothing
        fired = true;
        *held_ms = held;
        return true;
    }
    // Called every tick while pressed. Returns true once, the moment the hold completes.
    bool update(uint32_t now_ms, uint32_t *held_ms) {
        if (!active || fired) return false;
        const uint32_t held = now_ms - start_ms;
        if (held < hold_ms) return false;
        active = false;
        fired = true;
        *held_ms = held;
        return true;
    }
    // Abandon an in-progress hold (e.g. the finger slid off the button).
    void cancel() { active = false; }
    float progress(uint32_t now_ms) const {
        if (fired) return 1.0f;
        if (!active || hold_ms == 0) return 0.0f;
        const float p = (float)(now_ms - start_ms) / (float)hold_ms;
        return p > 1.0f ? 1.0f : p;
    }
};
