#include "frames.h"

#include <ArduinoJson.h>
#include <string.h>

namespace charm {

namespace {

size_t finish(JsonDocument &doc, char *out, size_t cap) {
    if (doc.overflowed()) return 0;
    size_t need = measureJson(doc);
    if (need == 0 || need + 1 > cap || need > kMaxTextFrame) return 0;
    return serializeJson(doc, out, cap);
}

bool in_list(const char *s, const char *const *list, size_t n) {
    if (!s) return false;
    for (size_t i = 0; i < n; ++i)
        if (strcmp(s, list[i]) == 0) return true;
    return false;
}

const char *const kReasons[] = {"released", "limit", "cancel"};
const char *const kEvents[] = {"face_down", "face_up", "pickup", "shake", "battery"};

}  // namespace

bool is_audio_end_reason(const char *reason) { return in_list(reason, kReasons, 3); }
bool is_event_name(const char *name) { return in_list(name, kEvents, 5); }

size_t frame_hello(char *out, size_t cap, const char *device_id, const char *fw, const char *token,
                   const char *const *caps, size_t caps_count) {
    JsonDocument doc;
    doc["type"] = "hello";
    doc["device_id"] = device_id ? device_id : "";
    doc["fw"] = fw ? fw : "";
    doc["token"] = token ? token : "";
    JsonArray list = doc["caps"].to<JsonArray>();
    for (size_t i = 0; i < caps_count; ++i) list.add(caps[i]);
    return finish(doc, out, cap);
}

size_t frame_audio_start(char *out, size_t cap) {
    JsonDocument doc;
    doc["type"] = "audio_start";
    doc["rate"] = kSampleRate;
    doc["format"] = "s16le";
    doc["channels"] = 1;
    return finish(doc, out, cap);
}

size_t frame_audio_end(char *out, size_t cap, const char *reason) {
    if (!is_audio_end_reason(reason)) return 0;
    JsonDocument doc;
    doc["type"] = "audio_end";
    doc["reason"] = reason;
    return finish(doc, out, cap);
}

size_t frame_ping(char *out, size_t cap) {
    JsonDocument doc;
    doc["type"] = "ping";
    return finish(doc, out, cap);
}

size_t frame_cancel(char *out, size_t cap) {
    JsonDocument doc;
    doc["type"] = "cancel";
    return finish(doc, out, cap);
}

size_t frame_event(char *out, size_t cap, const char *name) {
    if (!is_event_name(name)) return 0;
    JsonDocument doc;
    doc["type"] = "event";
    doc["name"] = name;
    return finish(doc, out, cap);
}

size_t frame_event_value(char *out, size_t cap, const char *name, int value) {
    if (!is_event_name(name)) return 0;
    JsonDocument doc;
    doc["type"] = "event";
    doc["name"] = name;
    doc["value"] = value;
    return finish(doc, out, cap);
}

Peek peek_message(const char *json, size_t len) {
    Peek p;
    if (!json || len == 0 || len > kMaxTextFrame) return p;
    JsonDocument filter;
    filter["type"] = true;
    filter["rate"] = true;
    filter["format"] = true;
    filter["channels"] = true;
    filter["code"] = true;
    JsonDocument doc;
    if (deserializeJson(doc, json, len, DeserializationOption::Filter(filter))) return p;
    if (!doc.is<JsonObject>()) return p;
    const char *type = doc["type"] | static_cast<const char *>(nullptr);
    if (!type) return p;
    p.type = MsgType::Other;
    if (strcmp(type, "welcome") == 0) {
        p.type = MsgType::Welcome;
    } else if (strcmp(type, "pong") == 0) {
        p.type = MsgType::Pong;
    } else if (strcmp(type, "error") == 0) {
        p.type = MsgType::Error;
        const char *code = doc["code"] | "";
        p.auth_error = strcmp(code, "auth") == 0;
    } else if (strcmp(type, "speech_start") == 0) {
        p.type = MsgType::SpeechStart;
        long rate = doc["rate"] | static_cast<long>(kSampleRate);
        const char *format = doc["format"] | "s16le";
        long channels = doc["channels"] | 1L;
        p.speech_format_ok = rate == static_cast<long>(kSampleRate) && strcmp(format, "s16le") == 0 && channels == 1;
    } else if (strcmp(type, "speech_end") == 0) {
        p.type = MsgType::SpeechEnd;
    }
    return p;
}

}  // namespace charm
