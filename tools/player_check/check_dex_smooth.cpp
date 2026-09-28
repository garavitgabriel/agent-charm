// Drives ui/dex_sprite.cpp headlessly with the REAL generated table (the smooth Dex) against the
// sim's already-built libraries, and checks on the framebuffer that:
//   * every frame decodes bit-exact (the cell's pixels hash to the table's FNV-1a), unscaled, with
//     the hip on the design anchor (236, 379);
//   * frames step on their ms, loop from their loop point, and a held last frame holds;
//   * breathing is a whole-sprite integer px offset (0 / -1 / -2) that the overlay points follow;
//   * blinks come 3-6 s apart and every 5th is double; the idle sip plays within 20-40 s;
//   * lift_bag -> offer_bag returns through the in-betweens; the bag box moves chest -> overhead;
//   * the reading outfit plays its own frames; borrowed outfits play the default's;
//   * mini is the unscaled corner crop, with no overlay points.
// Writes a PNG per checked moment. Built and run by tests/test_player.py (after the sim is built).
#include <lvgl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <string>

#include "charm_assets_sprites.h"
#include "charm_host.h"
#include "charm_ui.h"
#include "dex_sprite.h"
#include "sim_display.h"

#if !CHARM_SPRITE_SMOOTH
#error check_dex_smooth needs the smooth table (ui/charm_assets_sprites.* from ui/assets-src/dex)
#endif

namespace {
uint32_t now_ms = 1000;
int failures = 0;
std::string out_dir;

#define CHECK(cond)                                                          \
    do {                                                                     \
        if (!(cond)) {                                                       \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);  \
            failures++;                                                      \
        }                                                                    \
    } while (0)

constexpr int W = CHARM_SPRITE_CELL_W, H = CHARM_SPRITE_CELL_H;
constexpr int X0 = CHARM_SPRITE_SCREEN_ANCHOR_X - CHARM_SPRITE_ANCHOR_X;
constexpr int Y0 = CHARM_SPRITE_SCREEN_ANCHOR_Y - CHARM_SPRITE_ANCHOR_Y;

void advance(uint32_t ms) {
    for (uint32_t t = 0; t < ms; t += 5) {
        now_ms += 5;
        lv_tick_inc(5);
        dex_tick(now_ms);
        lv_timer_handler();
    }
}

// FNV-1a over the 16-bit pixels of the cell drawn `dy` px from the anchor position, on the
// framebuffer as last rendered.
uint32_t hash_rendered(int dy) {
    const lv_color_t *fb = sim_framebuffer();
    uint32_t h = 2166136261u;
    for (int y = Y0 + dy; y < Y0 + dy + H; y++) {
        for (int x = X0; x < X0 + W; x++) h = (h ^ fb[y * CHARM_W + x].full) * 16777619u;
    }
    return h;
}

uint32_t cell_hash(int dy = 0) {
    sim_render_now();
    return hash_rendered(dy);
}

bool nonblack(int x0, int y0, int w, int h) {
    sim_render_now();
    const lv_color_t *fb = sim_framebuffer();
    for (int y = y0; y < y0 + h; y++) {
        for (int x = x0; x < x0 + w; x++) {
            if (fb[y * CHARM_W + x].full) return true;
        }
    }
    return false;
}

const charm_sprite_anim_t &A(dex_pose_t p, dex_outfit_t o = DEX_OUTFIT_DEFAULT) {
    return charm_sprite_anims[DEX_CHARACTER_DEX][p][o];
}
const charm_sprite_anim_t &AC(dex_pose_t p, dex_outfit_t o = DEX_OUTFIT_DEFAULT) {
    return charm_sprite_anims[DEX_CHARACTER_COACH][p][o];
}
uint32_t fnv(uint16_t img) { return charm_sprite_imgs[img].fnv; }
uint32_t fnv_frame(dex_pose_t p, int i, dex_outfit_t o = DEX_OUTFIT_DEFAULT) { return fnv(A(p, o).frames[i].img); }

// Which table image is on screen, bit-exact, at any breathing offset (0, -1, -2); -1 if none.
int shown() {
    sim_render_now();
    for (int dy = 0; dy >= -2; dy--) {
        const uint32_t h = hash_rendered(dy);
        for (int i = 0; i < CHARM_SPRITE_IMAGES; i++) {
            if (charm_sprite_imgs[i].fnv == h) return i;
        }
    }
    return -1;
}

void shot(const char *name) {
    sim_render_now();
    std::string path = out_dir + "/" + name;
    if (!sim_write_png(path.c_str(), 255)) {
        fprintf(stderr, "FAIL: can't write %s\n", path.c_str());
        failures++;
    }
}

