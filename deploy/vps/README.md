# Deploying the charm server

The server is one container. It needs `ffmpeg` and outbound HTTPS (Edge TTS, and your LLM
endpoint unless it's local). Whisper `base` is baked into the image, so the first question isn't a
150 MB download. About 1 GB of RAM is plenty.

## 1. Put it on a host

```sh
# on your machine, from the repo root (HOST is an ssh alias for your server)
rsync -a --delete --exclude '.venv' --exclude '__pycache__' --exclude '.local' --exclude '.env' \
  contract notes server deploy HOST:/opt/dex-charm/src/
ssh HOST 'cd /opt/dex-charm && cp src/deploy/vps/compose.yaml . && mkdir -p state'
```

On the host, create `/opt/dex-charm/.env` from [`.env.example`](.env.example) (`chmod 600`), then:

```sh
cd /opt/dex-charm && docker compose up -d --build && docker compose logs -f
```

The log line `listening on ws://0.0.0.0:8765/charm (… dex: openai-compatible <model> …)` means
it's up. Point the simulator at it from a machine that can reach the bound address:

```sh
CHARM_TOKEN=… ./build/sim/charm-sim --connect ws://<host-address>:8765/charm
```

**Backends.** `CHARM_AGENT=openai` needs nothing else. `CHARM_AGENT=hermes` with
`HERMES_SSH_ALIAS=local` runs `docker exec` into a Hermes container on the same host: uncomment
the Docker socket volume in `compose.yaml` (it's root-equivalent, so only do it on a host you
control). The image's Docker CLI is x86_64; change `DOCKER_ARCH` in the Dockerfile on ARM.

## 2. A public endpoint for the device

The ESP32 connects with `wss://` (TLS, verified against the Let's Encrypt roots in
`firmware/src/ca_roots.h`), so it needs a public hostname with a Let's Encrypt certificate that
forwards WebSocket upgrades to the container. Keep the container bound to a private address and put
one of these in front:

**Tailscale Funnel** (no open ports, no domain needed). With Tailscale on the host and Funnel
enabled for your tailnet:

```sh
tailscale funnel --bg --https=8443 --set-path=/charm http://127.0.0.1:8765/charm
tailscale funnel status          # shows https://<machine>.<tailnet>.ts.net:8443/charm
```

(Flags vary a little between Tailscale versions; `tailscale funnel --help` has yours. The goal is
`https://<machine>.<tailnet>.ts.net:8443/charm` → `http://127.0.0.1:8765/charm`.) Funnel's
certificate is from Let's Encrypt, so the firmware verifies it as is. Only `/charm` is
exposed. Your devices on the tailnet can also use the private `ws://<tailscale-ip>:8765/charm`
if you set `CHARM_BIND` to that IP.

**Any TLS reverse proxy** on a domain you own. Caddy gets the certificate itself:

```caddyfile
charm.example.com {
    reverse_proxy /charm 127.0.0.1:8765
}
```

(nginx works too: `proxy_http_version 1.1` and the `Upgrade`/`Connection` headers on
`location /charm`.)

Then in the firmware's `src/secrets.h`:

```c
#define CHARM_SERVER_HOST "charm.example.com"   // or <machine>.<tailnet>.ts.net
#define CHARM_SERVER_PORT 443                   // 8443 for the Funnel example above
#define CHARM_SERVER_PATH "/charm"
#define CHARM_SERVER_TLS 1
```

The `CHARM_TOKEN` is the only thing standing between the internet and your agent, so make it long
and random (the `.env.example` has a one-liner), and rotate it if a device is lost. The charm is
read-and-converse only, and money actions need a 2-second hold on a preview card, but your agent's
lookups (mail, notes) are still reachable by anyone with the token.
