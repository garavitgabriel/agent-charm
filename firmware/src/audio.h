// ES8311 codec over I2S: microphone capture and speaker playback.
//
// Two FreeRTOS tasks own the I2S channels: the mic task reads 16 kHz stereo and, while capturing,
// keeps the left channel as mono PCM in a PSRAM ring; the speaker task pulls from the
// SpeechPlayer's PSRAM ring and writes stereo (mono duplicated). The speaker amplifier enable
// (GPIO46) is HIGH only while the player is Playing or Draining.
#pragma once
#include <stddef.h>
#include <stdint.h>

#include "speech.h"

namespace audio {

bool begin();
bool ready();

// Capture. mic_start() discards anything stale; mic_read() returns whole samples only.
void mic_start();
void mic_stop();
bool mic_capturing();
size_t mic_available();
size_t mic_read(uint8_t *out, size_t len);
float mic_level();  // 0..1, updated per I2S block while capturing

// Playback. The network task drives the player (start/feed/end); anyone may stop it.
charm::SpeechPlayer &speech();
void speech_stop();  // cuts playback now and drops the PA

}  // namespace audio
