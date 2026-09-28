// ctest suite for the shared UI: feeds every contract example card and checks the contract
// behaviors (state transitions, receipts, hold-to-confirm timing, stale labels, honesty rules).
// Touches go through LVGL's real input driver (sim_display's pointer), not direct calls.
#include "charm_ui.h"
#include "charm_ui_debug.h"
#include "dex_sprite.h"
#include "sim_display.h"
#include "test_host.h"
#include "ui_card.h"
#include "ui_hold.h"
#include "ui_motion.h"
#include "ui_time.h"

#include <ArduinoJson.h>
#include <algorithm>
#include <dirent.h>
#include <math.h>
#include <fstream>
#include <sstream>
#include <stdio.h>
#include <string.h>
#include <string>
#include <vector>

// ---------------------------------------------------------------- tiny test framework

static int g_failures = 0, g_checks = 0;
static const char *g_test = "";

#define CHECK(cond)                                                                      \
    do {                                                                                 \
        g_checks++;                                                                      \
        if (!(cond)) {                                                                   \
            g_failures++;                                                                \
            fprintf(stderr, "FAIL [%s] %s:%d: %s\n", g_test, __FILE__, __LINE__, #cond); \
        }                                                                                \
    } while (0)

#define CHECK_EQ(a, b)                                                                                    \
    do {                                                                                                  \
        g_checks++;                                                                                       \
        const auto va_ = (a);                                                                             \
        const auto vb_ = (b);                                                                             \
        if (!(va_ == vb_)) {                                                                              \
            g_failures++;                                                                                 \
            fprintf(stderr, "FAIL [%s] %s:%d: %s == %s\n", g_test, __FILE__, __LINE__, #a, #b);           \
        }                                                                                                 \
    } while (0)

// ---------------------------------------------------------------- helpers

static void run(uint32_t ms) {
    for (uint32_t t = 0; t < ms; t += 5) {
        host_advance(5);
        lv_timer_handler();
        charm_ui_tick(host.now);
    }
}

static void feed(const std::string &m) { charm_ui_on_message(m.c_str(), m.size()); }

static std::string read_file(const std::string &path) {
    std::ifstream f(path, std::ios::binary);
    std::stringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

static std::string example(const char *name) { return read_file(std::string(CHARM_EXAMPLES_DIR) + "/" + name); }
static void feed_card(const std::string &card_json) { feed("{\"type\":\"card\",\"card\":" + card_json + "}"); }
static void feed_example(const char *name) { feed_card(example(name)); }

static void welcome(const char *iso) {
    feed(std::string("{\"type\":\"welcome\",\"server\":\"test\",\"time\":\"") + iso + "\",\"tz\":\"America/Chicago\"}");
}

// A fresh UI on a fresh screen, connected, with the clock at 18:00 Chicago unless told otherwise.
static void fresh(bool with_welcome = true) {
    lv_obj_t *old = lv_scr_act();
    lv_obj_t *scr = lv_obj_create(nullptr);
    lv_scr_load(scr);
    lv_obj_del(old);
    host_reset();
    charm_ui_init();  // before any tick: the old screen's widgets are gone
    sim_pointer_set(0, 0, false);
    run(20);
    charm_ui_set_connected(true);
    if (with_welcome) welcome("2026-09-25T18:00:00-05:00");
    host.sent.clear();
}

static std::vector<JsonDocument> sent_of(const char *type) {
    std::vector<JsonDocument> out;
    for (const std::string &s : host.sent) {
        JsonDocument d;
        if (deserializeJson(d, s)) continue;
        if (strcmp(d["type"] | "", type) == 0) out.push_back(d);
    }
    return out;
}

static int displayed_count(const char *id) {
    int n = 0;
    for (auto &d : sent_of("displayed")) n += strcmp(d["id"] | "", id) == 0;
    return n;
}

static void press(lv_obj_t *obj) {
    lv_area_t a;
    lv_obj_update_layout(obj);
    lv_obj_get_coords(obj, &a);
    sim_pointer_set((a.x1 + a.x2) / 2, (a.y1 + a.y2) / 2, true);
}

static void release_at(lv_obj_t *obj) {
    lv_area_t a;
    lv_obj_update_layout(obj);
    lv_obj_get_coords(obj, &a);
    sim_pointer_set((a.x1 + a.x2) / 2, (a.y1 + a.y2) / 2, false);
}

static void click(lv_obj_t *obj) {
    press(obj);
    run(40);
    release_at(obj);
    run(40);
}

// ---------------------------------------------------------------- pure logic

static void test_iso8601() {
    int64_t e;
    int32_t off;
    CHECK(ui_parse_iso8601("1970-01-01T00:00:00Z", &e, &off));
    CHECK_EQ(e, (int64_t)0);
    CHECK(ui_parse_iso8601("2026-09-25T18:00:00-05:00", &e, &off));
    CHECK_EQ(e, (int64_t)1790377200);
    CHECK_EQ(off, -5 * 3600);
    CHECK(ui_parse_iso8601("2026-09-25T23:00:00.123Z", &e, &off));
    CHECK_EQ(e, (int64_t)1790377200);
    CHECK(ui_parse_iso8601("2026-09-26T04:30:00+0530", &e, &off));
    CHECK_EQ(e, (int64_t)1790377200);
    CHECK(!ui_parse_iso8601("2026-09-25", &e, &off));
    CHECK(!ui_parse_iso8601("2026-13-25T00:00:00Z", &e, &off));
    CHECK(!ui_parse_iso8601("yesterday", &e, &off));
    char hhmm[8];
    ui_format_hhmm(1790377200, -5 * 3600, hhmm, sizeof hhmm);
    CHECK_EQ(std::string(hhmm), std::string("18:00"));
}

static void test_money_format() {
    CHECK_EQ(ui_format_money(51300, "COP"), std::string("51,300 COP"));
    CHECK_EQ(ui_format_money(1234567, ""), std::string("1,234,567"));
    CHECK_EQ(ui_format_money(999, "COP"), std::string("999 COP"));
    CHECK_EQ(ui_format_money(12.5, "USD"), std::string("12.50 USD"));
}

static void test_hold_tracker() {
    HoldTracker h;
    uint32_t held = 0;
    h.reset(2000);
    h.press(0);
    CHECK(!h.update(1999, &held));
    CHECK(!h.release(1999, &held));  // one ms early: cancelled, nothing
    CHECK(!h.fired);
    h.press(5000);
    CHECK(h.update(7000, &held));  // completes while still pressed
    CHECK_EQ(held, 2000u);
    CHECK(!h.update(9000, &held));  // never twice
    CHECK(!h.release(9000, &held));
    h.reset(2000);
    h.press(100);
    CHECK(h.release(2150, &held));  // completes on a late release too
    CHECK_EQ(held, 2050u);
    h.reset(2000);
    h.press(0);
    h.cancel();  // finger slid off
    CHECK(!h.update(5000, &held));
}

static void test_card_parse() {
    // Every contract example parses, with its kind-specific fields.
    Card c;
    JsonDocument d;
    CHECK(!deserializeJson(d, example("money.json")));
    CHECK(ui_card_parse(d.as<JsonObjectConst>(), &c));
    CHECK(c.kind == CardKind::Money);
    CHECK_EQ(c.items.size(), (size_t)2);
    CHECK(c.fixture);
    CHECK_EQ(c.actions[0].hold_ms, 2000u);
    CHECK(!deserializeJson(d, "{\"id\":\"x\",\"kind\":\"poster\",\"title\":\"t\"}"));
    CHECK(!ui_card_parse(d.as<JsonObjectConst>(), &c));  // unknown kind
    CHECK(!deserializeJson(d, "{\"kind\":\"answer\",\"title\":\"t\"}"));
    CHECK(!ui_card_parse(d.as<JsonObjectConst>(), &c));  // no id
}

// ---------------------------------------------------------------- UI contract

struct ExampleExpect {
    const char *file, *id;
    CharmSurface surface;
};

static void test_every_example_card() {
    const ExampleExpect all[] = {
        {"answer.json", "ans-001", CharmSurface::Answer},
        {"decision.json", "dec-001", CharmSurface::Decision},
        {"edition-almanac.json", "ed-almanac", CharmSurface::Edition},
        {"edition-sports.json", "ed-sports", CharmSurface::Edition},
        {"job.json", "job-001", CharmSurface::Job},
        {"money.json", "order-001", CharmSurface::Money},
        {"notice.json", "ntc-001", CharmSurface::Answer},
        {"tracker.json", "trk-001", CharmSurface::Tracker},
    };
    // Guard: this list covers every file in contract/examples.
    size_t files = 0;
    if (DIR *dir = opendir(CHARM_EXAMPLES_DIR)) {
        while (dirent *e = readdir(dir)) files += strstr(e->d_name, ".json") != nullptr;
        closedir(dir);
    }
    CHECK_EQ(files, sizeof all / sizeof all[0]);

    for (const ExampleExpect &x : all) {
        fresh();
        CHECK(charm_ui_debug_surface() == CharmSurface::Home);
        if (x.surface == CharmSurface::Edition) {
            charm_ui_debug_swipe(LV_DIR_LEFT);
            run(20);
            CHECK(charm_ui_debug_surface() == CharmSurface::Edition);
            CHECK_EQ(sent_of("request").size(), (size_t)1);
        }
        feed_example(x.file);
        if (charm_ui_debug_surface() != x.surface) fprintf(stderr, "  (example %s)\n", x.file);
        CHECK(charm_ui_debug_surface() == x.surface);
        CHECK_EQ(charm_ui_debug_card_id(), std::string(x.id));
        CHECK_EQ(displayed_count(x.id), 1);
        // Dex never disappears. Design § 11.6 (and dex_sprite.h): full body at the one anchor on
        // every surface, never the old corner mini.
        CHECK(dex_get_size() == DEX_SIZE_FULL);
        run(200);
        CHECK_EQ(displayed_count(x.id), 1);  // one receipt per version, not per frame
    }
}

static void test_replace_and_dismiss() {
    fresh();
    feed_example("answer.json");
    CHECK_EQ(displayed_count("ans-001"), 1);
    CHECK_EQ(charm_ui_debug_card_title(), std::string("Metaphor vs simile"));
    // Same id = replace: still one card, new content, a new receipt.
    feed_card("{\"id\":\"ans-001\",\"kind\":\"answer\",\"title\":\"Revised\",\"source\":\"dex\",\"created_at\":\"2026-09-25T18:01:00-05:00\"}");
    CHECK_EQ(charm_ui_debug_card_count(), (size_t)1);
    CHECK_EQ(charm_ui_debug_card_title(), std::string("Revised"));
    CHECK_EQ(displayed_count("ans-001"), 2);
    // A second card takes focus; dismissing it returns to the first.
    feed_example("tracker.json");
    CHECK_EQ(charm_ui_debug_card_count(), (size_t)2);
    CHECK(charm_ui_debug_surface() == CharmSurface::Tracker);
    feed("{\"type\":\"dismiss\",\"card_id\":\"trk-001\"}");
    CHECK(charm_ui_debug_surface() == CharmSurface::Answer);
    CHECK_EQ(charm_ui_debug_card_id(), std::string("ans-001"));
    CHECK_EQ(displayed_count("ans-001"), 2);  // already receipted: not re-sent on return
    feed("{\"type\":\"dismiss\",\"card_id\":\"nope\"}");  // unknown id: harmless
    feed("{\"type\":\"dismiss\",\"card_id\":\"ans-001\"}");
    CHECK_EQ(charm_ui_debug_card_count(), (size_t)0);
    CHECK(charm_ui_debug_surface() == CharmSurface::Home);
}

static void test_receipt_only_when_visible() {
    fresh();
    charm_ui_talk_pressed();
    CHECK(charm_ui_debug_surface() == CharmSurface::Listening);
    feed_example("answer.json");
    CHECK(charm_ui_debug_surface() == CharmSurface::Listening);  // listening stays on top
    CHECK_EQ(displayed_count("ans-001"), 0);                        // not drawn, no receipt
    charm_ui_talk_released();
    CHECK(charm_ui_debug_surface() == CharmSurface::Answer);
    CHECK_EQ(displayed_count("ans-001"), 1);

    // Edition sections that arrive while another section is on screen get no receipt until seen.
    fresh();
    charm_ui_debug_swipe(LV_DIR_LEFT);
    run(20);
    feed_example("edition-sports.json");
    feed_example("edition-almanac.json");
    CHECK_EQ(charm_ui_debug_edition_section(), std::string("sports"));
    CHECK_EQ(displayed_count("ed-sports"), 1);
    CHECK_EQ(displayed_count("ed-almanac"), 0);
    charm_ui_debug_swipe(LV_DIR_LEFT);
    run(20);
    CHECK_EQ(charm_ui_debug_edition_section(), std::string("almanac"));
    CHECK_EQ(displayed_count("ed-almanac"), 1);
}

static void test_edition_order_and_swipes() {
    fresh();
    charm_ui_debug_swipe(LV_DIR_LEFT);
    run(20);
    CHECK(charm_ui_debug_surface() == CharmSurface::Edition);
    CHECK_EQ(sent_of("request").size(), (size_t)1);
    CHECK_EQ(std::string(sent_of("request")[0]["what"] | ""), std::string("edition"));
    // Arrive out of order; the device shows them in the protocol's order.
    const char *sections[] = {"wire", "almanac", "masthead", "sports", "one_thing", "waiting"};
    for (const char *s : sections) {
        feed_card(std::string("{\"id\":\"ed-") + s + "\",\"kind\":\"edition\",\"title\":\"" + s +
                  "\",\"source\":\"edition\",\"created_at\":\"2026-09-25T18:00:00-05:00\",\"data\":{\"section\":\"" + s +
                  "\"}}");
    }
    CHECK_EQ(charm_ui_debug_edition_count(), (size_t)6);
    CHECK_EQ(charm_ui_debug_edition_section(), std::string("masthead"));
    const char *order[] = {"masthead", "one_thing", "sports", "almanac", "waiting", "wire"};
    for (int i = 1; i < 6; i++) {
        charm_ui_debug_swipe(LV_DIR_LEFT);
        run(20);
        CHECK_EQ(charm_ui_debug_edition_section(), std::string(order[i]));
    }
    charm_ui_debug_swipe(LV_DIR_LEFT);  // past the end: stays on the wire
    run(20);
    CHECK_EQ(charm_ui_debug_edition_section(), std::string("wire"));
    charm_ui_debug_swipe(LV_DIR_RIGHT);
    run(20);
    CHECK_EQ(charm_ui_debug_edition_section(), std::string("waiting"));
    for (const char *s : order) CHECK_EQ(displayed_count((std::string("ed-") + s).c_str()), 1);
    charm_ui_debug_swipe(LV_DIR_BOTTOM);
    run(20);
    CHECK(charm_ui_debug_surface() == CharmSurface::Home);
}

static void test_stale_labels() {
    // Producer-flagged stale shows even with no clock.
    fresh(false);
    feed_example("notice.json");
    CHECK(charm_ui_debug_stale_shown());

    // fresh_until with an unknown clock: the device can't judge it, so it doesn't claim stale.
    fresh(false);
    charm_ui_debug_swipe(LV_DIR_LEFT);
    run(20);
    feed_example("edition-sports.json");
    CHECK(!charm_ui_debug_stale_shown());

    // Before fresh_until (23:59 Chicago): fresh.
    fresh();
    feed_example("answer.json");
    CHECK(!charm_ui_debug_stale_shown());
    charm_ui_debug_swipe(LV_DIR_BOTTOM);
    run(20);
    charm_ui_debug_swipe(LV_DIR_LEFT);
    run(20);
    feed_example("edition-sports.json");
    CHECK(!charm_ui_debug_stale_shown());

    // Past fresh_until at arrival: stale.
    fresh(false);
    welcome("2026-09-26T08:00:00-05:00");
    charm_ui_debug_swipe(LV_DIR_LEFT);
    run(20);
    feed_example("edition-almanac.json");
    CHECK(charm_ui_debug_stale_shown());
}

// Goes stale while on screen: the label appears on its own when fresh_until passes.
static void test_stale_crossing() {
    fresh(false);
    welcome("2026-09-25T23:58:00-05:00");
    charm_ui_debug_swipe(LV_DIR_LEFT);
    run(20);
    feed_example("edition-sports.json");
    CHECK(!charm_ui_debug_stale_shown());
    run(30000);  // 23:58:30
    CHECK(!charm_ui_debug_stale_shown());
    run(32000);  // 23:59:02, past 23:59:00
    CHECK(charm_ui_debug_stale_shown());
    CHECK_EQ(charm_ui_debug_surface() == CharmSurface::Edition, true);
}

static void test_hold_to_confirm() {
    fresh();
    feed_example("money.json");
    run(20);
    lv_obj_t *confirm = charm_ui_debug_action_button("confirm");
    CHECK(confirm != nullptr);
    if (!confirm) return;

    // A quick tap sends nothing.
    click(confirm);
    CHECK_EQ(sent_of("action").size(), (size_t)0);

    // Early release (1.5 s of 2 s): cancelled, nothing sent, progress resets.
    press(confirm);
    run(1500);
    CHECK(charm_ui_debug_hold_progress() > 0.6f);
    release_at(confirm);
    run(40);
    CHECK_EQ(sent_of("action").size(), (size_t)0);
    CHECK(charm_ui_debug_hold_progress() == 0.0f);
    run(3000);  // time passing afterwards doesn't complete it either
    CHECK_EQ(sent_of("action").size(), (size_t)0);

    // A continuous hold of >= hold_ms sends exactly one action with held_ms.
    confirm = charm_ui_debug_action_button("confirm");
    press(confirm);
    run(2100);
    auto actions = sent_of("action");
    CHECK_EQ(actions.size(), (size_t)1);
    if (!actions.empty()) {
        CHECK_EQ(std::string(actions[0]["card_id"] | ""), std::string("order-001"));
        CHECK_EQ(std::string(actions[0]["action"] | ""), std::string("confirm"));
        CHECK(actions[0]["held_ms"].is<unsigned>());
        const unsigned held = actions[0]["held_ms"] | 0u;
        CHECK(held >= 2000u && held < 2100u);
    }
    sim_pointer_set(0, 0, false);
    run(500);
    CHECK_EQ(sent_of("action").size(), (size_t)1);  // releasing afterwards sends nothing more
    CHECK(!charm_ui_debug_done_shown());             // no check before the backend confirms
    CHECK(charm_ui_debug_action_button("confirm") == nullptr);  // can't be sent twice

    // A new frame arriving mid-hold abandons the hold rather than completing it blind.
    fresh();
    feed_example("money.json");
    run(20);
    confirm = charm_ui_debug_action_button("confirm");
    press(confirm);
    run(1000);
    feed("{\"type\":\"state\",\"value\":\"working\"}");
    run(1500);
    CHECK_EQ(sent_of("action").size(), (size_t)0);
    sim_pointer_set(0, 0, false);
    run(40);

    // The money card's non-hold action is a plain tap without held_ms.
    fresh();
    feed_example("money.json");
    run(20);
    click(charm_ui_debug_action_button("reject"));
    actions = sent_of("action");
    CHECK_EQ(actions.size(), (size_t)1);
    if (!actions.empty()) {
        CHECK_EQ(std::string(actions[0]["action"] | ""), std::string("reject"));
        CHECK(actions[0]["held_ms"].isNull());
    }
}

static void test_decision_confirmation() {
    fresh();
    feed_example("decision.json");
    CHECK(charm_ui_debug_surface() == CharmSurface::Decision);
    CHECK(charm_ui_debug_action_button("approve") && charm_ui_debug_action_button("reject") &&
          charm_ui_debug_action_button("snooze"));
    click(charm_ui_debug_action_button("approve"));
    auto actions = sent_of("action");
    CHECK_EQ(actions.size(), (size_t)1);
    if (!actions.empty()) {
        CHECK_EQ(std::string(actions[0]["card_id"] | ""), std::string("dec-001"));
        CHECK_EQ(std::string(actions[0]["action"] | ""), std::string("approve"));
    }
    CHECK(!charm_ui_debug_done_shown());  // sent is not confirmed
    feed("{\"type\":\"state\",\"value\":\"done\"}");
    CHECK(charm_ui_debug_done_shown());
    CHECK(dex_get_pose() == DEX_POSE_DONE);
    feed("{\"type\":\"dismiss\",\"card_id\":\"dec-001\"}");
    CHECK(charm_ui_debug_surface() == CharmSurface::Home);
    run(5000);
    CHECK(dex_get_pose() == DEX_POSE_IDLE);  // the done pose settles back
}

static void test_job_actions() {
    fresh();
    feed_example("job.json");
    click(charm_ui_debug_action_button("send_claude"));
    auto actions = sent_of("action");
    CHECK_EQ(actions.size(), (size_t)1);
    if (!actions.empty()) CHECK_EQ(std::string(actions[0]["action"] | ""), std::string("send_claude"));
}

static void test_listening_honesty() {
    // The mic didn't start: never show listening.
    fresh();
    host.mic_result = false;
    charm_ui_talk_pressed();
    CHECK_EQ(host.mic_starts, 1);
    CHECK(!charm_ui_debug_listening());
    CHECK(charm_ui_debug_surface() != CharmSurface::Listening);
    CHECK(dex_get_pose() != DEX_POSE_LISTENING);
    charm_ui_talk_released();
    CHECK(host.mic_stops.empty());

    // The server's listening echo is not a command.
    fresh();
    feed("{\"type\":\"state\",\"value\":\"listening\"}");
    CHECK(charm_ui_debug_surface() != CharmSurface::Listening);
    CHECK(dex_get_pose() != DEX_POSE_LISTENING);

    // The mic started: listening, then released -> working.
    fresh();
    charm_ui_talk_pressed();
    CHECK(charm_ui_debug_listening());
    CHECK(charm_ui_debug_surface() == CharmSurface::Listening);
    CHECK(dex_get_pose() == DEX_POSE_LISTENING);
    charm_ui_mic_level(0.5f);
    run(1000);
    charm_ui_talk_released();
    CHECK_EQ(host.mic_stops.size(), (size_t)1);
    if (!host.mic_stops.empty()) CHECK_EQ(host.mic_stops[0], std::string("released"));
    CHECK(charm_ui_debug_surface() == CharmSurface::Working);
    feed("{\"type\":\"state\",\"value\":\"transcribing\"}");
    feed("{\"type\":\"state\",\"value\":\"working\",\"agent\":\"dex\"}");
    CHECK(charm_ui_debug_surface() == CharmSurface::Working);
    feed("{\"type\":\"state\",\"value\":\"idle\"}");
    CHECK(charm_ui_debug_surface() == CharmSurface::Home);

    // The 25 s limit stops the mic with reason "limit".
    fresh();
    charm_ui_talk_pressed();
    run(24900);
    CHECK(charm_ui_debug_listening());
    run(200);
    CHECK(!charm_ui_debug_listening());
    CHECK_EQ(host.mic_stops.size(), (size_t)1);
    if (!host.mic_stops.empty()) CHECK_EQ(host.mic_stops[0], std::string("limit"));
    charm_ui_talk_released();  // the late release is a no-op
    CHECK_EQ(host.mic_stops.size(), (size_t)1);
}

static void test_offline_only_from_host() {
    fresh();
    feed("{\"type\":\"state\",\"value\":\"offline\"}");
    CHECK(charm_ui_debug_surface() != CharmSurface::Offline);
    CHECK(dex_get_pose() != DEX_POSE_OFFLINE);
    feed_example("decision.json");
    charm_ui_set_connected(false);
    CHECK(charm_ui_debug_surface() == CharmSurface::Offline);
    CHECK(dex_get_pose() == DEX_POSE_OFFLINE);
    charm_ui_talk_pressed();  // no mic while offline: nothing to stream to
    CHECK_EQ(host.mic_starts, 0);
    CHECK(charm_ui_debug_surface() == CharmSurface::Offline);
    charm_ui_set_connected(true);
    CHECK(charm_ui_debug_surface() == CharmSurface::Decision);  // the card is still held

    // Dropping mid-talk cancels the capture.
    fresh();
    charm_ui_talk_pressed();
    charm_ui_set_connected(false);
    CHECK(!charm_ui_debug_listening());
    CHECK_EQ(host.mic_stops.size(), (size_t)1);
    if (!host.mic_stops.empty()) CHECK_EQ(host.mic_stops[0], std::string("cancel"));
}

static void test_errors_and_garbage() {
    fresh();
    feed("{\"type\":\"error\",\"code\":\"no_speech\",\"text\":\"I didn't catch that.\"}");
    CHECK(charm_ui_debug_surface() == CharmSurface::Error);
    CHECK(dex_get_pose() == DEX_POSE_ERROR);
    charm_ui_debug_tap();
    run(20);
    CHECK(charm_ui_debug_surface() == CharmSurface::Home);

    const char *junk[] = {"", "not json", "{", "[]", "{\"type\":42}", "{\"type\":\"unknown_thing\"}",
                          "{\"type\":\"card\"}", "{\"type\":\"card\",\"card\":{\"kind\":\"answer\"}}",
                          "{\"type\":\"state\",\"value\":\"dancing\"}", "{\"type\":\"pong\"}"};
    for (const char *j : junk) feed(j);
    CHECK(charm_ui_debug_surface() == CharmSurface::Home);
    CHECK_EQ(charm_ui_debug_card_count(), (size_t)0);
    CHECK(host.sent.empty());
}

static void test_working_cancel_and_interrupt() {
    fresh();
    feed("{\"type\":\"state\",\"value\":\"working\",\"agent\":\"coach\"}");
    CHECK(charm_ui_debug_surface() == CharmSurface::Working);
    CHECK(dex_get_pose() == DEX_POSE_WORKING);
    lv_obj_t *cancel = charm_ui_debug_cancel_button();
    CHECK(cancel != nullptr);
    if (cancel) click(cancel);
    CHECK_EQ(sent_of("cancel").size(), (size_t)1);

    // Tapping the answer while Dex speaks stops playback and cancels the job.
    fresh();
    feed_example("answer.json");
    feed("{\"type\":\"speech_start\",\"rate\":16000,\"format\":\"s16le\",\"channels\":1}");
    CHECK(dex_get_pose() == DEX_POSE_SPEAKING);
    charm_ui_debug_tap();
    run(20);
    CHECK_EQ(host.speech_stops, 1);
    CHECK_EQ(sent_of("cancel").size(), (size_t)1);
}

static void test_night_and_modes() {
    fresh();
    feed("{\"type\":\"mode\",\"value\":\"gameday\"}");
    CHECK(dex_get_outfit() == DEX_OUTFIT_GAMEDAY);
    feed("{\"type\":\"mode\",\"value\":\"disco\"}");  // unknown: unchanged
    CHECK(dex_get_outfit() == DEX_OUTFIT_GAMEDAY);

    run(59000);
    CHECK(!charm_ui_debug_night());
    run(2000);
    CHECK(charm_ui_debug_night());
    CHECK(charm_ui_debug_surface() == CharmSurface::Night);
    CHECK_EQ(host.brightness, (uint8_t)16);
    CHECK(dex_get_pose() == DEX_POSE_ASLEEP);
    charm_ui_talk_pressed();  // any interaction wakes it
    CHECK(!charm_ui_debug_night());
    CHECK_EQ(host.brightness, (uint8_t)255);
    CHECK(charm_ui_debug_surface() == CharmSurface::Listening);
    charm_ui_talk_released();

    // A waiting card keeps it awake; a new card wakes it.
    fresh();
    run(61000);
    CHECK(charm_ui_debug_night());
    feed_example("tracker.json");
    CHECK(!charm_ui_debug_night());
    CHECK(charm_ui_debug_surface() == CharmSurface::Tracker);
    run(61000);
    CHECK(!charm_ui_debug_night());
}

static void test_hidden_card_and_home_tap() {
    fresh();
    feed_example("decision.json");
    charm_ui_debug_swipe(LV_DIR_BOTTOM);
    run(20);
    CHECK(charm_ui_debug_surface() == CharmSurface::Home);
    CHECK(dex_get_pose() == DEX_POSE_ATTENTION);  // something is waiting
    charm_ui_debug_tap();
    run(20);
    CHECK(charm_ui_debug_surface() == CharmSurface::Decision);
    CHECK_EQ(displayed_count("dec-001"), 1);
}

// docs/PROTOCOL.md clarifications (2026-09-25): errors are followed by state{idle}; a rejected money
// hold leaves the card retryable; a fixture confirm comes back as a notice with no check.
static void test_protocol_clarifications() {
    fresh();
    feed("{\"type\":\"error\",\"code\":\"agent_timeout\",\"text\":\"Dex didn't answer.\"}");
    feed("{\"type\":\"state\",\"value\":\"idle\"}");
    CHECK(charm_ui_debug_surface() == CharmSurface::Error);  // the idle doesn't hide the error

    fresh();
    feed_example("money.json");
    run(20);
    press(charm_ui_debug_action_button("confirm"));
    run(2100);
    sim_pointer_set(0, 0, false);
    run(40);
    CHECK_EQ(sent_of("action").size(), (size_t)1);
    CHECK(charm_ui_debug_action_button("confirm") == nullptr);
    feed("{\"type\":\"error\",\"code\":\"too_short\",\"text\":\"Hold for 2 seconds.\"}");
    feed("{\"type\":\"state\",\"value\":\"idle\"}");
    charm_ui_debug_tap();
    run(20);
    CHECK(charm_ui_debug_surface() == CharmSurface::Money);  // the card stayed in place
    CHECK(charm_ui_debug_action_button("confirm") != nullptr);  // and can be held again

    fresh();
    feed_example("money.json");
    run(20);
    press(charm_ui_debug_action_button("confirm"));
    run(2100);
    sim_pointer_set(0, 0, false);
    run(40);
    feed_card("{\"id\":\"order-001\",\"kind\":\"notice\",\"title\":\"Sample order: nothing was charged\","
              "\"source\":\"delivery\",\"created_at\":\"2026-09-25T18:00:00-05:00\"}");
    CHECK(charm_ui_debug_surface() == CharmSurface::Answer);
    CHECK_EQ(charm_ui_debug_card_count(), (size_t)1);
    CHECK(!charm_ui_debug_done_shown());
    CHECK_EQ(displayed_count("order-001"), 2);

    // An edition section with only a failure footer and no edition_no still renders, labeled stale.
    fresh();
    charm_ui_debug_swipe(LV_DIR_LEFT);
    run(20);
    feed_card("{\"id\":\"ed-sports\",\"kind\":\"edition\",\"title\":\"Sports desk\",\"source\":\"edition\","
              "\"created_at\":\"2026-09-25T18:00:00-05:00\",\"stale\":true,"
              "\"footer\":\"Sports desk missed deadline - last filed 04:10\",\"data\":{\"section\":\"sports\"}}");
    CHECK_EQ(charm_ui_debug_edition_section(), std::string("sports"));
    CHECK(charm_ui_debug_stale_shown());
}

// The UI lives in LVGL's 96 KB pool on the device: the heaviest surface must fit with headroom, and
// rebuilding surfaces over and over must not leak.
static void test_lvgl_memory() {
    fresh();
    lv_mem_monitor_t m;
    feed_example("money.json");
    feed_example("decision.json");
    feed_example("job.json");
    run(40);
    lv_mem_monitor(&m);
    const size_t used_start = m.total_size - m.free_size;
    CHECK(m.used_pct < 60);
    for (int i = 0; i < 100; i++) {
        feed("{\"type\":\"state\",\"value\":\"working\"}");
        feed("{\"type\":\"state\",\"value\":\"idle\"}");
        feed_example("decision.json");
        charm_ui_debug_swipe(LV_DIR_BOTTOM);
        run(10);
        charm_ui_debug_tap();
        run(10);
    }
    run(40);
    lv_mem_monitor(&m);
    const size_t used_end = m.total_size - m.free_size;
    CHECK(used_end <= used_start + 1024);  // allow fragmentation slack, not growth
    fprintf(stderr, "  lvgl pool: %u%% used, %u bytes free of %u\n", (unsigned)m.used_pct, (unsigned)m.free_size,
            (unsigned)m.total_size);
}

// ---------------------------------------------------------------- design § 11 motion + reading (batch 9)

static lv_obj_t *ui_button(const char *id) { return charm_ui_debug_ui_button(id); }

static const char *const READING_BOOK = "{\"title\":\"Piranesi\",\"author\":\"Susanna Clarke\",\"chapter\":\"7\"}";

static void enter_reading() {
    feed(std::string("{\"type\":\"mode\",\"value\":\"reading\",\"book\":") + READING_BOOK + "}");
}

// motion.md: the separator fuse grows 0 -> 320 px over the 25 s listen limit (contract, not the
// render's 30 s), in 250 ms steps, and the recording ends at the end of the fuse.
static void test_fuse_25s() {
    CHECK_EQ(motion::fuse_px(0, 320), 0);
    CHECK_EQ(motion::fuse_px(249, 320), 0);
    CHECK_EQ(motion::fuse_px(250, 320), 3);            // 320 * 250 / 25000 = 3.2 -> 3
    CHECK_EQ(motion::fuse_px(12500, 320), 160);        // half the listen limit, half the rule
    CHECK_EQ(motion::fuse_px(12600, 320), 160);        // redrawn only every 250 ms
    CHECK_EQ(motion::fuse_px(25000, 320), 320);
    CHECK_EQ(motion::FUSE_MS, (uint32_t)25000);

    fresh();
    charm_ui_talk_pressed();
    CHECK(charm_ui_debug_listening());
    run(12500);
    CHECK(charm_ui_debug_fuse_px() >= 155 && charm_ui_debug_fuse_px() <= 160);
    run(12400);  // 24.9 s: still listening, the fuse is almost full
    CHECK(charm_ui_debug_listening());
    CHECK(charm_ui_debug_fuse_px() > 310 && charm_ui_debug_fuse_px() < 320);
    run(200);  // past 25 s: ends as if released, with reason "limit"
    CHECK(!charm_ui_debug_listening());
    CHECK_EQ(host.mic_stops.size(), (size_t)1);
    if (!host.mic_stops.empty()) CHECK_EQ(host.mic_stops[0], std::string("limit"));
    CHECK(charm_ui_debug_surface() == CharmSurface::Working);
    run(300);  // the fuse fades out over 200 ms
    CHECK_EQ(charm_ui_debug_fuse_px(), 0);

    // Released early: the fuse stops and fades; nothing about it says "limit".
    fresh();
    charm_ui_talk_pressed();
    run(3000);
    charm_ui_talk_released();
    CHECK_EQ(host.mic_stops.size(), (size_t)1);
    if (!host.mic_stops.empty()) CHECK_EQ(host.mic_stops[0], std::string("released"));
    run(300);
    CHECK_EQ(charm_ui_debug_fuse_px(), 0);
}

// The voice stream spawns from mic amplitude (80 ms samples), never in silence, and drains on release.
static void test_voice_stream() {
    motion::VoiceStream vs;
    vs.begin(1000);
    vs.update(1100, 0.9f);  // before the 120 ms first-capsule delay
    CHECK(vs.empty());
    vs.update(1120, 0.9f);
    CHECK_EQ(vs.caps.size(), (size_t)1);
    vs.update(1600, 0.0f);  // silence: no spawns
    CHECK_EQ(vs.caps.size(), (size_t)1);
    CHECK(vs.caps[0].width >= 4.0f && vs.caps[0].width <= 10.0f);
    CHECK(vs.caps[0].len >= 0.04f && vs.caps[0].len <= 0.12f);
    vs.update(1120 + 900 + 200, 0.0f);  // transit 900 ms: gone at the hand
    CHECK(vs.empty());
    const motion::Pt edge = motion::stream_point(0, {306, 306}), hand = motion::stream_point(1, {306, 306});
    CHECK(edge.x < 0 && hand.x == 306 && hand.y == 306);

    fresh();
    charm_ui_talk_pressed();
    run(1000);
    CHECK_EQ(charm_ui_debug_capsules(), (size_t)0);  // silence
    charm_ui_mic_level(0.7f);
    run(400);
    CHECK(charm_ui_debug_capsules() >= 3);
    charm_ui_talk_released();  // capsules in flight finish; no new ones
    run(1200);
    CHECK_EQ(charm_ui_debug_capsules(), (size_t)0);
}

// The 2 s bag hold: 20 fill steps, "Ordering…" on the first tick, an early release drains in 300 ms
// and sends nothing, a full hold sends held_ms, and Done appears only after the server confirms.
static void test_bag_hold_timing() {
    motion::BagFill f;
    f.press(0, 2000);
    CHECK(f.level(99) == 0.0f);
    CHECK(fabsf(f.level(100) - 0.05f) < 1e-6f);
    CHECK(fabsf(f.level(1250) - 0.60f) < 1e-6f);  // 12 of 20 steps
    CHECK(fabsf(f.level(1999) - 0.95f) < 1e-6f);
    CHECK(f.level(2000) == 1.0f);
    f.release(1000);  // at 0.5
    CHECK(fabsf(f.level(1000) - 0.5f) < 1e-6f);
    CHECK(f.level(1100) < 0.5f && f.level(1100) > 0.0f);
    CHECK(f.level(1300) == 0.0f);

    fresh();
    feed_example("money.json");
    run(20);
    CHECK_EQ(charm_ui_debug_hold_label(), std::string("Hold Dex\nto order"));
    CHECK(dex_get_pose() == DEX_POSE_OFFER_BAG);
    lv_obj_t *bag = charm_ui_debug_action_button("confirm");
    CHECK(bag != nullptr);
    if (!bag) return;
    // The hold control is Dex's bag: in the anchor zone, right of the rail, >= 56 px.
    lv_area_t a;
    lv_obj_get_coords(bag, &a);
    CHECK(a.y1 >= 209 && a.x1 > 172);
    CHECK(lv_area_get_width(&a) >= 56 && lv_area_get_height(&a) >= 56);

    press(bag);
    run(60);
    CHECK_EQ(charm_ui_debug_hold_label(), std::string("Ordering\xE2\x80\xA6"));
    CHECK(dex_get_pose() == DEX_POSE_LIFT_BAG);
    run(1140);  // ~1.2 s held
    CHECK(charm_ui_debug_bag_fill() >= 0.55f && charm_ui_debug_bag_fill() <= 0.65f);
    release_at(bag);
    run(40);
    CHECK_EQ(sent_of("action").size(), (size_t)0);  // early release sends nothing
    CHECK(charm_ui_debug_bag_fill() > 0.0f);        // ...and drains rather than snapping
    run(300);
    CHECK_EQ(charm_ui_debug_bag_fill(), 0.0f);
    CHECK_EQ(charm_ui_debug_hold_label(), std::string("Hold Dex\nto order"));
    CHECK(dex_get_pose() == DEX_POSE_OFFER_BAG);
    CHECK(charm_ui_debug_surface() == CharmSurface::Money);  // no message, no error

    bag = charm_ui_debug_action_button("confirm");
    press(bag);
    run(2100);
    auto actions = sent_of("action");
    CHECK_EQ(actions.size(), (size_t)1);
    if (!actions.empty()) CHECK((actions[0]["held_ms"] | 0u) >= 2000u);
    sim_pointer_set(0, 0, false);
    run(400);
    CHECK(charm_ui_debug_surface() == CharmSurface::Money);  // sent is not confirmed: no Done
    CHECK_EQ(charm_ui_debug_bag_fill(), 1.0f);                // the full bag, waiting
    CHECK(!charm_ui_debug_done_shown());
    feed("{\"type\":\"state\",\"value\":\"done\"}");
    CHECK(charm_ui_debug_surface() == CharmSurface::Done);
    CHECK(charm_ui_debug_done_shown());
    CHECK(dex_get_pose() == DEX_POSE_DONE);
    // money.json is a fixture: even confirmed, it never claims "Ordered."
    CHECK_EQ(charm_ui_debug_headline(), std::string("Sample order."));

    // A non-fixture order says "Ordered." once confirmed.
    fresh();
    std::string real = example("money.json");
    const size_t fx = real.find("\"fixture\":true");
    CHECK(fx != std::string::npos);
    if (fx != std::string::npos) real.replace(fx, strlen("\"fixture\":true"), "\"fixture\":false");
    feed_card(real);
    run(20);
    press(charm_ui_debug_action_button("confirm"));
    run(2100);
    sim_pointer_set(0, 0, false);
    run(100);
    CHECK(charm_ui_debug_surface() == CharmSurface::Money);
    feed("{\"type\":\"state\",\"value\":\"done\"}");
    CHECK(charm_ui_debug_surface() == CharmSurface::Done);
    CHECK_EQ(charm_ui_debug_headline(), std::string("Ordered."));
}

// Content exit (120 ms) + staggered enter never costs a receipt, however fast frames arrive.
static void test_enter_exit_receipts() {
    fresh();
    feed_example("decision.json");
    CHECK(charm_ui_debug_transitioning());
    feed_example("job.json");      // arrives while the decision is still entering
    feed_example("tracker.json");  // and again, mid-exit of the job
    CHECK_EQ(displayed_count("dec-001"), 1);
    CHECK_EQ(displayed_count("job-001"), 1);
    CHECK_EQ(displayed_count("trk-001"), 1);
    CHECK(charm_ui_debug_surface() == CharmSurface::Tracker);
    run(700);
    CHECK(!charm_ui_debug_transitioning());
    CHECK_EQ(displayed_count("trk-001"), 1);
    // Dismissing mid-transition returns to the previous card, which already has its receipt.
    feed("{\"type\":\"dismiss\",\"card_id\":\"trk-001\"}");
    run(30);
    CHECK(charm_ui_debug_surface() == CharmSurface::Job);
    CHECK_EQ(displayed_count("job-001"), 1);
    // A replaced card (same id) earns a fresh receipt, even mid-enter.
    feed_card("{\"id\":\"job-001\",\"kind\":\"job\",\"title\":\"PR #42 re-reviewed\",\"source\":\"github\","
              "\"created_at\":\"2026-09-25T18:00:00-05:00\"}");
    CHECK_EQ(displayed_count("job-001"), 2);
    // Buttons are live while their content is still entering.
    fresh();
    feed_example("job.json");
    click(charm_ui_debug_action_button("send_claude"));
    CHECK_EQ(sent_of("action").size(), (size_t)1);
}

// Speak/quiet is shown only from the server's `setting` echo; a tap alone changes nothing.
static void test_reading_toggle_echo() {
    fresh();
    enter_reading();
    CHECK(charm_ui_debug_surface() == CharmSurface::ReadingHome);
    CHECK(dex_get_outfit() == DEX_OUTFIT_READING);
    CHECK_EQ(charm_ui_debug_headline(), std::string("Piranesi"));
    CHECK_EQ(charm_ui_debug_speech(), std::string("off"));  // PROTOCOL: reading defaults to quiet
    click(ui_button("speech"));
    auto settings = sent_of("setting");
    CHECK_EQ(settings.size(), (size_t)1);
    if (!settings.empty()) {
        CHECK_EQ(std::string(settings[0]["name"] | ""), std::string("speech"));
        CHECK_EQ(std::string(settings[0]["value"] | ""), std::string("on"));
    }
    run(500);
    CHECK_EQ(charm_ui_debug_speech(), std::string("off"));  // no echo yet: unchanged
    feed("{\"type\":\"setting\",\"name\":\"speech\",\"value\":\"on\"}");
    CHECK_EQ(charm_ui_debug_speech(), std::string("on"));

    // No echo at all: after 3 s the toggle springs back and the state never changed.
    host.sent.clear();
    click(ui_button("speech"));
    CHECK_EQ(sent_of("setting").size(), (size_t)1);
    run(3200);
    CHECK_EQ(charm_ui_debug_speech(), std::string("on"));
    // An echo that disagrees with the tap wins (the server decides).
    feed("{\"type\":\"setting\",\"name\":\"speech\",\"value\":\"on\"}");
    CHECK_EQ(charm_ui_debug_speech(), std::string("on"));
    feed("{\"type\":\"mode\",\"value\":\"default\"}");
    CHECK(charm_ui_debug_surface() == CharmSurface::Home);
}

// Saved only on data.saved:true; "Not saved." (no check, Offline frown) on false.
static void test_saved_true_false() {
    fresh();
    enter_reading();
    feed_card(example("reading/notice-saved.json"));
    CHECK(charm_ui_debug_surface() == CharmSurface::Saved);
    CHECK_EQ(charm_ui_debug_headline(), std::string("Saved."));
    CHECK(dex_get_pose() == DEX_POSE_DONE);
    CHECK(charm_ui_debug_headline().find("\xE2\x9C\x93") == std::string::npos);  // no ✓
    CHECK_EQ(displayed_count("ntc-saved-001"), 1);

    fresh();
    enter_reading();
    feed("{\"type\":\"state\",\"value\":\"working\",\"label\":\"Saving\"}");
    CHECK(charm_ui_debug_surface() == CharmSurface::Working);
    feed("{\"type\":\"error\",\"code\":\"save_failed\",\"text\":\"The note store didn't confirm.\"}");
    feed_card("{\"id\":\"ntc-f\",\"kind\":\"notice\",\"title\":\"Not saved\",\"body\":\"Not saved.\",\"source\":\"dex\","
              "\"created_at\":\"2026-09-27T21:12:00-05:00\",\"data\":{\"saved\":false}}");
    feed("{\"type\":\"state\",\"value\":\"idle\"}");
    CHECK(charm_ui_debug_surface() == CharmSurface::Saved);
    CHECK_EQ(charm_ui_debug_headline(), std::string("Not saved."));
    CHECK(dex_get_pose() == DEX_POSE_OFFLINE);
    CHECK(dex_get_pose() != DEX_POSE_DONE);

    // A plain notice is not a save receipt.
    fresh();
    feed_example("notice.json");
    CHECK(charm_ui_debug_surface() == CharmSurface::Answer);
}

// The lead + detail share one column that rests on whole lines; text size steps 18/22/26.
static void test_reading_answer_scroll() {
    fresh();
    enter_reading();
    feed_card(example("reading/answer-reading.json"));
    CHECK(charm_ui_debug_surface() == CharmSurface::ReadingAnswer);
    CHECK_EQ(charm_ui_debug_scroll(), 0);
    CHECK(charm_ui_debug_scroll_max() > 0);
    CHECK(dex_get_pose() != DEX_POSE_SPEAKING);  // quiet: no talking mouth
    CHECK(ui_button("read_more") != nullptr);
    click(ui_button("read_more"));
    run(400);
    const int top = charm_ui_debug_scroll();
    CHECK(top > 0);
    CHECK(ui_button("read_more") == nullptr);  // in the detail: the size controls instead
    CHECK(ui_button("larger") != nullptr && ui_button("smaller") != nullptr);
    CHECK_EQ(charm_ui_debug_read_step(), 1);
    click(ui_button("larger"));
    run(700);
    CHECK_EQ(charm_ui_debug_read_step(), 2);
    CHECK(ui_button("larger") == nullptr);  // at the end, that control isn't drawn
    // Snapping: a drag leaves the column on the line grid.
    CHECK_EQ(motion::snap_scroll(47, 21, 5, 160, 32, 400), 42);
    CHECK_EQ(motion::snap_scroll(190, 21, 5, 160, 32, 400), 192);
    CHECK_EQ(motion::snap_scroll(999, 21, 5, 160, 32, 400), 400);
    int x = 0, len = 0;
    CHECK(!motion::scroll_thumb(0, 100, 160, 24, 320, &x, &len));  // fits: no thumb
    CHECK(motion::scroll_thumb(0, 640, 160, 24, 320, &x, &len) && x == 24 && len == 80);
    CHECK(motion::scroll_thumb(480, 640, 160, 24, 320, &x, &len) && x + len == 344);
    // Swipe right: detail -> lead -> reading home.
    charm_ui_debug_swipe(LV_DIR_RIGHT);
    run(400);
    CHECK_EQ(charm_ui_debug_scroll(), 0);
    charm_ui_debug_swipe(LV_DIR_RIGHT);
    run(30);
    CHECK(charm_ui_debug_surface() == CharmSurface::ReadingHome);
    // Speech in reading shows the speaking pose only while speech actually plays.
    charm_ui_debug_tap();
    run(30);
    feed("{\"type\":\"speech_start\",\"rate\":16000,\"format\":\"s16le\",\"channels\":1}");
    CHECK(dex_get_pose() == DEX_POSE_SPEAKING);
}

// Every surface: the design's single scale and zones (no mini Dex, nothing in the content zone below 190).
static void test_design_invariants() {
    fresh();
    CHECK(dex_get_size() == DEX_SIZE_FULL);
    CHECK_EQ(charm_ui_debug_headline(), std::string("Nothing needs you"));
    feed("{\"type\":\"state\",\"value\":\"working\",\"agent\":\"dex\",\"label\":\"Asking Dex...\"}");
    run(1300);
    CHECK_EQ(charm_ui_debug_headline(), std::string("Asking Dex"));  // dots step on their own
    charm_ui_set_connected(false);
    CHECK_EQ(charm_ui_debug_headline(), std::string("No connection"));
    CHECK(dex_get_size() == DEX_SIZE_FULL);
    charm_ui_set_connected(true);
    // A decision with no default is "needs more": Dex shrugs, every choice is a pill.
    feed_card("{\"id\":\"q-1\",\"kind\":\"decision\",\"title\":\"Downtown or Riverside?\",\"source\":\"dex\","
              "\"created_at\":\"2026-09-25T18:00:00-05:00\",\"data\":{\"deadline\":\"now\"},"
              "\"actions\":[{\"id\":\"a\",\"label\":\"Downtown\"},{\"id\":\"b\",\"label\":\"Riverside\"}]}");
    CHECK(charm_ui_debug_surface() == CharmSurface::NeedsMore);
    CHECK(dex_get_pose() == DEX_POSE_ERROR);
    CHECK(charm_ui_debug_action_button("a") && charm_ui_debug_action_button("b"));
    // The decision's default rides on Dex's placard (in the anchor zone, right of the rail).
    fresh();
    feed_example("decision.json");
    CHECK(dex_get_pose() == DEX_POSE_ASK_YES);
    lv_area_t a;
    lv_obj_get_coords(charm_ui_debug_action_button("approve"), &a);
    CHECK(a.y1 >= 209 && a.x1 > 240);
}

int main() {
    sim_display_init();
    struct {
        const char *name;
        void (*fn)();
    } tests[] = {
        {"iso8601", test_iso8601},
        {"money_format", test_money_format},
        {"hold_tracker", test_hold_tracker},
        {"card_parse", test_card_parse},
        {"every_example_card", test_every_example_card},
        {"replace_and_dismiss", test_replace_and_dismiss},
        {"receipt_only_when_visible", test_receipt_only_when_visible},
        {"edition_order_and_swipes", test_edition_order_and_swipes},
        {"stale_labels", test_stale_labels},
        {"stale_crossing", test_stale_crossing},
        {"hold_to_confirm", test_hold_to_confirm},
        {"decision_confirmation", test_decision_confirmation},
        {"job_actions", test_job_actions},
        {"listening_honesty", test_listening_honesty},
        {"offline_only_from_host", test_offline_only_from_host},
        {"errors_and_garbage", test_errors_and_garbage},
        {"working_cancel_and_interrupt", test_working_cancel_and_interrupt},
        {"night_and_modes", test_night_and_modes},
        {"hidden_card_and_home_tap", test_hidden_card_and_home_tap},
        {"protocol_clarifications", test_protocol_clarifications},
        {"lvgl_memory", test_lvgl_memory},
        {"fuse_25s", test_fuse_25s},
        {"voice_stream", test_voice_stream},
        {"bag_hold_timing", test_bag_hold_timing},
        {"enter_exit_receipts", test_enter_exit_receipts},
        {"reading_toggle_echo", test_reading_toggle_echo},
        {"saved_true_false", test_saved_true_false},
        {"reading_answer_scroll", test_reading_answer_scroll},
        {"design_invariants", test_design_invariants},
    };
    for (auto &t : tests) {
        g_test = t.name;
        const int before = g_failures;
        t.fn();
        fprintf(stderr, "%s %s\n", g_failures == before ? "PASS" : "FAIL", t.name);
    }
    fprintf(stderr, "%d checks, %d failures\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}
