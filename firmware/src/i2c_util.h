// Register helpers for the shared I2C bus (Wire), as in Margin. Main-loop use only: the audio
// tasks never touch I2C, so the bus needs no lock.
#pragma once
#include <Arduino.h>
#include <Wire.h>

namespace i2c {

inline bool write_reg(uint8_t address, uint8_t reg, uint8_t value) {
    Wire.beginTransmission(address);
    Wire.write(reg);
    Wire.write(value);
    return Wire.endTransmission() == 0;
}

inline bool read_regs(uint8_t address, uint8_t reg, uint8_t *out, size_t size) {
    Wire.beginTransmission(address);
    Wire.write(reg);
    if (Wire.endTransmission(false)) return false;
    if (Wire.requestFrom(address, static_cast<uint8_t>(size)) != size) return false;
    for (size_t i = 0; i < size; ++i) out[i] = Wire.read();
    return true;
}

}  // namespace i2c
