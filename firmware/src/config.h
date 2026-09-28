// Build-time configuration: secrets.h if present, else the committed placeholders.
#pragma once

#if __has_include("secrets.h")
#include "secrets.h"
#define CHARM_HAS_SECRETS 1
#else
#warning "firmware/src/secrets.h not found: building with secrets.example.h placeholders (see README)"
#include "secrets.example.h"
#define CHARM_HAS_SECRETS 0
#endif

// Plain ws:// unless secrets.h asks for TLS (wss://, e.g. the public Funnel address).
#ifndef CHARM_SERVER_TLS
#define CHARM_SERVER_TLS 0
#endif

#define CHARM_FW_VERSION "dex-charm-fw/0.1 proto/0"
