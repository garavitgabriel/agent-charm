#include "sim_script.h"
#include "charm_ui.h"
#include "charm_ui_debug.h"
#include "sim_display.h"
#include "sim_host.h"
#include "charm_host.h"

#include <ArduinoJson.h>
#include <algorithm>
#include <dirent.h>
#include <fstream>
#include <sstream>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

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

bool example(const char *name) { return sim_inject_card_file(std::string(CHARM_EXAMPLES_DIR) + "/" + name); }

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

void shot(const std::string &dir, const char *name, CharmSurface expect) {
    sim_advance(30);
    sim_render_now();
    const std::string path = dir + "/" + name;
    const bool ok = sim_write_png(path.c_str(), sim_brightness());
    const CharmSurface got = charm_ui_debug_surface();
    fprintf(stderr, "[shots] %-22s surface=%-9s %s\n", name, charm_ui_surface_name(got), ok ? "ok" : "WRITE FAILED");
    if (!ok || got != expect) {
        if (got != expect) fprintf(stderr, "[shots]   expected surface %s\n", charm_ui_surface_name(expect));
        failures++;
    }
}

void dismiss(const char *id) {
    std::string m = std::string("{\"type\":\"dismiss\",\"card_id\":\"") + id + "\"}";
    feed(m);
}

}  // namespace

int sim_run_shots(const char *dir_c) {
    const std::string dir = dir_c;
    // mkdir -p
    for (size_t i = 1; i <= dir.size(); i++) {
        if (i == dir.size() || dir[i] == '/') mkdir(dir.substr(0, i).c_str(), 0755);
    }
    headless_init();

    // A fixed evening so every run renders the same pixels.
    charm_ui_set_connected(true);
    feed_str("{\"type\":\"welcome\",\"server\":\"charm-sim proto/0\",\"time\":\"2026-09-25T18:00:00-05:00\",\"tz\":\"America/Chicago\"}");
    feed_str("{\"type\":\"state\",\"value\":\"idle\"}");
    shot(dir, "01-home.png", CharmSurface::Home);

    charm_ui_talk_pressed();
    sim_advance(3200);
    charm_ui_mic_level(0.6f);
    shot(dir, "02-listening.png", CharmSurface::Listening);

    charm_ui_talk_released();
    feed_str("{\"type\":\"state\",\"value\":\"transcribing\"}");
    feed_str("{\"type\":\"transcript\",\"text\":\"What's the difference between a metaphor and a simile?\",\"final\":true}");
    feed_str("{\"type\":\"state\",\"value\":\"working\",\"agent\":\"dex\",\"label\":\"Asking Dex...\"}");
    shot(dir, "03-working.png", CharmSurface::Working);

    example("answer.json");
    feed_str("{\"type\":\"speech_start\",\"rate\":16000,\"format\":\"s16le\",\"channels\":1,\"card_id\":\"ans-001\"}");
    shot(dir, "04-answer.png", CharmSurface::Answer);
    feed_str("{\"type\":\"speech_end\"}");
    feed_str("{\"type\":\"state\",\"value\":\"idle\"}");
    dismiss("ans-001");

    example("decision.json");
    shot(dir, "05-decision.png", CharmSurface::Decision);
    dismiss("dec-001");

    // Money: hold the confirm for 1 s of its 2 s, then let go early (nothing is sent).
    example("money.json");
    sim_advance(30);
    if (lv_obj_t *confirm = charm_ui_debug_action_button("confirm")) {
        press_obj(confirm);
        sim_advance(1000);
    } else {
        fprintf(stderr, "[shots] money card has no confirm button\n");
        failures++;
    }
    shot(dir, "06-money.png", CharmSurface::Money);
    release_pointer();
    sim_advance(60);
    dismiss("order-001");

    example("tracker.json");
    shot(dir, "07-tracker.png", CharmSurface::Tracker);
    dismiss("trk-001");

    charm_ui_debug_swipe(LV_DIR_LEFT);  // Home -> edition (sends request{edition})
    sim_advance(30);
    example("edition-sports.json");
    example("edition-almanac.json");
    shot(dir, "08-edition.png", CharmSurface::Edition);
    charm_ui_debug_swipe(LV_DIR_BOTTOM);
    sim_advance(30);

    example("job.json");
    shot(dir, "09-job.png", CharmSurface::Job);
    dismiss("job-001");

    sim_advance(61000);  // a minute with nothing pending dims to night
    shot(dir, "10-night.png", CharmSurface::Night);

    charm_ui_set_connected(false);
    shot(dir, "11-offline.png", CharmSurface::Offline);

    // Extra: surface 11's error variant.
    charm_ui_set_connected(true);
    feed_str("{\"type\":\"error\",\"code\":\"agent_timeout\",\"text\":\"Dex didn't answer within 120 s.\"}");
    shot(dir, "12-error.png", CharmSurface::Error);

    fprintf(stderr, "[shots] wrote to %s, %d failure(s)\n", dir.c_str(), failures);
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
