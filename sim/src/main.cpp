// charm-sim: the Dex Charm UI in a 368x448 SDL2 window.
//   mouse = touch · space = talk button (hold) · 1-8 = inject contract/examples/*.json (sorted)
//   arrows = swipe · c = toggle connection · d = state{done} · i = state{idle} · x = dismiss card
//   --scale N        window scale (default 2)
//   --replay FILE    feed server frames from a .jsonl file (one per --interval ms, default 700)
//   --headless       no window: run --replay on a virtual clock and exit
//   --shots DIR      render every surface headlessly to DIR/01-home.png … and exit
// Device->server frames print to stdout as JSON lines; host notes go to stderr.
#include "charm_ui.h"
#include "charm_ui_debug.h"
#include "sim_display.h"
#include "sim_host.h"
#include "charm_host.h"
#include "sim_script.h"

#include <SDL.h>
#include <fstream>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>

namespace {

void usage() {
    fprintf(stderr,
            "usage: charm-sim [--scale N] [--replay FILE.jsonl [--interval MS] [--headless]] [--shots DIR]\n");
}

void help_keys() {
    fprintf(stderr,
            "[sim] mouse=touch  space=talk  arrows=swipe  c=connection  d=done  i=idle  x=dismiss\n");
    const auto examples = sim_example_paths();
    for (size_t i = 0; i < examples.size() && i < 9; i++) {
        fprintf(stderr, "[sim] %zu = %s\n", i + 1, examples[i].substr(examples[i].rfind('/') + 1).c_str());
    }
}

void feed(const std::string &m) { charm_ui_on_message(m.c_str(), m.size()); }

}  // namespace

