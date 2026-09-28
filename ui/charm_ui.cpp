// Dex Charm UI: the protocol-driven state machine and the surfaces of design § 11 (the 14 final
// screens) and § 11.8 (reading). Visuals follow docs/design/final/tokens.md and motion.md; behavior
// is contract: card replace by id, dismiss, displayed receipts, stale labels, hold-to-confirm,
// honest listening, offline and saves. Uses only LVGL, ArduinoJson and charm_host.h, so the
// ESP32 build compiles it unchanged. Dex is posed only through dex_sprite.h.
#include "charm_ui.h"
#include "charm_host.h"
#include "charm_ui_debug.h"
#include "dex_sprite.h"
#include "ui_card.h"
#include "ui_hold.h"
#include "ui_motion.h"
#include "ui_time.h"
#include "ui_tokens.h"

#include <ArduinoJson.h>
#include <lvgl.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <string>
#include <utility>
#include <vector>

namespace {

constexpr uint32_t LISTEN_LIMIT_MS = 25000;  // the firmware's audio limit; the fuse runs over it
constexpr uint32_t SENDING_TIMEOUT_MS = 20000;
constexpr uint32_t DONE_DECAY_MS = 4000;
constexpr uint32_t NIGHT_AFTER_MS = 60000;
constexpr uint32_t SETTING_TIMEOUT_MS = 3000;  // a toggle with no echo springs back, changing nothing
constexpr uint8_t BRIGHT_DAY = 255;
constexpr uint8_t BRIGHT_NIGHT = 16;
constexpr int STREAM_LINES = 16;
constexpr int STREAM_PTS = 7;

struct HeldCard {
    Card card;
    bool receipted = false;
    std::string sent_action;  // action sent, awaiting the backend
    bool confirmed = false;   // state{done} arrived for the sent action
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
    // reading mode (PROTOCOL § Reading mode)
    bool reading = false;
    CardBook book;
    std::string speech;  // last `setting{speech}` echo; "" = none yet (the mode's default applies)
    bool speech_pending = false;
    uint32_t speech_pending_since = 0;
    int read_step = 1;  // 0 = 18, 1 = 22 (default), 2 = 26
    std::string read_card;
    int read_offset = 0;
    int read_anchor_para = -1;  // paragraph to keep at the top across a text-size change
};

// Objects that live as long as the screen: the gesture root, the base layer (floor, separator,
// fuse, scroll thumb) under Dex, and the overlay above him (voice stream, placard, bag).
struct Layers {
    lv_obj_t *root = nullptr, *base = nullptr, *overlay = nullptr;
    lv_obj_t *sep = nullptr, *fuse = nullptr, *thumb = nullptr;
    lv_point_t sep_pts[2], fuse_pts[2], thumb_pts[2];
    lv_obj_t *stream[STREAM_LINES] = {};
    lv_point_t stream_pts[STREAM_LINES][STREAM_PTS];
    lv_obj_t *exiting = nullptr;  // the previous page, fading out
    bool fuse_fading = false;
};

struct Widgets {
    lv_obj_t *page = nullptr;  // this surface's content (child of root)
    lv_obj_t *over = nullptr;  // this surface's overlay items (child of overlay)
    lv_obj_t *cancel = nullptr;
    std::vector<std::pair<std::string, lv_obj_t *>> actions;     // card actions
    std::vector<std::pair<std::string, lv_obj_t *>> ui_buttons;  // UI-only buttons
    std::string headline;
    // enter animation
    std::vector<lv_obj_t *> enter_lines, enter_rail;
    uint32_t enter_end = 0;
    // working
    lv_obj_t *working = nullptr;
    std::string working_base;
    int working_dots = 0;
    // money
    lv_obj_t *hold_label = nullptr, *bag_hit = nullptr, *bag_fill = nullptr, *bag_edge = nullptr;
    lv_obj_t *reject = nullptr;
    bool money_sent = false;
    bool done_bag = false;
    // reading column
    lv_obj_t *viewport = nullptr, *column = nullptr;
    int view_h = 0, total = 0, detail_top = 0, lead_lines = 0, lead_lh = 21, lh = 32, lines = 5;
    std::vector<int> para_tops;
    lv_obj_t *read_more = nullptr, *larger = nullptr, *smaller = nullptr, *foot1 = nullptr, *foot2 = nullptr;
    bool scroll_pressed = false, dragging = false;
    lv_coord_t press_y = 0;
    int press_offset = 0;
    // speech toggle
    lv_obj_t *speech = nullptr;
};

UiState S;
Layers L;
Widgets W;
bool ready = false;
bool dirty = false;
uint32_t rebuild_at = 0;  // a pending rebuild after tap feedback (0 = none)
CharmSurface shown = CharmSurface::Home;
std::string shown_identity;
std::string shown_card;     // id on screen ("" = none)
std::string shown_section;  // edition section on screen
bool shown_stale = false;
HoldTracker hold;
motion::BagFill bag;
motion::VoiceStream stream;
std::string hold_card, hold_action;
uint32_t last_second = 0;
uint32_t last_frame = 0;

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

void send_setting(const char *name, const char *value) {
    JsonDocument doc;
    doc["type"] = "setting";
    doc["name"] = name;
    doc["value"] = value;
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

bool speech_on() {
    if (!S.speech.empty()) return S.speech == "on";
    return !S.reading;  // PROTOCOL: reading defaults to quiet, everything else to speech on
}

// Which action sits on Dex's placard (the default) on a decision.
int placard_action(const Card &c) {
    for (size_t i = 0; i < c.actions.size(); i++) {
        if (c.actions[i].style == "primary") return (int)i;
    }
    for (size_t i = 0; i < c.actions.size(); i++) {
        if (c.actions[i].id == "approve") return (int)i;
    }
    return c.actions.empty() ? -1 : 0;
}

CharmSurface card_surface(const HeldCard &h) {
    const Card &c = h.card;
    switch (c.kind) {
        case CardKind::Decision: return c.default_choice.empty() ? CharmSurface::NeedsMore : CharmSurface::Decision;
        case CardKind::Money: return h.confirmed ? CharmSurface::Done : CharmSurface::Money;
        case CardKind::Tracker: return CharmSurface::Tracker;
        case CardKind::Edition: return CharmSurface::Edition;
        case CardKind::Job: return CharmSurface::Job;
        case CardKind::Answer:
            return (S.reading || c.book.present() || !c.detail.empty()) ? CharmSurface::ReadingAnswer
                                                                          : CharmSurface::Answer;
        case CardKind::Notice: return c.has_saved ? CharmSurface::Saved : CharmSurface::Answer;
    }
    return CharmSurface::Answer;
}

bool is_card_surface(CharmSurface s) {
    switch (s) {
        case CharmSurface::Answer:
        case CharmSurface::Decision:
        case CharmSurface::Money:
        case CharmSurface::Tracker:
        case CharmSurface::Job:
        case CharmSurface::Done:
        case CharmSurface::NeedsMore:
        case CharmSurface::ReadingAnswer:
        case CharmSurface::Saved: return true;
        default: return false;
    }
}

CharmSurface compute_surface() {
    if (S.connected == 0) return CharmSurface::Offline;  // only set_connected(false) gets here
    if (S.listening) return CharmSurface::Listening;     // only after mic_start() returned true
    if (S.error_active) return CharmSurface::Error;
    if (S.night) return CharmSurface::Night;
    if (S.edition_view) return CharmSurface::Edition;
    if (HeldCard *c = focused_card()) return card_surface(*c);
    if (S.sending || server_busy()) return CharmSurface::Working;
    if (S.reading) return CharmSurface::ReadingHome;
    return CharmSurface::Home;
}

dex_pose_t compute_pose(CharmSurface s) {
    const HeldCard *h = focused_card();
    switch (s) {
        case CharmSurface::Offline: return DEX_POSE_OFFLINE;
        case CharmSurface::Listening: return DEX_POSE_LISTENING;
        case CharmSurface::Error: return DEX_POSE_ERROR;
        case CharmSurface::Night: return DEX_POSE_ASLEEP;
        case CharmSurface::Working: return DEX_POSE_WORKING;
        case CharmSurface::Done: return DEX_POSE_DONE;
        case CharmSurface::NeedsMore: return DEX_POSE_ERROR;
        case CharmSurface::Tracker: return DEX_POSE_LOOKOUT;
        case CharmSurface::Edition: return DEX_POSE_PAPER;
        case CharmSurface::Saved: return h && h->card.saved ? DEX_POSE_DONE : DEX_POSE_OFFLINE;
        case CharmSurface::Decision: return h && h->confirmed ? DEX_POSE_DONE : DEX_POSE_ASK_YES;
        case CharmSurface::Job: return h && h->confirmed ? DEX_POSE_DONE : DEX_POSE_SHOW_PHONE;
        case CharmSurface::Money:
            return (hold.active || (h && !h->sent_action.empty())) ? DEX_POSE_LIFT_BAG : DEX_POSE_OFFER_BAG;
        case CharmSurface::Answer: return S.speaking ? DEX_POSE_SPEAKING : DEX_POSE_ATTENTION;
        // Honest mouth (chief ruling): talking only while speech plays. Quiet, he shows the page
        // (ATTENTION + reading outfit); once the lead has scrolled away he reads (PAPER).
        case CharmSurface::ReadingAnswer:
            if (S.speaking) return DEX_POSE_SPEAKING;
            return W.column && S.read_offset >= W.detail_top && W.detail_top < W.total ? DEX_POSE_PAPER
                                                                                     : DEX_POSE_ATTENTION;
        case CharmSurface::Home:
        case CharmSurface::ReadingHome: break;
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

std::string upper_first(std::string s) {
    if (!s.empty() && s[0] >= 'a' && s[0] <= 'z') s[0] = (char)(s[0] - 'a' + 'A');
    return s;
}

std::string lower_first(std::string s) {
    if (s.size() > 1 && s[0] >= 'A' && s[0] <= 'Z' && !(s[1] >= 'A' && s[1] <= 'Z')) s[0] = (char)(s[0] - 'A' + 'a');
    return s;
}

// Strip trailing "..." / "…" so the working dots can step on their own.
std::string strip_dots(std::string s) {
    for (;;) {
        if (!s.empty() && s.back() == '.') s.pop_back();
        else if (s.size() >= 3 && s.compare(s.size() - 3, 3, "\xE2\x80\xA6") == 0) s.resize(s.size() - 3);
        else break;
    }
    return s;
}

// "“thought”": the verbatim words in curly quotes, never paraphrased.
std::string curly_quoted(std::string s) {
    if (s.size() >= 2 && s.front() == '"' && s.back() == '"') s = s.substr(1, s.size() - 2);
    if (s.compare(0, 3, "\xE2\x80\x9C") == 0) return s;
    return "\xE2\x80\x9C" + s + "\xE2\x80\x9D";
}

std::string last_word(const std::string &s) {
    const size_t sp = s.find_last_of(' ');
    return sp == std::string::npos ? s : s.substr(sp + 1);
}

const char *weekday(int64_t epoch_local) {
    static const char *const DAYS[] = {"Thursday", "Friday", "Saturday", "Sunday", "Monday", "Tuesday", "Wednesday"};
    int64_t days = epoch_local / 86400;
    if (epoch_local < 0 && epoch_local % 86400) days--;
    return DAYS[((days % 7) + 7) % 7];
}

// ---------------------------------------------------------------- drawing helpers

lv_area_t point_or(dex_point_t which, const lv_area_t &fallback) {
    lv_area_t a;
    if (dex_get_point_area(which, &a)) return a;
    return fallback;
}

lv_obj_t *plain(lv_obj_t *parent) {
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_style_all(o);
    lv_obj_clear_flag(o, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_clear_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    return o;
}

lv_obj_t *rect(lv_obj_t *parent, lv_coord_t x, lv_coord_t y, lv_coord_t w, lv_coord_t h, uint32_t color,
               lv_coord_t radius = 0) {
    lv_obj_t *o = plain(parent);
    lv_obj_set_pos(o, x, y);
    lv_obj_set_size(o, w, h);
    lv_obj_set_style_bg_color(o, lv_color_hex(color), 0);
    lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(o, radius, 0);
    return o;
}

lv_obj_t *hline(lv_obj_t *parent, lv_point_t *pts, lv_coord_t x0, lv_coord_t x1, lv_coord_t y, uint32_t color) {
    pts[0] = {x0, y};
    pts[1] = {x1, y};
    lv_obj_t *l = lv_line_create(parent);
    lv_line_set_points(l, pts, 2);
    lv_obj_set_style_line_width(l, tok::SEP_W, 0);
    lv_obj_set_style_line_rounded(l, true, 0);
    lv_obj_set_style_line_color(l, lv_color_hex(color), 0);
    lv_obj_clear_flag(l, LV_OBJ_FLAG_CLICKABLE);
    return l;
}

void set_hline(lv_obj_t *l, lv_point_t *pts, lv_coord_t x0, lv_coord_t x1) {
    pts[0].x = x0;
    pts[1].x = x1;
    lv_line_set_points(l, pts, 2);
}

lv_coord_t line_space(const lv_font_t *font, lv_coord_t lh) { return (lv_coord_t)(lh - lv_font_get_line_height(font)); }

// Lines `text` wraps to at `width` in `font`.
int text_lines(const std::string &text, const lv_font_t *font, lv_coord_t lh, lv_coord_t width) {
    lv_point_t sz;
    const lv_coord_t ls = line_space(font, lh);
    lv_txt_get_size(&sz, text.c_str(), font, 0, ls, width, LV_TEXT_FLAG_NONE);
    return (int)((sz.y + ls + lh / 2) / lh);
}

lv_coord_t text_width(const std::string &text, const lv_font_t *font) {
    lv_point_t sz;
    lv_txt_get_size(&sz, text.c_str(), font, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
    return sz.x;
}

// A text line or block on true black. width 0 = one line, no wrap; max_lines > 0 clips with "…".
lv_obj_t *text(lv_obj_t *parent, const std::string &s, const lv_font_t *font, uint32_t color, lv_coord_t x,
               lv_coord_t y, lv_coord_t lh, lv_coord_t width = 0, int max_lines = 0) {
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, lv_color_hex(color), 0);
    lv_obj_set_style_text_line_space(l, line_space(font, lh), 0);
    lv_label_set_text(l, s.c_str());
    if (width > 0) {
        lv_obj_set_width(l, width);
        if (max_lines > 0 && text_lines(s, font, lh, width) > max_lines) {
            lv_label_set_long_mode(l, LV_LABEL_LONG_DOT);
            lv_obj_set_height(l, (lv_coord_t)(max_lines * lh - line_space(font, lh)));
        } else {
            lv_label_set_long_mode(l, LV_LABEL_LONG_WRAP);
        }
    } else {
        // Content width, never wrapped: in WRAP mode LVGL can push the last glyph ("…") onto a
        // hidden second line when the text exactly fills its own measured width.
        lv_label_set_long_mode(l, LV_LABEL_LONG_CLIP);
        lv_obj_set_width(l, LV_SIZE_CONTENT);
    }
    lv_obj_set_pos(l, x, y);
    return l;
}

// A content line that takes part in the enter stagger.
lv_obj_t *line(const std::string &s, const lv_font_t *font, uint32_t color, lv_coord_t x, lv_coord_t y, lv_coord_t lh,
               lv_coord_t width = 0, int max_lines = 0) {
    lv_obj_t *l = text(W.page, s, font, color, x, y, lh, width, max_lines);
    W.enter_lines.push_back(l);
    return l;
}

struct Fit {
    const lv_font_t *font;
    lv_coord_t lh;
    int lines;
};

// The largest headline step (32, then 24, then 18) that fits `max_h` px at `width`.
Fit fit_headline(const std::string &s, lv_coord_t width, lv_coord_t max_h) {
    const Fit steps[] = {{tok::f32m(), tok::LH32, 0}, {tok::f24m(), tok::LH24, 0}, {tok::f18m(), tok::LH18, 0}};
    for (int i = 0; i < 3; i++) {
        Fit f = steps[i];
        f.lines = text_lines(s, f.font, f.lh, width);
        if (f.lines * f.lh <= max_h) return f;
        if (i == 2) {
            f.lines = LV_MAX(1, max_h / f.lh);
            return f;
        }
    }
    return steps[2];
}

// Returns the y just below the headline.
lv_coord_t headline(const std::string &s, lv_coord_t y, lv_coord_t max_h) {
    const Fit f = fit_headline(s, tok::CONTENT_W, max_h);
    line(s, f.font, tok::FG, tok::PAD, y, f.lh, tok::CONTENT_W, f.lines);
    W.headline = s;
    return (lv_coord_t)(y + f.lines * f.lh);
}

void tap_feedback_event(lv_event_t *e) {
    lv_obj_t *t = lv_event_get_target(e);
    const lv_event_code_t code = lv_event_get_code(e);
    if (code == LV_EVENT_PRESSED) lv_obj_set_style_opa(t, motion::TAP_OPA, 0);
    else if (code == LV_EVENT_PRESS_LOST) lv_obj_set_style_opa(t, LV_OPA_COVER, 0);
}

// A text action: accent type on black, a 56 px transparent hit box, no outline.
lv_obj_t *text_action(const std::string &label, lv_coord_t y, lv_coord_t w = tok::RAIL_W,
                      const lv_font_t *font = tok::f24s(), lv_coord_t x = tok::RAIL_X) {
    lv_obj_t *b = plain(W.page);
    lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);
    const int lines = text_lines(label, font, tok::LH_ACTION, w);
    lv_obj_set_pos(b, x, y);
    lv_obj_set_size(b, w, (lv_coord_t)LV_MAX(tok::TOUCH, lines * tok::LH_ACTION + 16));
    lv_obj_t *l = text(b, label, font, tok::ACC, 0, 0, tok::LH_ACTION, w);
    lv_obj_align(l, LV_ALIGN_LEFT_MID, 0, 0);
    lv_obj_add_event_cb(b, tap_feedback_event, LV_EVENT_ALL, nullptr);
    W.enter_rail.push_back(b);
    return b;
}

// A filled action: accent fill, 56 px (72 px for two lines), radius 28, no stroke.
lv_obj_t *pill(const std::string &label, lv_coord_t y, lv_coord_t w, lv_coord_t padx = 18) {
    // Grow (up to the rail's 172 + a hand's width) until the label fits two lines: LVGL sets
    // Instrument Sans a few px wider than the browser the reference was rendered in.
    auto lines_at = [&](lv_coord_t ww) { return text_lines(label, tok::f24s(), tok::LH_ACTION, (lv_coord_t)(ww - 2 * padx)); };
    lv_coord_t one = w;
    while (one < tok::RAIL_MAX_W && lines_at(one) > 1) one = (lv_coord_t)(one + 4);
    if (lines_at(one) == 1) w = one;  // one line when it fits the rail
    while (w < 196 && lines_at(w) > 2) w = (lv_coord_t)(w + 4);
    lv_obj_t *b = plain(W.page);
    lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);
    const int lines = LV_MIN(2, text_lines(label, tok::f24s(), tok::LH_ACTION, (lv_coord_t)(w - 2 * padx)));
    lv_obj_set_pos(b, tok::RAIL_X, y);
    lv_obj_set_size(b, w, (lv_coord_t)LV_MAX(tok::PILL_H, lines * tok::LH_ACTION + 16));
    lv_obj_set_style_bg_color(b, lv_color_hex(tok::ACC), 0);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(b, tok::PILL_R, 0);
    lv_obj_t *l = text(b, label, tok::f24s(), tok::ON_ACC, 0, 0, tok::LH_ACTION, (lv_coord_t)(w - 2 * padx), 2);
    lv_obj_align(l, LV_ALIGN_LEFT_MID, padx, 0);
    lv_obj_add_event_cb(b, tap_feedback_event, LV_EVENT_ALL, nullptr);
    W.enter_rail.push_back(b);
    return b;
}

// Bottom-left secondary text in the rail (answer footer, stale reason), ending at y = 438.
void rail_footer(const std::string &s, lv_coord_t bottom = 438) {
    if (s.empty()) return;
    const int n = LV_MIN(3, text_lines(s, tok::f18r(), tok::LH18, tok::RAIL_MAX_W));
    lv_obj_t *l = text(W.page, s, tok::f18r(), tok::FG2, tok::PAD, (lv_coord_t)(bottom - n * tok::LH18), tok::LH18,
                       tok::RAIL_MAX_W, 3);
    W.enter_rail.push_back(l);
}

std::string stale_reason(const Card &c) {
    return c.stale ? "Stale: the desk missed its deadline." : "Stale: past its fresh-until time.";
}

// ---------------------------------------------------------------- animation

void anim_opa(void *o, int32_t v) { lv_obj_set_style_opa((lv_obj_t *)o, (lv_opa_t)v, 0); }
void anim_ty(void *o, int32_t v) { lv_obj_set_style_translate_y((lv_obj_t *)o, (lv_coord_t)v, 0); }

void start_anim(lv_obj_t *o, lv_anim_exec_xcb_t cb, int32_t from, int32_t to, uint32_t ms, uint32_t delay,
                lv_anim_path_cb_t path, lv_anim_ready_cb_t ready = nullptr) {
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, o);
    lv_anim_set_exec_cb(&a, cb);
    lv_anim_set_values(&a, from, to);
    lv_anim_set_time(&a, ms);
    lv_anim_set_delay(&a, delay);
    lv_anim_set_path_cb(&a, path);
    if (ready) lv_anim_set_ready_cb(&a, ready);
    cb(o, from);
    lv_anim_start(&a);
}

// Content enter (motion.md): each line fades in and rises 8 px over 180 ms, 40 ms apart, top to
// bottom, after the old content's 120 ms exit; the rail actions follow, fade only, 120 ms.
void start_enter() {
    int i = 0;
    uint32_t end = 0;
    for (lv_obj_t *o : W.enter_lines) {
        const uint32_t d = motion::enter_delay(i++, true);
        start_anim(o, anim_opa, 0, 255, motion::ENTER_MS, d, lv_anim_path_ease_out);
        start_anim(o, anim_ty, motion::ENTER_RISE_PX, 0, motion::ENTER_MS, d, lv_anim_path_ease_out);
        end = LV_MAX(end, d + motion::ENTER_MS);
    }
    const uint32_t rd = motion::enter_delay(i, true);
    for (lv_obj_t *o : W.enter_rail) {
        start_anim(o, anim_opa, 0, lv_obj_get_style_opa(o, 0), motion::RAIL_ENTER_MS, rd, lv_anim_path_linear);
        end = LV_MAX(end, rd + motion::RAIL_ENTER_MS);
    }
    W.enter_end = now_ms() + end;
}

void unclick_tree(lv_obj_t *o) {
    lv_obj_clear_flag(o, LV_OBJ_FLAG_CLICKABLE);
    const uint32_t n = lv_obj_get_child_cnt(o);
    for (uint32_t i = 0; i < n; i++) unclick_tree(lv_obj_get_child(o, (int32_t)i));
}

void exiting_deleted(lv_event_t *e) {
    if (L.exiting == lv_event_get_target(e)) L.exiting = nullptr;
}

// Content exit (motion.md): everything fades out over 120 ms, ease-in, no movement.
void exit_page(lv_obj_t *page) {
    if (L.exiting) lv_obj_del(L.exiting);  // at most one page fading at a time
    unclick_tree(page);
    L.exiting = page;
    lv_obj_add_event_cb(page, exiting_deleted, LV_EVENT_DELETE, nullptr);
    start_anim(page, anim_opa, 255, 0, motion::EXIT_MS, 0, lv_anim_path_ease_in, lv_obj_del_anim_ready_cb);
}

// ---------------------------------------------------------------- events

void action_event(lv_event_t *e);
void bag_event(lv_event_t *e);
void ui_button_event(lv_event_t *e);

void register_action(const std::string &id, lv_obj_t *b) {
    W.actions.emplace_back(id, b);
    lv_obj_add_event_cb(b, action_event, LV_EVENT_CLICKED, nullptr);
}

void register_ui(const char *id, lv_obj_t *b) {
    W.ui_buttons.emplace_back(id, b);
    lv_obj_add_event_cb(b, ui_button_event, LV_EVENT_CLICKED, nullptr);
}

// After an action is sent: the rail says so honestly, and only state{done} earns "Done."
void rail_sent_state(const HeldCard &h, lv_coord_t y) {
    if (h.confirmed) {
        W.enter_rail.push_back(text(W.page, "Done.", tok::f24m(), tok::FG, tok::PAD, y, tok::LH24));
    } else {
        W.enter_rail.push_back(text(W.page, "Sent. Waiting for Dex.", tok::f18r(), tok::FG2, tok::PAD, y, tok::LH18,
                                    tok::RAIL_MAX_W));
    }
}

// ---------------------------------------------------------------- surfaces

void build_home() {
    std::string status;
    if (!S.cards.empty()) {
        status = S.cards.size() == 1 ? "One card is waiting" : std::to_string(S.cards.size()) + " cards are waiting";
    } else if (S.server_state == "done") {
        status = S.state_label.empty() ? "Done." : S.state_label;
    } else if (S.connected < 0) {
        status = "Connecting\xE2\x80\xA6";
    } else {
        status = "Nothing needs you";
    }
    line(status, tok::f24m(), tok::FG2, tok::PAD, tok::SEP_Y - 20 - 28, tok::LH24, tok::CONTENT_W, 1);
    W.headline = status;
}

void build_listening() {
    line("I\xE2\x80\x99m listening.", tok::f32m(), tok::FG, tok::PAD, tok::PAD, tok::LH32);
    W.headline = "I\xE2\x80\x99m listening.";
}

void cancel_event(lv_event_t *) {
    activity();
    send_simple("cancel");
    S.sending = false;
    rebuild_at = now_ms() + motion::TAP_MS;
}

void build_working() {
    std::string what = strip_dots(S.state_label);
    if (what.empty()) {
        if (S.sending) what = "Sending";
        else if (S.server_state == "transcribing") what = "Listening back";
        else if (!S.agent.empty()) what = "Asking " + upper_first(S.agent);
        else what = "Working";
    }
    W.working_base = what;
    W.working_dots = -1;
    W.working = line(what + ".", tok::f32m(), tok::FG, tok::PAD, tok::PAD, tok::LH32, tok::CONTENT_W, 1);
    W.headline = what;
    if (!S.transcript.empty()) line(S.transcript, tok::f18r(), tok::FG2, tok::PAD, tok::PAD + 46, tok::LH18, tok::CONTENT_W, 2);
    W.cancel = text_action("Cancel", 340);
    lv_obj_add_event_cb(W.cancel, cancel_event, LV_EVENT_CLICKED, nullptr);
}

void build_answer(const HeldCard &h, bool stale) {
    const Card &c = h.card;
    if (c.body.empty()) {
        headline(c.title, tok::PAD, tok::CONTENT_BOTTOM - tok::PAD);
    } else {
        line(c.title, tok::f18r(), tok::FG2, tok::PAD, tok::PAD, tok::LH18, tok::CONTENT_W, 1);
        headline(c.body, tok::PAD + 28, tok::CONTENT_BOTTOM - tok::PAD - 28);
    }
    std::string foot = c.footer;
    if (stale) foot = stale_reason(c) + (foot.empty() ? "" : " " + foot);
    rail_footer(foot);
    int y = 236;
    for (const CardAction &a : c.actions) {
        if (!h.sent_action.empty()) break;
        register_action(a.id, text_action(a.label.empty() ? a.id : a.label, (lv_coord_t)y));
        y += 60;
    }
    if (!h.sent_action.empty()) rail_sent_state(h, 236);
}

void placard_face(const std::string &label) {
    // The sign itself (gold, 5° tilt) is in the ask_yes frames; the UI sets only its word.
    text(W.over, label, tok::f24s(), tok::ON_ACC, (lv_coord_t)(tok::PLACARD_CX - text_width(label, tok::f24s()) / 2),
         (lv_coord_t)(tok::PLACARD_CY - 13), 26);
}

void build_decision(const HeldCard &h, bool stale) {
    const Card &c = h.card;
    lv_coord_t y = headline(c.title, tok::PAD, 2 * tok::LH32);
    std::string def = "Default: " + lower_first(strip_dots(c.default_choice));
    if (!c.deadline.empty()) def += ", " + c.deadline;
    def += ".";
    y = (lv_coord_t)(y + 8);
    line(def, tok::f18r(), tok::FG2, tok::PAD, y, tok::LH18, tok::CONTENT_W, 1);
    y = (lv_coord_t)(y + tok::LH18 + 8);
    const int body_lines = (tok::CONTENT_BOTTOM - y) / tok::LH18;
    if (!c.body.empty() && body_lines > 0) line(c.body, tok::f18r(), tok::FG2, tok::PAD, y, tok::LH18, tok::CONTENT_W, body_lines);
    if (stale) rail_footer(stale_reason(c));

    if (!h.sent_action.empty()) {
        rail_sent_state(h, 300);
        return;
    }
    const int yes = placard_action(c);
    if (yes >= 0) {
        // The default rides on Dex's placard: "Yes" unless the action's own label fits the sign.
        const CardAction &a = c.actions[(size_t)yes];
        const std::string label = !a.label.empty() && text_width(a.label, tok::f24s()) <= 60 ? a.label : "Yes";
        placard_face(label);
        lv_obj_t *b = plain(W.over);
        lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_pos(b, tok::PLACARD_CX - 36, tok::PLACARD_CY - 30);
        lv_obj_set_size(b, 72, 60);
        register_action(a.id, b);
    }
    lv_coord_t ay = 300;
    for (size_t i = 0; i < c.actions.size(); i++) {
        if ((int)i == yes) continue;
        const CardAction &a = c.actions[i];
        register_action(a.id, text_action(a.label.empty() ? a.id : a.label, ay, 150));
        ay = (lv_coord_t)(ay + 62);
    }
}

void build_needs_more(const HeldCard &h) {
    const Card &c = h.card;
    lv_coord_t y = headline(c.title, tok::PAD, 3 * tok::LH32);
    const int body_lines = (tok::CONTENT_BOTTOM - y - 8) / tok::LH18;
    if (!c.body.empty() && body_lines > 0)
        line(c.body, tok::f18r(), tok::FG2, tok::PAD, (lv_coord_t)(y + 8), tok::LH18, tok::CONTENT_W, body_lines);
    if (!h.sent_action.empty()) {
        rail_sent_state(h, 300);
        return;
    }
    lv_coord_t py = c.actions.size() >= 3 ? 226 : 282;
    for (const CardAction &a : c.actions) {
        register_action(a.id, pill(a.label.empty() ? a.id : a.label, py, 148));
        py = (lv_coord_t)(py + 64);
    }
}

// Merchant, total (40) + currency (32) on one baseline, items · ETA · place.
void money_head(const Card &c) {
    line(c.store.empty() ? c.title : c.store, tok::f18m(), tok::FG, tok::PAD, tok::PAD + 3, tok::LH18, tok::CONTENT_W, 1);
    const std::string total = ui_format_total(c.total, c.currency);
    line(total, tok::f40m(), tok::FG, tok::PAD, 62, tok::LH40);
    W.headline = total;
    if (!c.currency.empty()) {
        const lv_font_t *f40 = tok::f40m(), *f32 = tok::f32m();
        const lv_coord_t base40 = (lv_coord_t)(lv_font_get_line_height(f40) - f40->base_line);
        const lv_coord_t base32 = (lv_coord_t)(lv_font_get_line_height(f32) - f32->base_line);
        line(c.currency, f32, tok::FG, (lv_coord_t)(tok::PAD + text_width(total, f40) + 8), (lv_coord_t)(62 + base40 - base32),
             tok::LH32);
    }
    int n = 0;
    for (const CardItem &it : c.items) n += it.qty;
    std::string meta = std::to_string(n) + (n == 1 ? " item" : " items");
    if (c.eta_min >= 0) meta += " \xC2\xB7 " + std::to_string(c.eta_min) + " min";
    if (!c.address_label.empty()) meta += " \xC2\xB7 " + c.address_label;
    line(meta, tok::f18r(), tok::FG2, tok::PAD, 120, tok::LH18, tok::CONTENT_W, 1);
}

void build_money(const HeldCard &h, bool stale) {
    const Card &c = h.card;
    money_head(c);
    // Honesty: a sample order says so (v0 never places a real order).
    std::string note = c.fixture && c.footer.empty() ? "Sample order. Nothing will be charged." : c.footer;
    if (stale) note = stale_reason(c);
    if (!note.empty()) line(note, tok::f18r(), tok::FG2, tok::PAD, 146, tok::LH18, tok::CONTENT_W, 2);

    W.money_sent = !h.sent_action.empty();
    W.hold_label = text(W.page, "", tok::f32s(), tok::ACC, tok::RAIL_X, 300, tok::LH_HOLD);  // explicit line break
    W.enter_rail.push_back(W.hold_label);

    // The fill is drawn over Dex's bag (overlay), never baked into the sprite.
    W.bag_fill = rect(W.over, 0, 0, 1, 1, tok::ACC);
    // The bag's side plane (ACC_D), as the design's filled bag carries it.
    rect(W.bag_fill, 0, 0, 1, LV_PCT(100), tok::ACC_D);
    W.bag_edge = rect(W.over, 0, 0, 1, 2, tok::INK);
    lv_obj_add_flag(W.bag_fill, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(W.bag_edge, LV_OBJ_FLAG_HIDDEN);
    if (W.money_sent) return;

    // The bag is the hold control: a >= 56 px hit box over it, at his chest.
    const CardAction *confirm = nullptr;
    for (const CardAction &a : c.actions) {
        if (a.hold_ms > 0 && !confirm) confirm = &a;
    }
    if (confirm) {
        const lv_area_t box = point_or(DEX_POINT_BAG, tok::BAG_PREVIEW);
        const lv_coord_t w = (lv_coord_t)LV_MAX(tok::TOUCH, lv_area_get_width(&box) + 16);
        const lv_coord_t hh = (lv_coord_t)LV_MAX(tok::TOUCH, lv_area_get_height(&box) + 16);
        W.bag_hit = plain(W.over);
        lv_obj_add_flag(W.bag_hit, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_pos(W.bag_hit, (lv_coord_t)((box.x1 + box.x2) / 2 - w / 2), (lv_coord_t)((box.y1 + box.y2) / 2 - hh / 2));
        lv_obj_set_size(W.bag_hit, w, hh);
        lv_obj_add_event_cb(W.bag_hit, bag_event, LV_EVENT_ALL, nullptr);
        W.actions.emplace_back(confirm->id, W.bag_hit);
        if (hold_card != c.id || hold_action != confirm->id) {
            hold.reset(confirm->hold_ms);
            hold_card = c.id;
            hold_action = confirm->id;
        }
    }
    // Any other action (e.g. reject) is a plain text action, at 18 px so money keeps 18/32/40.
    for (const CardAction &a : c.actions) {
        if (a.hold_ms > 0) continue;
        W.reject = text_action(a.label.empty() ? a.id : a.label, 380, 140, tok::f18m());
        register_action(a.id, W.reject);
        break;
    }
}

void build_done(const HeldCard &h) {
    const Card &c = h.card;
    // The fixture guard: a sample confirm never says "Ordered." (PROTOCOL clarification 4).
    const std::string head = c.fixture ? "Sample order." : "Ordered.";
    line(head, tok::f32m(), tok::FG, tok::PAD, tok::PAD, tok::LH32);
    W.headline = head;
    std::string second;
    if (c.fixture) {
        second = "Nothing was ordered.";
    } else if (c.eta_min >= 0 && S.clock.known) {
        char hhmm[8];
        ui_format_hhmm(S.clock.now_epoch(now_ms()) + c.eta_min * 60, S.clock.offset_s, hhmm, sizeof hhmm);
        second = std::string("Arriving ") + hhmm + ".";
    } else if (c.eta_min >= 0) {
        second = "Arriving in " + std::to_string(c.eta_min) + " min.";
    }
    if (!second.empty()) line(second, tok::f24m(), tok::FG, tok::PAD, tok::PAD + 44, tok::LH24, tok::CONTENT_W, 1);
    std::string where = c.store;
    if (!c.address_label.empty()) where += (where.empty() ? "" : " \xC2\xB7 ") + c.address_label;
    if (!where.empty()) line(where, tok::f18r(), tok::FG2, tok::PAD, tok::PAD + 82, tok::LH18, tok::CONTENT_W, 1);
    // The bag he hands over is full accent, baked into the `done` frames (chief ruling): no overlay.
    W.done_bag = true;
}

void build_tracker(const HeldCard &h, bool stale) {
    const Card &c = h.card;
    std::string top = c.title;
    if (c.eta_min >= 0) top += " \xC2\xB7 " + std::to_string(c.eta_min) + " min";
    line(top, tok::f18r(), tok::FG2, tok::PAD, tok::PAD, tok::LH18, tok::CONTENT_W, 1);
    const int n = (int)c.steps.size();
    if (n == 0) return;
    const int cur = LV_MAX(0, LV_MIN(c.current, n - 1));
    // Stop centres: 26 px apart, 34 before the current stop (32 px), 42 after; tighter if long.
    int gap = 26, before = 34, after = 42;
    auto span = [&](int g, int b, int a) { return (n - 1) * g + (cur > 0 ? b - g : 0) + (cur < n - 1 ? a - g : 0); };
    if (62 + span(gap, before, after) > tok::CONTENT_BOTTOM - 8) gap = 21, before = 29, after = 34;
    std::vector<int> ys((size_t)n);
    int y = 62;
    for (int i = 0; i < n; i++) {
        if (i > 0) y += (i == cur) ? before : (i == cur + 1 ? after : gap);
        ys[(size_t)i] = y;
    }
    const lv_coord_t x = tok::PAD + 6;
    static lv_point_t done_pts[2], todo_pts[2];
    if (cur > 0) {
        lv_obj_t *l = hline(W.page, done_pts, x, x, 0, tok::FG2);
        done_pts[0] = {x, (lv_coord_t)ys[0]};
        done_pts[1] = {x, (lv_coord_t)ys[(size_t)cur]};
        lv_line_set_points(l, done_pts, 2);
    }
    if (cur < n - 1) {
        lv_obj_t *l = hline(W.page, todo_pts, x, x, 0, tok::LINE);
        todo_pts[0] = {x, (lv_coord_t)ys[(size_t)cur]};
        todo_pts[1] = {x, (lv_coord_t)ys[(size_t)(n - 1)]};
        lv_line_set_points(l, todo_pts, 2);
    }
    for (int i = 0; i < n; i++) {
        const lv_coord_t cy = (lv_coord_t)ys[(size_t)i];
        if (i == cur) {
            rect(W.page, (lv_coord_t)(x - 8), (lv_coord_t)(cy - 8), 16, 16, tok::FG, LV_RADIUS_CIRCLE);
            line(c.steps[(size_t)i], tok::f32m(), tok::FG, tok::PAD + 24, (lv_coord_t)(cy - 19), tok::LH32, 296, 1);
            W.headline = c.steps[(size_t)i];
        } else if (i < cur) {
            rect(W.page, (lv_coord_t)(x - 5), (lv_coord_t)(cy - 5), 10, 10, tok::FG2, LV_RADIUS_CIRCLE);
            line(c.steps[(size_t)i], tok::f18r(), tok::FG2, tok::PAD + 24, (lv_coord_t)(cy - 11), tok::LH18, 296, 1);
        } else {
            lv_obj_t *ring = rect(W.page, (lv_coord_t)(x - 6), (lv_coord_t)(cy - 6), 12, 12, tok::BG, LV_RADIUS_CIRCLE);
            lv_obj_set_style_border_color(ring, lv_color_hex(tok::LINE), 0);
            lv_obj_set_style_border_width(ring, 3, 0);
            line(c.steps[(size_t)i], tok::f18r(), tok::FG2, tok::PAD + 24, (lv_coord_t)(cy - 11), tok::LH18, 296, 1);
        }
    }
    if (stale) rail_footer(stale_reason(c));
}

void build_edition(HeldCard *h, bool stale) {
    if (!h) {
        line("Pocket edition", tok::f18r(), tok::FG2, tok::PAD, tok::PAD, tok::LH18);
        headline("Nothing filed yet.", tok::PAD + 32, 2 * tok::LH32);
        line("Requested from the desk.", tok::f18r(), tok::FG2, tok::PAD, tok::PAD + 32 + tok::LH32 + 8, tok::LH18);
        return;
    }
    const Card &c = h->card;
    std::string top = c.title;
    if (c.section == "masthead") {
        top = c.edition_no >= 0 ? "Edition " + std::to_string(c.edition_no) : c.title;
        if (S.clock.known) top += std::string(" \xC2\xB7 ") + weekday(S.clock.now_epoch(now_ms()) + S.clock.offset_s);
    }
    line(top, tok::f18r(), tok::FG2, tok::PAD, tok::PAD, tok::LH18, tok::CONTENT_W, 1);
    lv_coord_t y = tok::PAD + 32;
    if (!c.body.empty()) y = (lv_coord_t)(headline(c.body, y, tok::CONTENT_BOTTOM - y) + 8);
    // Rows and tiles: a small 18 px stamp column, then the 24 px text (the answer-row style).
    std::vector<std::pair<std::string, std::string>> rows;
    for (const CardTile &t : c.tiles) rows.emplace_back(t.label, t.value);
    for (const CardRow &r : c.rows) rows.emplace_back(r.stamp, r.text);
    if (c.body.empty() && !rows.empty()) W.headline = rows[0].second;
    for (const auto &r : rows) {
        if (y + tok::LH24 > tok::CONTENT_BOTTOM) break;
        if (r.first.empty()) {
            line(r.second, tok::f24m(), tok::FG, tok::PAD, y, tok::LH24, tok::CONTENT_W, 1);
        } else {
            line(r.first, tok::f18r(), tok::FG2, tok::PAD, (lv_coord_t)(y + 5), tok::LH18, 80, 1);
            line(r.second, tok::f24m(), tok::FG, tok::PAD + 88, y, tok::LH24, 232, 1);
        }
        y = (lv_coord_t)(y + 30);
    }
    std::string foot = stale ? stale_reason(c) : "";
    if (!c.footer.empty()) foot = c.footer;  // a failed desk's own wording beats the generic one
    rail_footer(foot);
    if (h->sent_action.empty()) {
        lv_coord_t ay = 282;
        for (const CardAction &a : c.actions) {
            register_action(a.id, text_action(a.label.empty() ? a.id : a.label, ay));
            ay = (lv_coord_t)(ay - 60);
        }
    } else {
        rail_sent_state(*h, 226);
    }
    if (first_edition_from(S.edition_section + 1, 1) >= 0) {
        register_ui("edition_next", text_action(c.section == "masthead" ? "Read" : "Next", 340, 96));
    }
}

void build_job(const HeldCard &h, bool stale) {
    const Card &c = h.card;
    std::string top = c.title;
    if (!c.status.empty()) top += " \xC2\xB7 " + c.status;
    line(top, tok::f18r(), tok::FG2, tok::PAD, tok::PAD, tok::LH18, tok::CONTENT_W, 1);
    headline(c.body.empty() ? c.title : c.body, tok::PAD + 28, tok::CONTENT_BOTTOM - tok::PAD - 28);
    rail_footer(stale ? stale_reason(c) : c.footer);
    if (!h.sent_action.empty()) {
        rail_sent_state(h, 226);
        return;
    }
    lv_coord_t y = 226;
    bool primary_done = false;
    for (size_t i = 0; i < c.actions.size(); i++) {
        const CardAction &a = c.actions[i];
        const std::string label = a.label.empty() ? a.id : a.label;
        if (!primary_done && (a.style == "primary" || i == 0)) {
            lv_obj_t *p = pill(label, y, 170, 14);
            register_action(a.id, p);
            y = (lv_coord_t)(y + lv_obj_get_style_height(p, 0) + 20);
            primary_done = true;
        } else {
            register_action(a.id, text_action(label, y, 120));
            y = (lv_coord_t)(y + 58);
        }
    }
}

void build_offline() {
    headline("No connection", tok::PAD, tok::LH32);
    line("Nothing is sent or ordered\nuntil it\xE2\x80\x99s back.", tok::f18r(), tok::FG2, tok::PAD, tok::PAD + 46,
         tok::LH18, tok::CONTENT_W, 2);
}

std::string error_words() {
    if (!S.error_text.empty()) return S.error_text;
    if (S.error_code == "no_speech" || S.error_code == "too_short") return "I didn\xE2\x80\x99t catch that.";
    if (S.error_code == "agent_timeout") return "Dex didn\xE2\x80\x99t answer in time.";
    if (S.error_code == "save_failed") return "Not saved.";
    return "Something went wrong.";
}

void build_error() {
    headline(error_words(), tok::PAD, 3 * tok::LH32);
    register_ui("dismiss", text_action("OK", 362, 96));
}

// ---- reading (§ 11.8)

std::string book_line(const CardBook &b) {
    std::string s = b.author;
    if (!b.chapter.empty()) s += (s.empty() ? "" : " \xC2\xB7 ") + std::string("Chapter ") + b.chapter;
    return s;
}

void build_reading_home() {
    const CardBook &b = S.book;
    if (b.present()) {
        line(b.title, tok::f32m(), tok::FG, tok::PAD, tok::PAD, tok::LH32, tok::CONTENT_W, 1);
        W.headline = b.title;
        const std::string sub = book_line(b);
        if (!sub.empty()) line(sub, tok::f18r(), tok::FG2, tok::PAD, tok::PAD + 46, tok::LH18, tok::CONTENT_W, 1);
    } else {
        line("Reading", tok::f32m(), tok::FG, tok::PAD, tok::PAD, tok::LH32);
        W.headline = "Reading";
    }
    // The state is said in words, and only the server's echo changes it.
    const bool on = speech_on();
    line(on ? "Voice on \xC2\xB7 lead only" : "Quiet \xC2\xB7 text only", tok::f24m(), tok::FG2, tok::PAD, 158,
         tok::LH24, tok::CONTENT_W, 1);
    W.speech = text_action(on ? "Go quiet" : "Turn voice on", 362, 164);
    if (S.speech_pending) lv_obj_set_style_opa(W.speech, motion::TAP_OPA, 0);
    register_ui("speech", W.speech);
}

void set_read_offset(int y);

void scroll_anim_cb(void *, int32_t v) { set_read_offset((int)v); }

void scroll_to(int target, uint32_t ms) {
    if (!W.column) return;
    lv_anim_del(W.column, scroll_anim_cb);
    if (ms == 0 || target == S.read_offset) {
        set_read_offset(target);
        return;
    }
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, W.column);
    lv_anim_set_exec_cb(&a, scroll_anim_cb);
    lv_anim_set_values(&a, S.read_offset, target);
    lv_anim_set_time(&a, ms);
    lv_anim_set_path_cb(&a, lv_anim_path_ease_out);
    lv_anim_start(&a);
}

int max_scroll() { return LV_MAX(0, W.total - W.view_h); }

int snap(int y) { return motion::snap_scroll(y, W.lead_lh, W.lead_lines, W.detail_top, W.lh, max_scroll()); }

void show_if(lv_obj_t *o, bool on) {
    if (!o) return;
    if (on) lv_obj_clear_flag(o, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);
}

void update_read_rail() {
    if (!W.column) return;
    const bool in_detail = W.detail_top < W.total && S.read_offset >= W.detail_top - W.lh / 2;
    show_if(W.read_more, !in_detail);
    show_if(W.foot1, !in_detail);
    show_if(W.foot2, !in_detail);
    show_if(W.larger, in_detail);
    show_if(W.smaller, in_detail);
    if (shown == CharmSurface::ReadingAnswer) dex_set_pose(compute_pose(shown));  // lead <-> detail
}

void set_read_offset(int y) {
    if (!W.column) return;
    y = LV_MAX(0, LV_MIN(y, max_scroll()));
    S.read_offset = y;
    lv_obj_set_y(W.column, (lv_coord_t)-y);
    int x = 0, len = 0;
    if (motion::scroll_thumb(y, W.total, W.view_h, tok::SEP_X0, tok::SEP_X1 - tok::SEP_X0, &x, &len)) {
        set_hline(L.thumb, L.thumb_pts, (lv_coord_t)x, (lv_coord_t)(x + len));
        lv_obj_clear_flag(L.thumb, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(L.thumb, LV_OBJ_FLAG_HIDDEN);
    }
    update_read_rail();
}

int para_at(int offset) {
    int k = -1;
    for (size_t i = 0; i < W.para_tops.size(); i++) {
        if (W.para_tops[i] <= offset) k = (int)i;
    }
    return k;
}

void back_one_level();

void viewport_event(lv_event_t *e) {
    const lv_event_code_t code = lv_event_get_code(e);
    lv_indev_t *indev = lv_indev_get_act();
    lv_point_t p = {0, 0};
    if (indev) lv_indev_get_point(indev, &p);
    if (code == LV_EVENT_PRESSED) {
        activity();
        lv_anim_del(W.column, scroll_anim_cb);
        W.scroll_pressed = true;
        W.dragging = false;
        W.press_y = p.y;
        W.press_offset = S.read_offset;
    } else if (code == LV_EVENT_PRESSING && W.scroll_pressed) {
        const int dy = W.press_y - p.y;
        if (!W.dragging && (dy > 6 || dy < -6)) W.dragging = true;
        if (W.dragging) set_read_offset(W.press_offset + dy);  // 1:1
    } else if (code == LV_EVENT_RELEASED && W.scroll_pressed) {
        W.scroll_pressed = false;
        if (W.dragging) {
            scroll_to(snap(S.read_offset), 160);  // rest on whole lines
        } else {
            // A tap pages: lower half forward, upper half back, by (lines - 1) lines.
            lv_area_t a;
            lv_obj_get_coords(W.viewport, &a);
            const int page = (W.lines - 1) * W.lh;
            const bool fwd = p.y >= (a.y1 + a.y2) / 2;
            scroll_to(snap(S.read_offset + (fwd ? page : -page)), 240);
        }
    } else if (code == LV_EVENT_GESTURE && indev) {
        if (lv_indev_get_gesture_dir(indev) == LV_DIR_RIGHT) {
            W.scroll_pressed = false;
            back_one_level();
        }
    }
}

// One paragraph of the detail: a short lead-in sentence ("Interpretation.") set 600/FG, then 400/FG2.
int detail_para(lv_obj_t *parent, const std::string &p, const tok::ReadStep &st, lv_coord_t y) {
    lv_obj_t *sg = lv_spangroup_create(parent);
    lv_obj_clear_flag(sg, LV_OBJ_FLAG_CLICKABLE);
    lv_spangroup_set_mode(sg, LV_SPAN_MODE_BREAK);
    lv_obj_set_width(sg, tok::CONTENT_W);
    lv_obj_set_style_text_font(sg, st.text, 0);
    lv_obj_set_style_text_line_space(sg, line_space(st.text, st.lh), 0);
    std::string lead, rest = p;
    const size_t dot = p.find(". ");
    if (dot != std::string::npos && dot < 40) {
        int words = 1;
        for (size_t i = 0; i < dot; i++) words += p[i] == ' ';
        if (words <= 4) {
            lead = p.substr(0, dot + 1);
            rest = p.substr(dot + 1);
        }
    }
    if (!lead.empty()) {
        lv_span_t *s = lv_spangroup_new_span(sg);
        lv_span_set_text(s, lead.c_str());
        lv_style_set_text_font(&s->style, st.leadin);
        lv_style_set_text_color(&s->style, lv_color_hex(tok::FG));
    }
    lv_span_t *s = lv_spangroup_new_span(sg);
    lv_span_set_text(s, rest.c_str());
    lv_style_set_text_font(&s->style, st.text);
    lv_style_set_text_color(&s->style, lv_color_hex(tok::FG2));
    lv_spangroup_refr_mode(sg);
    const lv_coord_t h = lv_spangroup_get_expand_height(sg, tok::CONTENT_W);
    const int lines = LV_MAX(1, (int)((h + st.lh / 2) / st.lh));
    lv_obj_set_height(sg, (lv_coord_t)(lines * st.lh));
    lv_obj_set_pos(sg, 0, y);
    return lines * st.lh;
}

void build_reading_answer(const HeldCard &h) {
    const Card &c = h.card;
    const tok::ReadStep st = tok::read_step(S.read_step);
    if (S.read_card != c.id) {
        S.read_card = c.id;
        S.read_offset = 0;
        S.read_anchor_para = -1;
    }
    W.lh = st.lh;
    W.lines = st.lines;
    W.view_h = st.lines * st.lh;
    W.viewport = plain(W.page);
    lv_obj_set_pos(W.viewport, tok::CONTENT_X, tok::CONTENT_Y);
    lv_obj_set_size(W.viewport, tok::CONTENT_W, (lv_coord_t)W.view_h);
    lv_obj_add_flag(W.viewport, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_clear_flag(W.viewport, LV_OBJ_FLAG_GESTURE_BUBBLE);
    lv_obj_add_event_cb(W.viewport, viewport_event, LV_EVENT_ALL, nullptr);
    W.column = plain(W.viewport);
    lv_obj_set_width(W.column, tok::CONTENT_W);
    W.enter_lines.push_back(W.viewport);

    // The lead: 18/500 FG, the top of the one scroll column.
    const std::string lead = c.body.empty() ? c.title : c.body;
    W.headline = lead;
    text(W.column, lead, tok::f18m(), tok::FG, 0, 0, tok::LH18, tok::CONTENT_W);
    W.lead_lh = tok::LH18;
    W.lead_lines = text_lines(lead, tok::f18m(), tok::LH18, tok::CONTENT_W);
    const int lead_h = W.lead_lines * tok::LH18;
    W.para_tops.clear();
    if (c.detail.empty()) {
        W.detail_top = lead_h;
        W.total = lead_h;
    } else {
        W.detail_top = LV_MAX(lead_h, W.view_h);  // the lead fills the first view; the detail starts below
        int y = W.detail_top;
        size_t pos = 0;
        bool first = true;
        while (pos <= c.detail.size()) {
            size_t end = c.detail.find('\n', pos);
            if (end == std::string::npos) end = c.detail.size();
            const std::string para = c.detail.substr(pos, end - pos);
            pos = end + 1;
            if (para.find_first_not_of(" \t\r") == std::string::npos) continue;
            if (!first) y += st.lh;  // one empty line between paragraphs keeps one line grid
            first = false;
            W.para_tops.push_back(y);
            y += detail_para(W.column, para, st, (lv_coord_t)y);
        }
        W.total = y;
    }
    lv_obj_set_height(W.column, (lv_coord_t)LV_MAX(W.total, W.view_h));

    // Rail: "Read more" + book at the foot on the lead; Larger / Smaller in the detail.
    const CardBook &b = c.book.present() ? c.book : S.book;
    if (!c.detail.empty()) {
        W.read_more = text_action("Read more", 236);
        register_ui("read_more", W.read_more);
        if (S.read_step < 2) register_ui("larger", W.larger = text_action("Larger", 304, 120));
        if (S.read_step > 0) register_ui("smaller", W.smaller = text_action("Smaller", 362, 120));
    }
    if (b.present()) {
        W.foot1 = text(W.page, b.title, tok::f18m(), tok::FG, tok::PAD, 376, tok::LH18, tok::RAIL_MAX_W, 1);
        std::string sub = b.author.empty() ? "" : last_word(b.author);
        if (!b.chapter.empty()) sub += (sub.empty() ? "" : " \xC2\xB7 ") + std::string("ch ") + b.chapter;
        W.foot2 = text(W.page, sub, tok::f18r(), tok::FG2, tok::PAD, 397, tok::LH18, tok::RAIL_MAX_W, 1);
        W.enter_rail.push_back(W.foot1);
        W.enter_rail.push_back(W.foot2);
    } else if (!c.footer.empty()) {
        rail_footer(c.footer);
    }
    if (S.read_anchor_para >= 0 && S.read_anchor_para < (int)W.para_tops.size()) {
        S.read_offset = W.para_tops[(size_t)S.read_anchor_para];  // the same paragraph stays on top
        S.read_anchor_para = -1;
    }
    set_read_offset(snap(S.read_offset));
}

void build_saved(const HeldCard &h) {
    const Card &c = h.card;
    const std::string head = c.saved ? "Saved." : "Not saved.";
    line(head, tok::f32m(), tok::FG, tok::PAD, tok::PAD, tok::LH32);
    W.headline = head;
    const std::string words = c.body.empty() ? c.title : (c.saved ? curly_quoted(c.body) : c.body);
    line(words, tok::f24m(), tok::FG, tok::PAD, tok::PAD + 50, tok::LH24, tok::CONTENT_W, 4);
    const CardBook &b = c.book.present() ? c.book : S.book;
    if (b.present()) {
        W.enter_rail.push_back(text(W.page, b.title, tok::f18r(), tok::FG2, tok::PAD, 376, tok::LH18, tok::RAIL_MAX_W, 1));
        if (!b.chapter.empty())
            W.enter_rail.push_back(text(W.page, "Chapter " + b.chapter, tok::f18r(), tok::FG2, tok::PAD, 397, tok::LH18));
    }
}

// ---------------------------------------------------------------- rebuild

void update_live();

std::string identity_of(CharmSurface s, const HeldCard *visible) {
    std::string id = charm_ui_surface_name(s);
    if (visible) id += "|" + visible->card.id;
    if (s == CharmSurface::Edition) id += "|" + shown_section;
    if (s == CharmSurface::ReadingAnswer) id += "|" + std::to_string(S.read_step);
    return id;
}

void rebuild() {
    dirty = false;
    rebuild_at = 0;
    if (!ready) return;
    const CharmSurface s = compute_surface();
    shown = s;
    shown_card.clear();
    shown_section.clear();
    shown_stale = false;

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
    // A rebuild deletes the pressed control, so its release would never arrive: abandon the hold.
    hold.cancel();
    bag.release(now_ms());

    const std::string identity = identity_of(s, visible);
    const bool animate = !shown_identity.empty() && identity != shown_identity;
    shown_identity = identity;

    // Exit the old content (or drop it at once when it's the same screen, just updated).
    if (W.page) {
        if (animate) exit_page(W.page);
        else lv_obj_del(W.page);
    }
    if (W.over) lv_obj_del(W.over);
    W = Widgets{};
    W.page = plain(L.root);
    lv_obj_set_size(W.page, CHARM_W, CHARM_H);
    W.over = plain(L.overlay);
    lv_obj_set_size(W.over, CHARM_W, CHARM_H);
    lv_obj_add_flag(L.thumb, LV_OBJ_FLAG_HIDDEN);

    const bool night = s == CharmSurface::Night;
    lv_obj_set_style_line_color(L.sep, lv_color_hex(night ? tok::LINE_N : tok::LINE), 0);

    dex_set_size(DEX_SIZE_FULL);  // design § 11.6: full body at the one anchor, always
    dex_set_pose(compute_pose(s));

    switch (s) {
        case CharmSurface::Home: build_home(); break;
        case CharmSurface::Listening: build_listening(); break;
        case CharmSurface::Working: build_working(); break;
        case CharmSurface::Edition: build_edition(visible, shown_stale); break;
        case CharmSurface::Night: break;  // no text; the dim separator and floor are set above
        case CharmSurface::Offline: build_offline(); break;
        case CharmSurface::Error: build_error(); break;
        case CharmSurface::ReadingHome: build_reading_home(); break;
        case CharmSurface::Answer: if (visible) build_answer(*visible, shown_stale); break;
        case CharmSurface::Decision: if (visible) build_decision(*visible, shown_stale); break;
        case CharmSurface::NeedsMore: if (visible) build_needs_more(*visible); break;
        case CharmSurface::Money: if (visible) build_money(*visible, shown_stale); break;
        case CharmSurface::Done: if (visible) build_done(*visible); break;
        case CharmSurface::Tracker: if (visible) build_tracker(*visible, shown_stale); break;
        case CharmSurface::Job: if (visible) build_job(*visible, shown_stale); break;
        case CharmSurface::ReadingAnswer: if (visible) build_reading_answer(*visible); break;
        case CharmSurface::Saved: if (visible) build_saved(*visible); break;
    }
    if (animate) start_enter();
    update_live();

    // Receipt: once the card is committed to the display, once per version of the card.
    if (visible && !visible->receipted) {
        lv_refr_now(nullptr);
        visible->receipted = true;
        send_displayed(visible->card.id);
    }
}

// ---------------------------------------------------------------- live updates (25 fps)

void update_stream(uint32_t now) {
    stream.update(now, S.mic_level);
    const lv_area_t hand = point_or(DEX_POINT_HAND, tok::HAND_CUP);
    const motion::Pt end = {(float)(hand.x1 + hand.x2) / 2, (float)(hand.y1 + hand.y2) / 2};
    size_t i = 0;
    for (const motion::Capsule &c : stream.caps) {
        if (i >= (size_t)STREAM_LINES) break;
        const float head = LV_MIN(1.0f, motion::VoiceStream::head(c, now));
        const float tail = LV_MAX(0.0f, head - c.len);
        if (head <= 0 || head <= tail) continue;
        lv_point_t *pts = L.stream_pts[i];
        for (int k = 0; k < STREAM_PTS; k++) {
            const motion::Pt p = motion::stream_point(tail + (head - tail) * (float)k / (STREAM_PTS - 1), end);
            pts[k] = {(lv_coord_t)lroundf(p.x), (lv_coord_t)lroundf(p.y)};
        }
        const float mid = (head + tail) / 2;
        const float w = c.width - (c.width - 4.0f) * mid;  // full at the edge, 4 px at the hand
        lv_obj_t *l = L.stream[i];
        lv_line_set_points(l, pts, STREAM_PTS);
        lv_obj_set_style_line_width(l, (lv_coord_t)lroundf(LV_MAX(4.0f, w)), 0);
        lv_obj_clear_flag(l, LV_OBJ_FLAG_HIDDEN);
        i++;
    }
    for (; i < (size_t)STREAM_LINES; i++) lv_obj_add_flag(L.stream[i], LV_OBJ_FLAG_HIDDEN);
}

void fuse_faded(lv_anim_t *) {
    lv_obj_add_flag(L.fuse, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_style_opa(L.fuse, LV_OPA_COVER, 0);
    L.fuse_fading = false;
}

void update_fuse(uint32_t now) {
    if (S.listening) {
        if (L.fuse_fading) {
            lv_anim_del(L.fuse, anim_opa);
            L.fuse_fading = false;
        }
        lv_obj_set_style_opa(L.fuse, LV_OPA_COVER, 0);
        const int px = motion::fuse_px(elapsed(now, S.listen_start), tok::SEP_X1 - tok::SEP_X0);
        if (px > 0) {
            set_hline(L.fuse, L.fuse_pts, tok::SEP_X0, (lv_coord_t)(tok::SEP_X0 + px));
            lv_obj_clear_flag(L.fuse, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_add_flag(L.fuse, LV_OBJ_FLAG_HIDDEN);
        }
    } else if (!lv_obj_has_flag(L.fuse, LV_OBJ_FLAG_HIDDEN) && !L.fuse_fading) {
        L.fuse_fading = true;  // the fuse fades out over 200 ms
        start_anim(L.fuse, anim_opa, 255, 0, motion::FUSE_FADE_MS, 0, lv_anim_path_linear, fuse_faded);
    }
}

void update_bag(uint32_t now) {
    if (!W.hold_label) return;
    const bool lifting = hold.active || W.money_sent;
    const char *want = lifting ? "Ordering\xE2\x80\xA6" : "Hold Dex\nto order";
    if (strcmp(lv_label_get_text(W.hold_label), want) != 0) {
        lv_label_set_text(W.hold_label, want);
        lv_obj_set_y(W.hold_label, lifting ? 290 : 300);
    }
    show_if(W.reject, !lifting);
    dex_set_pose(lifting ? DEX_POSE_LIFT_BAG : DEX_POSE_OFFER_BAG);
    const float fill = W.money_sent ? 1.0f : bag.level(now);
    if (fill <= 0) {
        lv_obj_add_flag(W.bag_fill, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(W.bag_edge, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    // Bottom -> top inside the bag, in whichever position the bag is in this frame.
    // The exported box bounds the whole (slightly rotated) bag, handles included; the flat fill
    // stays inside its body: below the handles (top 22 %) and clear of the tilted sides.
    const lv_area_t box = point_or(DEX_POINT_BAG, lifting ? tok::BAG_LIFT : tok::BAG_PREVIEW);
    const lv_coord_t bw = lv_area_get_width(&box), bh = lv_area_get_height(&box);
    const lv_coord_t x = (lv_coord_t)(box.x1 + bw * 16 / 100), w = (lv_coord_t)(bw * 68 / 100);
    const lv_coord_t body_top = (lv_coord_t)(box.y1 + bh * 26 / 100), body_bottom = (lv_coord_t)(box.y2 - bh * 8 / 100);
    const lv_coord_t h = (lv_coord_t)lroundf(fill * (float)(body_bottom - body_top));
    const lv_coord_t top = (lv_coord_t)(body_bottom - h);
    lv_obj_set_pos(W.bag_fill, x, top);
    lv_obj_set_size(W.bag_fill, w, h);
    if (lv_obj_t *side = lv_obj_get_child(W.bag_fill, 0)) {
        lv_obj_set_x(side, (lv_coord_t)(w - w * 22 / 100));
        lv_obj_set_width(side, (lv_coord_t)(w * 22 / 100));
    }
    lv_obj_clear_flag(W.bag_fill, LV_OBJ_FLAG_HIDDEN);
    if (fill < 1.0f) {  // the fill edge carries an ink line
        lv_obj_set_pos(W.bag_edge, x, (lv_coord_t)(top - 1));
        lv_obj_set_size(W.bag_edge, w, 2);
        lv_obj_clear_flag(W.bag_edge, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(W.bag_edge, LV_OBJ_FLAG_HIDDEN);
    }
}

void update_live() {
    const uint32_t now = now_ms();
    update_fuse(now);
    update_stream(now);
    update_bag(now);
    if (W.working) {
        const int dots = 1 + (int)((now / motion::WORKING_DOT_MS) % 3);
        if (dots != W.working_dots) {
            W.working_dots = dots;
            lv_label_set_text(W.working, (W.working_base + std::string((size_t)dots, '.')).c_str());
        }
    }
    if (S.speech_pending && elapsed(now, S.speech_pending_since) >= SETTING_TIMEOUT_MS) {
        S.speech_pending = false;  // no echo: spring back, change nothing
        if (W.speech) lv_obj_set_style_opa(W.speech, LV_OPA_COVER, 0);
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
            lv_obj_set_style_opa(target, motion::TAP_OPA, 0);
            send_action(h->card.id, a.first, false, 0);
            h->sent_action = a.first;
            h->confirmed = false;
            rebuild_at = now_ms() + motion::TAP_MS;  // 70 % for 80 ms, then the exit (in tick)
            return;
        }
    }
}

void complete_hold(uint32_t held_ms) {
    HeldCard *h = card_for_actions();
    if (!h || h->card.id != hold_card || !h->sent_action.empty()) return;
    send_action(hold_card, hold_action, true, held_ms);
    h->sent_action = hold_action;
    h->confirmed = false;
    dirty = true;
}

void bag_event(lv_event_t *e) {
    const lv_event_code_t code = lv_event_get_code(e);
    const uint32_t now = now_ms();
    uint32_t held = 0;
    if (code == LV_EVENT_PRESSED) {
        activity();
        hold.press(now);
        bag.press(now, hold.hold_ms);
    } else if (code == LV_EVENT_RELEASED) {
        if (hold.release(now, &held)) complete_hold(held);
        else bag.release(now);  // early: drain in 300 ms, send nothing, say nothing
    } else if (code == LV_EVENT_PRESS_LOST) {
        hold.cancel();
        bag.release(now);
    } else {
        return;
    }
    update_bag(now);
}

void open_edition() {
    S.edition_view = true;
    S.edition_swiped = false;
    const int first = first_edition_from(0, 1);
    S.edition_section = first < 0 ? 0 : first;
    send_request("edition");
}

void edition_step(int step) {
    const int next = first_edition_from(S.edition_section + step, step);
    if (next >= 0) S.edition_section = next;
    S.edition_swiped = true;
}

void back_one_level() {
    activity();
    if (shown == CharmSurface::ReadingAnswer && W.column && W.detail_top > 0 && S.read_offset >= W.detail_top) {
        scroll_to(0, 240);  // detail -> lead
        return;
    }
    if (is_card_surface(shown)) S.card_hidden = true;  // lead / saved -> reading home
    dirty = true;
}

void ui_button_event(lv_event_t *e) {
    lv_obj_t *target = lv_event_get_target(e);
    std::string id;
    for (auto &b : W.ui_buttons) {
        if (b.second == target) id = b.first;
    }
    if (id.empty()) return;
    activity();
    if (id == "speech") {
        // Ask; the status changes only when the server's echo arrives.
        send_setting("speech", speech_on() ? "off" : "on");
        S.speech_pending = true;
        S.speech_pending_since = now_ms();
        lv_obj_set_style_opa(target, motion::TAP_OPA, 0);
    } else if (id == "read_more") {
        scroll_to(W.detail_top, 240);
    } else if (id == "larger" || id == "smaller") {
        const int step = LV_MAX(0, LV_MIN(2, S.read_step + (id == "larger" ? 1 : -1)));
        if (step != S.read_step) {
            S.read_anchor_para = LV_MAX(0, para_at(S.read_offset));
            S.read_step = step;
            rebuild_at = now_ms() + motion::TAP_MS;
        }
    } else if (id == "edition_next") {
        edition_step(1);
        rebuild_at = now_ms() + motion::TAP_MS;
    } else if (id == "dismiss") {
        S.error_active = false;
        rebuild_at = now_ms() + motion::TAP_MS;
    }
}

void on_swipe(lv_dir_t dir) {
    activity();
    switch (shown) {
        case CharmSurface::Home:
        case CharmSurface::ReadingHome:
            if (dir == LV_DIR_LEFT) open_edition();
            break;
        case CharmSurface::Edition:
            if (dir == LV_DIR_LEFT || dir == LV_DIR_RIGHT) edition_step(dir == LV_DIR_LEFT ? 1 : -1);
            else S.edition_view = false;
            break;
        case CharmSurface::ReadingAnswer:
        case CharmSurface::Saved:
            if (dir == LV_DIR_RIGHT) {
                back_one_level();
                return;
            }
            if (dir == LV_DIR_BOTTOM) S.card_hidden = true;
            break;
        default:
            if (is_card_surface(shown) && dir == LV_DIR_BOTTOM) S.card_hidden = true;
            break;
    }
    dirty = true;
}

void on_tap() {
    const bool was_night = S.night;
    activity();
    if (was_night) return;
    switch (shown) {
        case CharmSurface::Home:
        case CharmSurface::ReadingHome:
            if (!S.cards.empty()) S.card_hidden = false;
            break;
        case CharmSurface::Error: S.error_active = false; break;
        case CharmSurface::Answer:
        case CharmSurface::ReadingAnswer:
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

void root_event(lv_event_t *e) {
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
    if (strcmp(value, "done") == 0) {
        // The backend confirmed: only now may a sent action show as done.
        for (HeldCard &c : S.cards) c.confirmed = c.confirmed || !c.sent_action.empty();
        for (HeldCard &c : S.editions) c.confirmed = c.confirmed || !c.sent_action.empty();
    }
    if (strcmp(value, "error") == 0) {
        S.error_active = true;
        S.error_code = "error";
        S.error_text = S.state_label;
    }
}

bool holds_unsaved_notice() {
    for (const HeldCard &c : S.cards) {
        if (c.card.has_saved && !c.card.saved) return true;
    }
    return false;
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
    // A "Not saved." notice tells the save failure itself; it replaces the generic error screen.
    const bool unsaved = card.has_saved && !card.saved;
    if (unsaved && S.error_active && S.error_code == "save_failed") S.error_active = false;
    if (HeldCard *existing = find_card(card.id)) {
        // Same id = replace in place: fresh content, a fresh receipt, any pending action cleared.
        if (hold_card == existing->card.id) hold_card.clear();
        existing->card = std::move(card);
        existing->receipted = false;
        existing->sent_action.clear();
        existing->confirmed = false;
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
    S.error_code = msg["code"] | "unknown";
    S.error_text = msg["text"] | "";
    S.error_active = !(S.error_code == "save_failed" && holds_unsaved_notice());
    S.sending = false;
    // The action in flight failed (e.g. a too_short money hold): the card stays and can be retried.
    for (HeldCard &c : S.cards) {
        c.sent_action.clear();
        c.confirmed = false;
    }
    for (HeldCard &c : S.editions) {
        c.sent_action.clear();
        c.confirmed = false;
    }
    activity();
}

void on_mode(JsonObjectConst msg) {
    const char *value = msg["value"].as<const char *>();
    if (!value) return;
    dex_outfit_t outfit;
    if (dex_outfit_from_mode(value, &outfit)) dex_set_outfit(outfit);
    const bool reading = strcmp(value, "reading") == 0;
    if (reading != S.reading) S.speech.clear();  // a new mode starts from its protocol default
    S.reading = reading;
    S.book = reading ? ui_book_parse(msg["book"].as<JsonObjectConst>()) : CardBook{};
}

void on_setting(JsonObjectConst msg) {
    const char *name = msg["name"].as<const char *>();
    const char *value = msg["value"].as<const char *>();
    if (!name || !value) return;
    if (strcmp(name, "speech") == 0 && (strcmp(value, "on") == 0 || strcmp(value, "off") == 0)) {
        S.speech = value;  // the only way the shown state changes
        S.speech_pending = false;
    }
}

void create_layers(lv_obj_t *screen) {
    L = Layers{};
    L.root = plain(screen);
    lv_obj_set_size(L.root, CHARM_W, CHARM_H);
    lv_obj_add_flag(L.root, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(L.root, root_event, LV_EVENT_ALL, nullptr);

    L.base = plain(L.root);
    lv_obj_set_size(L.base, CHARM_W, CHARM_H);
    L.sep = hline(L.base, L.sep_pts, tok::SEP_X0, tok::SEP_X1, tok::SEP_Y, tok::LINE);
    L.fuse = hline(L.base, L.fuse_pts, tok::SEP_X0, tok::SEP_X0, tok::SEP_Y, tok::ACC);
    L.thumb = hline(L.base, L.thumb_pts, tok::SEP_X0, tok::SEP_X0, tok::SEP_Y, tok::FG2);
    lv_obj_add_flag(L.fuse, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(L.thumb, LV_OBJ_FLAG_HIDDEN);

    // Dex's frames are opaque (pre-composited on #000, § 11.7), so his 192x224 cell would black out
    // any rail text reaching past x = 160. He goes under the content; overlays that touch him (voice
    // stream, bag fill, placard text) go above him.
    dex_create(screen);
    lv_obj_move_background(lv_obj_get_child(screen, -1));

    L.overlay = plain(screen);
    lv_obj_set_size(L.overlay, CHARM_W, CHARM_H);
    for (int i = 0; i < STREAM_LINES; i++) {
        lv_obj_t *l = lv_line_create(L.overlay);
        lv_obj_set_style_line_color(l, lv_color_hex(tok::ACC), 0);
        lv_obj_set_style_line_rounded(l, true, 0);
        lv_obj_clear_flag(l, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_flag(l, LV_OBJ_FLAG_HIDDEN);
        L.stream[i] = l;
    }
}

}  // namespace

// ---------------------------------------------------------------- public API (charm_ui.h)

void charm_ui_init(void) {
    lv_obj_t *screen = lv_scr_act();
    lv_obj_set_style_bg_color(screen, lv_color_hex(tok::BG), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
    lv_obj_clear_flag(screen, LV_OBJ_FLAG_SCROLLABLE);

    W = Widgets{};
    create_layers(screen);
    S = UiState{};
    shown = CharmSurface::Home;
    shown_identity.clear();
    shown_card.clear();
    shown_section.clear();
    shown_stale = dirty = false;
    rebuild_at = 0;
    hold = HoldTracker{};
    bag = motion::BagFill{};
    stream = motion::VoiceStream{};
    hold_card.clear();
    hold_action.clear();
    S.last_activity = now_ms();
    last_second = last_frame = now_ms();
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
        on_mode(msg);
    } else if (strcmp(type, "setting") == 0) {
        on_setting(msg);
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
            stream.end();
            charm_host_mic_stop("cancel");
        }
        if (S.speaking) charm_host_speech_stop();
        S.speaking = false;
        S.sending = false;
        S.server_state = "idle";
        S.state_label.clear();
        S.transcript.clear();
        S.speech_pending = false;
        for (HeldCard &c : S.cards) {
            c.sent_action.clear();
            c.confirmed = false;
        }
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
        stream.begin(S.listen_start);
    }
    rebuild();
}

void charm_ui_talk_released(void) {
    if (!S.listening) return;
    activity();
    S.listening = false;
    stream.end();  // capsules in flight finish their transit
    charm_host_mic_stop("released");
    S.sending = true;
    S.sending_since = now_ms();
    rebuild();
}

void charm_ui_mic_level(float level) {
    if (level < 0) level = 0;
    if (level > 1) level = 1;
    S.mic_level = level;
}

void charm_ui_tick(uint32_t now) {
    if (!ready) return;
    dex_tick(now);

    if (S.listening && elapsed(now, S.listen_start) >= LISTEN_LIMIT_MS) {
        // The fuse reached the end: the recording ends as if the button were released.
        S.listening = false;
        stream.end();
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
    if (rebuild_at && (int32_t)(now - rebuild_at) >= 0) dirty = true;

    if (!S.night && S.connected == 1 && (shown == CharmSurface::Home || shown == CharmSurface::ReadingHome) &&
        S.cards.empty() && !S.speaking && S.server_state == "idle") {
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

    if (dirty || compute_surface() != shown) {
        rebuild();
    } else if (now - last_frame >= motion::TICK_MS) {
        last_frame = now - (now - last_frame) % motion::TICK_MS;  // 25 fps
        update_live();
    }
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
        case CharmSurface::Done: return "DONE";
        case CharmSurface::NeedsMore: return "NEEDS_MORE";
        case CharmSurface::ReadingHome: return "READING_HOME";
        case CharmSurface::ReadingAnswer: return "READING_ANSWER";
        case CharmSurface::Saved: return "SAVED";
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
    return h && !h->sent_action.empty() && h->confirmed;
}
bool charm_ui_debug_listening(void) { return S.listening; }
bool charm_ui_debug_night(void) { return S.night; }
float charm_ui_debug_hold_progress(void) { return hold.progress(now_ms()); }

int charm_ui_debug_fuse_px(void) {
    if (!L.fuse || lv_obj_has_flag(L.fuse, LV_OBJ_FLAG_HIDDEN)) return 0;
    return L.fuse_pts[1].x - L.fuse_pts[0].x;
}
float charm_ui_debug_bag_fill(void) {
    if (W.done_bag || W.money_sent) return 1.0f;
    return W.hold_label ? bag.level(now_ms()) : 0.0f;
}
std::string charm_ui_debug_hold_label(void) { return W.hold_label ? lv_label_get_text(W.hold_label) : ""; }
size_t charm_ui_debug_capsules(void) { return stream.caps.size(); }
std::string charm_ui_debug_headline(void) { return W.headline; }
bool charm_ui_debug_transitioning(void) { return L.exiting != nullptr || (int32_t)(W.enter_end - now_ms()) > 0; }
std::string charm_ui_debug_speech(void) { return speech_on() ? "on" : "off"; }
int charm_ui_debug_read_step(void) { return S.read_step; }
int charm_ui_debug_scroll(void) { return W.column ? S.read_offset : 0; }
int charm_ui_debug_scroll_max(void) { return W.column ? max_scroll() : 0; }
lv_obj_t *charm_ui_debug_ui_button(const char *id) {
    for (auto &b : W.ui_buttons) {
        if (b.first == id && !lv_obj_has_flag(b.second, LV_OBJ_FLAG_HIDDEN)) return b.second;
    }
    return nullptr;
}

lv_obj_t *charm_ui_debug_action_button(const char *action_id) {
    for (auto &a : W.actions) {
        if (a.first == action_id) return a.second;
    }
    return nullptr;
}
lv_obj_t *charm_ui_debug_cancel_button(void) { return W.cancel; }

void charm_ui_debug_swipe(lv_dir_t dir) { on_swipe(dir); }
void charm_ui_debug_tap(void) { on_tap(); }
