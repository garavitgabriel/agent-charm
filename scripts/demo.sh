#!/usr/bin/env bash
# Talk to Dex on the Mac, in one command: the charm server + the simulator as a real device.
#
#   scripts/demo.sh                          # hold space in the sim window to talk
#   scripts/demo.sh --pull                   # refresh the edition from a Hermes desk first
#   scripts/demo.sh --mic-wav q.wav --auto-talk --trace    # any extra flags go to charm-sim
#
# 1. makes sure server/.env has a CHARM_TOKEN (generates a random one; never prints it in full)
# 2. uses the fixture edition cards; with --pull, refreshes them from a Hermes desk (charm-feeds
#    pull + build into out/cards, gitignored), falling back to the fixtures if that fails
# 3. starts charm-server with CHARM_CARDS_DIR pointed at them (log: out/demo/server.log)
# 4. builds charm-sim and launches it connected, at --scale 2
# Ctrl-C (or closing the sim window) stops everything.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ENV_FILE="server/.env"
DEMO_DIR="out/demo"
PULL=0
SIM_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --pull) PULL=1 ;;
    --no-pull) PULL=0 ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) SIM_ARGS+=("$arg") ;;
  esac
done

say() { printf '\033[1m[demo]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[demo]\033[0m %s\n' "$*" >&2; exit 1; }

for tool in uv cmake ffmpeg; do
  command -v "$tool" >/dev/null || die "$tool is missing (brew install $tool)"
done
mkdir -p "$DEMO_DIR"

# ---- 1. token ----
env_value() { # the last KEY=value in server/.env, quotes stripped
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^[[:space:]]*$1=//p" "$ENV_FILE" | tail -n 1 | sed -e 's/^["'\'']//' -e 's/["'\'']$//'
}
if [ ! -f "$ENV_FILE" ]; then
  cp server/.env.example "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  say "created $ENV_FILE from .env.example"
fi
TOKEN="$(env_value CHARM_TOKEN)"
if [ -z "$TOKEN" ]; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  tmp="$(mktemp)"
  grep -v '^[[:space:]]*CHARM_TOKEN=' "$ENV_FILE" >"$tmp" || true
  printf 'CHARM_TOKEN=%s\n' "$TOKEN" >>"$tmp"
  cat "$tmp" >"$ENV_FILE" && rm -f "$tmp"
  chmod 600 "$ENV_FILE"
  say "generated a random CHARM_TOKEN in $ENV_FILE (gitignored)"
fi
say "CHARM_TOKEN ${TOKEN:0:4}… (full value only in $ENV_FILE)"
PORT="${CHARM_PORT:-$(env_value CHARM_PORT)}"
PORT="${PORT:-8765}"
if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
  die "something is already listening on port $PORT (another charm-server?). Stop it or set CHARM_PORT."
fi

# ---- 2. cards ----
CARDS="$ROOT/out/cards"
FIXTURE_CARDS="$ROOT/feeds/fixtures/cards"
if [ "$PULL" = 1 ]; then
  say "refreshing the edition: charm-feeds pull && build (read-only from Hermes)…"
  if (cd feeds && uv run --quiet charm-feeds pull && uv run --quiet charm-feeds build --out "$CARDS") \
       >"$DEMO_DIR/feeds.log" 2>&1; then
    say "cards: $(ls "$CARDS"/*.json 2>/dev/null | wc -l | tr -d ' ') fresh cards in out/cards"
  else
    say "the feeds pull/build FAILED (see $DEMO_DIR/feeds.log): using the fixture cards instead"
    CARDS="$FIXTURE_CARDS"
  fi
else
  say "using the fixture cards (--pull refreshes them from a Hermes desk)"
  CARDS="$FIXTURE_CARDS"
fi
say "CHARM_CARDS_DIR=${CARDS#"$ROOT"/}"

# ---- 3. server ----
SERVER_PID=""
SIM_PID=""
cleanup() {
  trap - INT TERM EXIT
  [ -n "$SIM_PID" ] && kill "$SIM_PID" 2>/dev/null || true
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    say "stopping the server"
    {
      kill -TERM "$SERVER_PID" || true  # not INT: background jobs start with SIGINT ignored
      for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$SERVER_PID" || break; sleep 0.3; done
      kill -KILL "$SERVER_PID" || true
      wait || true
    } 2>/dev/null
  fi
  say "bye"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

say "syncing the server environment…"
uv sync --quiet --project server
say "starting charm-server on 127.0.0.1:$PORT (loads Whisper first; log: $DEMO_DIR/server.log)"
CHARM_CARDS_DIR="$CARDS" server/.venv/bin/charm-server --host 127.0.0.1 --port "$PORT" \
  >"$DEMO_DIR/server.log" 2>&1 &
SERVER_PID=$!

# ---- 4. sim (built while Whisper loads) ----
say "building charm-sim…"
cmake -S sim -B build/sim >"$DEMO_DIR/sim-build.log" 2>&1 \
  && cmake --build build/sim --target charm-sim -j 8 >>"$DEMO_DIR/sim-build.log" 2>&1 \
  || die "the sim build failed (see $DEMO_DIR/sim-build.log)"

for _ in $(seq 1 240); do
  nc -z 127.0.0.1 "$PORT" 2>/dev/null && break
  kill -0 "$SERVER_PID" 2>/dev/null || die "charm-server exited: $(tail -n 5 "$DEMO_DIR/server.log")"
  sleep 0.5
done
nc -z 127.0.0.1 "$PORT" 2>/dev/null || die "charm-server didn't start listening within 2 minutes"
say "server up. Hold SPACE in the sim window to talk; Esc or Ctrl-C quits."

CHARM_TOKEN="$TOKEN" build/sim/charm-sim --connect "ws://127.0.0.1:$PORT/charm" --scale 2 \
  ${SIM_ARGS[@]+"${SIM_ARGS[@]}"} &
SIM_PID=$!
wait "$SIM_PID" || true
SIM_PID=""
