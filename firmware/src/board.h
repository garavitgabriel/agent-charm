// Waveshare ESP32-S3-Touch-AMOLED-1.8 V2 pin map. V1 is NOT compatible (different display/touch).
// Source: Waveshare repository commit 7ab8f957e22ea1ab811256359f4eddcaaf49ee91,
// examples/arduino-v2/libraries/Mylibrary/pin_config.h, as used by Margin (docs/hardware.md).
#pragma once
#include <stdint.h>

namespace board {

constexpr int kWidth = 368, kHeight = 448;

// CO5300 AMOLED over QSPI, column offset 16.
constexpr int kLcdCs = 12, kLcdSclk = 11, kLcdD0 = 4, kLcdD1 = 5, kLcdD2 = 6, kLcdD3 = 7;
constexpr int kLcdColOffset = 16;

// Shared I2C bus: touch, expander, codec, IMU, PMU.
constexpr int kI2cSda = 15, kI2cScl = 14;
constexpr uint8_t kTouchAddr = 0x15;     // CST820 (CST816-compatible registers)
constexpr int kTouchIrq = 21;
constexpr uint8_t kExpanderAddr = 0x20;  // XCA9554; output bits 0,1,2,6 reset the peripherals

// ES8311 codec over I2S. "device output" = ESP32 -> codec DAC; "device input" = mic -> ESP32.
constexpr int kI2sMclk = 16, kI2sBclk = 9, kI2sWs = 45, kI2sDout = 8, kI2sDin = 10;
constexpr int kSpeakerPa = 46;           // speaker amplifier enable: HIGH only while playing

constexpr int kBootButton = 0;           // BOOT, active low

}  // namespace board