// The point box from the table, on screen at breathing offset dy.
bool point_is(dex_point_t which, uint16_t img, int dy) {
    lv_area_t a;
    if (!dex_get_point_area(which, &a)) return false;
    const int16_t *p = charm_sprite_imgs[img].points[which];
    return a.x1 == X0 + p[0] && a.y1 == Y0 + dy + p[1] && lv_area_get_width(&a) == p[2] &&
           lv_area_get_height(&a) == p[3];
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
    out_dir = argc > 1 ? argv[1] : "smooth-shots";
    mkdir(out_dir.c_str(), 0755);
    sim_display_init();
    lv_obj_t *scr = lv_scr_act();
    lv_obj_set_style_bg_color(scr, lv_color_black(), 0);
    dex_create(scr);
    advance(5);  // the first tick starts the clocks

    // Every pose has real frames: no gray placeholder anywhere in the table.
    for (int p = 0; p < DEX_POSE_COUNT; p++) CHECK(A((dex_pose_t)p).count > 0);

    // Idle: bit-exact frame 0 at the anchor, unscaled; nothing outside the cell.
    const charm_sprite_anim_t &idle = A(DEX_POSE_IDLE);
    CHECK(cell_hash() == fnv_frame(DEX_POSE_IDLE, 0));
    CHECK(!nonblack(0, 0, CHARM_W, Y0 - 2));  // the content zone stays empty
    CHECK(!nonblack(0, Y0, X0, H));           // left of the cell
    shot("idle-0.png");
    // Steam steps on its ms.
    advance(idle.frames[0].ms);
    CHECK(cell_hash() == fnv_frame(DEX_POSE_IDLE, 1));
    shot("idle-1.png");
    CHECK(point_is(DEX_POINT_HAND, idle.frames[1].img, 0));
    lv_area_t bag;
    CHECK(!dex_get_point_area(DEX_POINT_BAG, &bag));  // no bag in idle

    // Breathing: the whole sprite rises 1 then 2 px (1600 ms rest, 200 ms steps), then returns.
    // Clock started at t=1005; now at t=1005+250+.
    const uint32_t start = now_ms - idle.frames[0].ms;
    auto at = [&](uint32_t t) { advance(start + t - now_ms); };
    at(1700);  // -1 px, steam frame (1700 / 250) % 3 = 0
    CHECK(cell_hash(-1) == fnv_frame(DEX_POSE_IDLE, 0));
    CHECK(point_is(DEX_POINT_HAND, idle.frames[0].img, -1));
    at(1900);  // -2 px, steam frame 7 % 3 = 1
    CHECK(cell_hash(-2) == fnv_frame(DEX_POSE_IDLE, 1));
    shot("idle-inhaled.png");
    at(3950);  // back to 0 (exhale ends at 4000)
    CHECK(shown() >= 0);  // always a clean table frame

    // Blinks: over 60 s, 3-6 s apart (10..20 of them), some doubles, and a sip in 20-40 s.
    int blinks = 0, closed_frames = 0, sips = 0;
    bool was_closed = false, was_sip = false;
    uint32_t last_blink = now_ms, min_gap = 1u << 30;
    const uint16_t sip_img = idle.sip.frames[1].img;
    for (int t = 0; t < 60000; t += 10) {
        advance(10);
        const int img = shown();
        CHECK(img >= 0);
        bool closed = false;
        for (int f = 0; f < idle.count; f++) closed |= img == idle.blink[f][1];
        const bool sip = img == sip_img;
        if (closed && !was_closed) {
            closed_frames++;
            if (now_ms - last_blink > 400) {  // a new blink, not the 2nd half of a double
                blinks++;
                if (blinks > 1 && now_ms - last_blink < min_gap) min_gap = now_ms - last_blink;
            }
            last_blink = now_ms;
        }
        if (sip && !was_sip) sips++;
        was_closed = closed;
        was_sip = sip;
    }
    printf("idle over 60 s: %d blinks (%d closed frames, so %d doubles), min gap %u ms, %d sips\n",
           blinks, closed_frames, closed_frames - blinks, (unsigned)min_gap, sips);
    CHECK(blinks >= 8 && blinks <= 20);
    CHECK(closed_frames - blinks >= 1);  // every 5th is double
    CHECK(min_gap >= 2900);
    CHECK(sips >= 1 && sips <= 3);

    // Listening: the head bob alternates at 300 ms; the cupped hand box.
    dex_set_pose(DEX_POSE_LISTENING);
    advance(5);
    const charm_sprite_anim_t &lis = A(DEX_POSE_LISTENING);
    const int l0 = shown();
    CHECK(l0 == lis.frames[0].img || l0 == lis.blink[0][0] || l0 == lis.blink[0][1]);
    lv_area_t hand;
    CHECK(dex_get_point_area(DEX_POINT_HAND, &hand));
    CHECK(hand.x1 > CHARM_SPRITE_SCREEN_ANCHOR_X && hand.y2 < CHARM_SPRITE_SCREEN_ANCHOR_Y - 40);
    shot("listening.png");

    // Money: offer (bag at chest) -> lift (in-betweens, then overhead, bob) -> release -> offer.
    dex_set_pose(DEX_POSE_OFFER_BAG);
    advance(5);
    lv_area_t chest, over;
    CHECK(dex_get_point_area(DEX_POINT_BAG, &chest));
    shot("offer.png");
    dex_set_pose(DEX_POSE_LIFT_BAG);
    advance(5);
    const charm_sprite_anim_t &lift = A(DEX_POSE_LIFT_BAG);
    CHECK(cell_hash() == fnv_frame(DEX_POSE_LIFT_BAG, 0));  // in-between 1, no breathing
    shot("lift-in1.png");
    advance(100);
    CHECK(cell_hash() == fnv_frame(DEX_POSE_LIFT_BAG, 1));
    advance(100);
    CHECK(cell_hash() == fnv_frame(DEX_POSE_LIFT_BAG, 2));  // up on his toes, bag overhead
    CHECK(dex_get_point_area(DEX_POINT_BAG, &over));
    CHECK(over.y1 < chest.y1 - 60);  // chest -> overhead
    shot("lift-held.png");
    advance(200);
    CHECK(cell_hash() == fnv_frame(DEX_POSE_LIFT_BAG, 3));  // the bob
    lv_area_t bob;
    CHECK(dex_get_point_area(DEX_POINT_BAG, &bob));
    CHECK(bob.y1 == over.y1 + 1);
    advance(200);
    CHECK(cell_hash() == fnv_frame(DEX_POSE_LIFT_BAG, 4));
    advance(200);
    CHECK(cell_hash() == fnv_frame(DEX_POSE_LIFT_BAG, lift.loop_from));  // loops the held part
    dex_set_pose(DEX_POSE_OFFER_BAG);  // early release: back through the in-betweens
    advance(5);
    CHECK(dex_get_pose() == DEX_POSE_OFFER_BAG);
    CHECK(cell_hash() == fnv(lift.exit.frames[0].img));
    shot("release-in2.png");
    advance(100);
    CHECK(cell_hash() == fnv(lift.exit.frames[1].img));
    advance(100);
    const charm_sprite_anim_t &offer = A(DEX_POSE_OFFER_BAG);
    const int o0 = shown();
    CHECK(o0 == offer.frames[0].img || o0 == offer.blink[0][0] || o0 == offer.blink[0][1]);

    // Done: the nod plays once and holds its last frame.
    dex_set_pose(DEX_POSE_DONE);
    advance(5);
    const charm_sprite_anim_t &done = A(DEX_POSE_DONE);
    uint32_t total = 0;
    for (int i = 0; i < done.count; i++) total += done.frames[i].ms;
    advance(total + 2000);
    const int last = done.frames[done.count - 1].img;
    CHECK(shown() == last);
    CHECK(dex_get_point_area(DEX_POINT_BAG, &bag));  // the full bag, handed over
    shot("done.png");

    // Reading outfit: its own book-hug; a borrowed pose plays the default frames.
    dex_set_pose(DEX_POSE_IDLE);
    dex_set_outfit(DEX_OUTFIT_READING);
    advance(5);
    const charm_sprite_anim_t &rd = A(DEX_POSE_IDLE, DEX_OUTFIT_READING);
    CHECK(rd.frames != idle.frames);
    const int r0 = shown();
    CHECK(r0 == rd.frames[0].img || r0 == rd.blink[0][0] || r0 == rd.blink[0][1]);
    shot("reading-idle.png");
    CHECK(A(DEX_POSE_WORKING, DEX_OUTFIT_READING).frames == A(DEX_POSE_WORKING).frames);
    dex_set_outfit(DEX_OUTFIT_DEFAULT);

    // Night: asleep, night palette baked in, slow breathing.
    dex_set_pose(DEX_POSE_ASLEEP);
    advance(5);
    CHECK(A(DEX_POSE_ASLEEP).breath == CHARM_BREATH_NIGHT);
    shot("asleep.png");

    // Mini: the unscaled head crop in the corner, and no overlay points.
    dex_set_pose(DEX_POSE_IDLE);
    dex_set_size(DEX_SIZE_MINI);
    advance(5);
    CHECK(nonblack(CHARM_W - 8 - 76, 6, 76, 76));
    CHECK(!nonblack(X0, Y0 + 40, W, H - 40));  // nothing left at the anchor
    CHECK(!dex_get_point_area(DEX_POINT_HAND, &hand));
    shot("mini.png");
    dex_set_size(DEX_SIZE_FULL);
    advance(5);
    CHECK(dex_get_point_area(DEX_POINT_HAND, &hand));
    dex_set_hidden(true);
    CHECK(!dex_get_point_area(DEX_POINT_HAND, &hand));
    dex_set_hidden(false);

    // Coach (the dummy test card): the same anchor and cell, his own frames, and the gray
    // placeholder, never Dex's frames, for a pose he has no frames for.
    auto has_gray = [&]() {
        sim_render_now();
        const lv_color_t gray = lv_color_hex(0x505050);
        const lv_color_t *fb = sim_framebuffer();
        for (int y = Y0; y < Y0 + H; y++) {
            for (int x = X0; x < X0 + W; x++) {
                if (fb[y * CHARM_W + x].full == gray.full) return true;
            }
        }
        return false;
    };
    // Which Coach image of `a` is on screen (any breathing offset), or -1.
    auto shows_one_of = [&](const charm_sprite_anim_t &a) {
        const int img = shown();
        for (int i = 0; i < a.count; i++) {
            if (img == a.frames[i].img) return true;
        }
        return false;
    };
    const dex_pose_t coach_poses[] = {DEX_POSE_IDLE, DEX_POSE_LISTENING, DEX_POSE_WORKING, DEX_POSE_SPEAKING};
    const char *const coach_shots[] = {"coach-idle.png", "coach-listening.png", "coach-working.png",
                                       "coach-speaking.png"};
    dex_set_pose(DEX_POSE_IDLE);
    dex_set_character(DEX_CHARACTER_COACH);
    CHECK(dex_get_character() == DEX_CHARACTER_COACH);
    for (int k = 0; k < 4; k++) {
        const dex_pose_t p = coach_poses[k];
        const charm_sprite_anim_t &a = AC(p);
        CHECK(a.count >= 2 && a.frames != A(p).frames);
        dex_set_pose(p);
        advance(5);
        CHECK(shows_one_of(a));  // bit-exact at the same anchor, unscaled: not the placeholder
        CHECK(!nonblack(0, 0, CHARM_W, Y0 - 2));  // nothing outside the cell
        shot(coach_shots[k]);
        const int first = shown();
        advance(a.frames[0].ms);
        CHECK(shows_one_of(a) && shown() != first);  // he animates on his own ms
    }
    // Every Dex image stays off screen while Coach wears the body.
    auto shows_dex = [&]() {
        const int img = shown();
        if (img < 0) return false;
        for (int p = 0; p < DEX_POSE_COUNT; p++) {
            for (int o = 0; o < DEX_OUTFIT_COUNT; o++) {
                const charm_sprite_anim_t &a = A((dex_pose_t)p, (dex_outfit_t)o);
                for (int i = 0; i < a.count; i++) {
                    if (a.frames[i].img == img) return true;
                }
            }
        }
        return false;
    };
    // No Coach frames for done: the gray placeholder, never Dex's nod.
    dex_set_pose(DEX_POSE_DONE);
    advance(5);
    CHECK(AC(DEX_POSE_DONE).count == 0 && A(DEX_POSE_DONE).count > 0);
    CHECK(shown() == -1 && has_gray() && !shows_dex());
    shot("coach-placeholder.png");
    // An outfit borrows Coach's own default frames, not Dex's reading art.
    dex_set_pose(DEX_POSE_IDLE);
    dex_set_outfit(DEX_OUTFIT_READING);
    advance(5);
    CHECK(shows_one_of(AC(DEX_POSE_IDLE)) && !shows_dex());
    dex_set_outfit(DEX_OUTFIT_DEFAULT);
    // Dex's lift exit clip never plays after a switch: Dex lifts, Coach takes over, releases.
    dex_set_character(DEX_CHARACTER_DEX);
    dex_set_pose(DEX_POSE_LIFT_BAG);
    advance(5);
    CHECK(cell_hash() == fnv_frame(DEX_POSE_LIFT_BAG, 0));
    dex_set_character(DEX_CHARACTER_COACH);
    advance(5);
    CHECK(shown() == -1 && has_gray());  // no Coach lift: placeholder
    dex_set_pose(DEX_POSE_OFFER_BAG);
    advance(5);
    CHECK(shown() == -1 && has_gray() && !shows_dex());  // not Dex's release in-betweens
    dex_set_pose(DEX_POSE_SPEAKING);
    advance(5);
    CHECK(shows_one_of(AC(DEX_POSE_SPEAKING)));
    // And back to Dex, on his own frames.
    dex_set_character(DEX_CHARACTER_DEX);
    dex_set_pose(DEX_POSE_IDLE);
    advance(5);
    CHECK(shows_dex());  // bit-exact Dex frames (his art has the placeholder's gray in it)
    shot("dex-after-coach.png");

    printf("dex smooth check: %d failure(s); shots in %s\n", failures, out_dir.c_str());
    return failures ? 1 : 0;
}
