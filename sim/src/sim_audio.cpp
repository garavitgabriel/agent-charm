#include "sim_audio.h"

#include <SDL.h>
#include <mutex>
#include <stdio.h>
#include <string.h>

namespace {

constexpr int kRate = 16000;
constexpr uint32_t kBytesPerMs = kRate * 2 / 1000;  // s16 mono: 32 bytes per ms

// ---- mic ----
bool wav_mode = false;
std::vector<uint8_t> wav_pcm;
size_t wav_pos = 0;
uint32_t wav_started = 0;

SDL_AudioDeviceID mic_dev = 0;
std::mutex mic_mutex;
std::vector<uint8_t> mic_buf;  // filled by SDL's audio thread, drained by the host loop

void mic_callback(void *, Uint8 *stream, int len) {
    std::lock_guard<std::mutex> lock(mic_mutex);
    // Bound the backlog to 2 s so a stalled loop can't grow it forever.
    if (mic_buf.size() + (size_t)len > 2 * kRate * 2) return;
    mic_buf.insert(mic_buf.end(), stream, stream + len);
}

// ---- speaker ----
bool spk_null = true;
SDL_AudioDeviceID spk_dev = 0;
bool spk_started = false;
size_t spk_bytes = 0;

uint32_t le32(const uint8_t *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }
uint16_t le16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }

}  // namespace

bool sim_wav_load(const std::string &path, std::vector<uint8_t> *pcm, std::string *error) {
    FILE *f = fopen(path.c_str(), "rb");
    if (!f) {
        *error = "cannot open " + path;
        return false;
    }
    std::vector<uint8_t> data;
    uint8_t chunk[8192];
    size_t n;
    while ((n = fread(chunk, 1, sizeof chunk, f)) > 0) data.insert(data.end(), chunk, chunk + n);
    fclose(f);
    const std::string hint = " (want 16 kHz mono s16le PCM; convert with "
                             "`afconvert -f WAVE -d LEI16@16000 -c 1 in out.wav`)";
    if (data.size() < 12 || memcmp(data.data(), "RIFF", 4) != 0 || memcmp(data.data() + 8, "WAVE", 4) != 0) {
        *error = path + " is not a RIFF/WAVE file" + hint;
        return false;
    }
    bool fmt_ok = false, have_fmt = false;
    for (size_t off = 12; off + 8 <= data.size();) {
        const uint32_t size = le32(&data[off + 4]);
        const size_t body = off + 8;
        if (body + size > data.size()) break;
        if (memcmp(&data[off], "fmt ", 4) == 0 && size >= 16) {
            have_fmt = true;
            const uint16_t format = le16(&data[body]);
            const uint16_t channels = le16(&data[body + 2]);
            const uint32_t rate = le32(&data[body + 4]);
            const uint16_t bits = le16(&data[body + 14]);
            // 1 = PCM; 0xFFFE = WAVE_FORMAT_EXTENSIBLE (afconvert writes it for some layouts).
            fmt_ok = (format == 1 || format == 0xFFFE) && channels == 1 && rate == kRate && bits == 16;
        } else if (memcmp(&data[off], "data", 4) == 0) {
            if (!have_fmt || !fmt_ok) break;
            pcm->assign(data.begin() + (long)body, data.begin() + (long)(body + (size & ~1u)));
            return true;
        }
        off = body + size + (size & 1);
    }
    *error = path + ": unsupported WAV layout" + hint;
    return false;
}

void sim_mic_use_wav(std::vector<uint8_t> pcm) {
    wav_mode = true;
    wav_pcm = std::move(pcm);
}

bool sim_mic_uses_wav(void) { return wav_mode; }

