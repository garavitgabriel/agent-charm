// Accelerometer -> motion events. Samples at 50 Hz (20 ms), values in g.
#include <unity.h>

#include "motion.h"

using namespace charm;

void setUp() {}
void tearDown() {}

struct Run {
    MotionDetector d;
    uint32_t t = 0;
    int face_down = 0, face_up = 0, pickup = 0, shake = 0;

    explicit Run(const MotionConfig &c = MotionConfig()) : d(c) {}

    void feed(float x, float y, float z, uint32_t ms) {
        for (uint32_t end = t + ms; t < end; t += 20) count(d.update(t, x, y, z));
    }
    void count(Motion m) {
        if (m == Motion::FaceDown) ++face_down;
        if (m == Motion::FaceUp) ++face_up;
        if (m == Motion::Pickup) ++pickup;
        if (m == Motion::Shake) ++shake;
    }
};

void test_flat_face_up_at_boot_reports_nothing() {
    Run r;
    r.feed(0, 0, 1, 5000);
    TEST_ASSERT_EQUAL(0, r.face_down + r.face_up + r.pickup + r.shake);
}

void test_face_down_then_face_up() {
    Run r;
    r.feed(0, 0, 1, 1000);
    r.feed(0, 0, -1, 1000);
    TEST_ASSERT_EQUAL(1, r.face_down);
    TEST_ASSERT_EQUAL(0, r.face_up);
    r.feed(0, 1, 0, 300);  // flipping over, on its edge
    r.feed(0, 0, 1, 1000);
    TEST_ASSERT_EQUAL(1, r.face_up);
    TEST_ASSERT_EQUAL(1, r.face_down);
}

void test_brief_face_down_below_hold_is_ignored() {
    Run r;
    r.feed(0, 0, 1, 1000);
    r.feed(0, 0, -1, 400);  // shorter than orient_hold_ms (600)
    r.feed(0, 0, 1, 1000);
    TEST_ASSERT_EQUAL(0, r.face_down);
    TEST_ASSERT_EQUAL(0, r.face_up);
}

void test_face_up_sign_is_configurable() {
    MotionConfig c;
    c.face_up_z_sign = -1.0f;  // IMU mounted upside down relative to the screen
    Run r(c);
    r.feed(0, 0, -1, 1000);
    r.feed(0, 0, 1, 1000);
    TEST_ASSERT_EQUAL(1, r.face_down);
}

void test_pickup_after_rest() {
    Run r;
    r.feed(0, 0, 1, 3000);        // resting on the table
    r.feed(0.6f, 0, 1.2f, 100);   // lifted: |a| ~1.34 g
    TEST_ASSERT_EQUAL(1, r.pickup);
    r.feed(0.6f, 0, 1.2f, 500);   // still moving: no second pickup
    TEST_ASSERT_EQUAL(1, r.pickup);
}

void test_no_pickup_without_rest() {
    Run r;
    r.feed(0, 0, 1, 500);  // not resting long enough
    r.feed(0.6f, 0, 1.2f, 100);
    TEST_ASSERT_EQUAL(0, r.pickup);
}

void test_shake_needs_several_peaks() {
    Run r;
    r.feed(0, 0, 1, 1000);
    // Two strong jolts: not a shake.
    r.feed(2, 0, 1, 20);
    r.feed(0, 0, 1, 100);
    r.feed(2, 0, 1, 20);
    r.feed(0, 0, 1, 1500);
    TEST_ASSERT_EQUAL(0, r.shake);
    // Three within the window: a shake.
    for (int i = 0; i < 3; ++i) {
        r.feed(2, 0, 1, 20);
        r.feed(0, 0, 1, 100);
    }
    TEST_ASSERT_EQUAL(1, r.shake);
}

void test_shake_cooldown() {
    Run r;
    r.feed(0, 0, 1, 1000);
    for (int i = 0; i < 9; ++i) {  // one long vigorous shake, ~1.1 s
        r.feed(2, 0, 1, 20);
        r.feed(0, 0, 1, 100);
    }
    TEST_ASSERT_EQUAL(1, r.shake);
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_flat_face_up_at_boot_reports_nothing);
    RUN_TEST(test_face_down_then_face_up);
    RUN_TEST(test_brief_face_down_below_hold_is_ignored);
    RUN_TEST(test_face_up_sign_is_configurable);
    RUN_TEST(test_pickup_after_rest);
    RUN_TEST(test_no_pickup_without_rest);
    RUN_TEST(test_shake_needs_several_peaks);
    RUN_TEST(test_shake_cooldown);
    return UNITY_END();
}
