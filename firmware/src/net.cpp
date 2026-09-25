#include "net.h"

#include <Arduino.h>
#include <WebSocketsClient.h>
#include <WiFi.h>
#include <atomic>
#include <string.h>

#include "audio.h"
#include "audio_util.h"
#include "backoff.h"
#include "config.h"
#include "frames.h"

namespace net {
namespace {

// Exposes the library's last-failure timestamp. TCP connect failures raise no event, so this is
// how the task notices each failed attempt and sets the next backoff interval.
class CharmSocket : public WebSocketsClient {
public:
    unsigned long last_fail() const { return _lastConnectionFail; }
};

struct Outbound {
    enum Kind : uint8_t { Text, AudioStart, AudioEnd } kind = Text;
    char *data = nullptr;
    size_t len = 0;
    char reason[12] = {0};
};

CharmSocket ws;
QueueHandle_t inbound_q = nullptr, outbound_q = nullptr;
std::atomic<bool> is_online{false};
charm::Backoff backoff;
charm::Keepalive keepalive;
unsigned long seen_fail = 0;
uint32_t hello_at = 0;   // when hello went out on the current socket; 0 once welcomed or down
constexpr uint32_t kWelcomeTimeoutMs = 10000;
bool streaming = false;  // between audio_start and audio_end (task-local)

char *copy_string(const char *s, size_t len) {
    auto *p = static_cast<char *>(ps_malloc(len + 1));
    if (!p) p = static_cast<char *>(malloc(len + 1));
    if (!p) return nullptr;
    memcpy(p, s, len);
    p[len] = '\0';
    return p;
}

void push_notice(Inbound::Kind kind) {
    Inbound item;
    item.kind = kind;
    xQueueSend(inbound_q, &item, portMAX_DELAY);  // notices must not be lost
}

void push_text(const char *s, size_t len) {
    Inbound item;
    item.data = copy_string(s, len);
    item.len = len;
    if (!item.data) return;
    if (xQueueSend(inbound_q, &item, 0) != pdTRUE) {
        Serial.println("[net] inbound queue full, frame dropped");
        free(item.data);
    }
}

void send_frame(const char *json, size_t len) {
    if (len) ws.sendTXT(json, len);
}

void go_offline() {
    streaming = false;
    hello_at = 0;
    audio::speech_stop();
    if (is_online.exchange(false)) push_notice(Inbound::Offline);
}

void on_event(WStype_t type, uint8_t *payload, size_t length) {
    switch (type) {
    case WStype_CONNECTED: {
        static const char *const caps[] = {"mic", "speaker", "imu"};
        char hello[512];
        size_t n = charm::frame_hello(hello, sizeof hello, CHARM_DEVICE_ID, CHARM_FW_VERSION, CHARM_TOKEN, caps, 3);
        send_frame(hello, n);
        hello_at = millis() | 1;
        keepalive.reset(millis());
        break;
    }
    case WStype_TEXT: {
        const char *text = reinterpret_cast<const char *>(payload);
        charm::Peek p = charm::peek_message(text, length);
        if (p.type == charm::MsgType::Welcome && !is_online.exchange(true)) {
            hello_at = 0;
            backoff.reset();
            keepalive.reset(millis());
            push_notice(Inbound::Online);  // the UI hears "connected" before the welcome itself
        } else if (p.type == charm::MsgType::Pong) {
            keepalive.on_pong(millis());
        } else if (p.type == charm::MsgType::SpeechStart) {
            if (p.speech_format_ok) audio::speech().start();
            else Serial.println("[net] speech_start in an unsupported format, not playing");
        } else if (p.type == charm::MsgType::SpeechEnd) {
            audio::speech().end();
        }
        push_text(text, length);
        break;
    }
    case WStype_BIN:
        audio::speech().feed(payload, length);
        break;
    case WStype_DISCONNECTED:
        go_offline();
        break;
    default:
        break;
    }
}

void pump_mic(bool flush_all) {
    static uint8_t frame[charm::kMaxBinaryFrame];
    for (;;) {
        size_t avail = audio::mic_available();
        if (avail < sizeof frame && !(flush_all && avail >= 2)) return;
        size_t n = audio::mic_read(frame, sizeof frame);
        if (!n) return;
        ws.sendBIN(frame, n);
    }
}

void handle_outbound(Outbound &o) {
    bool up = is_online.load();
    switch (o.kind) {
    case Outbound::Text:
        if (up) send_frame(o.data, o.len);
        free(o.data);
        break;
    case Outbound::AudioStart: {
        char buf[96];
        if (up) {
            send_frame(buf, charm::frame_audio_start(buf, sizeof buf));
            streaming = true;
        }
        break;
    }
    case Outbound::AudioEnd: {
        char buf[64];
        if (up && streaming) {
            if (strcmp(o.reason, "cancel") != 0) pump_mic(true);
            send_frame(buf, charm::frame_audio_end(buf, sizeof buf, o.reason));
        }
        streaming = false;
        break;
    }
    }
}

void task(void *) {
    bool wifi_was_up = false;
    for (;;) {
        bool wifi_up = WiFi.status() == WL_CONNECTED;
        if (wifi_up != wifi_was_up) {
            Serial.printf("[net] wifi %s\n", wifi_up ? WiFi.localIP().toString().c_str() : "down");
            if (!wifi_up) {
                ws.disconnect();
                go_offline();
            }
            wifi_was_up = wifi_up;
        }
        if (wifi_up) {
            ws.loop();
            unsigned long lf = ws.last_fail();
            if (lf && lf != seen_fail) {  // an attempt failed or the link dropped
                seen_fail = lf;
                uint32_t wait = backoff.next();
                ws.setReconnectInterval(wait);
                Serial.printf("[net] socket down, retry in %lu ms\n", static_cast<unsigned long>(wait));
            }
        }

        uint32_t now = millis();
        if (hello_at && now - hello_at > kWelcomeTimeoutMs) {
            Serial.println("[net] no welcome within 10 s, reconnecting");
            hello_at = 0;
            ws.disconnect();
        }
        if (is_online.load()) {
            char buf[32];
            if (keepalive.ping_due(now)) send_frame(buf, charm::frame_ping(buf, sizeof buf));
            if (keepalive.dead(now)) {
                Serial.println("[net] no pong for 30 s, reconnecting");
                ws.disconnect();
                go_offline();
            }
        }

        Outbound o;
        while (xQueueReceive(outbound_q, &o, 0) == pdTRUE) handle_outbound(o);
        if (streaming && is_online.load()) pump_mic(false);

        vTaskDelay(pdMS_TO_TICKS(2));
    }
}

bool enqueue(Outbound &o) {
    if (!outbound_q || xQueueSend(outbound_q, &o, 0) != pdTRUE) {
        free(o.data);
        return false;
    }
    return true;
}

}  // namespace

bool begin() {
    inbound_q = xQueueCreate(32, sizeof(Inbound));
    outbound_q = xQueueCreate(24, sizeof(Outbound));
    if (!inbound_q || !outbound_q) return false;
#if !CHARM_HAS_SECRETS
    Serial.println("[net] no secrets.h: staying offline (see firmware/README.md)");
    return false;
#else
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);  // modem sleep adds latency to the audio stream
    WiFi.setAutoReconnect(true);
    WiFi.begin(CHARM_WIFI_SSID, CHARM_WIFI_PASSWORD);
    ws.begin(CHARM_SERVER_HOST, CHARM_SERVER_PORT, CHARM_SERVER_PATH);
    ws.onEvent(on_event);
    xTaskCreatePinnedToCore(task, "charm-net", 8192, nullptr, 4, nullptr, 0);
    return true;
#endif
}

bool online() { return is_online.load(); }

bool send_text(const char *json, size_t len) {
    if (!is_online.load() || !json || !len || len > charm::kMaxTextFrame) return false;
    Outbound o;
    o.data = copy_string(json, len);
    o.len = len;
    return o.data && enqueue(o);
}

bool audio_start() {
    if (!is_online.load()) return false;
    Outbound o;
    o.kind = Outbound::AudioStart;
    return enqueue(o);
}

bool audio_end(const char *reason) {
    if (!charm::is_audio_end_reason(reason)) return false;
    Outbound o;
    o.kind = Outbound::AudioEnd;
    strncpy(o.reason, reason, sizeof o.reason - 1);
    return enqueue(o);
}

bool poll(Inbound &out) { return inbound_q && xQueueReceive(inbound_q, &out, 0) == pdTRUE; }

void release(Inbound &item) {
    free(item.data);
    item.data = nullptr;
}

}  // namespace net