bool sim_mic_open(uint32_t now_ms) {
    if (wav_mode) {
        wav_pos = 0;
        wav_started = now_ms;
        return true;
    }
    if (mic_dev) return true;
    SDL_AudioSpec want, have;
    SDL_zero(want);
    want.freq = kRate;
    want.format = AUDIO_S16LSB;
    want.channels = 1;
    want.samples = 512;  // 32 ms callbacks
    want.callback = mic_callback;
    {
        std::lock_guard<std::mutex> lock(mic_mutex);
        mic_buf.clear();
    }
    // No allowed changes: SDL converts from the mic's native format to exactly 16 kHz s16 mono.
    mic_dev = SDL_OpenAudioDevice(nullptr, 1, &want, &have, 0);
    if (!mic_dev) {
        fprintf(stderr, "[audio] mic open failed: %s\n", SDL_GetError());
        return false;
    }
    SDL_PauseAudioDevice(mic_dev, 0);
    return true;
}

size_t sim_mic_read(uint8_t *out, size_t max, uint32_t now_ms) {
    max &= ~(size_t)1;
    if (wav_mode) {
        // Real time: the file plays out at 16 kHz, like someone speaking it.
        size_t due = (size_t)(now_ms - wav_started) * kBytesPerMs;
        if (due > wav_pcm.size()) due = wav_pcm.size();
        size_t n = due > wav_pos ? due - wav_pos : 0;
        if (n > max) n = max;
        n &= ~(size_t)1;
        memcpy(out, wav_pcm.data() + wav_pos, n);
        wav_pos += n;
        return n;
    }
    std::lock_guard<std::mutex> lock(mic_mutex);
    const size_t n = mic_buf.size() < max ? mic_buf.size() & ~(size_t)1 : max;
    memcpy(out, mic_buf.data(), n);
    mic_buf.erase(mic_buf.begin(), mic_buf.begin() + (long)n);
    return n;
}

bool sim_mic_exhausted(void) { return wav_mode && wav_pos >= wav_pcm.size(); }

void sim_mic_close(std::vector<uint8_t> *tail) {
    if (tail) tail->clear();
    if (wav_mode) return;  // the WAV has no backlog: only what's due in real time was ever read
    if (!mic_dev) return;
    SDL_CloseAudioDevice(mic_dev);  // stops the callback; the mic indicator goes off with it
    mic_dev = 0;
    std::lock_guard<std::mutex> lock(mic_mutex);
    if (tail) tail->swap(mic_buf);
    mic_buf.clear();
}

bool sim_speaker_open(bool null_sink) {
    spk_null = null_sink;
    if (null_sink) return true;
    SDL_AudioSpec want, have;
    SDL_zero(want);
    want.freq = kRate;
    want.format = AUDIO_S16LSB;
    want.channels = 1;
    want.samples = 1024;
    want.callback = nullptr;  // SDL_QueueAudio
    spk_dev = SDL_OpenAudioDevice(nullptr, 0, &want, &have, 0);
    if (!spk_dev) {
        fprintf(stderr, "[audio] speaker open failed: %s\n", SDL_GetError());
        return false;
    }
    SDL_PauseAudioDevice(spk_dev, 0);
    return true;
}

void sim_speaker_start(void) {
    if (spk_dev) SDL_ClearQueuedAudio(spk_dev);
    spk_started = true;
    spk_bytes = 0;
}

void sim_speaker_feed(const uint8_t *pcm, size_t n) {
    if (!spk_started) return;  // after a stop, late frames of the cut speech are dropped
    spk_bytes += n;
    if (spk_dev) SDL_QueueAudio(spk_dev, pcm, (Uint32)n);
}

void sim_speaker_end(void) { spk_started = false; }

void sim_speaker_stop(void) {
    spk_started = false;
    if (spk_dev) SDL_ClearQueuedAudio(spk_dev);
}

bool sim_speaker_active(void) { return spk_started || (spk_dev && SDL_GetQueuedAudioSize(spk_dev) > 0); }

size_t sim_speaker_bytes(void) { return spk_bytes; }

void sim_speaker_close(void) {
    if (spk_dev) SDL_CloseAudioDevice(spk_dev);
    spk_dev = 0;
}
