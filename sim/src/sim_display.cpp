#include "sim_display.h"
#include "charm_ui.h"
#include "png_write.h"
#include <string.h>
#include <vector>

namespace {

lv_color_t fb[CHARM_W * CHARM_H];
lv_color_t draw_buf_px[CHARM_W * 64];
lv_disp_draw_buf_t draw_buf;
lv_disp_drv_t disp_drv;
lv_indev_drv_t indev_drv;
int ptr_x, ptr_y;
bool ptr_down;

void flush_cb(lv_disp_drv_t *drv, const lv_area_t *area, lv_color_t *px) {
    const int w = area->x2 - area->x1 + 1;
    for (int y = area->y1; y <= area->y2; y++) {
        if (y < 0 || y >= CHARM_H) {
            px += w;
            continue;
        }
        memcpy(&fb[y * CHARM_W + area->x1], px, (size_t)w * sizeof(lv_color_t));
        px += w;
    }
    lv_disp_flush_ready(drv);
}

void read_cb(lv_indev_drv_t *, lv_indev_data_t *data) {
    data->point.x = (lv_coord_t)ptr_x;
    data->point.y = (lv_coord_t)ptr_y;
    data->state = ptr_down ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

}  // namespace

void sim_display_init(void) {
    lv_init();
    lv_disp_draw_buf_init(&draw_buf, draw_buf_px, nullptr, CHARM_W * 64);
    lv_disp_drv_init(&disp_drv);
    disp_drv.hor_res = CHARM_W;
    disp_drv.ver_res = CHARM_H;
    disp_drv.flush_cb = flush_cb;
    disp_drv.draw_buf = &draw_buf;
    lv_disp_drv_register(&disp_drv);

    lv_indev_drv_init(&indev_drv);
    indev_drv.type = LV_INDEV_TYPE_POINTER;
    indev_drv.read_cb = read_cb;
    lv_indev_drv_register(&indev_drv);
}

void sim_pointer_set(int x, int y, bool pressed) {
    ptr_x = x < 0 ? 0 : x >= CHARM_W ? CHARM_W - 1 : x;
    ptr_y = y < 0 ? 0 : y >= CHARM_H ? CHARM_H - 1 : y;
    ptr_down = pressed;
}

const lv_color_t *sim_framebuffer(void) { return fb; }

void sim_render_now(void) {
    lv_obj_invalidate(lv_scr_act());
    lv_refr_now(nullptr);
}

bool sim_write_png(const char *path, uint8_t brightness) {
    std::vector<uint8_t> rgb((size_t)CHARM_W * CHARM_H * 3);
    for (int i = 0; i < CHARM_W * CHARM_H; i++) {
        const uint32_t c = lv_color_to32(fb[i]);  // 0xAARRGGBB
        rgb[i * 3 + 0] = (uint8_t)(((c >> 16) & 0xFF) * brightness / 255);
        rgb[i * 3 + 1] = (uint8_t)(((c >> 8) & 0xFF) * brightness / 255);
        rgb[i * 3 + 2] = (uint8_t)((c & 0xFF) * brightness / 255);
    }
    return png_write_rgb(path, CHARM_W, CHARM_H, rgb.data());
}
