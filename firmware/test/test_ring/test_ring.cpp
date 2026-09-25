// The byte ring buffer and the speech player built on it.
#include <string.h>
#include <unity.h>

#include "ring_buffer.h"
#include "speech.h"

using namespace charm;

void setUp() {}
void tearDown() {}

void test_ring_write_read_roundtrip() {
    uint8_t store[8];
    ByteRing r;
    r.init(store, sizeof store);
    TEST_ASSERT_TRUE(r.empty());
    const uint8_t in[] = {1, 2, 3, 4, 5};
    TEST_ASSERT_EQUAL(5, r.write(in, 5));
    TEST_ASSERT_EQUAL(5, r.size());
    TEST_ASSERT_EQUAL(3, r.free_space());
    uint8_t out[5] = {0};
    TEST_ASSERT_EQUAL(5, r.read(out, 5));
    TEST_ASSERT_EQUAL_UINT8_ARRAY(in, out, 5);
    TEST_ASSERT_TRUE(r.empty());
}

void test_ring_wraps_around() {
    uint8_t store[8];
    ByteRing r;
    r.init(store, sizeof store);
    uint8_t scratch[8];
    for (int round = 0; round < 50; ++round) {  // walks the indices around many times
        uint8_t in[5];
        for (int i = 0; i < 5; ++i) in[i] = static_cast<uint8_t>(round * 5 + i);
        TEST_ASSERT_EQUAL(5, r.write(in, 5));
        TEST_ASSERT_EQUAL(5, r.read(scratch, 5));
        TEST_ASSERT_EQUAL_UINT8_ARRAY(in, scratch, 5);
    }
}

void test_ring_full_never_overwrites() {
    uint8_t store[4];
    ByteRing r;
    r.init(store, sizeof store);
    const uint8_t in[] = {9, 8, 7, 6, 5, 4};
    TEST_ASSERT_EQUAL(4, r.write(in, 6));  // only what fits
    TEST_ASSERT_EQUAL(0, r.write(in, 1));
    uint8_t out[4];
    TEST_ASSERT_EQUAL(4, r.read(out, 10));
    TEST_ASSERT_EQUAL_UINT8_ARRAY(in, out, 4);
    TEST_ASSERT_EQUAL(0, r.read(out, 1));
}

void test_ring_clear_and_uninitialised() {
    uint8_t store[4];
    ByteRing r;
    const uint8_t in[] = {1, 2};
    TEST_ASSERT_EQUAL(0, r.write(in, 2));  // no storage yet: accepts nothing, doesn't crash
    r.init(store, sizeof store);
    r.write(in, 2);
    r.clear();
    TEST_ASSERT_TRUE(r.empty());
    TEST_ASSERT_EQUAL(4, r.free_space());
}

void test_locked_ring_read_aligned() {
    uint8_t store[16];
    LockedRing r;
    r.init(store, sizeof store);
    const uint8_t in[] = {1, 2, 3, 4, 5};
    r.write(in, 5);
    uint8_t out[8];
    TEST_ASSERT_EQUAL(4, r.read_aligned(out, 8, 2));  // leaves the odd byte behind
    TEST_ASSERT_EQUAL(1, r.size());
}

// ---- speech player ----

static uint8_t speech_store[64];

static void feed_samples(SpeechPlayer &p, int16_t first, size_t count) {
    for (size_t i = 0; i < count; ++i) {
        int16_t v = static_cast<int16_t>(first + i);
        p.feed(reinterpret_cast<const uint8_t *>(&v), 2);
    }
}

void test_speech_idle_pa_off_and_ignores_frames() {
    SpeechPlayer p;
    p.init(speech_store, sizeof speech_store, 8);
    TEST_ASSERT_FALSE(p.pa_on());
    const uint8_t junk[4] = {1, 2, 3, 4};
    TEST_ASSERT_EQUAL(0, p.feed(junk, 4));  // no speech_start: dropped
    int16_t out[8];
    TEST_ASSERT_EQUAL(0, p.pull(out, 4));
}

void test_speech_prebuffer_then_play_duplicates_to_stereo() {
    SpeechPlayer p;
    p.init(speech_store, sizeof speech_store, 8);  // 4 samples of prebuffer
    p.start();
    TEST_ASSERT_EQUAL(SpeechPlayer::State::Buffering, p.state());
    feed_samples(p, 100, 3);
    TEST_ASSERT_FALSE(p.pa_on());  // still buffering: amplifier stays off
    int16_t out[16];
    TEST_ASSERT_EQUAL(0, p.pull(out, 8));
    feed_samples(p, 103, 1);
    TEST_ASSERT_TRUE(p.pa_on());
    TEST_ASSERT_EQUAL(2, p.pull(out, 2));
    const int16_t want[] = {100, 100, 101, 101};
    TEST_ASSERT_EQUAL_INT16_ARRAY(want, out, 4);
}

