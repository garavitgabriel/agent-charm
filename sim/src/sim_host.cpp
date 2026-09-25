// charm_host.h for the Mac: device->server frames go to stdout as JSON lines (the chief pipes them
// to the server at integration); host notes go to stderr. The fake mic always starts.
#include "sim_host.h"
#include "charm_host.h"
#include <chrono>
#include <lvgl.h>
#include <stdio.h>

namespace {
bool virtual_clock = false;
uint32_t virtual_ms = 0;
uint8_t brightness = 255;
bool mic_on = false;
const auto t0 = std::chrono::steady_clock::now();
}  // namespace

void sim_clock_use_virtual(uint32_t start_ms) {
    virtual_clock = true;
    virtual_ms = start_ms;
}

bool sim_clock_is_virtual(void) { return virtual_clock; }

void sim_clock_advance(uint32_t ms) {
    if (!virtual_clock) return;
    virtual_ms += ms;
    lv_tick_inc(ms);
}

uint8_t sim_brightness(void) { return brightness; }
bool sim_mic_capturing(void) { return mic_on; }

void charm_host_send(const char *json, size_t len) {
    fwrite(json, 1, len, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

bool charm_host_mic_start(void) {
    mic_on = true;
    fprintf(stderr, "[host] mic_start -> true (fake mic)\n");
    return true;
}

void charm_host_mic_stop(const char *reason) {
    mic_on = false;
    fprintf(stderr, "[host] mic_stop reason=%s\n", reason ? reason : "?");
}

void charm_host_speech_stop(void) { fprintf(stderr, "[host] speech_stop\n"); }

void charm_host_set_brightness(uint8_t level) {
    if (level != brightness) fprintf(stderr, "[host] brightness %u\n", level);
    brightness = level;
}

uint32_t charm_host_millis(void) {
    if (virtual_clock) return virtual_ms;
    return (uint32_t)std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0)
        .count();
}
