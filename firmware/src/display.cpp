// Display, touch and expander bring-up. Ported from Margin (margin, firmware/src/main.cpp,
// commit 1b49136), which is verified on this board. The Arduino_GFX CO5300 driver is the vendored
// Waveshare copy in lib/waveshare-gfx (see its PROVENANCE.md).
#include "display.h"

#include <Arduino.h>
#include <Arduino_GFX_Library.h>
#include <Wire.h>
#include <esp_heap_caps.h>
#include <lvgl.h>

#include "board.h"
#include "i2c_util.h"

namespace display {
namespace {

using namespace board;

Arduino_ESP32QSPI bus(kLcdCs, kLcdSclk, kLcdD0, kLcdD1, kLcdD2, kLcdD3);
Arduino_CO5300 panel(&bus, GFX_NOT_DEFINED, 0, kWidth, kHeight, kLcdColOffset, 0, 0, 0);

constexpr int kBufferLines = 40;
lv_color_t *draw_buffer = nullptr;
lv_disp_draw_buf_t draw;
bool touch_ok = false;

void flush(lv_disp_drv_t *driver, const lv_area_t *area, lv_color_t *color) {
    const int w = area->x2 - area->x1 + 1, h = area->y2 - area->y1 + 1;
    panel.draw16bitRGBBitmap(area->x1, area->y1, reinterpret_cast<uint16_t *>(color), w, h);
    lv_disp_flush_ready(driver);
}

// CST820 report: 0x02 = touch count (low nibble), 0x03..0x06 = X/Y high nibble + low byte.
void touch_read(lv_indev_drv_t *, lv_indev_data_t *data) {
    uint8_t bytes[5];
    data->state = LV_INDEV_STATE_REL;
    if (!touch_ok || !i2c::read_regs(kTouchAddr, 0x02, bytes, 5)) return;
    int x = ((bytes[1] & 0x0F) << 8) | bytes[2];
    int y = ((bytes[3] & 0x0F) << 8) | bytes[4];
    if ((bytes[0] & 0x0F) && x < kWidth && y < kHeight) {
        data->point.x = x;
        data->point.y = y;
        data->state = LV_INDEV_STATE_PR;
    }
}

}  // namespace

bool reset_peripherals() {
    // XCA9554 output pins 0/1/2/6 reset the board peripherals together (Margin).
    uint8_t config = 0xFF, output = 0xFF;
    if (!i2c::read_regs(kExpanderAddr, 3, &config, 1)) return false;
    i2c::read_regs(kExpanderAddr, 1, &output, 1);
    i2c::write_reg(kExpanderAddr, 3, config & ~0x47);
    i2c::write_reg(kExpanderAddr, 1, output & ~0x47);
    delay(20);
    i2c::write_reg(kExpanderAddr, 1, output | 0x47);
    delay(150);
    return true;
}

bool begin() {
    uint8_t touch_id = 0;
    touch_ok = i2c::read_regs(kTouchAddr, 0xA7, &touch_id, 1);
    // Disable the touch chip's automatic sleep so every touch is sampled without a wake tap.
    if (touch_ok) i2c::write_reg(kTouchAddr, 0xFE, 0xFF);

    if (!panel.begin()) return false;
    panel.setBrightness(150);
    panel.fillScreen(0);

    draw_buffer = static_cast<lv_color_t *>(
        heap_caps_malloc(kWidth * kBufferLines * sizeof(lv_color_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    if (!draw_buffer) return false;

    lv_init();
    lv_disp_draw_buf_init(&draw, draw_buffer, nullptr, kWidth * kBufferLines);
    static lv_disp_drv_t disp;
    lv_disp_drv_init(&disp);
    disp.hor_res = kWidth;
    disp.ver_res = kHeight;
    disp.flush_cb = flush;
    disp.draw_buf = &draw;
    lv_disp_drv_register(&disp);

    static lv_indev_drv_t input;
    lv_indev_drv_init(&input);
    input.type = LV_INDEV_TYPE_POINTER;
    input.read_cb = touch_read;
    lv_indev_drv_register(&input);
    return true;
}

bool touch_ready() { return touch_ok; }

void set_brightness(uint8_t level) { panel.setBrightness(level); }

}  // namespace display
