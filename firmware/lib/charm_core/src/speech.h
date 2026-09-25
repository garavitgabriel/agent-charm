// Speech playback state: speech_start -> binary PCM frames -> speech_end, played from a ring buffer.
//
// The network side (main loop) calls start/feed/end/stop. The speaker task calls pull(), which hands
// back stereo frames for I2S (the mono stream duplicated to both channels) and says whether the
// speaker amplifier (PA) may be on. The PA is on only while the state is Playing or Draining:
// never while idle, and never while pre-buffering the first few frames.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <atomic>
#include <mutex>
#include "ring_buffer.h"

namespace charm {

class SpeechPlayer {
public:
    enum class State : uint8_t { Idle, Buffering, Playing, Draining };

    // prebuffer_bytes: how much mono PCM to hold before starting (default 100 ms at 16 kHz s16).
    void init(uint8_t *storage, size_t capacity, size_t prebuffer_bytes = 3200) {
        std::lock_guard<std::mutex> lock(m_);
        ring_.init(storage, capacity);
        prebuffer_ = prebuffer_bytes;
        state_ = State::Idle;
    }

    // speech_start: drop anything left over and wait for frames.
    void start() {
        std::lock_guard<std::mutex> lock(m_);
        ring_.clear();
        dropped_ = 0;
        state_ = ring_.capacity() ? State::Buffering : State::Idle;
    }

    // One binary frame. Ignored unless a speech is active (late frames after stop are dropped).
    // Returns the bytes accepted; anything that didn't fit is counted in dropped().
    size_t feed(const uint8_t *data, size_t len) {
        std::lock_guard<std::mutex> lock(m_);
        State s = state_;
        if (s != State::Buffering && s != State::Playing) return 0;
        size_t n = ring_.write(data, len);
        dropped_ += len - n;
        if (s == State::Buffering && (ring_.size() >= prebuffer_ || ring_.free_space() == 0))
            state_ = State::Playing;
        return n;
    }

    // speech_end: play out what's buffered, then go idle.
    void end() {
        std::lock_guard<std::mutex> lock(m_);
        State s = state_;
        if (s == State::Buffering || s == State::Playing)
            state_ = ring_.empty() ? State::Idle : State::Draining;
    }

    // Immediate stop (user interrupt, cancel, disconnect). The next pull() returns nothing.
    void stop() {
        std::lock_guard<std::mutex> lock(m_);
        ring_.clear();
        state_ = State::Idle;
    }

    // Speaker task: fill up to max_frames stereo frames (2 x s16 each) into out.
    // Returns the frames written. While Playing with an empty ring (network underrun) it returns
    // silence so the stream stays continuous; while Idle or Buffering it returns 0.
    size_t pull(int16_t *out, size_t max_frames) {
        std::lock_guard<std::mutex> lock(m_);
        State s = state_;
        if (s != State::Playing && s != State::Draining) return 0;
        size_t want = max_frames * 2;  // mono bytes
        size_t have = ring_.size();
        size_t n = (want < have ? want : have) & ~static_cast<size_t>(1);
        // Decode in place from the back so mono -> stereo expansion doesn't clobber unread samples.
        uint8_t *bytes = reinterpret_cast<uint8_t *>(out);
        ring_.read(bytes, n);
        size_t samples = n / 2;
        for (size_t i = samples; i-- > 0;) {
            int16_t v;
            memcpy(&v, bytes + i * 2, 2);
            out[i * 2] = v;
            out[i * 2 + 1] = v;
        }
        if (s == State::Draining && ring_.size() < 2) {
            ring_.clear();
            state_ = State::Idle;
            return samples;
        }
        if (s == State::Playing && samples < max_frames) {
            memset(out + samples * 2, 0, (max_frames - samples) * 4);
            return max_frames;
        }
        return samples;
    }

    State state() const { return state_; }
    bool active() const { return state_ != State::Idle; }
    bool pa_on() const {
        State s = state_;
        return s == State::Playing || s == State::Draining;
    }
    size_t dropped() const { return dropped_; }

private:
    std::mutex m_;
    ByteRing ring_;
    size_t prebuffer_ = 0;
    std::atomic<State> state_{State::Idle};
    size_t dropped_ = 0;
};

}  // namespace charm
