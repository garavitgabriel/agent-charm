// The live sim's audio: the Mac mic (SDL2 capture) or a WAV file standing in for it, and the Mac
// speakers (SDL2 queue) or a null sink that only counts bytes (headless runs).
// Everything is PCM s16le, mono, 16 000 Hz: the protocol's format, so nothing is resampled here
// (SDL converts from the device's native rate).
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string>
#include <vector>

// Read a 16 kHz mono s16le PCM WAV. Anything else fails with a hint in *error.
bool sim_wav_load(const std::string &path, std::vector<uint8_t> *pcm, std::string *error);

// ---- microphone ----
// Source: the default SDL capture device, or (when a WAV was set) that file, delivered in real time.
void sim_mic_use_wav(std::vector<uint8_t> pcm);
bool sim_mic_uses_wav(void);
// Open and start capturing. False when the device can't be opened (the UI then never shows
// listening). SDL's audio subsystem must be initialised for the SDL source.
bool sim_mic_open(uint32_t now_ms);
// Move up to `max` captured bytes into out. Returns the count (always even).
size_t sim_mic_read(uint8_t *out, size_t max, uint32_t now_ms);
// WAV source only: the whole file has been delivered.
bool sim_mic_exhausted(void);
// Stop capturing; *tail receives whatever was captured but not read yet (empty for "cancel").
void sim_mic_close(std::vector<uint8_t> *tail);

// ---- speaker ----
// SDL output device, or a null sink when `null_sink` (headless). False if SDL can't open one.
bool sim_speaker_open(bool null_sink);
void sim_speaker_start(void);                    // a speech_start arrived
void sim_speaker_feed(const uint8_t *pcm, size_t n);  // ignored unless started
void sim_speaker_end(void);                      // speech_end: let queued audio finish
void sim_speaker_stop(void);                     // cut playback now, drop what's queued
bool sim_speaker_active(void);                   // started, or audio still playing
size_t sim_speaker_bytes(void);                  // bytes fed since the last start
void sim_speaker_close(void);
