// Dex Charm firmware: the host for the shared UI (../ui) on the Waveshare AMOLED 1.8 V2.
//
// The UI loop (Arduino loop, core 1) runs LVGL, the talk button, the IMU/battery and the
// charm_ui_* calls. Wi-Fi/WebSocket (net.cpp) and the mic/speaker (audio.cpp) run on their own
// tasks on core 0 and meet the UI loop through queues and ring buffers.
#include <Arduino.h>
#include <Wire.h>
#include <lvgl.h>

#include "audio.h"
#include "audio_util.h"
#include "battery.h"
#include "board.h"
#include "button.h"
#include "charm_host.h"
#include "charm_ui.h"
#include "config.h"
#include "display.h"
#include "frames.h"
#include "net.h"
#include "sensors.h"

namespace {

bool ui_ready = false;
uint32_t last_tick = 0, last_level = 0, last_battery_poll = 0;
charm::HoldButton talk_button;
charm::TalkSession talk;
charm::BatteryReporter battery;

void end_talk(const char *reason) {
    if (!talk.active()) return;
    audio::mic_stop();
    talk.end();
    net::audio_end(reason);
}

void drain_network() {
    net::Inbound item;
    // Bounded per loop so a burst of cards can't starve rendering.
    for (int i = 0; i < 8 && net::poll(item); ++i) {
        switch (item.kind) {
        case net::Inbound::Online:
            battery.reset();
            charm_ui_set_connected(true);
            break;
        case net::Inbound::Offline:
            if (talk.active()) {  // the stream is gone: nothing more to send
                audio::mic_stop();
                talk.end();
            }
            charm_ui_set_connected(false);
            break;
        case net::Inbound::Text:
            charm_ui_on_message(item.data, item.len);
            break;
        }
        net::release(item);
    }
}

void pump_talk(uint32_t now) {
    if (!talk.active()) return;
    if (talk.expired(now)) {  // 25 s: the host ends the talk itself
        end_talk("limit");
        charm_ui_mic_level(0.0f);
        return;
    }
    if (now - last_level >= 50) {
        last_level = now;
        charm_ui_mic_level(audio::mic_level());
    }
}

void send_event(const char *name) {
    char buf[96];
    size_t n = charm::frame_event(buf, sizeof buf, name);
    if (n) net::send_text(buf, n);
}

void poll_sensors(uint32_t now) {
    charm::Motion m = sensors::poll_motion(now);
    if (const char *name = charm::motion_name(m)) send_event(name);

    if (now - last_battery_poll < 5000) return;
    last_battery_poll = now;
    int percent = sensors::battery_percent();
    if (net::online() && battery.should_send(now, percent)) {
        char buf[96];
        size_t n = charm::frame_event_value(buf, sizeof buf, "battery", percent);
        if (n) net::send_text(buf, n);
    }
}

}  // namespace

// ---- charm_host.h ----

void charm_host_send(const char *json, size_t len) { net::send_text(json, len); }

bool charm_host_mic_start(void) {
    if (talk.active()) return true;
    if (!audio::ready() || !net::online()) return false;
    audio::speech_stop();  // half-duplex: don't record Dex's own voice
    if (!net::audio_start()) return false;
    audio::mic_start();
    talk.begin(millis());
    return true;
}

void charm_host_mic_stop(const char *reason) {
    end_talk(charm::is_audio_end_reason(reason) ? reason : "released");
}

void charm_host_speech_stop(void) { audio::speech_stop(); }

void charm_host_set_brightness(uint8_t level) { display::set_brightness(level); }

uint32_t charm_host_millis(void) { return millis(); }

// ---- Arduino ----

void setup() {
    Serial.begin(115200);
    Serial.setTxTimeoutMs(20);
    delay(300);
    Serial.printf("[charm] %s\n", CHARM_FW_VERSION);

    Wire.begin(board::kI2cSda, board::kI2cScl);
    Wire.setClock(400000);
    Wire.setTimeOut(30);
    if (!display::reset_peripherals()) Serial.println("[charm] XCA9554 expander not found");
    if (!display::begin()) {
        Serial.println("[charm] FATAL: display init failed");
        return;
    }
    pinMode(board::kBootButton, INPUT_PULLUP);

    bool audio_ok = audio::begin();
    sensors::Status s = sensors::begin();
    Serial.printf("[charm] touch=%d audio=%d imu=%d pmu=%d psram=%u\n", display::touch_ready(), audio_ok, s.imu,
                  s.pmu, static_cast<unsigned>(ESP.getPsramSize()));

    charm_ui_init();
    charm_ui_set_connected(false);  // offline until the server's welcome
    net::begin();
    last_tick = millis();
    ui_ready = true;
}

void loop() {
    if (!ui_ready) {
        delay(100);
        return;
    }
    uint32_t now = millis();
    lv_tick_inc(now - last_tick);
    last_tick = now;

    drain_network();

    switch (talk_button.update(now, digitalRead(board::kBootButton) == LOW)) {
    case charm::ButtonEvent::Pressed: charm_ui_talk_pressed(); break;
    case charm::ButtonEvent::Released: charm_ui_talk_released(); break;
    default: break;
    }

    pump_talk(now);
    poll_sensors(now);

    lv_timer_handler();
    charm_ui_tick(millis());
    delay(3);
}
