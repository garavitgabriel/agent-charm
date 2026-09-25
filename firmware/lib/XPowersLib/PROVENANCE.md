# Vendored XPowersLib

Copied without source edits from the Waveshare first-party board repository:
https://github.com/waveshareteam/ESP32-S3-Touch-AMOLED-1.8

Commit: `7ab8f957e22ea1ab811256359f4eddcaaf49ee91`
Directory: `examples/arduino/libraries/XPowersLib` (`src/`, `LICENSE`, `library.properties`)
Upstream: https://github.com/lewisxhe/XPowersLib, version 0.2.6, MIT license (`LICENSE`, kept as is).

Why this chip: at that commit the V2 pin map `examples/arduino-v2/libraries/Mylibrary/pin_config.h`
declares `#define XPOWERS_CHIP_AXP2101`, the repository README's hardware table lists the
**AXP2101 PMU** for the board (both display/touch revisions), and
`examples/esp-idf/90_axp2101_pmu` (which detects the CO5300/V2 variant) initialises it with
`AXP2101_SLAVE_ADDRESS` (0x34, `src/REG/AXP2101Constants.h`).

The V2 Arduino example set doesn't bundle XPowersLib (it has no PMU sketch), so the Arduino copy is
taken from the original example set at the same commit. It's the Arduino build of the same library
the ESP-IDF PMU diagnostic carries as a component.

The firmware uses it read-only: `begin()`, battery detection and the battery-voltage ADC enable
(as in the Waveshare diagnostic), then `getBatteryPercent()`. It changes no regulator or charger
settings.
