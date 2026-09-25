// Scripted drivers for the simulator: example cards, replay files, headless screenshots.
#pragma once
#include <stdint.h>
#include <string>
#include <vector>

// contract/examples/*.json, sorted by name (number keys 1..8 in the window).
std::vector<std::string> sim_example_paths(void);
bool sim_read_file(const std::string &path, std::string *out);
// Feed a card file to the UI as a server `card` frame.
bool sim_inject_card_file(const std::string &path);
// A server `welcome` with the Mac's local time (the sim plays the backend until integration).
void sim_send_welcome_now(void);

// One replay line: a server->device JSON frame, or a sim directive:
//   {"_sim":"wait","ms":N}  {"_sim":"connected","value":bool}  {"_sim":"talk","value":"press"|"release"}
// Blank lines and lines starting with '#' are skipped. Returns false for invalid JSON.
// *wait_ms receives a requested pause (0 for none).
bool sim_replay_line(const std::string &line, uint32_t *wait_ms);

// Virtual clock: advance in 5 ms steps, running LVGL and charm_ui_tick like the host loop.
void sim_advance(uint32_t ms);

// Headless runs. Both init LVGL, the display and the UI themselves; return a process exit code.
int sim_run_shots(const char *dir);
int sim_run_replay_headless(const char *file, uint32_t interval_ms);
