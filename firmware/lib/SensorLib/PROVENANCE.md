# Vendored SensorLib (QMI8658 subset)

Copied without source edits from the Waveshare first-party board repository:
https://github.com/waveshareteam/ESP32-S3-Touch-AMOLED-1.8

Commit: `7ab8f957e22ea1ab811256359f4eddcaaf49ee91`
Directory: `examples/arduino-v2/libraries/SensorLib` (the V2 example set's bundled copy)
Upstream: https://github.com/lewisxhe/SensorsLib, version 0.3.3 (`library.properties`), MIT license
(`LICENSE`, kept as is).

Why this chip: Waveshare's V2 example `examples/arduino-v2/examples/11_LVGL_QMI8658_ui` drives the
board's IMU with `SensorQMI8658` at `QMI8658_L_SLAVE_ADDRESS` (0x6B, `src/REG/QMI8658Constants.h`)
on the shared I2C bus (SDA 15, SCL 14).

Included: only what `SensorQMI8658.hpp` needs: `SensorQMI8658.hpp`, `SensorPlatform.hpp`,
`SensorLib.h`, `SensorLib_Version.h`, `DevicesPins.h`, `REG/QMI8658Constants.h`, `platform/`,
plus `LICENSE` and `library.properties`. The other drivers, the Bosch firmware blobs (~20 MB),
datasheets and examples are omitted.
