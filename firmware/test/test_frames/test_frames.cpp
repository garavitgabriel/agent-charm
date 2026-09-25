// Frame building and the host's message peek (docs/PROTOCOL.md).
#include <ArduinoJson.h>
#include <string.h>
#include <unity.h>

#include "frames.h"

using namespace charm;

void setUp() {}
void tearDown() {}

static JsonDocument parse(const char *s, size_t n) {
    JsonDocument doc;
    TEST_ASSERT_FALSE(deserializeJson(doc, s, n));
    return doc;
}

void test_hello_has_token_caps_and_fw() {
    char out[512];
    const char *caps[] = {"mic", "speaker", "imu"};
    size_t n = frame_hello(out, sizeof out, "charm-01", "dex-charm-fw/0.1 proto/0", "s3cret", caps, 3);
    TEST_ASSERT_GREATER_THAN(0, n);
    TEST_ASSERT_EQUAL(strlen(out), n);
    JsonDocument doc = parse(out, n);
    TEST_ASSERT_EQUAL_STRING("hello", doc["type"]);
    TEST_ASSERT_EQUAL_STRING("charm-01", doc["device_id"]);
    TEST_ASSERT_EQUAL_STRING("dex-charm-fw/0.1 proto/0", doc["fw"]);
    TEST_ASSERT_EQUAL_STRING("s3cret", doc["token"]);
    TEST_ASSERT_EQUAL(3, doc["caps"].size());
    TEST_ASSERT_EQUAL_STRING("speaker", doc["caps"][1]);
}

void test_hello_escapes_quotes_in_token() {
    char out[256];
    size_t n = frame_hello(out, sizeof out, "d", "f", "a\"b\\c", nullptr, 0);
    JsonDocument doc = parse(out, n);
    TEST_ASSERT_EQUAL_STRING("a\"b\\c", doc["token"]);
    TEST_ASSERT_EQUAL(0, doc["caps"].size());
}

void test_audio_start_matches_protocol() {
    char out[128];
    size_t n = frame_audio_start(out, sizeof out);
    JsonDocument doc = parse(out, n);
    TEST_ASSERT_EQUAL_STRING("audio_start", doc["type"]);
    TEST_ASSERT_EQUAL(16000, doc["rate"].as<int>());
    TEST_ASSERT_EQUAL_STRING("s16le", doc["format"]);
    TEST_ASSERT_EQUAL(1, doc["channels"].as<int>());
}

void test_audio_end_reasons() {
    char out[128];
    const char *ok[] = {"released", "limit", "cancel"};
    for (const char *r : ok) {
        size_t n = frame_audio_end(out, sizeof out, r);
        JsonDocument doc = parse(out, n);
        TEST_ASSERT_EQUAL_STRING("audio_end", doc["type"]);
        TEST_ASSERT_EQUAL_STRING(r, doc["reason"]);
    }
    TEST_ASSERT_EQUAL(0, frame_audio_end(out, sizeof out, "timeout"));
    TEST_ASSERT_EQUAL(0, frame_audio_end(out, sizeof out, nullptr));
}

void test_ping_and_cancel() {
    char out[64];
    TEST_ASSERT_EQUAL_STRING("{\"type\":\"ping\"}", (frame_ping(out, sizeof out), out));
    TEST_ASSERT_EQUAL_STRING("{\"type\":\"cancel\"}", (frame_cancel(out, sizeof out), out));
}

void test_events() {
    char out[128];
    size_t n = frame_event(out, sizeof out, "face_down");
    JsonDocument doc = parse(out, n);
    TEST_ASSERT_EQUAL_STRING("event", doc["type"]);
    TEST_ASSERT_EQUAL_STRING("face_down", doc["name"]);
    TEST_ASSERT_TRUE(doc["value"].isNull());

    n = frame_event_value(out, sizeof out, "battery", 87);
    doc = parse(out, n);
    TEST_ASSERT_EQUAL_STRING("battery", doc["name"]);
    TEST_ASSERT_EQUAL(87, doc["value"].as<int>());

    TEST_ASSERT_EQUAL(0, frame_event(out, sizeof out, "tilt"));
    TEST_ASSERT_EQUAL(0, frame_event_value(out, sizeof out, "volume", 3));
}

