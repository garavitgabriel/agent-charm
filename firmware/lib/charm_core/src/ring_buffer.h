// Byte ring buffer over caller-owned storage (PSRAM on the device, a plain array in tests).
// Not thread-safe by itself: LockedRing adds a mutex for the producer/consumer split across tasks.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <mutex>

namespace charm {

class ByteRing {
public:
    void init(uint8_t *storage, size_t capacity) {
        buf_ = storage;
        cap_ = storage ? capacity : 0;
        head_ = tail_ = 0;
    }

    size_t capacity() const { return cap_; }
    size_t size() const { return head_ - tail_; }
    size_t free_space() const { return cap_ - size(); }
    bool empty() const { return head_ == tail_; }
    void clear() { tail_ = head_; }

    // Writes as much as fits; returns the bytes accepted. Never overwrites unread data.
    size_t write(const uint8_t *data, size_t len) {
        size_t n = len < free_space() ? len : free_space();
        size_t at = head_ % (cap_ ? cap_ : 1);
        size_t first = n < cap_ - at ? n : cap_ - at;
        if (n) {
            memcpy(buf_ + at, data, first);
            memcpy(buf_, data + first, n - first);
        }
        head_ += n;
        return n;
    }

    // Reads up to len bytes; returns the bytes copied out.
    size_t read(uint8_t *out, size_t len) {
        size_t n = len < size() ? len : size();
        size_t at = tail_ % (cap_ ? cap_ : 1);
        size_t first = n < cap_ - at ? n : cap_ - at;
        if (n) {
            memcpy(out, buf_ + at, first);
            memcpy(out + first, buf_, n - first);
        }
        tail_ += n;
        return n;
    }

private:
    uint8_t *buf_ = nullptr;
    size_t cap_ = 0;
    // Monotonic counters: size is head - tail, positions are taken modulo the capacity.
    size_t head_ = 0, tail_ = 0;
};

class LockedRing {
public:
    void init(uint8_t *storage, size_t capacity) {
        std::lock_guard<std::mutex> lock(m_);
        ring_.init(storage, capacity);
    }
    size_t write(const uint8_t *data, size_t len) {
        std::lock_guard<std::mutex> lock(m_);
        return ring_.write(data, len);
    }
    size_t read(uint8_t *out, size_t len) {
        std::lock_guard<std::mutex> lock(m_);
        return ring_.read(out, len);
    }
    // Reads only whole units of `align` bytes (e.g. 2 for s16 samples).
    size_t read_aligned(uint8_t *out, size_t len, size_t align) {
        std::lock_guard<std::mutex> lock(m_);
        size_t n = len < ring_.size() ? len : ring_.size();
        n -= n % align;
        return ring_.read(out, n);
    }
    size_t size() {
        std::lock_guard<std::mutex> lock(m_);
        return ring_.size();
    }
    void clear() {
        std::lock_guard<std::mutex> lock(m_);
        ring_.clear();
    }
    size_t capacity() {
        std::lock_guard<std::mutex> lock(m_);
        return ring_.capacity();
    }

private:
    std::mutex m_;
    ByteRing ring_;
};

}  // namespace charm
