# VPS deploy (Hermes box, <vps>)

The charm server runs as the `dex-charm` container next to Hermes and os-api. It reaches Dex with
`docker exec` into the Hermes container (the same worker as the Mac's SSH path, minus SSH), and saves
notes through os-api `POST /submit`. The port is **Tailscale-only** (`<host-address>:8765`), so the Macs
and the simulator reach it; the ESP32 can't join Tailscale and needs a public TLS endpoint (a separate
step with its own decision).

Deploy or update (from a Mac with the `hermes` alias):

```sh
rsync -a --delete --exclude '.venv' --exclude '__pycache__' --exclude '.local' --exclude '.env' \
  contract notes server deploy hermes:/docker/dex-charm/src/
ssh hermes 'cd /docker/dex-charm && cp src/deploy/vps/compose.yaml . && docker compose up -d --build'
```

The first deploy needs `/docker/dex-charm/.env` (see `.env.example`, chmod 600) and `state/`.
Connect the simulator: `charm-sim --connect ws://<host-address>:8765/charm --token <CHARM_TOKEN>`.
