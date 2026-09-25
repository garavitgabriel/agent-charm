#include "sim_live.h"

#include "audio_util.h"  // firmware/lib/charm_core: level meter, 25 s TalkSession, Keepalive
#include "backoff.h"
#include "charm_host.h"
#include "charm_ui.h"
#include "frames.h"
#include "sim_audio.h"

#include <ArduinoJson.h>
#include <deque>
#include <ixwebsocket/IXNetSystem.h>
#include <ixwebsocket/IXWebSocket.h>
#include <memory>
#include <mutex>
#include <stdio.h>
#include <string.h>
#include <vector>

namespace {

constexpr uint32_t kWelcomeTimeoutMs = 10000;  // as firmware/src/net.cpp
constexpr size_t kSendChunk = 2048;            // 64 ms of mic audio per binary frame (<= 4096)
constexpr uint32_t kAutoTalkDelayMs = 800;

// ---- socket thread -> host loop ----
struct Item {
    enum Kind { Open, Text, Binary, Down } kind;
    uint64_t gen;
    std::string data;  // Text/Binary payload, Down reason
};
std::mutex q_mutex;
std::deque<Item> queue;

void push(Item item) {
    std::lock_guard<std::mutex> lock(q_mutex);
    queue.push_back(std::move(item));
}

bool pop(Item *out) {
    std::lock_guard<std::mutex> lock(q_mutex);
    if (queue.empty()) return false;
    *out = std::move(queue.front());
    queue.pop_front();
    return true;
}

// ---- link state (host loop only) ----
enum class Link { Waiting, Connecting, Hello, Online, Paused };

bool active = false;
SimLiveOptions opts;
std::unique_ptr<ix::WebSocket> ws;
uint64_t gen = 0;  // bumps on every connect; late events from an old socket are ignored
Link link_state = Link::Waiting;
uint32_t next_attempt = 0, hello_at = 0;
charm::Backoff backoff;
charm::Keepalive keepalive;

// ---- talk ----
charm::TalkSession talk;
std::vector<uint8_t> pending;  // captured mic audio not sent yet
uint32_t last_level = 0;
bool auto_talk_done = false;
uint32_t online_at = 0;
bool wav_released = false;
bool silence_warned = false;
bool heard_any_sound = false;

// ---- the reply to the last talk, for timings and headless checks ----
bool awaiting_reply = false, reply_done = false, speech_seen = false;
uint32_t t_release = 0;
std::string answer_id;
size_t speech_bytes = 0;

void note(const char *fmt, const char *arg = "") {
    fprintf(stderr, fmt, arg);
    fputc('\n', stderr);
}

void timing(const char *what, uint32_t now) {
    if (awaiting_reply) fprintf(stderr, "[timing] %-14s +%6u ms after release\n", what, now - t_release);
}

void send_text_frame(const char *json, size_t len) {
    if (!ws || (link_state != Link::Hello && link_state != Link::Online)) return;
    ws->sendText(std::string(json, len));
}

void send_binary(const uint8_t *data, size_t n) {
    if (!ws || link_state != Link::Online) return;
    for (size_t off = 0; off < n; off += charm::kMaxBinaryFrame) {
        const size_t len = n - off < charm::kMaxBinaryFrame ? n - off : charm::kMaxBinaryFrame;
        ws->sendBinary(std::string((const char *)data + off, len));
    }
}

void connect_now(uint32_t now) {
    if (ws) ws->stop();
    const uint64_t my_gen = ++gen;
    ws = std::make_unique<ix::WebSocket>();
    ws->setUrl(opts.url);
    ws->disableAutomaticReconnection();  // charm::Backoff drives reconnects, as on the device
    ws->disablePerMessageDeflate();      // audio doesn't compress; the server turns it off too
    ws->setHandshakeTimeout(5);
    ws->setOnMessageCallback([my_gen](const ix::WebSocketMessagePtr &msg) {
        switch (msg->type) {
            case ix::WebSocketMessageType::Open: push({Item::Open, my_gen, {}}); break;
            case ix::WebSocketMessageType::Message:
                push({msg->binary ? Item::Binary : Item::Text, my_gen, msg->str});
                break;
            case ix::WebSocketMessageType::Close:
                push({Item::Down, my_gen,
                      "closed " + std::to_string(msg->closeInfo.code) + " " + msg->closeInfo.reason});
                break;
            case ix::WebSocketMessageType::Error:
                push({Item::Down, my_gen, "error: " + msg->errorInfo.reason});
                break;
            default: break;
        }
    });
    link_state = Link::Connecting;
    hello_at = now;
    fprintf(stderr, "[net] connecting to %s\n", opts.url.c_str());
    ws->start();
}

void end_talk(const char *reason) {
    if (!talk.active()) return;
    std::vector<uint8_t> tail;
    sim_mic_close(strcmp(reason, "cancel") == 0 ? nullptr : &tail);
    if (strcmp(reason, "cancel") != 0) {
        pending.insert(pending.end(), tail.begin(), tail.end());
        send_binary(pending.data(), pending.size() & ~(size_t)1);
    }
    pending.clear();
    talk.end();
    char buf[96];
    const size_t n = charm::frame_audio_end(buf, sizeof buf, reason);
    send_text_frame(buf, n);
    if (opts.trace) note("[tx] audio_end{%s}", reason);
    if (strcmp(reason, "cancel") != 0) {
        awaiting_reply = true;
        reply_done = speech_seen = false;
        answer_id.clear();
        speech_bytes = 0;
        t_release = charm_host_millis();
        fprintf(stderr, "[talk] sent %.2f s of audio (%s)\n", (double)talk.bytes() / 32000.0, reason);
    }
}

// The socket is gone (or we dropped it): offline, stop listening and speaking, schedule a retry.
void go_down(uint32_t now, const std::string &why, bool paused) {
    const bool was_online = link_state == Link::Online;
    if (ws) ws->stop();
    ws.reset();
    ++gen;
    if (talk.active()) {  // the stream is gone: nothing more to send
        sim_mic_close(nullptr);
        pending.clear();
        talk.end();
    }
    sim_speaker_stop();
    if (awaiting_reply) {
        awaiting_reply = false;
        reply_done = true;  // no reply is coming on this socket
    }
    if (was_online) charm_ui_set_connected(false);
    if (paused) {
        link_state = Link::Paused;
        note("[net] disconnected (c to reconnect)");
        return;
    }
    link_state = Link::Waiting;
    const uint32_t wait = backoff.next();
    next_attempt = now + wait;
    fprintf(stderr, "[net] down (%s); retry in %u ms\n", why.c_str(), wait);
}

void on_text(const std::string &text, uint32_t now) {
    const charm::Peek peek = charm::peek_message(text.data(), text.size());
    if (opts.trace && peek.type != charm::MsgType::Pong) fprintf(stderr, "[rx] %s\n", text.c_str());
    switch (peek.type) {
        case charm::MsgType::Welcome:
            link_state = Link::Online;
            online_at = now;
            backoff.reset();
            keepalive.reset(now);
            note("[net] welcome: online");
            charm_ui_set_connected(true);  // the UI hears "connected" before the welcome itself
            break;
        case charm::MsgType::Pong: keepalive.on_pong(now); break;
        case charm::MsgType::SpeechStart:
            if (peek.speech_format_ok) {
                sim_speaker_start();
                speech_seen = true;
                timing("speech_start", now);
            } else {
                note("[net] speech_start in an unsupported format, not playing");
            }
            break;
        case charm::MsgType::SpeechEnd:
            sim_speaker_end();
            if (awaiting_reply && speech_seen) {
                speech_bytes = sim_speaker_bytes();
                timing("speech_end", now);
                fprintf(stderr, "[speech] %zu bytes (%.2f s)\n", speech_bytes, (double)speech_bytes / 32000.0);
            }
            break;
        case charm::MsgType::Error:
            if (peek.auth_error) note("[net] the server refused our token (check CHARM_TOKEN)");
            break;
        default: break;
    }
    if (awaiting_reply && peek.type == charm::MsgType::Other) {
        JsonDocument doc;
        if (!deserializeJson(doc, text)) {
            const char *type = doc["type"] | "";
            if (strcmp(type, "transcript") == 0 && (doc["final"] | false)) {
                timing("transcript", now);
                fprintf(stderr, "[talk] heard: %s\n", (const char *)(doc["text"] | ""));
            } else if (strcmp(type, "card") == 0 && strcmp(doc["card"]["kind"] | "", "answer") == 0) {
                answer_id = doc["card"]["id"] | "";
                timing("answer card", now);
            } else if (strcmp(type, "state") == 0) {
                const char *value = doc["value"] | "";
                if (strcmp(value, "working") == 0) timing("working", now);
                if (strcmp(value, "idle") == 0) {
                    timing("idle", now);
                    awaiting_reply = false;
                    reply_done = true;
                }
            }
        }
    }
    charm_ui_on_message(text.data(), text.size());
}

void drain(uint32_t now) {
    Item item;
    // Bounded per loop so a burst can't starve rendering (speech frames are cheap, allow more).
    for (int i = 0; i < 64 && pop(&item); ++i) {
        if (item.gen != gen) continue;  // from a socket we already dropped
        switch (item.kind) {
            case Item::Open: {
                const char *caps[] = {"mic", "speaker"};
                char buf[512];
                const size_t n = charm::frame_hello(buf, sizeof buf, opts.device_id.c_str(),
                                                    "charm-sim/0.2 proto/0", opts.token.c_str(), caps, 2);
                link_state = Link::Hello;
                hello_at = now;
                send_text_frame(buf, n);  // never printed: it carries the token
                note("[net] socket open, hello sent");
                break;
            }
            case Item::Text: on_text(item.data, now); break;
            case Item::Binary:
                if (awaiting_reply && sim_speaker_active() && sim_speaker_bytes() == 0 && !item.data.empty())
                    timing("first audio", now);
                sim_speaker_feed((const uint8_t *)item.data.data(), item.data.size());
                break;
            case Item::Down: go_down(now, item.data, false); return;
        }
    }
}

void pump_talk(uint32_t now) {
    if (!talk.active()) return;
    uint8_t buf[4096];
    size_t n;
    while ((n = sim_mic_read(buf, sizeof buf, now)) > 0) {
        pending.insert(pending.end(), buf, buf + n);
        talk.add_bytes(n);
        if (now - last_level >= 50) {
            last_level = now;
            charm_ui_mic_level(charm::pcm_level((const int16_t *)buf, n / 2));
        }
        for (size_t i = 0; i + 1 < n && !heard_any_sound; i += 2)
            if (buf[i] | buf[i + 1]) heard_any_sound = true;
    }
    while (pending.size() >= kSendChunk) {
        send_binary(pending.data(), kSendChunk);
        pending.erase(pending.begin(), pending.begin() + kSendChunk);
    }
    if (!sim_mic_uses_wav() && !heard_any_sound && !silence_warned && talk.elapsed_ms(now) > 1500) {
        silence_warned = true;
        note("[audio] the mic delivers pure silence: allow Microphone access for this terminal in "
             "System Settings > Privacy & Security > Microphone");
    }
    if (talk.expired(now)) {  // 25 s: the host ends the talk itself
        end_talk("limit");
        charm_ui_mic_level(0.0f);
        charm_ui_talk_released();  // the UI leaves listening; its mic_stop is a no-op now
        return;
    }
    if (sim_mic_exhausted() && !wav_released) {  // --mic-wav: the question is over
        wav_released = true;
        charm_ui_talk_released();
    }
}

}  // namespace

