#pragma once
#include <stdint.h>

// Write an 8-bit RGB PNG (rgb = width*height*3 bytes). Returns false on I/O or zlib failure.
bool png_write_rgb(const char *path, int width, int height, const uint8_t *rgb);
