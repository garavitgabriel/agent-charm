// Copy to secrets.h (gitignored) and fill in. Never commit secrets.h.
//   cp src/secrets.example.h src/secrets.h
// Without secrets.h the firmware still builds with these placeholders (and a compile warning),
// but it can't join Wi-Fi or authenticate.
#pragma once

#define CHARM_WIFI_SSID "your-wifi-name"
#define CHARM_WIFI_PASSWORD "your-wifi-password"

// The charm server (server/ in this repo): ws://CHARM_SERVER_HOST:CHARM_SERVER_PORT/charm
#define CHARM_SERVER_HOST "192.168.1.10"
#define CHARM_SERVER_PORT 8765
#define CHARM_SERVER_PATH "/charm"
// 1 = wss:// verified against the Let's Encrypt roots (the public Tailscale Funnel address on the VPS:
// host "<machine>.<tailnet>.ts.net", port 8443). 0 = plain ws:// on your LAN.
#define CHARM_SERVER_TLS 0

// Must equal the server's CHARM_TOKEN environment variable.
#define CHARM_TOKEN "change-me"

#define CHARM_DEVICE_ID "charm-01"
