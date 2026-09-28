# Third-party notices

Dex Charm's own code is MIT (see [`LICENSE`](LICENSE)). It ships with, or fetches at build time,
the components below. Each keeps its own license. Every entry names the file the license was
verified from; "not verified in-repo" means the license was checked only against the package
cache on a build machine or its published metadata, not a file committed here.

## Vendored in this repository

| Component | Version | Where | License | Verified from |
|---|---|---|---|---|
| GFX Library for Arduino (Arduino_GFX), Waveshare's board-repo copy | 1.6.4 (Waveshare commit `7ab8f957`) | `firmware/lib/waveshare-gfx/` | BSD-2-Clause (Adafruit wording) | `firmware/lib/waveshare-gfx/license.txt`, `PROVENANCE.md`, `library.properties` |
| SensorLib (Lewis He) | 0.3.3 | `firmware/lib/SensorLib/` | MIT | `firmware/lib/SensorLib/LICENSE` |
| XPowersLib (Lewis He) | 0.2.6 | `firmware/lib/XPowersLib/` | MIT | `firmware/lib/XPowersLib/LICENSE` |
| ES8311 codec driver (Espressif Systems) | 2015–2022 | `firmware/src/es8311.c`, `es8311.h`, `es8311_reg.h` | Apache-2.0 | SPDX headers in those files; license text in [`licenses/Apache-2.0.txt`](licenses/Apache-2.0.txt) |
| Instrument Sans (Regular, Medium, SemiBold) | — | `ui/assets-src/fonts/*.ttf`, rasterized into `ui/charm_assets_fonts.cpp` | SIL OFL 1.1 | `ui/assets-src/fonts/InstrumentSans-OFL.txt` |
| Atkinson Hyperlegible Regular (Braille Institute) | — | `tools/fonts/AtkinsonHyperlegible-Regular.ttf` (placeholder face for the asset tool; not in the current generated fonts) | SIL OFL 1.1 | `tools/fonts/AtkinsonHyperlegible-OFL.txt` |
| Font Awesome 5 Free subset (`lvgl-symbols.ttf`, 60 `LV_SYMBOL_*` glyphs, from LVGL 8.3.11's bundled woff) | 5 | `tools/fonts/lvgl-symbols.ttf`, rasterized into `ui/charm_assets_fonts.cpp` | SIL OFL 1.1 (font) | `tools/fonts/lvgl-symbols-OFL.txt` (provenance + license) |
| ISRG Root X1 and X2 (Let's Encrypt root certificates) | X1 to 2035, X2 to 2040 | `firmware/src/ca_roots.h` | Public root certificates, redistributed as trust anchors; no license terms attach | `firmware/src/ca_roots.h` header comment |
| u8g2 bitmap fonts bundled inside Arduino_GFX (Unifont, Cubic 11, Galmuri/Quan7 …) | — | `firmware/lib/waveshare-gfx/src/font/` | Per-file: OFL 1.1, or Unifont's dual "OFL 1.1 and GPLv2+ with the GNU Font Embedding Exception" | Header comments in each font file. Not referenced by the charm firmware |

## Fetched at build time (not committed)

| Component | Version | Used by | License | Verified from |
|---|---|---|---|---|
| LVGL | 8.3.11 | firmware (`lvgl/lvgl@8.3.11`), sim (`FetchContent`, SHA256-pinned) | MIT | `firmware/platformio.ini`, `sim/CMakeLists.txt`; license from the fetched `LICENCE.txt` (not verified in-repo) |
| ArduinoJson (Benoît Blanchon) | 7.4.2 | firmware, sim, firmware native tests | MIT | same; fetched `LICENSE.txt` (not verified in-repo) |
| arduinoWebSockets (links2004) | 2.7.3 | firmware | **LGPL-2.1** | `firmware/platformio.ini`; fetched `LICENSE` (not verified in-repo) |
| IXWebSocket (Machine Zone) | 11.4.6 | sim live mode | BSD-3-Clause | `sim/CMakeLists.txt`; fetched `LICENSE.txt` (not verified in-repo) |
| Arduino core for ESP32 (pioarduino platform 55.03.311, Arduino-ESP32 3.3.11) + ESP-IDF libs | 3.3.11 | firmware | **LGPL-2.1-or-later** (core); ESP-IDF components mostly Apache-2.0 | `firmware/platformio.ini`; license from the framework's `package.json` (not verified in-repo) |
| SDL2 (via Homebrew `sdl2-compat`) | system | sim | zlib | not verified in-repo |

## Python dependencies (installed by `uv`, not redistributed)

Pinned in each package's `pyproject.toml` / `uv.lock`. The main runtime ones:

| Package | License (from installed package metadata; not verified in-repo) |
|---|---|
| faster-whisper 1.2.1 (+ CTranslate2) | MIT |
| edge-tts 7.2.8 | LGPL-3.0 (it also calls Microsoft's online Edge TTS service, which has its own terms) |
| websockets 17.1 | BSD-3-Clause |
| httpx 0.28.1 | BSD-3-Clause |
| jsonschema | MIT |
| Pillow, lz4, resvg-py (asset tools) | see each package |

The Whisper model weights are downloaded at first run by faster-whisper and are not part of this
repository.

## Notes for redistributors

- **Firmware binaries** link arduinoWebSockets and the Arduino-ESP32 core, both LGPL. If you ship a
  prebuilt `.bin`, ship the LGPL texts and let recipients relink (this repo's source + PlatformIO
  build satisfies that). Source-only distribution of this repo is unaffected.
- **Fonts** keep their OFL license files next to them; the rasterized LVGL fonts in
  `ui/charm_assets_fonts.cpp` are derived works under the same OFL (Reserved Font Names do not
  apply: the generated C arrays are not distributed under the original font names as fonts).
- The design HTML under `docs/design/` loads web fonts from Google Fonts at view time; none are
  committed.
- Code ported from Margin (the author's earlier reading-companion project) is the author's own
  work and is covered by this repository's MIT license. The pin map and bring-up sequences follow
  Waveshare's public ESP32-S3-Touch-AMOLED-1.8 examples.
