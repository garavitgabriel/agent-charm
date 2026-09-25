# Vendored Waveshare GFX build

Copied without source edits from the Waveshare first-party board repository:
https://github.com/waveshareteam/ESP32-S3-Touch-AMOLED-1.8

Commit: `7ab8f957e22ea1ab811256359f4eddcaaf49ee91`
Directory: `examples/arduino-v2/libraries/GFX_Library_for_Arduino`
Included: `src/`, `library.properties`, `license.txt`. Example sketches omitted.

Although both report version 1.6.4, this vendor copy contains Arduino-ESP32 3.3.11
SPI clock compatibility fixes absent from the registry's 1.6.4 package. The CO5300
driver is the same. Keep the library's original notices and license.

Copied into Dex Charm (firmware/lib/waveshare-gfx) unchanged from Margin
(`margin`, commit `1b49136`, `firmware/lib/waveshare-gfx`), which vendored it from the
Waveshare commit above.
