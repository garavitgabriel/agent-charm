// Microphone-side helpers: channel extraction, the level meter and the 25 s talk limit.
#pragma once
#include <math.h>
#include <stddef.h>
#include <stdint.h>

namespace charm {

// The ES8311 microphone arrives on the left slot of 16 kHz stereo I2S (as in Margin).
// Copies the left channel of `frames` interleaved stereo frames into mono. In-place is allowed.
inline void stereo_left_to_mono(const int16_t *stereo, size_t frames, int16_t *mono) {
    for (size_t i = 0; i < frames; ++i) mono[i] = stereo[i * 2];
}

// Mic level 0..1 for charm_ui_mic_level: RMS in dBFS mapped linearly from -60 dB (0) to 0 dB (1).
inline float pcm_level(const int16_t *samples, size_t n) {
    if (!n) return 0.0f;
    double sum = 0;
    for (size_t i = 0; i < n; ++i) sum += static_cast<double>(samples[i]) * samples[i];
    double rms = sqrt(sum / n);
    if (rms < 1.0) return 0.0f;
    double db = 20.0 * log10(rms / 32768.0);
    double level = (db + 60.0) / 60.0;
    if (level < 0) level = 0;
    if (level > 1) level = 1;
    return static_cast<float>(level);
}

// One hold-to-talk capture. The host ends it with reason "limit" once expired() is true.
class TalkSession {
public:
    static constexpr uint32_t kLimitMs = 25000;

    void begin(uint32_t now_ms) {
        active_ = true;
        started_ = now_ms;
        bytes_ = 0;
    }
    void end() { active_ = false; }
    void add_bytes(size_t n) { bytes_ += n; }

    bool active() const { return active_; }
    bool expired(uint32_t now_ms) const {
        // Time-based, with the audio actually captured as a second bound (25 s of s16 mono).
        return active_ && (now_ms - started_ >= kLimitMs || bytes_ >= kLimitMs / 1000 * 16000 * 2);
    }
    uint32_t elapsed_ms(uint32_t now_ms) const { return active_ ? now_ms - started_ : 0; }
    size_t bytes() const { return bytes_; }

private:
    bool active_ = false;
    uint32_t started_ = 0;
    size_t bytes_ = 0;
};

// App-level keepalive: a {"type":"ping"} every 10 s; the link is dead after 30 s without a pong.
class Keepalive {
public:
    explicit Keepalive(uint32_t interval_ms = 10000, uint32_t timeout_ms = 30000)
        : interval_(interval_ms), timeout_(timeout_ms) {}

    void reset(uint32_t now_ms) {
        last_ping_ = now_ms;
        last_pong_ = now_ms;
    }
    // True when a ping should go out now; marks it sent.
    bool ping_due(uint32_t now_ms) {
        if (now_ms - last_ping_ < interval_) return false;
        last_ping_ = now_ms;
        return true;
    }
    void on_pong(uint32_t now_ms) { last_pong_ = now_ms; }
    bool dead(uint32_t now_ms) const { return now_ms - last_pong_ >= timeout_; }

private:
    uint32_t interval_, timeout_;
    uint32_t last_ping_ = 0, last_pong_ = 0;
};

}  // namespace charm
