// Timing logic: talk button hold/debounce, reconnect backoff, keepalive, the 25 s talk limit,
// the mic level, and when to report the battery.
#include <unity.h>

#include "audio_util.h"
#include "backoff.h"
#include "battery.h"
#include "button.h"

using namespace charm;

void setUp() {}
void tearDown() {}

// ---- button ----

void test_button_press_after_debounce() {
    HoldButton b(30);
    TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(0, false));
    TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(100, true));
    TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(129, true));  // 29 ms: not yet
    TEST_ASSERT_EQUAL(ButtonEvent::Pressed, b.update(130, true));
    TEST_ASSERT_TRUE(b.held());
    TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(500, true));  // holding: no repeats
}

void test_button_release_reports_hold_duration() {
    HoldButton b(30);
    b.update(0, false);
    b.update(100, true);
    TEST_ASSERT_EQUAL(ButtonEvent::Pressed, b.update(130, true));
    TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(1600, false));
    TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(1620, false));
    TEST_ASSERT_EQUAL(ButtonEvent::Released, b.update(1630, false));
    TEST_ASSERT_EQUAL(1500, b.last_hold_ms());
    TEST_ASSERT_FALSE(b.held());
}

void test_button_bounce_is_ignored() {
    HoldButton b(30);
    b.update(0, false);
    // Contact bounce: toggling every 5 ms never stays stable for 30 ms.
    for (uint32_t t = 100; t < 160; t += 5)
        TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(t, (t / 5) % 2 == 0));
    TEST_ASSERT_FALSE(b.held());
    // Then it settles down.
    TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(160, true));
    TEST_ASSERT_EQUAL(ButtonEvent::Pressed, b.update(190, true));
}

void test_button_short_glitch_while_held_is_not_a_release() {
    HoldButton b(30);
    b.update(0, false);
    b.update(10, true);
    TEST_ASSERT_EQUAL(ButtonEvent::Pressed, b.update(40, true));
    TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(300, false));  // 20 ms glitch
    TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(320, true));
    TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(400, true));
    TEST_ASSERT_TRUE(b.held());
}

void test_button_held_at_boot_is_ignored_until_released() {
    HoldButton b(30);
    TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(0, true));
    TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(100, true));
    TEST_ASSERT_FALSE(b.held());
    TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(200, false));
    TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(240, false));  // silent release
    TEST_ASSERT_EQUAL(ButtonEvent::None, b.update(300, true));
    TEST_ASSERT_EQUAL(ButtonEvent::Pressed, b.update(330, true));
}

void test_button_survives_millis_wraparound() {
    HoldButton b(30);
    uint32_t t = 0xFFFFFFF0u;
    b.update(t, false);
    b.update(t + 5, true);
    TEST_ASSERT_EQUAL(ButtonEvent::Pressed, b.update(t + 35, true));  // wraps past zero
}

// ---- backoff ----

void test_backoff_schedule() {
    Backoff b;
    const uint32_t want[] = {1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000};
    for (uint32_t w : want) TEST_ASSERT_EQUAL_UINT32(w, b.next());
    TEST_ASSERT_EQUAL_UINT32(8, b.attempts());
}

void test_backoff_reset_after_success() {
    Backoff b;
    b.next();
    b.next();
    b.next();
    b.reset();
    TEST_ASSERT_EQUAL_UINT32(1000, b.next());
    TEST_ASSERT_EQUAL_UINT32(2000, b.next());
}

void test_backoff_many_attempts_stay_capped() {
    Backoff b(500, 20000);
    uint32_t d = 0;
    for (int i = 0; i < 1000; ++i) d = b.next();
    TEST_ASSERT_EQUAL_UINT32(20000, d);
}

// ---- keepalive ----

void test_keepalive_pings_every_10s() {
    Keepalive k;
    k.reset(1000);
    TEST_ASSERT_FALSE(k.ping_due(10999));
    TEST_ASSERT_TRUE(k.ping_due(11000));
    TEST_ASSERT_FALSE(k.ping_due(11001));
    TEST_ASSERT_TRUE(k.ping_due(21000));
}

void test_keepalive_dead_after_30s_without_pong() {
    Keepalive k;
    k.reset(0);
    k.on_pong(12000);
    TEST_ASSERT_FALSE(k.dead(41999));
    TEST_ASSERT_TRUE(k.dead(42000));
}