bool sim_live_begin(const SimLiveOptions &options) {
    opts = options;
    ix::initNetSystem();
    if (!sim_speaker_open(opts.null_speaker)) return false;
    active = true;
    link_state = Link::Waiting;
    next_attempt = 0;
    charm_ui_set_connected(false);  // offline until the server's welcome
    return true;
}

bool sim_live_active(void) { return active; }

void sim_live_pump(uint32_t now) {
    if (!active) return;
    drain(now);
    switch (link_state) {
        case Link::Waiting:
            if ((int32_t)(now - next_attempt) >= 0) connect_now(now);
            break;
        case Link::Connecting:
        case Link::Hello:
            if (now - hello_at > kWelcomeTimeoutMs) go_down(now, "no welcome within 10 s", false);
            break;
        case Link::Online: {
            char buf[32];
            if (keepalive.ping_due(now)) send_text_frame(buf, charm::frame_ping(buf, sizeof buf));
            if (keepalive.dead(now)) go_down(now, "no pong for 30 s", false);
            break;
        }
        case Link::Paused: break;
    }
    pump_talk(now);
    if (opts.auto_talk && !auto_talk_done && link_state == Link::Online && now - online_at >= kAutoTalkDelayMs) {
        auto_talk_done = true;
        note("[talk] auto-talk: holding the talk button");
        charm_ui_talk_pressed();
    }
}

