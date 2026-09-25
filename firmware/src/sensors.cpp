#include "sensors.h"

#include <Arduino.h>
#include <Wire.h>

#include "SensorQMI8658.hpp"
#define XPOWERS_CHIP_AXP2101
#include "XPowersLib.h"
#include "board.h"

namespace sensors {
namespace {

SensorQMI8658 imu;
XPowersPMU pmu;
Status status;
charm::MotionDetector motion;
uint32_t last_sample = 0;
constexpr uint32_t kSampleMs = 20;

}  // namespace

Status begin() {
    // Same calls as Waveshare's V2 example 11_LVGL_QMI8658_ui, at a lower data rate: motion
    // gestures don't need 1 kHz. Range/ODR/LPF are the library's enums, not raw register values.
    status.imu = imu.begin(Wire, QMI8658_L_SLAVE_ADDRESS, board::kI2cSda, board::kI2cScl);
    if (status.imu) {
        imu.configAccelerometer(SensorQMI8658::ACC_RANGE_4G, SensorQMI8658::ACC_ODR_125Hz, SensorQMI8658::LPF_MODE_0);
        imu.enableAccelerometer();
    }

    // Read-only use of the PMU, following Waveshare's 90_axp2101_pmu diagnostic: turn on battery
    // detection and the battery-voltage ADC so the gauge reads. No regulator or charger changes.
    status.pmu = pmu.begin(Wire, AXP2101_SLAVE_ADDRESS, board::kI2cSda, board::kI2cScl);
    if (status.pmu) {
        pmu.enableBattDetection();
        pmu.enableBattVoltageMeasure();
    }
    return status;
}

charm::Motion poll_motion(uint32_t now) {
    if (!status.imu || now - last_sample < kSampleMs) return charm::Motion::None;
    last_sample = now;
    float x, y, z;
    if (!imu.getDataReady() || !imu.getAccelerometer(x, y, z)) return charm::Motion::None;
    return motion.update(now, x, y, z);
}

int battery_percent() {
    if (!status.pmu) return -1;
    return pmu.getBatteryPercent();  // -1 when no battery is connected
}

}  // namespace sensors
