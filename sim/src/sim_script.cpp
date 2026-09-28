#include "sim_script.h"
#include "charm_ui.h"
#include "charm_ui_debug.h"
#include "sim_display.h"
#include "sim_host.h"
#include "charm_host.h"
#include "png_write.h"

#include <ArduinoJson.h>
#include <algorithm>
#include <dirent.h>
#include <fstream>
#include <sstream>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <vector>
#include <zlib.h>

#ifndef CHARM_EXAMPLES_DIR
#define CHARM_EXAMPLES_DIR "contract/examples"
#endif

std::vector<std::string> sim_example_paths(void) {
    std::vector<std::string> out;
    if (DIR *d = opendir(CHARM_EXAMPLES_DIR)) {
        while (dirent *e = readdir(d)) {
            const std::string name = e->d_name;
            if (name.size() > 5 && name.compare(name.size() - 5, 5, ".json") == 0) {
                out.push_back(std::string(CHARM_EXAMPLES_DIR) + "/" + name);
            }
        }
        closedir(d);
    }
    std::sort(out.begin(), out.end());
    return out;
}

bool sim_read_file(const std::string &path, std::string *out) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return false;
    std::stringstream ss;
    ss << f.rdbuf();
    *out = ss.str();
    return true;
}

static void feed(const std::string &msg) { charm_ui_on_message(msg.c_str(), msg.size()); }

bool sim_inject_card_file(const std::string &path) {
    std::string card;
    if (!sim_read_file(path, &card)) {
        fprintf(stderr, "[sim] cannot read %s\n", path.c_str());
        return false;
    }
    feed("{\"type\":\"card\",\"card\":" + card + "}");
    return true;
}

void sim_send_welcome_now(void) {
    const time_t t = time(nullptr);
    struct tm local;
    localtime_r(&t, &local);
    char stamp[32], msg[160];
    strftime(stamp, sizeof stamp, "%Y-%m-%dT%H:%M:%S", &local);
    const long off = local.tm_gmtoff;
    snprintf(msg, sizeof msg,
             "{\"type\":\"welcome\",\"server\":\"charm-sim proto/0\",\"time\":\"%s%c%02ld:%02ld\",\"tz\":\"local\"}",
             stamp, off < 0 ? '-' : '+', labs(off) / 3600, labs(off) % 3600 / 60);
    feed(msg);
}

bool sim_replay_line(const std::string &line, uint32_t *wait_ms) {
    *wait_ms = 0;
    size_t start = line.find_first_not_of(" \t\r\n");
    if (start == std::string::npos || line[start] == '#') return true;
    JsonDocument doc;
    if (deserializeJson(doc, line)) return false;
    const char *directive = doc["_sim"];
    if (!directive) {
        feed(line);
        return true;
    }
    if (strcmp(directive, "wait") == 0) {
        *wait_ms = doc["ms"] | 0u;
    } else if (strcmp(directive, "connected") == 0) {
        charm_ui_set_connected(doc["value"] | true);
    } else if (strcmp(directive, "talk") == 0) {
        if (strcmp(doc["value"] | "", "press") == 0) charm_ui_talk_pressed();
        else charm_ui_talk_released();
    } else {
        fprintf(stderr, "[sim] unknown directive %s\n", directive);
    }
    return true;
}

void sim_advance(uint32_t ms) {
    for (uint32_t t = 0; t < ms; t += 5) {
        sim_clock_advance(5);
        lv_timer_handler();
        charm_ui_tick(charm_host_millis());
    }
}

// ---------------------------------------------------------------- headless runs

