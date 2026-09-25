// The simulator's side of charm_host.h, plus its clock.
#pragma once
#include <stdint.h>

// Real time (default) or a virtual clock that only moves with sim_clock_advance() (headless runs:
// deterministic screenshots and replays).
void sim_clock_use_virtual(uint32_t start_ms);
bool sim_clock_is_virtual(void);
// Virtual clock only: move time forward and feed LVGL's tick by the same amount.
void sim_clock_advance(uint32_t ms);

uint8_t sim_brightness(void);
bool sim_mic_capturing(void);
