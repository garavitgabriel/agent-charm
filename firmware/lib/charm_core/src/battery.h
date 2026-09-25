// When to send event{name:"battery", value:<percent>}: on the first reading after (re)connecting,
// when the percentage moves by min_delta or more (at most once per min_interval), and as a
// heartbeat every heartbeat_ms. An unknown reading (< 0, no battery or no gauge) is never sent:
// the device doesn't invent a battery level.
#pragma once
#include <stdint.h>

namespace charm {

class BatteryReporter {
public:
    BatteryReporter(int min_delta = 2, uint32_t min_interval_ms = 60000, uint32_t heartbeat_ms = 600000)
        : delta_(min_delta), interval_(min_interval_ms), heartbeat_(heartbeat_ms) {}

    // Forget what was sent (call when the socket reconnects so the server hears the level again).
    void reset() { sent_ = false; }

    // True when `percent` should be sent now; marks it sent.
    bool should_send(uint32_t now_ms, int percent) {
        if (percent < 0 || percent > 100) return false;
        bool send = !sent_;
        if (sent_) {
            int moved = percent > last_ ? percent - last_ : last_ - percent;
            uint32_t since = now_ms - last_at_;
            send = (moved >= delta_ && since >= interval_) || since >= heartbeat_;
        }
        if (send) {
            sent_ = true;
            last_ = percent;
            last_at_ = now_ms;
        }
        return send;
    }

private:
    int delta_;
    uint32_t interval_, heartbeat_;
    bool sent_ = false;
    int last_ = 0;
    uint32_t last_at_ = 0;
};

}  // namespace charm
