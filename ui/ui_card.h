// A card as the device holds it (contract/card.schema.json), parsed with ArduinoJson.
#pragma once
#include <stdint.h>
#include <string>
#include <vector>
#include <ArduinoJson.h>

enum class CardKind { Answer, Decision, Money, Tracker, Edition, Job, Notice };

struct CardAction {
    std::string id, label, style;
    uint32_t hold_ms = 0;
};

struct CardItem {
    std::string name;
    int qty = 1;
    bool has_price = false;
    double price = 0;
};

struct CardRow {
    std::string text, stamp;
};

struct CardTile {
    std::string value, label;
};

struct CardBook {
    std::string title, author, chapter;  // chapter may arrive as a number; kept as text
    bool present() const { return !title.empty(); }
};

struct Card {
    std::string id, title, body, detail, source, footer, created_at;
    CardKind kind = CardKind::Answer;
    bool stale = false;          // producer says the feed missed its deadline
    bool has_fresh_until = false;
    int64_t fresh_until = 0;     // epoch seconds
    std::vector<CardAction> actions;

    // decision
    std::string default_choice, deadline;
    std::string flip_if;  // Coach's call: "Flip only if …" (optional, ≤ 80 chars)
    // money
    std::string store, currency, address_label;
    std::vector<CardItem> items;
    double total = 0;
    int eta_min = -1;
    bool fixture = false;
    // tracker (eta_min shared)
    std::vector<std::string> steps;
    int current = 0;
    // edition
    std::string section;
    int edition_no = -1;
    std::vector<CardRow> rows;
    std::vector<CardTile> tiles;
    std::string moon;
    // job
    std::string status;
    float progress = -1;
    std::string link;
    // reading (PROTOCOL § Reading mode)
    CardBook book;          // data.book
    bool has_saved = false; // data.saved present: a save receipt notice
    bool saved = false;     // true only after the note store confirmed
};

// Parse a protocol book object ({title, author?, chapter?}); chapter may be a string or a number.
CardBook ui_book_parse(JsonObjectConst obj);

// The six edition sections, in the protocol's order.
extern const char *const EDITION_SECTIONS[6];
int edition_section_index(const std::string &section);  // -1 if unknown

// Parse a card object. Returns false if id/kind/title are missing or the kind is unknown.
bool ui_card_parse(JsonObjectConst obj, Card *out);

const char *card_kind_name(CardKind kind);

// Stale when the producer flagged it, or when wall time is known and past fresh_until.
bool card_is_stale(const Card &card, bool clock_known, int64_t now_epoch_s);

// The money screen's total as the design sets it: "$51.300" for COP (dots group thousands, no
// decimals), "$12.50" for other currencies. The currency code is set beside it, not in it.
std::string ui_format_total(double amount, const std::string &currency);

// "51,300 COP": whole amounts with thousands separators, otherwise two decimals.
std::string ui_format_money(double amount, const std::string &currency);