// ---- talk session / level ----

void test_talk_limit_25s() {
    TalkSession s;
    TEST_ASSERT_FALSE(s.expired(99999));  // inactive never expires
    s.begin(5000);
    TEST_ASSERT_FALSE(s.expired(29999));
    TEST_ASSERT_TRUE(s.expired(30000));
    s.end();
    TEST_ASSERT_FALSE(s.expired(30000));
}

void test_talk_limit_by_audio_captured() {
    TalkSession s;
    s.begin(0);
    s.add_bytes(25 * 16000 * 2 - 2);
    TEST_ASSERT_FALSE(s.expired(100));
    s.add_bytes(2);
    TEST_ASSERT_TRUE(s.expired(100));
}

void test_level_silence_and_full_scale() {
    int16_t zero[64] = {0};
    TEST_ASSERT_EQUAL_FLOAT(0.0f, pcm_level(zero, 64));
    int16_t loud[64];
    for (int i = 0; i < 64; ++i) loud[i] = (i % 2) ? 32767 : -32767;
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 1.0f, pcm_level(loud, 64));
    int16_t mid[64];
    for (int i = 0; i < 64; ++i) mid[i] = (i % 2) ? 328 : -328;  // about -40 dBFS
    TEST_ASSERT_FLOAT_WITHIN(0.02f, 1.0f / 3.0f, pcm_level(mid, 64));
    TEST_ASSERT_EQUAL_FLOAT(0.0f, pcm_level(mid, 0));
}

void test_stereo_left_to_mono_in_place() {
    int16_t buf[] = {1, -1, 2, -2, 3, -3};
    stereo_left_to_mono(buf, 3, buf);
    const int16_t want[] = {1, 2, 3};
    TEST_ASSERT_EQUAL_INT16_ARRAY(want, buf, 3);
}

// ---- battery ----

void test_battery_first_reading_then_rate_limited() {
    BatteryReporter r(2, 60000, 600000);
    TEST_ASSERT_TRUE(r.should_send(0, 80));
    TEST_ASSERT_FALSE(r.should_send(1000, 70));   // moved, but too soon
    TEST_ASSERT_FALSE(r.should_send(61000, 79));  // not enough movement
    TEST_ASSERT_TRUE(r.should_send(61000, 78));
    TEST_ASSERT_TRUE(r.should_send(61000 + 600000, 78));  // heartbeat
}

void test_battery_unknown_is_never_sent() {
    BatteryReporter r;
    TEST_ASSERT_FALSE(r.should_send(0, -1));
    TEST_ASSERT_FALSE(r.should_send(0, 101));
    TEST_ASSERT_TRUE(r.should_send(0, 55));
}

void test_battery_reset_resends_on_reconnect() {
    BatteryReporter r;
    TEST_ASSERT_TRUE(r.should_send(0, 50));
    TEST_ASSERT_FALSE(r.should_send(10, 50));
    r.reset();
    TEST_ASSERT_TRUE(r.should_send(20, 50));
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_button_press_after_debounce);
    RUN_TEST(test_button_release_reports_hold_duration);
    RUN_TEST(test_button_bounce_is_ignored);
    RUN_TEST(test_button_short_glitch_while_held_is_not_a_release);
    RUN_TEST(test_button_held_at_boot_is_ignored_until_released);
    RUN_TEST(test_button_survives_millis_wraparound);
    RUN_TEST(test_backoff_schedule);
    RUN_TEST(test_backoff_reset_after_success);
    RUN_TEST(test_backoff_many_attempts_stay_capped);
    RUN_TEST(test_keepalive_pings_every_10s);
    RUN_TEST(test_keepalive_dead_after_30s_without_pong);
    RUN_TEST(test_talk_limit_25s);
    RUN_TEST(test_talk_limit_by_audio_captured);
    RUN_TEST(test_level_silence_and_full_scale);
    RUN_TEST(test_stereo_left_to_mono_in_place);
    RUN_TEST(test_battery_first_reading_then_rate_limited);
    RUN_TEST(test_battery_unknown_is_never_sent);
    RUN_TEST(test_battery_reset_resends_on_reconnect);
    return UNITY_END();
}
