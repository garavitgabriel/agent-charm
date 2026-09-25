// The live sim: a real client of docs/PROTOCOL.md over WebSocket (IXWebSocket), the Mac mic and
// speakers. It does what firmware/src/net.cpp + main.cpp do on the device, with the same
// charm_core pieces (frames, reconnect backoff, keepalive, the 25 s talk limit):
//   hello -> welcome (10 s timeout), ping every 10 s (dead after 30 s without a pong),
//   reconnect 1 s, 2 s, 4 s ... 30 s; charm_ui_set_connected() follows the real socket;
//   every server text frame goes to charm_ui_on_message(); speech frames go to the speaker.
// The socket runs on IXWebSocket's thread; everything else (UI, audio, sends) on the host loop.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string>

struct SimLiveOptions {
    std::string url;            // ws://HOST:PORT/charm
    std::string token;          // CHARM_TOKEN (never printed)
    std::string device_id = "charm-sim";
    bool null_speaker = false;  // count speech bytes instead of playing them (headless)
    bool auto_talk = false;     // hold the talk button once, as soon as the server welcomes us
    bool trace = false;         // print server text frames and host frames to stderr
};

// Call after charm_ui_init(). Opens the speaker and starts connecting. False on setup failure.
bool sim_live_begin(const SimLiveOptions &options);
bool sim_live_active(void);
// Host loop, before lv_timer_handler(): socket events, mic streaming, keepalive, reconnects.
void sim_live_pump(uint32_t now_ms);
// The window's `c` key: drop the socket and stay offline / reconnect.
void sim_live_toggle(void);
void sim_live_end(void);

// After a talk: true once the server went back to state{idle} (after speech_end or an error).
bool sim_live_reply_done(void);
// Summary for headless checks: answer card id and speech bytes of the last reply.
std::string sim_live_last_answer_id(void);
size_t sim_live_last_speech_bytes(void);

// charm_host.h in live mode (sim_host.cpp delegates here while sim_live_active()).
void sim_live_send(const char *json, size_t len);
bool sim_live_mic_start(void);
void sim_live_mic_stop(const char *reason);
void sim_live_speech_stop(void);
