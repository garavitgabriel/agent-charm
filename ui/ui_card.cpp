#include "ui_card.h"
#include "ui_time.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

const char *const EDITION_SECTIONS[6] = {"masthead", "one_thing", "sports", "almanac", "waiting", "wire"};

int edition_section_index(const std::string &section) {
    for (int i = 0; i < 6; i++) {
        if (section == EDITION_SECTIONS[i]) return i;
    }
    return -1;
}

namespace {

struct KindName {
    const char *name;
    CardKind kind;
};
const KindName KINDS[] = {
    {"answer", CardKind::Answer}, {"decision", CardKind::Decision}, {"money", CardKind::Money},
    {"tracker", CardKind::Tracker}, {"edition", CardKind::Edition}, {"job", CardKind::Job},
    {"notice", CardKind::Notice},
};

std::string str(JsonVariantConst v) {
    const char *s = v.as<const char *>();
    return s ? std::string(s) : std::string();
}

}  // namespace

const char *card_kind_name(CardKind kind) {
    for (const KindName &k : KINDS) {
        if (k.kind == kind) return k.name;
    }
    return "?";
}

bool ui_card_parse(JsonObjectConst obj, Card *out) {
    if (obj.isNull()) return false;
    Card c;
    c.id = str(obj["id"]);
    c.title = str(obj["title"]);
    const char *kind = obj["kind"].as<const char *>();
    if (c.id.empty() || c.title.empty() || !kind) return false;
    bool known = false;
    for (const KindName &k : KINDS) {
        if (strcmp(kind, k.name) == 0) {
            c.kind = k.kind;
            known = true;
        }
    }
    if (!known) return false;

    c.body = str(obj["body"]);
    c.detail = str(obj["detail"]);
    c.source = str(obj["source"]);
    c.footer = str(obj["footer"]);
    c.created_at = str(obj["created_at"]);
    c.stale = obj["stale"] | false;
    if (const char *fu = obj["fresh_until"].as<const char *>()) {
        c.has_fresh_until = ui_parse_iso8601(fu, &c.fresh_until, nullptr);
    }
    for (JsonObjectConst a : obj["actions"].as<JsonArrayConst>()) {
        CardAction action;
        action.id = str(a["id"]);
        action.label = str(a["label"]);
        action.style = str(a["style"]);
        action.hold_ms = a["hold_ms"] | 0u;
        if (!action.id.empty()) c.actions.push_back(action);
    }

    JsonObjectConst d = obj["data"].as<JsonObjectConst>();
    c.default_choice = str(d["default"]);
    c.deadline = str(d["deadline"]);
    c.store = str(d["store"]);
    c.currency = str(d["currency"]);
    c.address_label = str(d["address_label"]);
    for (JsonObjectConst it : d["items"].as<JsonArrayConst>()) {
        CardItem item;
        item.name = str(it["name"]);
        item.qty = it["qty"] | 1;
        item.has_price = it["price"].is<double>();
        item.price = it["price"] | 0.0;
        c.items.push_back(item);
    }
    c.total = d["total"] | 0.0;
    c.eta_min = d["eta_min"] | -1;
    c.fixture = d["fixture"] | false;
    for (JsonVariantConst s : d["steps"].as<JsonArrayConst>()) c.steps.push_back(str(s));
    c.current = d["current"] | 0;
    c.section = str(d["section"]);
    c.edition_no = d["edition_no"] | -1;
    for (JsonObjectConst r : d["rows"].as<JsonArrayConst>()) c.rows.push_back({str(r["text"]), str(r["stamp"])});
    for (JsonObjectConst t : d["tiles"].as<JsonArrayConst>()) c.tiles.push_back({str(t["value"]), str(t["label"])});
    c.moon = str(d["moon"]);
    c.status = str(d["status"]);
    c.progress = d["progress"] | -1.0f;
    c.link = str(d["link"]);
    c.book = ui_book_parse(d["book"].as<JsonObjectConst>());
    c.has_saved = d["saved"].is<bool>();
    c.saved = d["saved"] | false;

    *out = std::move(c);
    return true;
}

CardBook ui_book_parse(JsonObjectConst obj) {
    CardBook b;
    if (obj.isNull()) return b;
    b.title = str(obj["title"]);
    b.author = str(obj["author"]);
    JsonVariantConst ch = obj["chapter"];
    if (ch.is<const char *>()) {
        b.chapter = str(ch);
    } else if (ch.is<long>()) {
        b.chapter = std::to_string(ch.as<long>());
    }
    return b;
}

std::string ui_format_total(double amount, const std::string &currency) {
    char buf[48];
    if (currency == "COP" || currency.empty()) {
        char digits[32];
        snprintf(digits, sizeof digits, "%.0f", floor(fabs(amount) + 0.5));
        std::string grouped;
        const size_t len = strlen(digits);
        for (size_t i = 0; i < len; i++) {
            if (i > 0 && (len - i) % 3 == 0) grouped += '.';
            grouped += digits[i];
        }
        snprintf(buf, sizeof buf, "%s$%s", amount < 0 ? "-" : "", grouped.c_str());
    } else {
        snprintf(buf, sizeof buf, "%s$%.2f", amount < 0 ? "-" : "", fabs(amount));
    }
    return buf;
}

bool card_is_stale(const Card &card, bool clock_known, int64_t now_epoch_s) {
    if (card.stale) return true;
    return clock_known && card.has_fresh_until && now_epoch_s > card.fresh_until;
}

std::string ui_format_money(double amount, const std::string &currency) {
    char buf[48];
    const double whole = floor(fabs(amount));
    if (fabs(fabs(amount) - whole) < 0.005) {
        // Group thousands by hand; printf's ' flag is not portable to newlib.
        char digits[32];
        snprintf(digits, sizeof digits, "%.0f", whole);
        std::string grouped;
        const size_t len = strlen(digits);
        for (size_t i = 0; i < len; i++) {
            if (i > 0 && (len - i) % 3 == 0) grouped += ',';
            grouped += digits[i];
        }
        snprintf(buf, sizeof buf, "%s%s", amount < 0 ? "-" : "", grouped.c_str());
    } else {
        snprintf(buf, sizeof buf, "%.2f", amount);
    }
    std::string out = buf;
    if (!currency.empty()) out += " " + currency;
    return out;
}