namespace {

void headless_init() {
    sim_clock_use_virtual(1000);
    sim_display_init();
    charm_ui_init();
    sim_advance(20);
}

void feed_str(const char *msg) { feed(msg); }

// Press the pointer on an object's center (a real touch through LVGL's input driver).
void press_obj(lv_obj_t *obj) {
    lv_area_t a;
    lv_obj_update_layout(obj);
    lv_obj_get_coords(obj, &a);
    sim_pointer_set((a.x1 + a.x2) / 2, (a.y1 + a.y2) / 2, true);
}

void release_pointer() {
    lv_indev_t *indev = lv_indev_get_next(nullptr);
    lv_point_t p = {0, 0};
    if (indev) lv_indev_get_point(indev, &p);
    sim_pointer_set(p.x, p.y, false);
}

int failures = 0;
std::string compare_dir;  // side-by-sides (sim | reference) for the chief's review
std::string design_dir;   // docs/design/final, found from the contract examples path

// ---- a minimal PNG reader (8-bit RGB/RGBA, non-interlaced) for the reference screens

uint32_t be32(const uint8_t *p) { return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }

bool png_read_rgb(const std::string &path, int *w, int *h, std::vector<uint8_t> *rgb) {
    std::string data;
    if (!sim_read_file(path, &data) || data.size() < 8 || data.compare(0, 8, "\x89PNG\r\n\x1a\n", 8) != 0) return false;
    const uint8_t *d = (const uint8_t *)data.data();
    size_t i = 8;
    int ct = -1, depth = 0, interlace = 0;
    std::string idat;
    while (i + 12 <= data.size()) {
        const uint32_t n = be32(d + i);
        const std::string type = data.substr(i + 4, 4);
        if (i + 12 + n > data.size()) return false;
        const uint8_t *c = d + i + 8;
        if (type == "IHDR") {
            *w = (int)be32(c);
            *h = (int)be32(c + 4);
            depth = c[8];
            ct = c[9];
            interlace = c[12];
        } else if (type == "IDAT") {
            idat.append((const char *)c, n);
        }
        i += 12 + n;
    }
    if (depth != 8 || (ct != 2 && ct != 6) || interlace != 0) return false;
    const int bpp = ct == 2 ? 3 : 4;
    const size_t stride = (size_t)*w * bpp;
    std::vector<uint8_t> raw((stride + 1) * (size_t)*h);
    uLongf raw_len = (uLongf)raw.size();
    if (uncompress(raw.data(), &raw_len, (const Bytef *)idat.data(), (uLong)idat.size()) != Z_OK) return false;
    std::vector<uint8_t> prev(stride, 0), cur(stride);
    rgb->assign((size_t)*w * (size_t)*h * 3, 0);
    for (int y = 0; y < *h; y++) {
        const uint8_t f = raw[(size_t)y * (stride + 1)];
        memcpy(cur.data(), &raw[(size_t)y * (stride + 1) + 1], stride);
        for (size_t x = 0; x < stride; x++) {
            const int a = x >= (size_t)bpp ? cur[x - bpp] : 0, b = prev[x], cc = x >= (size_t)bpp ? prev[x - bpp] : 0;
            int v = cur[x];
            if (f == 1) v += a;
            else if (f == 2) v += b;
            else if (f == 3) v += (a + b) / 2;
            else if (f == 4) {
                const int p = a + b - cc, pa = abs(p - a), pb = abs(p - b), pc = abs(p - cc);
                v += (pa <= pb && pa <= pc) ? a : (pb <= pc ? b : cc);
            }
            cur[x] = (uint8_t)v;
        }
        for (int x = 0; x < *w; x++) memcpy(&(*rgb)[((size_t)y * *w + x) * 3], &cur[(size_t)x * bpp], 3);
        prev.swap(cur);
    }
    return true;
}

// sim shot | 16 px gutter | reference PNG, at 1x, into compare_dir.
void write_compare(const char *name, const char *ref) {
    if (compare_dir.empty() || !ref) return;
    int rw = 0, rh = 0;
    std::vector<uint8_t> ref_rgb;
    if (!png_read_rgb(design_dir + "/" + ref, &rw, &rh, &ref_rgb) || rw != CHARM_W || rh != CHARM_H) {
        fprintf(stderr, "[shots]   no reference %s/%s (compare skipped)\n", design_dir.c_str(), ref);
        return;
    }
    const int gap = 16, W2 = CHARM_W * 2 + gap;
    std::vector<uint8_t> out((size_t)W2 * CHARM_H * 3, 0x2B);
    const lv_color_t *fb = sim_framebuffer();
    const uint8_t br = sim_brightness();
    for (int y = 0; y < CHARM_H; y++) {
        for (int x = 0; x < CHARM_W; x++) {
            const uint32_t c = lv_color_to32(fb[y * CHARM_W + x]);
            uint8_t *o = &out[((size_t)y * W2 + x) * 3];
            o[0] = (uint8_t)(((c >> 16) & 0xFF) * br / 255);
            o[1] = (uint8_t)(((c >> 8) & 0xFF) * br / 255);
            o[2] = (uint8_t)((c & 0xFF) * br / 255);
            memcpy(&out[((size_t)y * W2 + CHARM_W + gap + x) * 3], &ref_rgb[((size_t)y * CHARM_W + x) * 3], 3);
        }
    }
    const std::string path = compare_dir + "/" + name;
    if (!png_write_rgb(path.c_str(), W2, CHARM_H, out.data())) {
        fprintf(stderr, "[shots]   compare WRITE FAILED %s\n", path.c_str());
        failures++;
    }
}

// Settle `settle_ms` (the ~400 ms content enter), render, write DIR/name, check the surface.
void shot(const std::string &dir, const char *name, CharmSurface expect, const char *ref = nullptr,
          uint32_t settle_ms = 600) {
    sim_advance(settle_ms);
    sim_render_now();
    const std::string path = dir + "/" + name;
    const bool ok = sim_write_png(path.c_str(), sim_brightness());
    const CharmSurface got = charm_ui_debug_surface();
    fprintf(stderr, "[shots] %-24s surface=%-14s %s\n", name, charm_ui_surface_name(got), ok ? "ok" : "WRITE FAILED");
    if (!ok || got != expect) {
        if (got != expect) fprintf(stderr, "[shots]   expected surface %s\n", charm_ui_surface_name(expect));
        failures++;
    }
    write_compare(name, ref);
}

void dismiss(const char *id) {
    std::string m = std::string("{\"type\":\"dismiss\",\"card_id\":\"") + id + "\"}";
    feed(m);
}

void card(const std::string &json) { feed("{\"type\":\"card\",\"card\":" + json + "}"); }

// A real tap through LVGL's input driver.
void tap_obj(lv_obj_t *obj, const char *what) {
    if (!obj) {
        fprintf(stderr, "[shots] no %s to tap\n", what);
        failures++;
        return;
    }
    press_obj(obj);
    sim_advance(40);
    release_pointer();
    sim_advance(40);
}

void mkdir_p(const std::string &dir) {
    for (size_t i = 1; i <= dir.size(); i++) {
        if (i == dir.size() || dir[i] == '/') mkdir(dir.substr(0, i).c_str(), 0755);
    }
}

const char *const PIRANESI_LEAD =
    "He trusts the House because it never fails him: it feeds him through the tides, shelters him and rewards "
    "attention with order. That\xE2\x80\x99s his claim, not Clarke\xE2\x80\x99s. Read it as a clue: his trust is total; "
    "she wants you to notice what he never asks.";
const char *const PIRANESI_DETAIL =
    "What the text says. Through chapter 7 the narrator describes the House as generous. The tides bring fish and "
    "seaweed, the halls give shelter, and the statues repay the time he spends looking at them. He keeps careful "
    "journals and treats the House\xE2\x80\x99s patterns as a kind of speech.\\n"
    "Interpretation. His trust reads as faith more than evidence. He records everything, yet he never asks where the "
    "House came from or why so few people walk its halls. The calm voice is the point; the questions he steps "
    "around are where the tension sits.\\n"
    "Background. The title nods to Giovanni Battista Piranesi, the 18th-century artist known for etchings of vast, "
    "impossible prisons. Treat that as context, not as a key to the plot.\\n"
    "No spoilers past chapter 7. Give me the passage you\xE2\x80\x99re on and I\xE2\x80\x99ll stay with the words on "
    "the page.";
const char *const BOOK = "{\"title\":\"Piranesi\",\"author\":\"Susanna Clarke\",\"chapter\":\"7\"}";

}  // namespace