void test_too_small_buffer_returns_zero() {
    char out[8];
    TEST_ASSERT_EQUAL(0, frame_audio_start(out, sizeof out));
    char exact[16];  // {"type":"ping"} is 15 chars + NUL
    TEST_ASSERT_EQUAL(15, frame_ping(exact, sizeof exact));
    TEST_ASSERT_EQUAL(0, frame_ping(exact, 15));
}

void test_peek_types() {
    const char *w = "{\"type\":\"welcome\",\"server\":\"charm-server/0.1 proto/0\",\"time\":\"x\",\"tz\":\"y\"}";
    TEST_ASSERT_EQUAL(MsgType::Welcome, peek_message(w, strlen(w)).type);
    const char *p = "{\"type\":\"pong\"}";
    TEST_ASSERT_EQUAL(MsgType::Pong, peek_message(p, strlen(p)).type);
    const char *e = "{\"type\":\"speech_end\"}";
    TEST_ASSERT_EQUAL(MsgType::SpeechEnd, peek_message(e, strlen(e)).type);
    const char *c = "{\"type\":\"card\",\"card\":{\"id\":\"a\",\"kind\":\"answer\"}}";
    TEST_ASSERT_EQUAL(MsgType::Other, peek_message(c, strlen(c)).type);
}

void test_peek_speech_start_format() {
    const char *good = "{\"type\":\"speech_start\",\"rate\":16000,\"format\":\"s16le\",\"channels\":1,\"card_id\":\"c1\"}";
    Peek p = peek_message(good, strlen(good));
    TEST_ASSERT_EQUAL(MsgType::SpeechStart, p.type);
    TEST_ASSERT_TRUE(p.speech_format_ok);
    const char *bare = "{\"type\":\"speech_start\"}";
    TEST_ASSERT_TRUE(peek_message(bare, strlen(bare)).speech_format_ok);
    const char *rate = "{\"type\":\"speech_start\",\"rate\":24000,\"format\":\"s16le\",\"channels\":1}";
    TEST_ASSERT_FALSE(peek_message(rate, strlen(rate)).speech_format_ok);
    const char *stereo = "{\"type\":\"speech_start\",\"rate\":16000,\"format\":\"s16le\",\"channels\":2}";
    TEST_ASSERT_FALSE(peek_message(stereo, strlen(stereo)).speech_format_ok);
    const char *mp3 = "{\"type\":\"speech_start\",\"rate\":16000,\"format\":\"mp3\",\"channels\":1}";
    TEST_ASSERT_FALSE(peek_message(mp3, strlen(mp3)).speech_format_ok);
}

void test_peek_auth_error() {
    const char *a = "{\"type\":\"error\",\"code\":\"auth\",\"text\":\"bad token\"}";
    Peek p = peek_message(a, strlen(a));
    TEST_ASSERT_EQUAL(MsgType::Error, p.type);
    TEST_ASSERT_TRUE(p.auth_error);
    const char *b = "{\"type\":\"error\",\"code\":\"busy\",\"text\":\"one at a time\"}";
    TEST_ASSERT_FALSE(peek_message(b, strlen(b)).auth_error);
}

void test_peek_rejects_garbage() {
    TEST_ASSERT_EQUAL(MsgType::Invalid, peek_message("not json", 8).type);
    TEST_ASSERT_EQUAL(MsgType::Invalid, peek_message("[1,2]", 5).type);
    TEST_ASSERT_EQUAL(MsgType::Invalid, peek_message("{\"kind\":1}", 10).type);
    TEST_ASSERT_EQUAL(MsgType::Invalid, peek_message(nullptr, 0).type);
    // Uses only len bytes: a valid object followed by junk past len still parses.
    const char *buf = "{\"type\":\"pong\"}GARBAGE";
    TEST_ASSERT_EQUAL(MsgType::Pong, peek_message(buf, 15).type);
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_hello_has_token_caps_and_fw);
    RUN_TEST(test_hello_escapes_quotes_in_token);
    RUN_TEST(test_audio_start_matches_protocol);
    RUN_TEST(test_audio_end_reasons);
    RUN_TEST(test_ping_and_cancel);
    RUN_TEST(test_events);
    RUN_TEST(test_too_small_buffer_returns_zero);
    RUN_TEST(test_peek_types);
    RUN_TEST(test_peek_speech_start_format);
    RUN_TEST(test_peek_auth_error);
    RUN_TEST(test_peek_rejects_garbage);
    return UNITY_END();
}
