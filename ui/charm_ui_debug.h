// Read-only introspection of the UI plus the gesture entry points, for sim/ tests and the sim's
// scripted screenshots. Not part of the host contract: firmware never needs it.
#pragma once
#include <stddef.h>
#include <string>
#include <lvgl.h>

// The named surfaces: BRIEF § 5 / § 11.3 (the 14 design surfaces) and § 11.8 (reading).
// Append-only so existing values keep their meaning; money mid-hold is Money with a hold running.
enum class CharmSurface {
    Home,
    Listening,
    Working,
    Answer,  // also notice cards
    Decision,
    Money,
    Tracker,
    Edition,  // the pocket edition
    Job,
    Night,
    Offline,
    Error,
    Done,           // § 11.3 #8: an order the backend confirmed (never before)
    NeedsMore,      // § 11.3 #14: a decision with no default: pick one of the choices
    ReadingHome,    // R1 / R4: book, chapter, speak/quiet state (from the server's echo)
    ReadingAnswer,  // R2 / R3 / R5: the lead + scrollable detail
    Saved,          // R6: a save receipt (saved or NOT saved)
    // Coach Beard (BRIEF § 11.9, docs/design/final/coach): the walk-away job and his call.
    CoachOnIt,      // C1: "Coach is on it" + "You can put it down." (no Cancel)
    CoachCall,      // C2: the verdict (32), deadline, flip_if; Hear it / Why? / Later
};

const char *charm_ui_surface_name(CharmSurface surface);

CharmSurface charm_ui_debug_surface(void);
std::string charm_ui_debug_card_id(void);     // card on screen, "" if none
std::string charm_ui_debug_card_title(void);  // title of the card on screen
std::string charm_ui_debug_edition_section(void);  // section on screen in the edition, "" if none
size_t charm_ui_debug_card_count(void);       // held non-edition cards
size_t charm_ui_debug_edition_count(void);    // held edition sections
bool charm_ui_debug_stale_shown(void);        // a stale label is on screen
bool charm_ui_debug_done_shown(void);         // a backend-confirmed check is on screen
bool charm_ui_debug_listening(void);
bool charm_ui_debug_night(void);
float charm_ui_debug_hold_progress(void);     // 0..1 of the on-screen hold action

// Design-motion introspection (docs/design/final/motion.md).
int charm_ui_debug_fuse_px(void);             // listening fuse accent length on the separator, 0..320
float charm_ui_debug_bag_fill(void);          // the bag fill as drawn (stepped, incl. the drain), 0..1
std::string charm_ui_debug_hold_label(void);  // "Hold Dex to order" / "Ordering…" ("" off money)
size_t charm_ui_debug_capsules(void);         // voice-stream capsules in flight
lv_point_t charm_ui_debug_stream_end(void);  // where the voice stream lands (the character's hand)
std::string charm_ui_debug_headline(void);    // the dominant text on screen ("" if none)
bool charm_ui_debug_transitioning(void);      // old content still exiting or new content entering

// Reading mode.
std::string charm_ui_debug_speech(void);      // "on" / "off": the state shown (server echo only)
int charm_ui_debug_read_step(void);           // detail text size: 0 = 18, 1 = 22, 2 = 26 px
int charm_ui_debug_scroll(void);              // reading column offset, px
int charm_ui_debug_scroll_max(void);          // largest offset (0 = the column fits)
// UI-only buttons: "speech", "read_more", "larger", "smaller", "edition_next", "dismiss".
lv_obj_t *charm_ui_debug_ui_button(const char *id);

// The on-screen button for a card action id, or NULL. On money, "confirm" is Dex's bag.
lv_obj_t *charm_ui_debug_action_button(const char *action_id);
// The working surface's cancel button, or NULL.
lv_obj_t *charm_ui_debug_cancel_button(void);

// Same code paths as a touch swipe / a tap on the surface background.
void charm_ui_debug_swipe(lv_dir_t dir);
void charm_ui_debug_tap(void);