int main(int argc, char **argv) {
    int scale = 2;
    const char *replay = nullptr;
    const char *shots = nullptr;
    bool headless = false;
    uint32_t interval = 700;
    for (int i = 1; i < argc; i++) {
        const std::string a = argv[i];
        const bool has_next = i + 1 < argc;
        if (a == "--scale" && has_next) scale = atoi(argv[++i]);
        else if (a == "--replay" && has_next) replay = argv[++i];
        else if (a == "--shots" && has_next) shots = argv[++i];
        else if (a == "--interval" && has_next) interval = (uint32_t)atoi(argv[++i]);
        else if (a == "--headless") headless = true;
        else {
            usage();
            return 2;
        }
    }
    if (scale < 1) scale = 1;

    if (shots) return sim_run_shots(shots);
    if (headless) {
        if (!replay) {
            usage();
            return 2;
        }
        return sim_run_replay_headless(replay, interval);
    }

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS) != 0) {
        fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
        return 1;
    }
    SDL_Window *win = SDL_CreateWindow("Dex Charm (sim)", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                                       CHARM_W * scale, CHARM_H * scale, 0);
    SDL_Renderer *ren = win ? SDL_CreateRenderer(win, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC) : nullptr;
    SDL_Texture *tex = ren ? SDL_CreateTexture(ren, SDL_PIXELFORMAT_RGB565, SDL_TEXTUREACCESS_STREAMING, CHARM_W, CHARM_H)
                           : nullptr;
    if (!tex) {
        fprintf(stderr, "SDL window: %s\n", SDL_GetError());
        return 1;
    }
    SDL_RenderSetLogicalSize(ren, CHARM_W, CHARM_H);

    sim_display_init();
    charm_ui_init();
    charm_ui_set_connected(true);
    sim_send_welcome_now();
    help_keys();

    std::ifstream replay_file;
    if (replay) {
        replay_file.open(replay);
        if (!replay_file) fprintf(stderr, "[sim] cannot open %s\n", replay);
    }
    uint32_t next_replay = charm_host_millis() + 500;

    const auto examples = sim_example_paths();
    bool connected = true;
    bool running = true;
    bool mouse_down = false;
    uint32_t last = charm_host_millis();
    while (running) {
        SDL_Event ev;
        while (SDL_PollEvent(&ev)) {
            switch (ev.type) {
                case SDL_QUIT: running = false; break;
                case SDL_MOUSEBUTTONDOWN:
                case SDL_MOUSEBUTTONUP:
                    if (ev.button.button == SDL_BUTTON_LEFT) mouse_down = ev.type == SDL_MOUSEBUTTONDOWN;
                    sim_pointer_set(ev.button.x, ev.button.y, mouse_down);
                    break;
                case SDL_MOUSEMOTION: sim_pointer_set(ev.motion.x, ev.motion.y, mouse_down); break;
                case SDL_KEYDOWN: {
                    if (ev.key.repeat) break;
                    const SDL_Keycode k = ev.key.keysym.sym;
                    if (k == SDLK_SPACE) charm_ui_talk_pressed();
                    else if (k >= SDLK_1 && k <= SDLK_9) {
                        const size_t idx = (size_t)(k - SDLK_1);
                        if (idx < examples.size()) {
                            // Edition sections only show inside the edition, so open it first.
                            if (examples[idx].find("/edition-") != std::string::npos &&
                                charm_ui_debug_surface() == CharmSurface::Home)
                                charm_ui_debug_swipe(LV_DIR_LEFT);
                            sim_inject_card_file(examples[idx]);
                        }
                    } else if (k == SDLK_LEFT) charm_ui_debug_swipe(LV_DIR_LEFT);
                    else if (k == SDLK_RIGHT) charm_ui_debug_swipe(LV_DIR_RIGHT);
                    else if (k == SDLK_DOWN) charm_ui_debug_swipe(LV_DIR_BOTTOM);
                    else if (k == SDLK_UP) charm_ui_debug_swipe(LV_DIR_TOP);
                    else if (k == SDLK_c) {
                        connected = !connected;
                        charm_ui_set_connected(connected);
                        if (connected) sim_send_welcome_now();
                    } else if (k == SDLK_d) feed("{\"type\":\"state\",\"value\":\"done\"}");
                    else if (k == SDLK_i) feed("{\"type\":\"state\",\"value\":\"idle\"}");
                    else if (k == SDLK_x) {
                        const std::string id = charm_ui_debug_card_id();
                        if (!id.empty()) feed("{\"type\":\"dismiss\",\"card_id\":\"" + id + "\"}");
                    } else if (k == SDLK_h) help_keys();
                    else if (k == SDLK_ESCAPE || k == SDLK_q) running = false;
                    break;
                }
                case SDL_KEYUP:
                    if (ev.key.keysym.sym == SDLK_SPACE) charm_ui_talk_released();
                    break;
                default: break;
            }
        }

        const uint32_t now = charm_host_millis();
        if (replay_file.is_open() && now >= next_replay) {
            std::string line;
            if (std::getline(replay_file, line)) {
                uint32_t wait = 0;
                if (!sim_replay_line(line, &wait)) fprintf(stderr, "[sim] replay: invalid JSON line\n");
                next_replay = now + (wait ? wait : interval);
            } else {
                replay_file.close();
                fprintf(stderr, "[sim] replay finished\n");
            }
        }
        if (sim_mic_capturing()) {
            // Fake mic: a wobbling level so the listening indicator moves.
            charm_ui_mic_level(0.35f + 0.3f * sinf((float)now / 180.0f));
        }

        lv_tick_inc(now - last);
        last = now;
        lv_timer_handler();
        charm_ui_tick(now);

        SDL_UpdateTexture(tex, nullptr, sim_framebuffer(), CHARM_W * (int)sizeof(lv_color_t));
        const uint8_t b = sim_brightness();
        SDL_SetTextureColorMod(tex, b, b, b);
        SDL_RenderClear(ren);
        SDL_RenderCopy(ren, tex, nullptr, nullptr);
        SDL_RenderPresent(ren);
        SDL_Delay(5);
    }

    SDL_DestroyTexture(tex);
    SDL_DestroyRenderer(ren);
    SDL_DestroyWindow(win);
    SDL_Quit();
    return 0;
}
