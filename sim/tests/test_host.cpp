#include "test_host.h"
#include "charm_host.h"
#include <lvgl.h>

TestHost host;

void host_reset(void) {
    const uint32_t now = host.now;  // the clock never goes backwards between tests
    host = TestHost{};
    host.now = now;
}

void host_advance(uint32_t ms) {
    host.now += ms;
    lv_tick_inc(ms);
}

void charm_host_send(const char *json, size_t len) { host.sent.emplace_back(json, len); }
bool charm_host_mic_start(void) {
    host.mic_starts++;
    return host.mic_result;
}
void charm_host_mic_stop(const char *reason) { host.mic_stops.emplace_back(reason ? reason : ""); }
void charm_host_speech_stop(void) { host.speech_stops++; }
void charm_host_set_brightness(uint8_t level) { host.brightness = level; }
uint32_t charm_host_millis(void) { return host.now; }
