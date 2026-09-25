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
#define LV_FONT_MONTSERRAT_12 1
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_MONTSERRAT_16 1
#define LV_FONT_MONTSERRAT_18 1
#define LV_FONT_MONTSERRAT_20 1
#define LV_FONT_MONTSERRAT_24 1
#define LV_FONT_MONTSERRAT_28 1
#define LV_FONT_MONTSERRAT_32 1
#define LV_FONT_DEFAULT &lv_font_montserrat_16
#define LV_USE_LOG 0
#define LV_USE_PERF_MONITOR 0
#define LV_USE_MEM_MONITOR 0
#define LV_BUILD_EXAMPLES 0
#define LV_USE_DEMO_WIDGETS 0
#define LV_USE_DEMO_MUSIC 0
#endif
