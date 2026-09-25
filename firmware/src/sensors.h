// QMI8658 IMU and AXP2101 PMU, polled from the UI loop (they share the I2C bus with touch).
//
// Both chips were identified from Waveshare's sources at commit 7ab8f957…:
//   - IMU: examples/arduino-v2/examples/11_LVGL_QMI8658_ui (SensorQMI8658 at QMI8658_L_SLAVE_ADDRESS)
//   - PMU: examples/arduino-v2/libraries/Mylibrary/pin_config.h (#define XPOWERS_CHIP_AXP2101), the
//     repository README's hardware table, and examples/esp-idf/90_axp2101_pmu (AXP2101_SLAVE_ADDRESS)
// Register access goes through those vendored libraries (lib/SensorLib, lib/XPowersLib); this
// firmware writes no IMU or PMU registers of its own and changes no charger settings.
#pragma once
#include <stdint.h>

#include "motion.h"

namespace sensors {

struct Status {
    bool imu = false;
    bool pmu = false;
};

Status begin();

// Poll the IMU (~50 Hz). Returns a motion event, or Motion::None.
charm::Motion poll_motion(uint32_t now_ms);

// Battery percent 0..100, or -1 when unknown (no PMU, no battery, or no reading yet).
int battery_percent();

}  // namespace sensors
