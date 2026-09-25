#include "ui_time.h"
#include <stdio.h>

namespace {

// Howard Hinnant's days_from_civil: days since 1970-01-01 for a proleptic Gregorian date.
int64_t days_from_civil(int64_t y, unsigned m, unsigned d) {
    y -= m <= 2;
    const int64_t era = (y >= 0 ? y : y - 399) / 400;
    const unsigned yoe = (unsigned)(y - era * 400);
    const unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
    const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + (int64_t)doe - 719468;
}

bool digits(const char *&p, int count, int *out) {
    int v = 0;
    for (int i = 0; i < count; i++) {
        if (p[i] < '0' || p[i] > '9') return false;
        v = v * 10 + (p[i] - '0');
    }
    p += count;
    *out = v;
    return true;
}

bool expect(const char *&p, char c) {
    if (*p != c) return false;
    p++;
    return true;
}

}  // namespace

bool ui_parse_iso8601(const char *s, int64_t *epoch_s, int32_t *offset_s) {
    if (!s) return false;
    const char *p = s;
    int y, mo, d, h, mi, sec = 0;
    if (!digits(p, 4, &y) || !expect(p, '-') || !digits(p, 2, &mo) || !expect(p, '-') ||
        !digits(p, 2, &d))
        return false;
    if (*p != 'T' && *p != 't' && *p != ' ') return false;
    p++;
    if (!digits(p, 2, &h) || !expect(p, ':') || !digits(p, 2, &mi)) return false;
    if (*p == ':') {
        p++;
        if (!digits(p, 2, &sec)) return false;
        if (*p == '.' || *p == ',') {
            p++;
            if (*p < '0' || *p > '9') return false;
            while (*p >= '0' && *p <= '9') p++;
        }
    }
    if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59 || sec > 60) return false;

    int32_t offset = 0;
    if (*p == 'Z' || *p == 'z') {
        p++;
    } else if (*p == '+' || *p == '-') {
        const int sign = *p == '-' ? -1 : 1;
        p++;
        int oh, om = 0;
        if (!digits(p, 2, &oh)) return false;
        if (*p == ':') p++;
        if (*p >= '0' && *p <= '9' && !digits(p, 2, &om)) return false;
        if (oh > 23 || om > 59) return false;
        offset = sign * (oh * 3600 + om * 60);
    }
    if (*p != '\0') return false;

    const int64_t local = days_from_civil(y, (unsigned)mo, (unsigned)d) * 86400 + h * 3600 + mi * 60 + sec;
    *epoch_s = local - offset;
    if (offset_s) *offset_s = offset;
    return true;
}

void UiClock::set(int64_t epoch_s, int32_t offset, uint32_t now_ms) {
    known = true;
    base_epoch_s = epoch_s;
    offset_s = offset;
    base_ms = now_ms;
}

int64_t UiClock::now_epoch(uint32_t now_ms) const {
    return base_epoch_s + (int64_t)((uint32_t)(now_ms - base_ms) / 1000u);
}

void UiClock::format_hhmm(uint32_t now_ms, char *out, size_t n) const {
    if (!known) {
        snprintf(out, n, "--:--");
        return;
    }
    ui_format_hhmm(now_epoch(now_ms), offset_s, out, n);
}

void ui_format_hhmm(int64_t epoch_s, int32_t offset_s, char *out, size_t n) {
    int64_t local = epoch_s + offset_s;
    int64_t sod = local % 86400;
    if (sod < 0) sod += 86400;
    snprintf(out, n, "%02d:%02d", (int)(sod / 3600), (int)(sod % 3600 / 60));
}
