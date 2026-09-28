// Dex Charm UI: the protocol-driven state machine and the 11 surfaces from docs/BRIEF.md § 5.
// Visuals are PLACEHOLDERS (gray boxes, default font). Behavior is contract: card replace by id,
// dismiss, displayed receipts, stale labels, hold-to-confirm, honest listening and offline.
// Uses only LVGL, ArduinoJson and charm_host.h, so the ESP32 build compiles it unchanged.
#include "charm_ui.h"
#include "charm_host.h"
#include "charm_ui_debug.h"
#include "dex_sprite.h"
#include "ui_card.h"
#include "ui_hold.h"
#include "ui_time.h"

#include <ArduinoJson.h>
#include <lvgl.h>
#include <stdio.h>
#include <string.h>
#include <string>
#include <utility>
#include <vector>

namespace {

constexpr uint32_t LISTEN_LIMIT_MS = 25000;  // matches the firmware's audio limit
constexpr uint32_t SENDING_TIMEOUT_MS = 20000;
constexpr uint32_t DONE_DECAY_MS = 4000;
constexpr uint32_t NIGHT_AFTER_MS = 60000;
constexpr uint8_t BRIGHT_DAY = 255;
constexpr uint8_t BRIGHT_NIGHT = 16;

// Placeholder grays. Not a palette: the design sprint replaces all of this.
const uint32_t C_BG = 0x000000, C_BOX = 0x2A2A2A, C_BTN = 0x5A5A5A, C_TEXT = 0xE0E0E0, C_DIM = 0x8A8A8A,
               C_NIGHT = 0x3A3A3A;

struct HeldCard {
    Card card;
    bool receipted = false;
    std::string sent_action;  // action sent, awaiting the backend
};

struct UiState {
    int connected = -1;  // -1 unknown (boot), 0 offline, 1 online
    std::string server_state = "idle", state_label, agent;
    uint32_t state_since = 0;
    bool listening = false;
    uint32_t listen_start = 0;
    float mic_level = 0;
    bool sending = false;  // talk released, audio handed to the host, no server reply yet
    uint32_t sending_since = 0;
    bool speaking = false;
    std::string transcript;
    bool error_active = false;
    std::string error_code, error_text;
    bool night = false;
    uint32_t last_activity = 0;
    bool edition_view = false;
    int edition_section = 0;
    bool edition_swiped = false;  // until the reader swipes, the edition opens at its first section
    bool card_hidden = false;
    std::vector<HeldCard> cards;  // arrival order; the back is in focus
    HeldCard editions[6];
    bool has_edition[6] = {};
    UiClock clock;
};

struct Widgets {
    lv_obj_t *content = nullptr;
    lv_obj_t *clock = nullptr;
    lv_obj_t *level_bar = nullptr;
    lv_obj_t *elapsed = nullptr;
    lv_obj_t *hold_bar = nullptr;
    lv_obj_t *cancel = nullptr;
    std::vector<std::pair<std::string, lv_obj_t *>> actions;
};

UiState S;
Widgets W;
bool ready = false;
bool dirty = false;
CharmSurface shown = CharmSurface::Home;
std::string shown_card;     // id on screen ("" = none)
std::string shown_section;  // edition section on screen
bool shown_stale = false;
bool shown_done = false;
HoldTracker hold;
std::string hold_card, hold_action;
uint32_t last_second = 0;

uint32_t now_ms() { return charm_host_millis(); }
// Elapsed ms, treating a `since` later than `now` (host read `now` first) as 0, never ~49 days.
uint32_t elapsed(uint32_t now, uint32_t since) { int32_t d = (int32_t)(now - since); return d > 0 ? (uint32_t)d : 0; }

// ---------------------------------------------------------------- outgoing frames

void send_doc(const JsonDocument &doc) {
    char buf[512];
    const size_t n = serializeJson(doc, buf, sizeof buf);
    if (n > 0 && n < sizeof buf) charm_host_send(buf, n);
}

void send_simple(const char *type) {
    JsonDocument doc;
    doc["type"] = type;
    send_doc(doc);
}

void send_displayed(const std::string &id) {
    JsonDocument doc;
    doc["type"] = "displayed";
    doc["id"] = id;
    send_doc(doc);
}

void send_action(const std::string &card_id, const std::string &action, bool with_held, uint32_t held_ms) {
    JsonDocument doc;
    doc["type"] = "action";
    doc["card_id"] = card_id;
    doc["action"] = action;
    if (with_held) doc["held_ms"] = held_ms;
    send_doc(doc);
}

void send_request(const char *what) {
    JsonDocument doc;
    doc["type"] = "request";
    doc["what"] = what;
    send_doc(doc);
}

// ---------------------------------------------------------------- model helpers

HeldCard *find_card(const std::string &id) {
    for (HeldCard &c : S.cards) {
        if (c.card.id == id) return &c;
    }
    return nullptr;
}

HeldCard *focused_card() {
    if (S.cards.empty() || S.card_hidden) return nullptr;
    return &S.cards.back();
}

int first_edition_from(int start, int step) {
    for (int i = start; i >= 0 && i < 6; i += step) {
        if (S.has_edition[i]) return i;
    }
    return -1;
}

int edition_count() {
    int n = 0;
    for (bool b : S.has_edition) n += b;
    return n;
}

HeldCard *edition_on_screen() {
    if (!S.edition_view) return nullptr;
    if (!S.edition_swiped || !S.has_edition[S.edition_section]) {
        const int first = first_edition_from(0, 1);
        if (first < 0) return nullptr;
        S.edition_section = first;
    }
    return &S.editions[S.edition_section];
}

bool is_stale(const Card &c) { return card_is_stale(c, S.clock.known, S.clock.now_epoch(now_ms())); }

bool server_busy() { return S.server_state == "working" || S.server_state == "transcribing"; }

CharmSurface card_surface(CardKind kind) {
    switch (kind) {
        case CardKind::Decision: return CharmSurface::Decision;
        case CardKind::Money: return CharmSurface::Money;
        case CardKind::Tracker: return CharmSurface::Tracker;
        case CardKind::Edition: return CharmSurface::Edition;
        case CardKind::Job: return CharmSurface::Job;
        case CardKind::Answer:
        case CardKind::Notice: break;
    }
    return CharmSurface::Answer;
}

bool is_card_surface(CharmSurface s) {
    return s == CharmSurface::Answer || s == CharmSurface::Decision || s == CharmSurface::Money ||
           s == CharmSurface::Tracker || s == CharmSurface::Job;
}

CharmSurface compute_surface() {
    if (S.connected == 0) return CharmSurface::Offline;  // only set_connected(false) gets here
    if (S.listening) return CharmSurface::Listening;     // only after mic_start() returned true
    if (S.error_active) return CharmSurface::Error;
    if (S.night) return CharmSurface::Night;
    if (S.edition_view) return CharmSurface::Edition;
    if (HeldCard *c = focused_card()) return card_surface(c->card.kind);
    if (S.sending || server_busy()) return CharmSurface::Working;
    return CharmSurface::Home;
}

dex_pose_t compute_pose(CharmSurface s) {
    switch (s) {
        case CharmSurface::Offline: return DEX_POSE_OFFLINE;
        case CharmSurface::Listening: return DEX_POSE_LISTENING;
        case CharmSurface::Error: return DEX_POSE_ERROR;
        case CharmSurface::Night: return DEX_POSE_ASLEEP;
        default: break;
    }
    if (S.speaking || S.server_state == "speaking") return DEX_POSE_SPEAKING;
    if (S.server_state == "done") return DEX_POSE_DONE;
    if (S.sending || server_busy()) return DEX_POSE_WORKING;
    if (S.server_state == "attention" || !S.cards.empty()) return DEX_POSE_ATTENTION;
    return DEX_POSE_IDLE;
}

void activity() {
    S.last_activity = now_ms();
    if (S.night) {
        S.night = false;
        charm_host_set_brightness(BRIGHT_DAY);
        dirty = true;
    }
}

// ---------------------------------------------------------------- widget helpers

lv_obj_t *label(lv_obj_t *parent, const std::string &text, uint32_t color = C_TEXT, lv_coord_t width = 0) {
    lv_obj_t *l = lv_label_create(parent);
    lv_label_set_text(l, text.c_str());
    lv_obj_set_style_text_color(l, lv_color_hex(color), 0);
    if (width > 0) {
        lv_obj_set_width(l, width);
        lv_label_set_long_mode(l, LV_LABEL_LONG_WRAP);
    }
    return l;
}

lv_obj_t *centered_label(lv_obj_t *parent, const std::string &text, lv_coord_t y, uint32_t color = C_TEXT) {
    lv_obj_t *l = label(parent, text, color, CHARM_W - 32);
    lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(l, LV_ALIGN_TOP_MID, 0, y);
    return l;
}

void header(const std::string &text, uint32_t color = C_DIM) {
    lv_obj_t *l = label(W.content, text, color);
    lv_obj_align(l, LV_ALIGN_TOP_LEFT, 10, 8);
}

lv_obj_t *button(lv_obj_t *parent, const std::string &text) {
    lv_obj_t *b = lv_btn_create(parent);
    lv_obj_set_style_bg_color(b, lv_color_hex(C_BTN), 0);
    lv_obj_set_style_shadow_width(b, 0, 0);
    lv_obj_set_style_radius(b, 0, 0);
    lv_obj_set_height(b, 40);
    lv_obj_t *l = label(b, text);
    lv_obj_center(l);
    return b;
}

lv_obj_t *bar(lv_obj_t *parent, lv_coord_t w) {
    lv_obj_t *b = lv_bar_create(parent);
    lv_obj_set_size(b, w, 12);
    lv_obj_set_style_radius(b, 0, 0);
    lv_obj_set_style_radius(b, 0, LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(b, lv_color_hex(C_BTN), 0);
    lv_obj_set_style_bg_color(b, lv_color_hex(C_TEXT), LV_PART_INDICATOR);
    lv_bar_set_range(b, 0, 1000);
    return b;
}

constexpr lv_coord_t PANEL_TEXT_W = CHARM_W - 16 - 24;

// The gray card panel under the mini Dex: a scrolling flex column.
lv_obj_t *card_panel() {
    lv_obj_t *p = lv_obj_create(W.content);
    lv_obj_remove_style_all(p);
    lv_obj_set_style_bg_color(p, lv_color_hex(C_BOX), 0);
    lv_obj_set_style_bg_opa(p, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(p, 12, 0);
    lv_obj_set_style_pad_row(p, 8, 0);
    lv_obj_set_pos(p, 8, 88);
    lv_obj_set_size(p, CHARM_W - 16, CHARM_H - 96);
    lv_obj_set_flex_flow(p, LV_FLEX_FLOW_COLUMN);
    lv_obj_clear_flag(p, LV_OBJ_FLAG_CLICKABLE);  // taps fall through to the surface
    return p;
}

void card_common_top(lv_obj_t *p, const Card &c, bool stale) {
    label(p, c.title, C_TEXT, PANEL_TEXT_W);
    if (stale) {
        label(p, c.stale ? "STALE - the desk missed its deadline" : "STALE - past its fresh-until time", C_TEXT,
              PANEL_TEXT_W);
    }
    if (!c.body.empty()) label(p, c.body, C_TEXT, PANEL_TEXT_W);
}

void card_footer(lv_obj_t *p, const Card &c) {
    if (!c.footer.empty()) label(p, c.footer, C_DIM, PANEL_TEXT_W);
}

void action_event(lv_event_t *e);
void hold_event(lv_event_t *e);

// Buttons for a card's actions. Hold actions track press/release; the rest send on click.
void card_actions(lv_obj_t *p, const HeldCard &h) {
    if (h.card.actions.empty()) return;
    if (!h.sent_action.empty()) {
        // Never a check before the backend confirms: only state{done} earns it.
        if (shown_done) label(p, "Confirmed", C_TEXT, PANEL_TEXT_W);
        else label(p, "Sent \"" + h.sent_action + "\". Waiting for confirmation.", C_DIM, PANEL_TEXT_W);
        return;
    }
    lv_obj_t *row = lv_obj_create(p);
    lv_obj_remove_style_all(row);
    lv_obj_set_size(row, PANEL_TEXT_W, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW_WRAP);
    lv_obj_set_style_pad_column(row, 6, 0);
    lv_obj_set_style_pad_row(row, 6, 0);
    lv_obj_clear_flag(row, LV_OBJ_FLAG_CLICKABLE);
    for (const CardAction &a : h.card.actions) {
        lv_obj_t *b = button(row, a.label.empty() ? a.id : a.label);
        lv_obj_set_width(b, a.hold_ms > 0 ? PANEL_TEXT_W : (PANEL_TEXT_W - 12) / 3);
        W.actions.emplace_back(a.id, b);
        if (a.hold_ms > 0) {
            lv_obj_add_event_cb(b, hold_event, LV_EVENT_ALL, nullptr);
            if (hold_card != h.card.id || hold_action != a.id) {
                hold.reset(a.hold_ms);
                hold_card = h.card.id;
                hold_action = a.id;
            }
            W.hold_bar = bar(row, PANEL_TEXT_W);
        } else {
            lv_obj_add_event_cb(b, action_event, LV_EVENT_CLICKED, nullptr);
        }
    }
}

// ---------------------------------------------------------------- surfaces

void build_home() {
    header("HOME");
    W.clock = centered_label(W.content, "--:--", 40);
    std::string status;
    if (!S.cards.empty()) {
        status = std::to_string(S.cards.size()) + (S.cards.size() == 1 ? " card waiting" : " cards waiting") +
                 " - tap";
    } else if (S.server_state == "done") {
        status = S.state_label.empty() ? "Done" : S.state_label;
    } else if (S.connected < 0) {
        status = "Connecting...";
    } else {
        status = "Nothing needs you. Swipe left for the edition.";
    }
    centered_label(W.content, status, 336, C_DIM);
}

void build_listening() {
    header("LISTENING");
    W.level_bar = bar(W.content, 200);
    lv_obj_align(W.level_bar, LV_ALIGN_TOP_MID, 0, 336);
    W.elapsed = centered_label(W.content, "", 360, C_DIM);
    centered_label(W.content, "Release to send", 392, C_DIM);
}

void cancel_event(lv_event_t *) {
    activity();
    send_simple("cancel");
    S.sending = false;
    dirty = true;
}

void build_working() {
    header("WORKING");
    std::string what = S.state_label;
    if (what.empty()) {
        if (S.sending) what = "Sending...";
        else if (S.server_state == "transcribing") what = "Transcribing...";
        else if (!S.agent.empty()) what = "Asking " + S.agent + "...";
        else what = "Working...";
    }
    centered_label(W.content, what, 328);
    if (!S.transcript.empty()) centered_label(W.content, "\"" + S.transcript + "\"", 354, C_DIM);
    W.cancel = button(W.content, "Cancel");
    lv_obj_set_width(W.cancel, 120);
    lv_obj_align(W.cancel, LV_ALIGN_BOTTOM_MID, 0, -12);
    lv_obj_add_event_cb(W.cancel, cancel_event, LV_EVENT_CLICKED, nullptr);
}

void build_card(const HeldCard &h, bool stale) {
    const Card &c = h.card;
    header(std::string(charm_ui_surface_name(card_surface(c.kind))) + " | " + c.source);
    lv_obj_t *p = card_panel();
    card_common_top(p, c, stale);
    switch (c.kind) {
        case CardKind::Decision:
            label(p, "Default: " + c.default_choice + " (by " + c.deadline + ")", C_DIM, PANEL_TEXT_W);
            break;
        case CardKind::Money: {
            if (c.fixture) label(p, "SAMPLE ORDER - nothing will be charged", C_TEXT, PANEL_TEXT_W);
            label(p, c.store, C_TEXT, PANEL_TEXT_W);
            for (const CardItem &it : c.items) {
                std::string line = std::to_string(it.qty) + "x " + it.name;
                if (it.has_price) line += "  " + ui_format_money(it.price, "");
                label(p, line, C_DIM, PANEL_TEXT_W);
            }
            std::string total = "Total " + ui_format_money(c.total, c.currency);
            if (c.eta_min >= 0) total += " | ETA " + std::to_string(c.eta_min) + " min";
            label(p, total, C_TEXT, PANEL_TEXT_W);
            if (!c.address_label.empty()) label(p, "To: " + c.address_label, C_DIM, PANEL_TEXT_W);
            break;
        }
        case CardKind::Tracker:
            for (size_t i = 0; i < c.steps.size(); i++) {
                const int idx = (int)i;
                const char *mark = idx < c.current ? "[x] " : idx == c.current ? "[>] " : "[ ] ";
                label(p, mark + c.steps[i], idx == c.current ? C_TEXT : C_DIM, PANEL_TEXT_W);
            }
            if (c.eta_min >= 0) label(p, "ETA " + std::to_string(c.eta_min) + " min", C_TEXT, PANEL_TEXT_W);
            break;
        case CardKind::Job: {
            std::string status = "Status: " + c.status;
            if (c.progress >= 0) status += " (" + std::to_string((int)(c.progress * 100)) + "%)";
            label(p, status, C_DIM, PANEL_TEXT_W);
            break;
        }
        case CardKind::Answer:
        case CardKind::Notice:
            if (S.speaking) label(p, "Speaking - tap to stop", C_DIM, PANEL_TEXT_W);
            break;
        case CardKind::Edition: break;
    }
    card_footer(p, c);
    card_actions(p, h);
}

void build_edition(HeldCard *h, bool stale) {
    if (!h) {
        header("EDITION");
        lv_obj_t *p = card_panel();
        label(p, "Pocket edition", C_TEXT, PANEL_TEXT_W);
        label(p, "Requested from the desk. Nothing filed yet.", C_DIM, PANEL_TEXT_W);
        return;
    }
    const Card &c = h->card;
    int pos = 0;
    for (int i = 0; i <= S.edition_section; i++) pos += S.has_edition[i];
    header("EDITION " + std::to_string(pos) + "/" + std::to_string(edition_count()) + " | " + c.section);
    lv_obj_t *p = card_panel();
    if (c.edition_no >= 0) label(p, "No. " + std::to_string(c.edition_no), C_DIM, PANEL_TEXT_W);
    card_common_top(p, c, stale);
    if (!c.tiles.empty()) {
        std::string tiles;
        for (const CardTile &t : c.tiles) tiles += "[" + t.value + " " + t.label + "] ";
        label(p, tiles, C_TEXT, PANEL_TEXT_W);
    }
    for (const CardRow &r : c.rows) {
        label(p, r.stamp.empty() ? "- " + r.text : "- " + r.text + "  (" + r.stamp + ")", C_TEXT, PANEL_TEXT_W);
    }
    if (!c.moon.empty()) label(p, "Moon: " + c.moon, C_DIM, PANEL_TEXT_W);
    card_footer(p, c);
    card_actions(p, *h);
    label(p, "< swipe >", C_DIM, PANEL_TEXT_W);
}

void build_night() {
    header("NIGHT", C_NIGHT);
    W.clock = centered_label(W.content, "--:--", 40, C_NIGHT);
}

void build_offline() {
    header("OFFLINE");
    centered_label(W.content, "Offline", 328);
    centered_label(W.content, "No connection to the charm server. Cards shown before may be out of date.", 356,
                   C_DIM);
}

void build_error() {
    header("ERROR");
    centered_label(W.content, "Error: " + S.error_code, 328);
    if (!S.error_text.empty()) centered_label(W.content, S.error_text, 356, C_DIM);
    centered_label(W.content, "Tap to dismiss", 410, C_DIM);
}

void update_live() {
    const uint32_t now = now_ms();
    if (W.level_bar) lv_bar_set_value(W.level_bar, (int32_t)(S.mic_level * 1000), LV_ANIM_OFF);
    if (W.elapsed) {
        char t[32];
        const uint32_t e = elapsed(now, S.listen_start);
        snprintf(t, sizeof t, "%u.%u s / %u s", (unsigned)(e / 1000), (unsigned)(e % 1000 / 100),
                 (unsigned)(LISTEN_LIMIT_MS / 1000));
        if (strcmp(lv_label_get_text(W.elapsed), t) != 0) lv_label_set_text(W.elapsed, t);
    }
    if (W.hold_bar) lv_bar_set_value(W.hold_bar, (int32_t)(hold.progress(now) * 1000), LV_ANIM_OFF);
    if (W.clock) {
        char hhmm[8];
        S.clock.format_hhmm(now, hhmm, sizeof hhmm);
        if (strcmp(lv_label_get_text(W.clock), hhmm) != 0) lv_label_set_text(W.clock, hhmm);
    }
}

void rebuild() {
    dirty = false;
    if (!ready) return;
    const CharmSurface s = compute_surface();
    lv_obj_clean(W.content);
    lv_obj_t *content = W.content;
    W = Widgets{};
    W.content = content;
    shown = s;
    shown_card.clear();
    shown_section.clear();
    shown_stale = false;
    shown_done = S.server_state == "done";

    HeldCard *visible = nullptr;
    if (s == CharmSurface::Edition) {
        visible = edition_on_screen();
        if (visible) shown_section = EDITION_SECTIONS[S.edition_section];
    } else if (is_card_surface(s)) {
        visible = focused_card();
    }
    if (visible) {
        shown_card = visible->card.id;
        shown_stale = is_stale(visible->card);
    }
    // A rebuild deletes the pressed button, so its release would never arrive: abandon the hold.
    hold.cancel();

    dex_set_size(s == CharmSurface::Edition || is_card_surface(s) ? DEX_SIZE_MINI : DEX_SIZE_FULL);
    dex_set_pose(compute_pose(s));

    switch (s) {
        case CharmSurface::Home: build_home(); break;
        case CharmSurface::Listening: build_listening(); break;
        case CharmSurface::Working: build_working(); break;
        case CharmSurface::Edition: build_edition(visible, shown_stale); break;
        case CharmSurface::Night: build_night(); break;
        case CharmSurface::Offline: build_offline(); break;
        case CharmSurface::Error: build_error(); break;
        default:
            if (visible) build_card(*visible, shown_stale);
            break;
    }
    update_live();

    // Receipt: only after the card is actually drawn, once per version of the card.
    if (visible && !visible->receipted) {
        lv_refr_now(nullptr);
        visible->receipted = true;
        send_displayed(visible->card.id);
    }
}

// ---------------------------------------------------------------- input

HeldCard *card_for_actions() {
    if (shown == CharmSurface::Edition) return edition_on_screen();
    if (!is_card_surface(shown)) return nullptr;
    return focused_card();
}

void action_event(lv_event_t *e) {
    lv_obj_t *target = lv_event_get_target(e);
    HeldCard *h = card_for_actions();
    if (!h || !h->sent_action.empty()) return;
    for (auto &a : W.actions) {
        if (a.second == target) {
            activity();
            send_action(h->card.id, a.first, false, 0);
            h->sent_action = a.first;
            dirty = true;  // rebuilt in tick: never delete a widget inside its own event
            return;
        }
    }
}

void complete_hold(uint32_t held_ms) {
    HeldCard *h = card_for_actions();
    if (!h || h->card.id != hold_card || !h->sent_action.empty()) return;
    send_action(hold_card, hold_action, true, held_ms);
    h->sent_action = hold_action;
    dirty = true;
}

void hold_event(lv_event_t *e) {
    const lv_event_code_t code = lv_event_get_code(e);
    uint32_t held = 0;
    if (code == LV_EVENT_PRESSED) {
        activity();
        hold.press(now_ms());
    } else if (code == LV_EVENT_RELEASED) {
        if (hold.release(now_ms(), &held)) complete_hold(held);
    } else if (code == LV_EVENT_PRESS_LOST) {
        hold.cancel();
    } else {
        return;
    }
    if (W.hold_bar) lv_bar_set_value(W.hold_bar, (int32_t)(hold.progress(now_ms()) * 1000), LV_ANIM_OFF);
}

void open_edition() {
    S.edition_view = true;
    S.edition_swiped = false;
    const int first = first_edition_from(0, 1);
    S.edition_section = first < 0 ? 0 : first;
    send_request("edition");
}

void on_swipe(lv_dir_t dir) {
    activity();
    switch (shown) {
        case CharmSurface::Home:
            if (dir == LV_DIR_LEFT) open_edition();
            break;
        case CharmSurface::Edition:
            if (dir == LV_DIR_LEFT || dir == LV_DIR_RIGHT) {
                const int step = dir == LV_DIR_LEFT ? 1 : -1;
                const int next = first_edition_from(S.edition_section + step, step);
                if (next >= 0) S.edition_section = next;
                S.edition_swiped = true;
            } else {
                S.edition_view = false;
            }
            break;
        case CharmSurface::Answer:
        case CharmSurface::Decision:
        case CharmSurface::Money:
        case CharmSurface::Tracker:
        case CharmSurface::Job:
            if (dir == LV_DIR_BOTTOM) S.card_hidden = true;
            break;
        default: break;
    }
    dirty = true;
}

void on_tap() {
    const bool was_night = S.night;
    activity();
    if (was_night) return;
    switch (shown) {
        case CharmSurface::Home:
            if (!S.cards.empty()) S.card_hidden = false;
            break;
        case CharmSurface::Error: S.error_active = false; break;
        case CharmSurface::Answer:
            if (S.speaking) {
                charm_host_speech_stop();
                send_simple("cancel");
                S.speaking = false;
            }
            break;
        default: break;
    }
    dirty = true;
}

void content_event(lv_event_t *e) {
    const lv_event_code_t code = lv_event_get_code(e);
    if (code == LV_EVENT_GESTURE) {
        lv_indev_t *indev = lv_indev_get_act();
        if (indev) on_swipe(lv_indev_get_gesture_dir(indev));
    } else if (code == LV_EVENT_CLICKED) {
        on_tap();
    }
}

// ---------------------------------------------------------------- protocol

void on_state(JsonObjectConst msg) {
    const char *value = msg["value"].as<const char *>();
    if (!value) return;
    // The device owns these two: listening only while the mic captures, offline only from the host.
    if (strcmp(value, "listening") == 0 || strcmp(value, "offline") == 0) return;
    static const char *const KNOWN[] = {"idle", "transcribing", "working", "speaking", "attention", "done", "error"};
    bool known = false;
    for (const char *k : KNOWN) known = known || strcmp(value, k) == 0;
    if (!known) return;

    S.server_state = value;
    S.state_since = now_ms();
    S.state_label = msg["label"] | "";
    S.agent = msg["agent"] | "";
    S.sending = false;
    if (strcmp(value, "idle") == 0) S.transcript.clear();
    else activity();
    if (strcmp(value, "error") == 0) {
        S.error_active = true;
        S.error_code = "error";
        S.error_text = S.state_label;
    }
}

void on_card(JsonObjectConst msg) {
    Card card;
    if (!ui_card_parse(msg["card"].as<JsonObjectConst>(), &card)) return;
    activity();
    if (card.kind == CardKind::Edition) {
        const int idx = edition_section_index(card.section);
        if (idx < 0) return;
        if (hold_card == S.editions[idx].card.id) hold_card.clear();
        S.editions[idx] = HeldCard{};
        S.editions[idx].card = std::move(card);
        S.has_edition[idx] = true;
        return;
    }
    if (HeldCard *existing = find_card(card.id)) {
        // Same id = replace in place: fresh content, a fresh receipt, any pending action cleared.
        if (hold_card == existing->card.id) hold_card.clear();
        existing->card = std::move(card);
        existing->receipted = false;
        existing->sent_action.clear();
        return;
    }
    S.cards.emplace_back();
    S.cards.back().card = std::move(card);
    S.card_hidden = false;
    S.edition_view = false;
    S.error_active = false;
}

void on_dismiss(JsonObjectConst msg) {
    const char *id = msg["card_id"].as<const char *>();
    if (!id) return;
    for (size_t i = 0; i < S.cards.size(); i++) {
        if (S.cards[i].card.id == id) {
            S.cards.erase(S.cards.begin() + (long)i);
            break;
        }
    }
    for (int i = 0; i < 6; i++) {
        if (S.has_edition[i] && S.editions[i].card.id == id) {
            S.has_edition[i] = false;
            S.editions[i] = HeldCard{};
        }
    }
    if (hold_card == id) hold_card.clear();
    if (S.cards.empty()) S.card_hidden = false;
}

void on_error(JsonObjectConst msg) {
    S.error_active = true;
    S.error_code = msg["code"] | "unknown";
    S.error_text = msg["text"] | "";
    S.sending = false;
    // The action in flight failed (e.g. a too_short money hold): the card stays and can be retried.
    for (HeldCard &c : S.cards) c.sent_action.clear();
    for (HeldCard &c : S.editions) c.sent_action.clear();
    activity();
}

}  // namespace

// ---------------------------------------------------------------- public API (charm_ui.h)

void charm_ui_init(void) {
    lv_obj_t *screen = lv_scr_act();
    lv_obj_set_style_bg_color(screen, lv_color_hex(C_BG), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
    lv_obj_clear_flag(screen, LV_OBJ_FLAG_SCROLLABLE);

    W.content = lv_obj_create(screen);
    lv_obj_remove_style_all(W.content);
    lv_obj_set_size(W.content, CHARM_W, CHARM_H);
    lv_obj_clear_flag(W.content, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(W.content, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(W.content, content_event, LV_EVENT_ALL, nullptr);

    dex_create(screen);  // after content, so Dex draws on top of every surface
    S = UiState{};
    shown = CharmSurface::Home;
    shown_card.clear();
    shown_section.clear();
    shown_stale = shown_done = dirty = false;
    hold = HoldTracker{};
    hold_card.clear();
    hold_action.clear();
    S.last_activity = now_ms();
    last_second = now_ms();
    ready = true;
    charm_host_set_brightness(BRIGHT_DAY);
    rebuild();
}

void charm_ui_on_message(const char *json, size_t len) {
    if (!ready || !json || len == 0) return;
    JsonDocument doc;
    if (deserializeJson(doc, json, len)) return;  // malformed: ignore
    JsonObjectConst msg = doc.as<JsonObjectConst>();
    const char *type = msg["type"].as<const char *>();
    if (!type) return;

    if (strcmp(type, "welcome") == 0) {
        int64_t epoch;
        int32_t offset;
        if (ui_parse_iso8601(msg["time"] | "", &epoch, &offset)) S.clock.set(epoch, offset, now_ms());
    } else if (strcmp(type, "state") == 0) {
        on_state(msg);
    } else if (strcmp(type, "mode") == 0) {
        dex_outfit_t outfit;
        if (dex_outfit_from_mode(msg["value"] | "", &outfit)) dex_set_outfit(outfit);
        return;
    } else if (strcmp(type, "transcript") == 0) {
        S.transcript = msg["text"] | "";
    } else if (strcmp(type, "card") == 0) {
        on_card(msg);
    } else if (strcmp(type, "dismiss") == 0) {
        on_dismiss(msg);
    } else if (strcmp(type, "speech_start") == 0) {
        S.speaking = true;
    } else if (strcmp(type, "speech_end") == 0) {
        S.speaking = false;
    } else if (strcmp(type, "error") == 0) {
        on_error(msg);
    } else {
        return;  // pong and unknown types change nothing
    }
    rebuild();
}

void charm_ui_set_connected(bool connected) {
    const int value = connected ? 1 : 0;
    if (S.connected == value) return;
    S.connected = value;
    if (!connected) {
        // The socket is gone: nothing in flight can finish honestly.
        if (S.listening) {
            S.listening = false;
            charm_host_mic_stop("cancel");
        }
        if (S.speaking) charm_host_speech_stop();
        S.speaking = false;
        S.sending = false;
        S.server_state = "idle";
        S.state_label.clear();
        S.transcript.clear();
        for (HeldCard &c : S.cards) c.sent_action.clear();
        hold.cancel();
        if (S.night) {
            S.night = false;
            charm_host_set_brightness(BRIGHT_DAY);
        }
    } else {
        S.last_activity = now_ms();
    }
    rebuild();
}

void charm_ui_talk_pressed(void) {
    if (!ready) return;
    activity();
    if (S.connected == 0 || S.listening) {
        rebuild();
        return;
    }
    if (S.speaking) {
        charm_host_speech_stop();
        send_simple("cancel");
        S.speaking = false;
    }
    S.error_active = false;
    S.edition_view = false;
    if (!S.cards.empty()) S.card_hidden = true;
    if (charm_host_mic_start()) {
        S.listening = true;
        S.listen_start = now_ms();
        S.mic_level = 0;
    }
    rebuild();
}

void charm_ui_talk_released(void) {
    if (!S.listening) return;
    activity();
    S.listening = false;
    charm_host_mic_stop("released");
    S.sending = true;
    S.sending_since = now_ms();
    rebuild();
}

void charm_ui_mic_level(float level) {
    if (level < 0) level = 0;
    if (level > 1) level = 1;
    S.mic_level = level;
    if (W.level_bar) lv_bar_set_value(W.level_bar, (int32_t)(level * 1000), LV_ANIM_OFF);
}

void charm_ui_tick(uint32_t now) {
    if (!ready) return;
    dex_tick(now);

    if (S.listening && elapsed(now, S.listen_start) >= LISTEN_LIMIT_MS) {
        S.listening = false;
        charm_host_mic_stop("limit");
        S.sending = true;
        S.sending_since = now;
        dirty = true;
    }
    if (S.sending && elapsed(now, S.sending_since) >= SENDING_TIMEOUT_MS) {
        S.sending = false;
        dirty = true;
    }
    if (S.server_state == "done" && elapsed(now, S.state_since) >= DONE_DECAY_MS) {
        S.server_state = "idle";
        S.state_label.clear();
        dirty = true;
    }
    uint32_t held = 0;
    if (hold.update(now, &held)) complete_hold(held);

    if (!S.night && S.connected == 1 && shown == CharmSurface::Home && S.cards.empty() && !S.speaking &&
        S.server_state == "idle") {
        uint32_t idle = elapsed(now, S.last_activity);
        const uint32_t touch_idle = lv_disp_get_inactive_time(nullptr);
        if (touch_idle < idle) idle = touch_idle;
        if (idle >= NIGHT_AFTER_MS) {
            S.night = true;
            charm_host_set_brightness(BRIGHT_NIGHT);
            dirty = true;
        }
    }

    // Once a second: a stale label can appear on its own when fresh_until passes.
    if (now - last_second >= 1000) {
        last_second = now;
        HeldCard *visible = shown == CharmSurface::Edition ? edition_on_screen() : nullptr;
        if (!visible && !shown_card.empty()) visible = find_card(shown_card);
        if (visible && is_stale(visible->card) != shown_stale) dirty = true;
    }

    if (dirty || compute_surface() != shown) rebuild();
    else update_live();
}

// ---------------------------------------------------------------- debug (charm_ui_debug.h)

const char *charm_ui_surface_name(CharmSurface s) {
    switch (s) {
        case CharmSurface::Home: return "HOME";
        case CharmSurface::Listening: return "LISTENING";
        case CharmSurface::Working: return "WORKING";
        case CharmSurface::Answer: return "ANSWER";
        case CharmSurface::Decision: return "DECISION";
        case CharmSurface::Money: return "MONEY";
        case CharmSurface::Tracker: return "TRACKER";
        case CharmSurface::Edition: return "EDITION";
        case CharmSurface::Job: return "JOB";
        case CharmSurface::Night: return "NIGHT";
        case CharmSurface::Offline: return "OFFLINE";
        case CharmSurface::Error: return "ERROR";
    }
    return "?";
}

CharmSurface charm_ui_debug_surface(void) { return shown; }
std::string charm_ui_debug_card_id(void) { return shown_card; }
std::string charm_ui_debug_card_title(void) {
    if (shown_card.empty()) return "";
    HeldCard *h = shown == CharmSurface::Edition ? edition_on_screen() : find_card(shown_card);
    return h ? h->card.title : "";
}
std::string charm_ui_debug_edition_section(void) { return shown_section; }
size_t charm_ui_debug_card_count(void) { return S.cards.size(); }
size_t charm_ui_debug_edition_count(void) { return (size_t)edition_count(); }
bool charm_ui_debug_stale_shown(void) { return shown_stale; }
bool charm_ui_debug_done_shown(void) {
    HeldCard *h = card_for_actions();
    return shown_done && h && !h->sent_action.empty();
}
bool charm_ui_debug_listening(void) { return S.listening; }
bool charm_ui_debug_night(void) { return S.night; }
float charm_ui_debug_hold_progress(void) { return hold.progress(now_ms()); }

lv_obj_t *charm_ui_debug_action_button(const char *action_id) {
    for (auto &a : W.actions) {
        if (a.first == action_id) return a.second;
    }
    return nullptr;
}
lv_obj_t *charm_ui_debug_cancel_button(void) { return W.cancel; }

void charm_ui_debug_swipe(lv_dir_t dir) { on_swipe(dir); }
void charm_ui_debug_tap(void) { on_tap(); }
