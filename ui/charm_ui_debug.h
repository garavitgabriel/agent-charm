// Read-only introspection of the UI plus the gesture entry points, for sim/ tests and the sim's
// scripted screenshots. Not part of the host contract: firmware never needs it.
#pragma once
#include <stddef.h>
#include <string>
#include <lvgl.h>

// The 11 named surfaces from docs/BRIEF.md § 5. Error shares surface 11 with Offline.
enum class CharmSurface {
    Home,
    Listening,
    Working,
    Answer,  // also notice cards
    Decision,
    Money,
    Tracker,
    Edition,
    Job,
    Night,
    Offline,
    Error,
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

// The on-screen button for a card action id, or NULL.
lv_obj_t *charm_ui_debug_action_button(const char *action_id);
// The working surface's cancel button, or NULL.
lv_obj_t *charm_ui_debug_cancel_button(void);

// Same code paths as a touch swipe / a tap on the surface background.
void charm_ui_debug_swipe(lv_dir_t dir);
void charm_ui_debug_tap(void);