void sim_live_toggle(void) {
    if (!active) return;
    if (link_state == Link::Paused) {
        backoff.reset();
        link_state = Link::Waiting;
        next_attempt = charm_host_millis();
    } else {
        go_down(charm_host_millis(), "dropped by the c key", true);
    }
}

void sim_live_end(void) {
    if (!active) return;
    if (ws) ws->stop();
    ws.reset();
    sim_mic_close(nullptr);
    sim_speaker_close();
    active = false;
}

bool sim_live_reply_done(void) { return reply_done; }
std::string sim_live_last_answer_id(void) { return answer_id; }
size_t sim_live_last_speech_bytes(void) { return speech_bytes; }

void sim_live_send(const char *json, size_t len) {
    if (link_state != Link::Online) {
        fprintf(stderr, "[net] offline, not sent: %.*s\n", (int)len, json);
        return;
    }
    send_text_frame(json, len);
}

bool sim_live_mic_start(void) {
    if (talk.active()) return true;
    if (link_state != Link::Online) return false;
    sim_speaker_stop();  // half-duplex: don't record Dex's own voice
    const uint32_t now = charm_host_millis();
    if (!sim_mic_open(now)) return false;
    char buf[96];
    send_text_frame(buf, charm::frame_audio_start(buf, sizeof buf));
    if (opts.trace) note("[tx] audio_start");
    pending.clear();
    wav_released = false;
    heard_any_sound = false;
    silence_warned = false;
    talk.begin(now);
    fprintf(stderr, "[host] mic_start -> true (%s)\n", sim_mic_uses_wav() ? "WAV file" : "Mac mic");
    return true;
}

void sim_live_mic_stop(const char *reason) {
    end_talk(charm::is_audio_end_reason(reason) ? reason : "released");
    charm_ui_mic_level(0.0f);
}

void sim_live_speech_stop(void) { sim_speaker_stop(); }
