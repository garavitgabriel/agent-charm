// Device -> server text frames (docs/PROTOCOL.md) and the few server -> device fields the host
// itself needs to see. Card, state and every other UI message is the UI's business
// (charm_ui_on_message); the host only peeks at the type.
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace charm {

constexpr size_t kMaxTextFrame = 8192;   // PROTOCOL: text frames are at most 8192 bytes
constexpr size_t kMaxBinaryFrame = 4096; // PROTOCOL: binary frames are at most 4096 bytes
constexpr uint32_t kSampleRate = 16000;

// Each builder writes one JSON object (no trailing newline, NUL-terminated) into out and returns
// its length, or 0 if it doesn't fit in cap (or wouldn't fit a protocol text frame).
size_t frame_hello(char *out, size_t cap, const char *device_id, const char *fw, const char *token,
                   const char *const *caps, size_t caps_count);
size_t frame_audio_start(char *out, size_t cap);
// reason must be "released", "limit" or "cancel"; anything else returns 0.
size_t frame_audio_end(char *out, size_t cap, const char *reason);
size_t frame_ping(char *out, size_t cap);
size_t frame_cancel(char *out, size_t cap);
// name must be one of face_down, face_up, pickup, shake, battery; anything else returns 0.
size_t frame_event(char *out, size_t cap, const char *name);
size_t frame_event_value(char *out, size_t cap, const char *name, int value);

bool is_audio_end_reason(const char *reason);
bool is_event_name(const char *name);

enum class MsgType { Invalid, Other, Welcome, Pong, Error, SpeechStart, SpeechEnd };

struct Peek {
    MsgType type = MsgType::Invalid;
    // speech_start only: true when rate/format/channels match what the speaker can play
    // (16000, "s16le", 1). Missing fields take the protocol defaults.
    bool speech_format_ok = false;
    // error only: true when code == "auth" (the server will close with 4401).
    bool auth_error = false;
};

// Classify one server -> device text frame without keeping it.
Peek peek_message(const char *json, size_t len);

}  // namespace charm
