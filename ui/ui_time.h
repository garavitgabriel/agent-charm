// Wall-clock helpers. The device has no RTC it can trust; wall time comes from the server's
// `welcome.time` and advances on charm_host_millis(). Until a welcome arrives, wall time is unknown.
#pragma once
#include <stdint.h>
#include <stddef.h>

// Parse ISO-8601 "YYYY-MM-DDTHH:MM[:SS[.fff]][Z|+HH:MM|-HH:MM|+HHMM]". A missing offset means UTC.
// Returns false on anything malformed.
bool ui_parse_iso8601(const char *s, int64_t *epoch_s, int32_t *offset_s);

struct UiClock {
    bool known = false;
    int64_t base_epoch_s = 0;   // wall time at base_ms
    int32_t offset_s = 0;       // local UTC offset from the welcome timestamp
    uint32_t base_ms = 0;

    void set(int64_t epoch_s, int32_t offset, uint32_t now_ms);
    int64_t now_epoch(uint32_t now_ms) const;
    // "HH:MM" local time, or "--:--" when unknown.
    void format_hhmm(uint32_t now_ms, char *out, size_t n) const;
};

// "HH:MM" of an epoch in the given UTC offset.
void ui_format_hhmm(int64_t epoch_s, int32_t offset_s, char *out, size_t n);
