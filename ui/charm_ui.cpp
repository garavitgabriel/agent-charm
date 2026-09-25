// SKELETON STUB (chief). Batch 2 replaces this with the real UI. Keeps firmware/ linkable meanwhile.
#include "charm_ui.h"
#include "charm_host.h"
#include <lvgl.h>

static lv_obj_t *status_label;

void charm_ui_init(void) {
    lv_obj_t *screen = lv_scr_act();
    lv_obj_set_style_bg_color(screen, lv_color_black(), 0);
    status_label = lv_label_create(screen);
    lv_label_set_text(status_label, "dex charm - stub ui");
    lv_obj_set_style_text_color(status_label, lv_color_white(), 0);
    lv_obj_center(status_label);
}
void charm_ui_on_message(const char *, size_t) {}
void charm_ui_set_connected(bool connected) {
    if (status_label) lv_label_set_text(status_label, connected ? "online" : "offline");
}
void charm_ui_talk_pressed(void) { charm_host_mic_start(); }
void charm_ui_talk_released(void) { charm_host_mic_stop("released"); }
void charm_ui_mic_level(float) {}
void charm_ui_tick(uint32_t) {}
