// CO5300 AMOLED + CST820 touch, wired into LVGL. Ported from Margin (firmware/src/main.cpp).
#pragma once
#include <stdint.h>

namespace display {

// Resets the peripherals through the XCA9554 expander. Needs Wire already started.
bool reset_peripherals();
// Panel, LVGL display driver and touch input. Returns false if the panel or buffers fail.
bool begin();
bool touch_ready();
void set_brightness(uint8_t level);

}  // namespace display