void test_speech_underrun_plays_silence_and_keeps_pa_on() {
    SpeechPlayer p;
    p.init(speech_store, sizeof speech_store, 2);
    p.start();
    feed_samples(p, 7, 1);
    int16_t out[8];
    memset(out, 0x55, sizeof out);
    TEST_ASSERT_EQUAL(4, p.pull(out, 4));
    const int16_t want[] = {7, 7, 0, 0, 0, 0, 0, 0};
    TEST_ASSERT_EQUAL_INT16_ARRAY(want, out, 8);
    TEST_ASSERT_TRUE(p.pa_on());
}

void test_speech_end_drains_then_pa_off() {
    SpeechPlayer p;
    p.init(speech_store, sizeof speech_store, 100);  // prebuffer larger than the clip
    p.start();
    feed_samples(p, 1, 3);
    p.end();  // short clip: end forces playback of what's there
    TEST_ASSERT_EQUAL(SpeechPlayer::State::Draining, p.state());
    TEST_ASSERT_TRUE(p.pa_on());
    int16_t out[16];
    TEST_ASSERT_EQUAL(2, p.pull(out, 2));
    TEST_ASSERT_TRUE(p.pa_on());
    TEST_ASSERT_EQUAL(1, p.pull(out, 8));
    TEST_ASSERT_EQUAL(3, out[0]);
    TEST_ASSERT_FALSE(p.pa_on());
    TEST_ASSERT_EQUAL(SpeechPlayer::State::Idle, p.state());
}

void test_speech_end_with_nothing_buffered_goes_idle() {
    SpeechPlayer p;
    p.init(speech_store, sizeof speech_store, 8);
    p.start();
    p.end();
    TEST_ASSERT_FALSE(p.active());
    TEST_ASSERT_FALSE(p.pa_on());
}

void test_speech_stop_cuts_immediately_and_drops_late_frames() {
    SpeechPlayer p;
    p.init(speech_store, sizeof speech_store, 2);
    p.start();
    feed_samples(p, 1, 10);
    TEST_ASSERT_TRUE(p.pa_on());
    p.stop();
    TEST_ASSERT_FALSE(p.pa_on());
    int16_t out[16];
    TEST_ASSERT_EQUAL(0, p.pull(out, 8));  // nothing more reaches the DAC
    feed_samples(p, 50, 4);                // frames still in flight from the server
    TEST_ASSERT_EQUAL(0, p.pull(out, 8));
    TEST_ASSERT_FALSE(p.pa_on());
}

void test_speech_overflow_counts_dropped_bytes() {
    SpeechPlayer p;
    p.init(speech_store, sizeof speech_store, 2);
    p.start();
    uint8_t big[100] = {0};
    TEST_ASSERT_EQUAL(64, p.feed(big, 100));
    TEST_ASSERT_EQUAL(36, p.dropped());
    p.start();  // a new speech resets the counter
    TEST_ASSERT_EQUAL(0, p.dropped());
}

void test_speech_new_start_discards_previous() {
    SpeechPlayer p;
    p.init(speech_store, sizeof speech_store, 2);
    p.start();
    feed_samples(p, 1, 5);
    p.start();
    feed_samples(p, 900, 2);
    int16_t out[8];
    TEST_ASSERT_EQUAL(4, p.pull(out, 4));
    TEST_ASSERT_EQUAL(900, out[0]);
    TEST_ASSERT_EQUAL(901, out[2]);
    TEST_ASSERT_EQUAL(0, out[4]);  // then silence (underrun), not the old clip
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_ring_write_read_roundtrip);
    RUN_TEST(test_ring_wraps_around);
    RUN_TEST(test_ring_full_never_overwrites);
    RUN_TEST(test_ring_clear_and_uninitialised);
    RUN_TEST(test_locked_ring_read_aligned);
    RUN_TEST(test_speech_idle_pa_off_and_ignores_frames);
    RUN_TEST(test_speech_prebuffer_then_play_duplicates_to_stereo);
    RUN_TEST(test_speech_underrun_plays_silence_and_keeps_pa_on);
    RUN_TEST(test_speech_end_drains_then_pa_off);
    RUN_TEST(test_speech_end_with_nothing_buffered_goes_idle);
    RUN_TEST(test_speech_stop_cuts_immediately_and_drops_late_frames);
    RUN_TEST(test_speech_overflow_counts_dropped_bytes);
    RUN_TEST(test_speech_new_start_discards_previous);
    return UNITY_END();
}
