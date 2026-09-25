// Debounced hold-to-talk button. A press counts once the raw level has been stable for debounce_ms;
// so does a release. Released is only reported after a reported Pressed, so the pair always matches.
#pragma once
#include <stdint.h>

namespace charm {

enum class ButtonEvent { None, Pressed, Released };

class HoldButton {
public:
    explicit HoldButton(uint32_t debounce_ms = 30) : debounce_(debounce_ms) {}

    // Feed the raw level (true = physically down) every loop. Returns at most one event.
    ButtonEvent update(uint32_t now_ms, bool raw_down) {
        if (!started_) {
            started_ = true;
            raw_ = raw_down;
            raw_since_ = now_ms;
            // A button already down at boot is ignored until it's released: no phantom talk.
            ignore_until_up_ = raw_down;
            return ButtonEvent::None;
        }
        if (raw_down != raw_) {
            raw_ = raw_down;
            raw_since_ = now_ms;
        }
        if (raw_ == stable_ || now_ms - raw_since_ < debounce_) return ButtonEvent::None;
        stable_ = raw_;
        if (ignore_until_up_) {
            if (!stable_) ignore_until_up_ = false;
            return ButtonEvent::None;
        }
        if (stable_) {
            pressed_at_ = raw_since_;
            return ButtonEvent::Pressed;
        }
        last_hold_ms_ = raw_since_ - pressed_at_;
        return ButtonEvent::Released;
    }

    bool held() const { return stable_ && !ignore_until_up_; }
    // Duration of the last completed hold, measured between the debounced edges.
    uint32_t last_hold_ms() const { return last_hold_ms_; }

private:
    uint32_t debounce_;
    bool started_ = false, raw_ = false, stable_ = false, ignore_until_up_ = false;
    uint32_t raw_since_ = 0, pressed_at_ = 0, last_hold_ms_ = 0;
};

}  // namespace charm
