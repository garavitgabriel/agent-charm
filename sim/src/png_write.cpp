// Minimal PNG encoder: IHDR + one zlib-compressed IDAT + IEND.
#include "png_write.h"
#include <stdio.h>
#include <vector>
#include <zlib.h>

namespace {

void put32(std::vector<uint8_t> &out, uint32_t v) {
    out.push_back((uint8_t)(v >> 24));
    out.push_back((uint8_t)(v >> 16));
    out.push_back((uint8_t)(v >> 8));
    out.push_back((uint8_t)v);
}

void chunk(std::vector<uint8_t> &out, const char *type, const std::vector<uint8_t> &data) {
    put32(out, (uint32_t)data.size());
    const size_t start = out.size();
    out.insert(out.end(), type, type + 4);
    out.insert(out.end(), data.begin(), data.end());
    const uLong crc = crc32(0L, out.data() + start, (uInt)(out.size() - start));
    put32(out, (uint32_t)crc);
}

}  // namespace

bool png_write_rgb(const char *path, int width, int height, const uint8_t *rgb) {
    std::vector<uint8_t> raw;
    raw.reserve((size_t)height * (width * 3 + 1));
    for (int y = 0; y < height; y++) {
        raw.push_back(0);  // filter: none
        const uint8_t *row = rgb + (size_t)y * width * 3;
        raw.insert(raw.end(), row, row + width * 3);
    }
    uLongf zlen = compressBound((uLong)raw.size());
    std::vector<uint8_t> z(zlen);
    if (compress2(z.data(), &zlen, raw.data(), (uLong)raw.size(), 6) != Z_OK) return false;
    z.resize(zlen);

    std::vector<uint8_t> png = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'};
    std::vector<uint8_t> ihdr;
    put32(ihdr, (uint32_t)width);
    put32(ihdr, (uint32_t)height);
    ihdr.insert(ihdr.end(), {8, 2, 0, 0, 0});  // 8-bit, truecolor RGB, deflate, no filter, no interlace
    chunk(png, "IHDR", ihdr);
    chunk(png, "IDAT", z);
    chunk(png, "IEND", {});

    FILE *f = fopen(path, "wb");
    if (!f) return false;
    const bool ok = fwrite(png.data(), 1, png.size(), f) == png.size();
    return fclose(f) == 0 && ok;
}
