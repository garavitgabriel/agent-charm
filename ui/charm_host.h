// Functions the HOST (firmware or simulator) provides to the UI. The UI declares intent; the host
// does the I/O. Implemented in firmware/ (batch 1) and sim/ (batch 2), never in ui/.
#pragma once
#include <stddef.h>
#include <stdint.h>

// Send one device->server text frame (a complete JSON object, no trailing newline).
void charm_host_send(const char *json, size_t len);

// Start or stop microphone capture and streaming. The host sends audio_start / binary PCM /
// audio_end{reason} itself. The UI shows "listening" only after charm_host_mic_start() returns true.
bool charm_host_mic_start(void);
void charm_host_mic_stop(const char *reason);  // "released" | "limit" | "cancel"

// Stop any speech playback immediately (user tapped to interrupt).
void charm_host_speech_stop(void);

// Screen brightness 0..255 (dim/night mode).
void charm_host_set_brightness(uint8_t level);

// Monotonic milliseconds.
uint32_t charm_host_millis(void);