// The design shot set: the 14 surfaces of BRIEF § 11.3, money mid-hold, the reading surfaces of
// § 11.8 and Coach's C0-C3 of § 11.9, each written to DIR and (with its reference) side by side to DIR/../compare. Fixture copy
// mirrors the reference renders so the side-by-sides compare like with like.
int sim_run_shots(const char *dir_c) {
    const std::string dir = dir_c;
    mkdir_p(dir);
    const size_t slash = dir.find_last_of('/');
    compare_dir = (slash == std::string::npos ? std::string(".") : dir.substr(0, slash)) + "/compare";
    mkdir_p(compare_dir);
    design_dir = CHARM_EXAMPLES_DIR;
    const size_t cut = design_dir.rfind("/contract/examples");
    design_dir = (cut == std::string::npos ? std::string("..") : design_dir.substr(0, cut)) + "/docs/design/final";
    headless_init();

    // A fixed evening so every run renders the same pixels.
    charm_ui_set_connected(true);
    feed_str("{\"type\":\"welcome\",\"server\":\"charm-sim proto/0\",\"time\":\"2026-09-25T18:00:00-05:00\",\"tz\":\"America/Chicago\"}");
    feed_str("{\"type\":\"state\",\"value\":\"idle\"}");
    shot(dir, "01-home.png", CharmSurface::Home, "01-home.png");

    // Listening: 9 s into the 25 s fuse (the render shows ~36 %), voice present.
    charm_ui_talk_pressed();
    for (int i = 0; i < 9000 / 80; i++) {
        charm_ui_mic_level(0.25f + 0.6f * (float)((i * 37) % 11) / 10.0f * ((i % 5) != 3));
        sim_advance(80);
    }
    shot(dir, "02-listening.png", CharmSurface::Listening, "02-listening.png", 0);

    charm_ui_talk_released();
    feed_str("{\"type\":\"state\",\"value\":\"transcribing\"}");
    feed_str("{\"type\":\"transcript\",\"text\":\"Sunday\xE2\x80\x99s lineup\",\"final\":true}");
    feed_str("{\"type\":\"state\",\"value\":\"working\",\"agent\":\"coach\",\"label\":\"Asking Coach Beard...\"}");
    shot(dir, "03-working.png", CharmSurface::Working, "03-working.png");

    card("{\"id\":\"ans-d\",\"kind\":\"answer\",\"title\":\"What\xE2\x80\x99s on tomorrow?\",\"body\":\"Light day.\","
         "\"source\":\"dex\",\"created_at\":\"2026-09-25T18:00:00-05:00\",\"footer\":\"Shortened. Ask Dex for the rest.\"}");
    feed_str("{\"type\":\"state\",\"value\":\"speaking\"}");
    feed_str("{\"type\":\"speech_start\",\"rate\":16000,\"format\":\"s16le\",\"channels\":1,\"card_id\":\"ans-d\"}");
    shot(dir, "04-answer.png", CharmSurface::Answer, "04-answer.png");
    feed_str("{\"type\":\"speech_end\"}");
    feed_str("{\"type\":\"state\",\"value\":\"idle\"}");
    dismiss("ans-d");

    card("{\"id\":\"dec-d\",\"kind\":\"decision\",\"title\":\"Pause the side project?\",\"source\":\"dex\","
         "\"created_at\":\"2026-09-25T18:00:00-05:00\",\"data\":{\"default\":\"Yes\",\"deadline\":\"Sunday\"},"
         "\"actions\":[{\"id\":\"approve\",\"label\":\"Yes\",\"style\":\"primary\"},"
         "{\"id\":\"reject\",\"label\":\"No\"},{\"id\":\"snooze\",\"label\":\"Later\"}]}");
    shot(dir, "05-decision.png", CharmSurface::Decision, "05-decision.png");
    dismiss("dec-d");

    // Money: preview, then hold Dex's bag 1.2 s of 2 s (60 %) for mid-hold, then let go early:
    // the fill drains and nothing is sent.
    const char *money =
        "{\"id\":\"order-d\",\"kind\":\"money\",\"title\":\"Your usual\",\"source\":\"delivery\","
        "\"created_at\":\"2026-09-25T18:00:00-05:00\",\"data\":{\"store\":\"Corner Bistro\","
        "\"items\":[{\"name\":\"Chicken crepe\",\"qty\":1},{\"name\":\"Coconut lemonade\",\"qty\":1}],"
        "\"total\":18.4,\"currency\":\"USD\",\"eta_min\":35,\"address_label\":\"Home\"},"
        "\"actions\":[{\"id\":\"confirm\",\"label\":\"Hold to order\",\"style\":\"primary\",\"hold_ms\":2000},"
        "{\"id\":\"reject\",\"label\":\"Not now\"}]}";
    card(money);
    shot(dir, "06-money-preview.png", CharmSurface::Money, "06-money-preview.png");
    lv_obj_t *bag = charm_ui_debug_action_button("confirm");
    if (bag) {
        press_obj(bag);
        sim_advance(1170);
        shot(dir, "07-money-mid-hold.png", CharmSurface::Money, "07-money-mid-hold.png", 30);
        release_pointer();
        sim_advance(400);
    } else {
        fprintf(stderr, "[shots] money card has no bag to hold\n");
        failures++;
    }
    // A full hold sends action{held_ms}; Done appears only once the backend confirms.
    bag = charm_ui_debug_action_button("confirm");
    if (bag) {
        press_obj(bag);
        sim_advance(2200);
        release_pointer();
        sim_advance(60);
    }
    feed_str("{\"type\":\"state\",\"value\":\"done\"}");
    shot(dir, "08-done.png", CharmSurface::Done, "08-done.png");
    dismiss("order-d");
    feed_str("{\"type\":\"state\",\"value\":\"idle\"}");

    card("{\"id\":\"trk-d\",\"kind\":\"tracker\",\"title\":\"Corner Bistro \xC2\xB7 Delivery\",\"source\":\"delivery\","
         "\"created_at\":\"2026-09-25T18:00:00-05:00\",\"data\":{\"steps\":[\"Preparing\",\"Picked up\",\"5 min away\","
         "\"Arrived\"],\"current\":2}}");
    shot(dir, "09-live-tracker.png", CharmSurface::Tracker, "09-live-tracker.png");
    dismiss("trk-d");

    charm_ui_debug_swipe(LV_DIR_LEFT);  // Home -> edition (sends request{edition})
    sim_advance(30);
    card("{\"id\":\"ed-mast\",\"kind\":\"edition\",\"title\":\"Masthead\",\"body\":\"Tonight: quiet day, one thing matters.\","
         "\"source\":\"edition\",\"created_at\":\"2026-09-25T18:00:00-05:00\",\"data\":{\"section\":\"masthead\",\"edition_no\":212}}");
    card("{\"id\":\"ed-one\",\"kind\":\"edition\",\"title\":\"One thing\",\"body\":\"Lock the lineup before 11:00.\","
         "\"source\":\"edition\",\"created_at\":\"2026-09-25T18:00:00-05:00\",\"data\":{\"section\":\"one_thing\"}}");
    shot(dir, "10-pocket-edition.png", CharmSurface::Edition, "10-pocket-edition.png");
    charm_ui_debug_swipe(LV_DIR_BOTTOM);
    sim_advance(30);

    card("{\"id\":\"job-d\",\"kind\":\"job\",\"title\":\"PR #42\",\"body\":\"1 blocking, 2 nits\",\"source\":\"github\","
         "\"created_at\":\"2026-09-25T18:00:00-05:00\",\"data\":{\"status\":\"review done\"},"
         "\"actions\":[{\"id\":\"send_claude\",\"label\":\"Send to Claude Code\",\"style\":\"primary\"},"
         "{\"id\":\"later\",\"label\":\"Later\"}]}");
    shot(dir, "11-job-done.png", CharmSurface::Job, "11-job-done.png");
    dismiss("job-d");

    sim_advance(61000);  // a minute with nothing pending dims to night
    shot(dir, "12-night.png", CharmSurface::Night, "12-night.png");

    charm_ui_set_connected(false);
    shot(dir, "13-offline.png", CharmSurface::Offline, "13-offline.png");

    charm_ui_set_connected(true);
    card("{\"id\":\"ask-d\",\"kind\":\"decision\",\"title\":\"Which Corner Bistro, Downtown or Riverside?\","
         "\"source\":\"dex\",\"created_at\":\"2026-09-25T18:00:00-05:00\",\"data\":{\"deadline\":\"now\"},"
         "\"actions\":[{\"id\":\"downtown\",\"label\":\"Downtown\",\"style\":\"primary\"},"
         "{\"id\":\"riverside\",\"label\":\"Riverside\",\"style\":\"primary\"}]}");
    shot(dir, "14-needs-more.png", CharmSurface::NeedsMore, "14-needs-more.png");
    dismiss("ask-d");

    feed_str("{\"type\":\"error\",\"code\":\"agent_timeout\",\"text\":\"Dex didn't answer within 120 s.\"}");
    shot(dir, "e1-error.png", CharmSurface::Error);
    charm_ui_debug_tap();

    // ---- reading mode (§ 11.8)
    feed("{\"type\":\"mode\",\"value\":\"reading\",\"book\":" + std::string(BOOK) + "}");
    feed_str("{\"type\":\"setting\",\"name\":\"speech\",\"value\":\"off\"}");
    shot(dir, "r1-home.png", CharmSurface::ReadingHome, "reading/r1-home.png");

    // Speak/quiet: the tap asks; the state changes only on the server's echo.
    tap_obj(charm_ui_debug_ui_button("speech"), "speech toggle");
    feed_str("{\"type\":\"setting\",\"name\":\"speech\",\"value\":\"on\"}");
    shot(dir, "r4-speak.png", CharmSurface::ReadingHome, "reading/r4-speak.png");
    tap_obj(charm_ui_debug_ui_button("speech"), "speech toggle");
    feed_str("{\"type\":\"setting\",\"name\":\"speech\",\"value\":\"off\"}");
    shot(dir, "r4-quiet.png", CharmSurface::ReadingHome, "reading/r4-quiet.png");

    card(std::string("{\"id\":\"ans-r\",\"kind\":\"answer\",\"title\":\"Why he trusts the House\",\"body\":\"") +
         PIRANESI_LEAD + "\",\"detail\":\"" + PIRANESI_DETAIL +
         "\",\"source\":\"dex\",\"created_at\":\"2026-09-27T21:10:00-05:00\",\"data\":{\"book\":" + BOOK + "}}");
    shot(dir, "r2-lead.png", CharmSurface::ReadingAnswer, "reading/r2-lead.png");
    tap_obj(charm_ui_debug_ui_button("read_more"), "Read more");
    sim_advance(300);
    shot(dir, "r3-detail.png", CharmSurface::ReadingAnswer, "reading/r3-detail.png");
    tap_obj(charm_ui_debug_ui_button("smaller"), "Smaller");
    shot(dir, "r5-size-small.png", CharmSurface::ReadingAnswer, "reading/r5-size-small.png");
    tap_obj(charm_ui_debug_ui_button("larger"), "Larger");
    sim_advance(600);
    tap_obj(charm_ui_debug_ui_button("larger"), "Larger");
    shot(dir, "r5-size-large.png", CharmSurface::ReadingAnswer, "reading/r5-size-large.png");
    dismiss("ans-r");

    feed_str("{\"type\":\"state\",\"value\":\"working\",\"label\":\"Saving\"}");
    card(std::string("{\"id\":\"ntc-s\",\"kind\":\"notice\",\"title\":\"Saved to reading notes\",\"body\":\"The House only "
                     "feels kind because he never stops paying attention to it.\",\"source\":\"dex\","
                     "\"created_at\":\"2026-09-27T21:12:00-05:00\",\"data\":{\"saved\":true,\"book\":") + BOOK + "}}");
    feed_str("{\"type\":\"state\",\"value\":\"done\"}");
    shot(dir, "r6-saved.png", CharmSurface::Saved, "reading/r6-saved.png");
    dismiss("ntc-s");
    feed_str("{\"type\":\"state\",\"value\":\"idle\"}");

    feed_str("{\"type\":\"error\",\"code\":\"save_failed\",\"text\":\"The note store didn't confirm.\"}");
    card(std::string("{\"id\":\"ntc-f\",\"kind\":\"notice\",\"title\":\"Not saved\",\"body\":\"Not saved: the note store "
                     "didn\xE2\x80\x99t confirm. Say it again when it\xE2\x80\x99s back.\",\"source\":\"dex\","
                     "\"created_at\":\"2026-09-27T21:12:00-05:00\",\"data\":{\"saved\":false,\"book\":") + BOOK + "}}");
    feed_str("{\"type\":\"state\",\"value\":\"idle\"}");
    shot(dir, "r6-not-saved.png", CharmSurface::Saved);
    dismiss("ntc-f");

    // ---- Coach Beard (§ 11.9): the server switches the character with mode.agent.
    feed_str("{\"type\":\"mode\",\"value\":\"default\",\"agent\":\"coach\"}");
    feed_str("{\"type\":\"state\",\"value\":\"idle\",\"agent\":\"coach\"}");
    shot(dir, "c0-home.png", CharmSurface::Home, "coach/c0-home.png");

    // His hand is at his headset: the voice stream lands there (no reference render).
    charm_ui_talk_pressed();
    for (int i = 0; i < 4000 / 80; i++) {
        charm_ui_mic_level(0.25f + 0.6f * (float)((i * 37) % 11) / 10.0f * ((i % 5) != 3));
        sim_advance(80);
    }
    shot(dir, "c-listening.png", CharmSurface::Listening, nullptr, 0);
    charm_ui_talk_released();
    sim_advance(1200);  // the capsules in flight land at his headset

    // A walk-away job: "Coach is on it", then (minutes later) his call, with no speech.
    feed_str("{\"type\":\"state\",\"value\":\"working\",\"agent\":\"coach\",\"label\":\"Coach is on it\"}");
    card("{\"id\":\"coach-job-001\",\"kind\":\"job\",\"title\":\"Coach is on it\",\"body\":\"Checking injury reports "
         "and your matchup.\",\"source\":\"coach\",\"created_at\":\"2026-09-28T12:00:00-05:00\",\"data\":{\"status\":\"running\"}}");
    shot(dir, "c1-on-it.png", CharmSurface::CoachOnIt, "coach/c1-on-it.png");
    card("{\"id\":\"coach-call-001\",\"kind\":\"decision\",\"title\":\"QB this week\",\"body\":\"Keep Purdy over Maye.\","
         "\"source\":\"coach\",\"created_at\":\"2026-09-28T12:00:00-05:00\",\"data\":{\"default\":\"Start Purdy\","
         "\"deadline\":\"Sun 12:00\",\"flip_if\":\"Flip only if Purdy is out before Sun 12:00\"},"
         "\"actions\":[{\"id\":\"hear\",\"label\":\"Hear it\",\"style\":\"primary\"},"
         "{\"id\":\"why\",\"label\":\"Why?\",\"style\":\"secondary\"},{\"id\":\"later\",\"label\":\"Later\",\"style\":\"secondary\"}]}");
    dismiss("coach-job-001");
    feed_str("{\"type\":\"state\",\"value\":\"attention\",\"agent\":\"coach\"}");
    shot(dir, "c2-call.png", CharmSurface::CoachCall, "coach/c2-call.png");
    dismiss("coach-call-001");
    feed_str("{\"type\":\"state\",\"value\":\"idle\",\"agent\":\"coach\"}");

    sim_advance(61000);  // a quiet minute: Coach sleeps too
    shot(dir, "c3-night.png", CharmSurface::Night, "coach/c3-night.png");

    fprintf(stderr, "[shots] wrote to %s (+ %s), %d failure(s)\n", dir.c_str(), compare_dir.c_str(), failures);
    return failures == 0 ? 0 : 1;
}

int sim_run_replay_headless(const char *file, uint32_t interval_ms) {
    std::ifstream f(file);
    if (!f) {
        fprintf(stderr, "[replay] cannot open %s\n", file);
        return 1;
    }
    headless_init();
    charm_ui_set_connected(true);
    std::string line;
    int n = 0, bad = 0;
    while (std::getline(f, line)) {
        n++;
        uint32_t wait = 0;
        if (!sim_replay_line(line, &wait)) {
            fprintf(stderr, "[replay] line %d: invalid JSON\n", n);
            bad++;
            continue;
        }
        sim_advance(wait ? wait : interval_ms);
        fprintf(stderr, "[replay] line %d -> %s\n", n, charm_ui_surface_name(charm_ui_debug_surface()));
    }
    return bad == 0 ? 0 : 1;
}
