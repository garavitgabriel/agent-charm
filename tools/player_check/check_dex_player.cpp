// Drives ui/dex_sprite.cpp headlessly against the sim's already-built libraries and checks the
// player really animates: frames change on their ms, loop, scale to full and mini, and fall back
// to the gray placeholder. Writes a PNG per checked frame. Built and run by
// tests/test_player.py (after `cmake --build build/sim`); not part of the firmware or the sim.
#include <lvgl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <string>

#include "charm_host.h"
#include "charm_ui.h"
#include "dex_sprite.h"
#include "sim_display.h"

namespace {
uint32_t now_ms = 1000;
int failures = 0;
std::string out_dir;

#define CHECK(cond)                                                     \
    do {                                                                \
        if (!(cond)) {                                                  \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
            failures++;                                                 \
        }                                                               \
    } while (0)

void advance(uint32_t ms) {
    for (uint32_t t = 0; t < ms; t += 5) {
        now_ms += 5;
        lv_tick_inc(5);
        dex_tick(now_ms);
        lv_timer_handler();
    }
}

// FNV-1a over the framebuffer inside a screen rectangle.
uint32_t region_hash(int x0, int y0, int w, int h) {
    sim_render_now();
    const lv_color_t *fb = sim_framebuffer();
    uint32_t hsh = 2166136261u;
    for (int y = y0; y < y0 + h; y++) {
        for (int x = x0; x < x0 + w; x++) {
            hsh = (hsh ^ fb[y * CHARM_W + x].full) * 16777619u;
        }
    }
    return hsh;
}

bool has_color(int x0, int y0, int w, int h, uint32_t rgb) {
    sim_render_now();
    const lv_color_t want = lv_color_hex(rgb);
    const lv_color_t *fb = sim_framebuffer();
    for (int y = y0; y < y0 + h; y++) {
        for (int x = x0; x < x0 + w; x++) {
            if (fb[y * CHARM_W + x].full == want.full) return true;
        }
    }
    return false;
}

// The boxes dex_sprite.cpp places Dex in (full: top-mid +92; mini: top-right -8,+6).
constexpr int FULL_X = (CHARM_W - 168) / 2, FULL_Y = 92, FULL_W = 168, FULL_H = 224;
constexpr int MINI_X = CHARM_W - 8 - 76, MINI_Y = 6, MINI_W = 76, MINI_H = 76;

void shot(const char *name) {
    sim_render_now();
    std::string path = out_dir + "/" + name;
    if (!sim_write_png(path.c_str(), 255)) {
        fprintf(stderr, "FAIL: can't write %s\n", path.c_str());
        failures++;
    }
}
}  // namespace

// charm_host.h, for the linker: dex_sprite never calls these.
void charm_host_send(const char *, size_t) {}
bool charm_host_mic_start(void) { return false; }
void charm_host_mic_stop(const char *) {}
void charm_host_speech_stop(void) {}
void charm_host_set_brightness(uint8_t) {}
uint32_t charm_host_millis(void) { return now_ms; }

int main(int argc, char **argv) {
    out_dir = argc > 1 ? argv[1] : "player-shots";
    mkdir(out_dir.c_str(), 0755);
    sim_display_init();
    lv_obj_t *scr = lv_scr_act();
    lv_obj_set_style_bg_color(scr, lv_color_black(), 0);
    dex_create(scr);
    advance(10);  // first tick starts the frame clock

    // idle/default: 600 ms then 400 ms (tools/fixtures/dummy/manifest.json).
    const uint32_t idle0 = region_hash(FULL_X, FULL_Y, FULL_W, FULL_H);
    shot("idle-f0.png");
    CHECK(has_color(FULL_X, FULL_Y, FULL_W, FULL_H, 0x00C8B4));  // the sprite, not the gray box
    CHECK(!has_color(FULL_X, FULL_Y, FULL_W, FULL_H, 0x505050));
    advance(300);
    CHECK(region_hash(FULL_X, FULL_Y, FULL_W, FULL_H) == idle0);  // still frame 0
    advance(320);
    const uint32_t idle1 = region_hash(FULL_X, FULL_Y, FULL_W, FULL_H);
    shot("idle-f1.png");
    CHECK(idle1 != idle0);  // frame 1 after 600 ms
    advance(420);
    CHECK(region_hash(FULL_X, FULL_Y, FULL_W, FULL_H) == idle0);  // looped back after 400 ms

    // Outfit variant, then the other poses.
    dex_set_outfit(DEX_OUTFIT_GAMEDAY);
    advance(10);
    CHECK(has_color(FULL_X, FULL_Y, FULL_W, FULL_H, 0xFFD000));  // the yellow hat bar
    shot("idle-gameday.png");
    dex_set_outfit(DEX_OUTFIT_DEFAULT);

    dex_set_pose(DEX_POSE_LISTENING);
    advance(10);
    const uint32_t l0 = region_hash(FULL_X, FULL_Y, FULL_W, FULL_H);
    shot("listening-f0.png");
    advance(310);
    CHECK(region_hash(FULL_X, FULL_Y, FULL_W, FULL_H) != l0);
    shot("listening-f1.png");

    dex_set_pose(DEX_POSE_WORKING);
    advance(10);
    const uint32_t w0 = region_hash(FULL_X, FULL_Y, FULL_W, FULL_H);
    shot("working-f0.png");
    advance(260);
    CHECK(region_hash(FULL_X, FULL_Y, FULL_W, FULL_H) != w0);
    shot("working-f1.png");

    // Mini: same frames, smaller scale, clipped to the corner box.
    dex_set_pose(DEX_POSE_IDLE);
    dex_set_size(DEX_SIZE_MINI);
    advance(10);
    CHECK(has_color(MINI_X, MINI_Y, MINI_W, MINI_H, 0x00C8B4));
    CHECK(!has_color(FULL_X, FULL_Y + 100, FULL_W, FULL_H - 100, 0x00C8B4));  // nothing left behind
    const uint32_t m0 = region_hash(MINI_X, MINI_Y, MINI_W, MINI_H);
    shot("mini-f0.png");
    advance(610);
    CHECK(region_hash(MINI_X, MINI_Y, MINI_W, MINI_H) != m0);
    shot("mini-f1.png");
    dex_set_size(DEX_SIZE_FULL);

    // No art for speaking: the gray placeholder, whose beat square still steps.
    dex_set_pose(DEX_POSE_SPEAKING);
    advance(10);
    CHECK(has_color(FULL_X, FULL_Y, FULL_W, FULL_H, 0x505050));
    CHECK(!has_color(FULL_X, FULL_Y, FULL_W, FULL_H, 0x00C8B4));
    shot("speaking-placeholder.png");

    // And back to art from the placeholder.
    dex_set_pose(DEX_POSE_IDLE);
    advance(10);
    CHECK(!has_color(FULL_X, FULL_Y, FULL_W, FULL_H, 0x505050));
    CHECK(region_hash(FULL_X, FULL_Y, FULL_W, FULL_H) == idle0);

    // The public API is unchanged.
    CHECK(dex_get_pose() == DEX_POSE_IDLE && dex_get_size() == DEX_SIZE_FULL);
    CHECK(dex_get_outfit() == DEX_OUTFIT_DEFAULT);

    printf("dex player check: %d failure(s); shots in %s\n", failures, out_dir.c_str());
    return failures ? 1 : 0;
}
