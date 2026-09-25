// Wi-Fi + the charm WebSocket (docs/PROTOCOL.md), run on its own FreeRTOS task.
//
// The socket's TCP connect blocks for up to 5 s when the server is unreachable, so it never runs on
// the UI loop. The task owns every socket call: it sends hello, pings every 10 s, reconnects with
// the charm_core Backoff schedule, streams mic frames, and feeds speech frames to the player.
// The UI loop talks to it through two queues: outbound (charm_host_send, audio start/end) and
// inbound (text frames for charm_ui_on_message, plus online/offline notices in order).
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace net {

struct Inbound {
    enum Kind : uint8_t { Text, Online, Offline } kind = Text;
    char *data = nullptr;  // Text only: NUL-terminated copy, release() it
    size_t len = 0;
};

// Starts Wi-Fi and the network task. Returns false when there are no secrets to connect with.
bool begin();

// True between the server's welcome and the socket going down.
bool online();

// Queue one device->server text frame. False (and nothing queued) when offline or full.
bool send_text(const char *json, size_t len);
// Queue audio_start; binary mic frames follow from audio::mic_read().
bool audio_start();
// Queue the end of a talk: remaining mic audio is flushed first (unless "cancel"), then audio_end.
bool audio_end(const char *reason);

// UI loop: take the next inbound item, if any. Call release() on it when done.
bool poll(Inbound &out);
void release(Inbound &item);

}  // namespace net
