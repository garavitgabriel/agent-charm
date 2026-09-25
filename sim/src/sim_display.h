// Headless LVGL display + pointer input backed by a CHARM_W x CHARM_H framebuffer. The SDL window
// (main.cpp) presents this framebuffer; screenshots and tests read it directly.
#pragma once
#include <stdint.h>
#include <lvgl.h>

// lv_init() + a display driver that flushes into the framebuffer + a pointer indev.
void sim_display_init(void);

// Pointer state fed by the window (mouse = touch) or by scripts.
void sim_pointer_set(int x, int y, bool pressed);

// RGB565 pixels, row-major, CHARM_W x CHARM_H.
const lv_color_t *sim_framebuffer(void);

// Render the current screen synchronously.
void sim_render_now(void);

// Write the framebuffer as an RGB PNG, scaled by brightness/255 (what the panel would show).
bool sim_write_png(const char *path, uint8_t brightness);
