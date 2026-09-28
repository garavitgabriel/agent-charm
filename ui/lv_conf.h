// Shared LVGL 8.3 config for firmware/ and sim/. Seeded from Margin (firmware/src/lv_conf.h).
// Owner: UI/simulator batch. Firmware includes it via -I ../ui and must not edit it.
#ifndef LV_CONF_H
#define LV_CONF_H
#include <stdint.h>
#define LV_COLOR_DEPTH 16
#define LV_COLOR_16_SWAP 0
#define LV_MEM_SIZE (96U * 1024U)
#define LV_DISP_DEF_REFR_PERIOD 25
#define LV_INDEV_DEF_READ_PERIOD 15
#define LV_DPI_DEF 160
// The UI sets Instrument Sans (charm_assets_fonts) on every label. Montserrat 14 stays only as
// LVGL's required default (dex_sprite's placeholder label); no other built-in font is compiled.
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_DEFAULT &lv_font_montserrat_14
#define LV_USE_SPAN 1  // reading detail: 600 lead-ins inside 400 paragraphs
#define LV_USE_LOG 0
#define LV_USE_PERF_MONITOR 0
#define LV_USE_MEM_MONITOR 0
#define LV_BUILD_EXAMPLES 0
#define LV_USE_DEMO_WIDGETS 0
#define LV_USE_DEMO_MUSIC 0
#endif
