// Reconnect backoff: 1 s, 2 s, 4 s, 8 s, 16 s, then 30 s forever, until reset() on a good connection.
// No jitter: v0 is one device talking to one server, so there's no herd to spread out.
#pragma once
#include <stdint.h>

namespace charm {

class Backoff {
public:
    explicit Backoff(uint32_t base_ms = 1000, uint32_t cap_ms = 30000) : base_(base_ms), cap_(cap_ms) {}

    // Delay to wait before the next attempt. Each call advances the schedule.
    uint32_t next() {
        uint32_t delay = base_;
        for (uint32_t i = 0; i < attempts_ && delay < cap_; ++i) delay *= 2;
        if (delay > cap_) delay = cap_;
        if (attempts_ < UINT32_MAX) ++attempts_;
        return delay;
    }

    void reset() { attempts_ = 0; }
    uint32_t attempts() const { return attempts_; }

private:
    uint32_t base_, cap_;
    uint32_t attempts_ = 0;
};

}  // namespace charm
