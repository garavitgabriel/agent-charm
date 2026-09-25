// Codec init follows Margin (firmware/src/main.cpp, initAudio) and Waveshare's V2 example
// examples/arduino-v2/examples/15_ES8311/15_ES8311.ino (commit 7ab8f957…), which also sets the
// DAC volume for playback. es8311.c/.h/_reg.h are that example's Espressif driver, unmodified.
#include "audio.h"

#include <Arduino.h>
#include <ESP_I2S.h>
#include <atomic>

#include "audio_util.h"
#include "board.h"
#include "es8311.h"
#include "ring_buffer.h"

namespace audio {
namespace {

constexpr uint32_t kRate = 16000;
constexpr int kVoiceVolume = 80;                    // 0..100; Waveshare's example uses 85
constexpr size_t kMicRingBytes = 64 * 1024;         // 2 s of mono s16: slack for a slow loop
constexpr size_t kSpeechRingBytes = 1024 * 1024;    // 32 s of mono s16: a whole spoken reply
constexpr size_t kBlockFrames = 256;                // 16 ms per I2S block

I2SClass i2s;
charm::LockedRing mic_ring;
charm::SpeechPlayer player;
std::atomic<bool> ok{false}, capturing{false};
std::atomic<float> level{0.0f};

void set_pa(bool on) { digitalWrite(board::kSpeakerPa, on ? HIGH : LOW); }

void mic_task(void *) {
    static int16_t block[kBlockFrames * 2];
    for (;;) {
        size_t bytes = 0;
        if (i2s_channel_read(i2s.rxChan(), block, sizeof block, &bytes, pdMS_TO_TICKS(100)) != ESP_OK || !bytes) continue;
        if (!capturing.load()) continue;
        size_t frames = bytes / 4;
        charm::stereo_left_to_mono(block, frames, block);
        level.store(charm::pcm_level(block, frames));
        mic_ring.write(reinterpret_cast<uint8_t *>(block), frames * 2);
    }
}

void speaker_task(void *) {
    static int16_t block[kBlockFrames * 2];
    for (;;) {
        size_t frames = player.pull(block, kBlockFrames);
        if (!frames) {
            set_pa(false);
            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }
        set_pa(true);
        size_t written = 0;
        i2s_channel_write(i2s.txChan(), block, frames * 4, &written, pdMS_TO_TICKS(100));
        // Re-check after the (blocking) write: a stop() during it drops the PA within one block.
        if (!player.pa_on()) set_pa(false);
    }
}

bool init_codec() {
    es8311_handle_t codec = es8311_create(0, ES8311_ADDRESS_0);
    if (!codec) return false;
    es8311_clock_config_t clk = {false, false, true, kRate * 256, kRate};
    return es8311_init(codec, &clk, ES8311_RESOLUTION_16, ES8311_RESOLUTION_16) == ESP_OK &&
           es8311_sample_frequency_config(codec, clk.mclk_frequency, clk.sample_frequency) == ESP_OK &&
           es8311_microphone_config(codec, false) == ESP_OK &&
           es8311_microphone_gain_set(codec, ES8311_MIC_GAIN_18DB) == ESP_OK &&
           es8311_voice_volume_set(codec, kVoiceVolume, nullptr) == ESP_OK;
}

}  // namespace

bool begin() {
    pinMode(board::kSpeakerPa, OUTPUT);
    set_pa(false);  // amplifier off until something actually plays

    auto *mic_store = static_cast<uint8_t *>(ps_malloc(kMicRingBytes));
    auto *speech_store = static_cast<uint8_t *>(ps_malloc(kSpeechRingBytes));
    if (!mic_store || !speech_store) return false;
    mic_ring.init(mic_store, kMicRingBytes);
    player.init(speech_store, kSpeechRingBytes);

    i2s.setPins(board::kI2sBclk, board::kI2sWs, board::kI2sDout, board::kI2sDin, board::kI2sMclk);
    if (!i2s.begin(I2S_MODE_STD, kRate, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO, I2S_STD_SLOT_BOTH)) return false;
    if (!init_codec()) return false;

    // Core 0 alongside Wi-Fi; the Arduino loop (UI) keeps core 1.
    xTaskCreatePinnedToCore(mic_task, "charm-mic", 4096, nullptr, 5, nullptr, 0);
    xTaskCreatePinnedToCore(speaker_task, "charm-spk", 4096, nullptr, 5, nullptr, 0);
    ok = true;
    return true;
}

bool ready() { return ok.load(); }

void mic_start() {
    mic_ring.clear();
    level = 0.0f;
    capturing = true;
}

void mic_stop() {
    capturing = false;
    level = 0.0f;
}

bool mic_capturing() { return capturing.load(); }
size_t mic_available() { return mic_ring.size(); }
size_t mic_read(uint8_t *out, size_t len) { return mic_ring.read_aligned(out, len, 2); }
float mic_level() { return level.load(); }

charm::SpeechPlayer &speech() { return player; }

void speech_stop() {
    player.stop();
    set_pa(false);
}

}  // namespace audio
