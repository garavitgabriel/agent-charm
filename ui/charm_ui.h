// Dex Charm UI: the screens and Dex, drawn with LVGL 8.3.
// Compiled unchanged by BOTH firmware/ (ESP32-S3) and sim/ (macOS SDL2).
// The UI never touches hardware or sockets; it talks to its host through charm_host.h.
// Contract owner: chief session. Batch 2 implements; batch 1 only links against it.
#pragma once
#include <stddef.h>
#include <stdint.h>

#define CHARM_W 368
#define CHARM_H 448

// Build every screen on lv_scr_act(). Call once after LVGL and the display driver are ready.
void charm_ui_init(void);

// Feed one server->device text frame (docs/PROTOCOL.md). The UI parses it, updates state, and calls
// charm_host_send() for any receipt (e.g. "displayed"). Unknown types are ignored.
void charm_ui_on_message(const char *json, size_t len);

// Connection changes seen by the host. Offline is the device's own state; the server never sends it.
void charm_ui_set_connected(bool connected);

// Physical talk button (BOOT on the device, space bar in the sim).
void charm_ui_talk_pressed(void);
void charm_ui_talk_released(void);

// Live microphone level 0..1 while listening (for the level indicator).
void charm_ui_mic_level(float level);

// Call every ~5 ms from the host loop, after lv_timer_handler(); drives Dex's animation clock.
void charm_ui_tick(uint32_t now_ms);
