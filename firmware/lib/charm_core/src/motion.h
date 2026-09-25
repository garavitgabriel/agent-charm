// Accelerometer (in g) -> the protocol's motion events: face_down, face_up, pickup, shake.
//
// The thresholds are starting points to tune on the device (firmware/HARDWARE-TEST.md). So is the
// sign of Z when the screen faces up: it depends on how the IMU sits on the board, so it's a
// config value (face_up_z_sign), confirmed by the hardware checklist rather than assumed.
#pragma once
#include <math.h>
#include <stdint.h>

namespace charm {

enum class Motion { None, FaceDown, FaceUp, Pickup, Shake };

inline const char *motion_name(Motion m) {
    switch (m) {
    case Motion::FaceDown: return "face_down";
    case Motion::FaceUp: return "face_up";
    case Motion::Pickup: return "pickup";
    case Motion::Shake: return "shake";
    default: return nullptr;
    }
}

struct MotionConfig {
    float face_up_z_sign = 1.0f;     // +1: Z reads +1 g with the screen up. Verify on hardware.
    float flat_z_g = 0.8f;           // |z| above this counts as lying flat
    uint32_t orient_hold_ms = 600;   // orientation must hold this long before it's reported
    float still_band_g = 0.06f;      // | |a| - 1 g | within this is "still"
    uint32_t rest_ms = 2000;         // still this long = resting (arms pickup)
    float pickup_g = 0.20f;          // deviation that ends a rest as a pickup
    float shake_g = 0.9f;            // deviation that counts as a shake peak
    uint8_t shake_peaks = 3;         // peaks needed within the window
    uint32_t shake_window_ms = 900;
    uint32_t shake_cooldown_ms = 1500;
};

class MotionDetector {
public:
    explicit MotionDetector(const MotionConfig &cfg = MotionConfig()) : c_(cfg) {}

    // Feed one sample (~50 Hz). Returns at most one event; shake wins over pickup over orientation.
    Motion update(uint32_t now, float x, float y, float z) {
        float dev = fabsf(sqrtf(x * x + y * y + z * z) - 1.0f);
        Motion shake = update_shake(now, dev);
        Motion pickup = update_pickup(now, dev);
        Motion orient = update_orientation(now, z * c_.face_up_z_sign, dev);
        if (shake != Motion::None) return shake;
        if (pickup != Motion::None) return pickup;
        return orient;
    }

private:
    enum class Orient : uint8_t { Unknown, Up, Down, Other };

    Motion update_shake(uint32_t now, float dev) {
        bool above = dev > c_.shake_g;
        bool edge = above && !shake_above_;
        shake_above_ = above;
        if (!edge) return Motion::None;
        if (peaks_ == 0 || now - first_peak_ > c_.shake_window_ms) {
            peaks_ = 0;
            first_peak_ = now;
        }
        if (++peaks_ < c_.shake_peaks) return Motion::None;
        peaks_ = 0;
        if (shaken_ && now - last_shake_ < c_.shake_cooldown_ms) return Motion::None;
        shaken_ = true;
        last_shake_ = now;
        return Motion::Shake;
    }

    Motion update_pickup(uint32_t now, float dev) {
        if (dev <= c_.still_band_g) {
            if (!still_) {
                still_ = true;
                still_since_ = now;
            }
            if (now - still_since_ >= c_.rest_ms) resting_ = true;
            return Motion::None;
        }
        still_ = false;
        if (resting_ && dev > c_.pickup_g) {
            resting_ = false;
            return Motion::Pickup;
        }
        return Motion::None;
    }

    Motion update_orientation(uint32_t now, float up_z, float dev) {
        Orient o = Orient::Other;
        if (dev < 0.3f) {  // ignore orientation while the device is being thrown around
            if (up_z > c_.flat_z_g) o = Orient::Up;
            else if (up_z < -c_.flat_z_g) o = Orient::Down;
        }
        if (o != candidate_) {
            candidate_ = o;
            candidate_since_ = now;
            return Motion::None;
        }
        if (o == stable_ || now - candidate_since_ < c_.orient_hold_ms) return Motion::None;
        stable_ = o;
        if (o == Orient::Down) {
            last_flat_ = Orient::Down;
            return Motion::FaceDown;
        }
        if (o == Orient::Up) {
            // face_up is reported only when coming back from face down, not at boot.
            bool was_down = last_flat_ == Orient::Down;
            last_flat_ = Orient::Up;
            if (was_down) return Motion::FaceUp;
        }
        return Motion::None;
    }

    MotionConfig c_;
    // shake
    bool shake_above_ = false, shaken_ = false;
    uint8_t peaks_ = 0;
    uint32_t first_peak_ = 0, last_shake_ = 0;
    // pickup
    bool still_ = false, resting_ = false;
    uint32_t still_since_ = 0;
    // orientation
    Orient candidate_ = Orient::Unknown, stable_ = Orient::Unknown, last_flat_ = Orient::Unknown;
    uint32_t candidate_since_ = 0;
};

}  // namespace charm
