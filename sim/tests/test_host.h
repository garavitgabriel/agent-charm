// A recording charm_host.h for the tests: every call is captured, the clock is virtual.
#pragma once
#include <stdint.h>
#include <string>
#include <vector>

struct TestHost {
    std::vector<std::string> sent;        // device->server frames
    std::vector<std::string> mic_stops;   // reasons
    int mic_starts = 0;
    int speech_stops = 0;
    bool mic_result = true;               // what charm_host_mic_start() returns
    uint8_t brightness = 255;
    uint32_t now = 1000;
};

extern TestHost host;
void host_reset(void);
void host_advance(uint32_t ms);  // clock + lv_tick together
