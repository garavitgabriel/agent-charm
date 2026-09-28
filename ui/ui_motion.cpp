#include "ui_motion.h"
#include <math.h>

namespace motion {

int fuse_px(uint32_t elapsed_ms, int span_px) {
    if (elapsed_ms >= FUSE_MS) return span_px;
    const uint32_t q = elapsed_ms / FUSE_STEP_MS * FUSE_STEP_MS;
    return (int)((uint64_t)q * (uint64_t)span_px / FUSE_MS);
}

float BagFill::level(uint32_t now) const {
    const uint32_t t = now - since;
    if (holding) {
        if (t >= hold_ms) return 1.0f;
        const uint32_t step_ms = hold_ms / HOLD_STEPS;
        return (float)(t / step_ms) / (float)HOLD_STEPS;
    }
    if (draining) {
        if (t >= DRAIN_MS) return 0.0f;
        const uint32_t step_ms = DRAIN_MS / DRAIN_STEPS;
        const uint32_t steps_done = (t + step_ms - 1) / step_ms;  // 0 at release, 3 (empty) by 300 ms
        const float left = 1.0f - (float)steps_done / (float)DRAIN_STEPS;
        return left <= 0 ? 0.0f : drain_from * left;
    }
    return 0.0f;
}

Pt stream_point(float t, Pt hand) {
    const Pt p0 = {-6, 322}, c1 = {90, 196}, c2 = {420, 190};
    const float u = 1 - t;
    return {u * u * u * p0.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * hand.x,
            u * u * u * p0.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * hand.y};
}

void VoiceStream::update(uint32_t now, float level) {
    // Retire capsules whose tail reached the hand.
    for (size_t i = 0; i < caps.size();) {
        if (head(caps[i], now) - caps[i].len >= 1.0f) caps.erase(caps.begin() + (long)i);
        else i++;
    }
    if (!active) return;
    while ((int32_t)(now - next_sample) >= 0) {
        const uint32_t at = next_sample;
        next_sample += STREAM_SAMPLE_MS;
        if (level >= STREAM_THRESHOLD) {
            float a = (level - STREAM_THRESHOLD) / (1.0f - STREAM_THRESHOLD);
            if (a > 1) a = 1;
            caps.push_back({at, 0.04f + 0.08f * a, 4.0f + 6.0f * a});
            last_voice = at;
            voice = true;
        } else if (voice && at - last_voice > STREAM_SILENCE_MS) {
            voice = false;  // silence: nothing spawns and the stream drains
        }
    }
}

int snap_scroll(int y, int lead_lh, int lead_lines, int detail_top, int lh, int max_scroll) {
    if (max_scroll <= 0) return 0;
    if (y <= 0) return 0;
    if (y >= max_scroll) return max_scroll;
    int best = 0, best_d = 1 << 30;
    auto consider = [&](int t) {
        if (t < 0 || t > max_scroll) return;
        const int d = t > y ? t - y : y - t;
        if (d < best_d) {
            best_d = d;
            best = t;
        }
    };
    for (int k = 0; k <= lead_lines && k * lead_lh < detail_top; k++) consider(k * lead_lh);
    if (lh > 0 && y >= detail_top - lh) {
        const int k = (int)lroundf((float)(y - detail_top) / (float)lh);
        consider(detail_top + k * lh);
        consider(detail_top + (k - 1) * lh);
        consider(detail_top + (k + 1) * lh);
    }
    consider(detail_top);
    consider(max_scroll);
    return best;
}

bool scroll_thumb(int offset, int total, int view, int x0, int span, int *x, int *len) {
    if (total <= view || view <= 0) return false;
    int l = span * view / total;
    if (l < 24) l = 24;
    const int range = total - view;
    if (offset < 0) offset = 0;
    if (offset > range) offset = range;
    *len = l;
    *x = x0 + (span - l) * offset / range;
    return true;
}

}  // namespace motion
