"""Time-to-first-audio benchmark: the same 10 spoken questions (5 EN + 5 ES) against real Dex.

Each question runs as its own `charm-client --say … --no-play` (a fresh connection, so no
conversation context carries over) against an already running `charm-server`. The client's own
timing line is parsed; the server's `talk timings` lines (agent first token etc.) are read from
the server log when `--server-log` is given.

    uv run python bench/latency.py --label before --server-log /tmp/server.log

Results go to `bench/results/<label>.json` (gitignored) and a summary is printed.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Conversation-only questions: nothing here needs a tool, an action or live data.
QUESTIONS: list[tuple[str, str, str | None]] = [
    ("en", "What is the difference between a metaphor and a simile?", None),
    ("en", "Why is the sky blue?", None),
    ("en", "How do I make a good cup of pour-over coffee?", None),
    ("en", "What is a good way to fall asleep faster?", None),
    ("en", "Explain compound interest in simple terms.", None),
    ("es", "¿Qué diferencia hay entre una metáfora y un símil?", "Mónica"),
    ("es", "¿Por qué el cielo es azul?", "Mónica"),
    ("es", "¿Cómo preparo un buen café colado?", "Mónica"),
    ("es", "¿Qué puedo hacer para dormirme más rápido?", "Mónica"),
    ("es", "Explícame el interés compuesto en palabras sencillas.", "Mónica"),
]

CLIENT_LINE = re.compile(
    r"stt (?P<stt>[\d.]+|n/a)s? · agent (?P<agent>[\d.]+|n/a)s? · tts (?P<tts>[\d.]+|n/a)s? · "
    r"first audio (?P<first_audio>[\d.]+|n/a)s? · total (?P<total>[\d.]+|n/a)s?"
)
SERVER_FIELD = re.compile(r"(\w+)=([\d.]+)s")


def _num(value: str) -> float | None:
    return None if value == "n/a" else float(value)


def run_one(language: str, question: str, voice: str | None, timeout: float) -> dict[str, object]:
    command = ["uv", "run", "charm-client", "--no-play", "--say", question]
    if voice:
        command += ["--voice", voice]
    started = time.time()
    proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    match = CLIENT_LINE.search(proc.stdout)
    result: dict[str, object] = {
        "language": language,
        "question": question,
        "exit": proc.returncode,
        "wall": round(time.time() - started, 2),
    }
    if match:
        result.update({k: _num(v) for k, v in match.groupdict().items()})
    else:
        result["error"] = (proc.stdout + proc.stderr)[-400:]
    return result


def server_timings(log_path: Path, offset: int) -> list[dict[str, float]]:
    """`talk timings k=v…` lines appended to the server log since `offset`."""
    text = log_path.read_bytes()[offset:].decode(errors="replace")
    rows = []
    for line in text.splitlines():
        if "talk timings" in line:
            rows.append({k: float(v) for k, v in SERVER_FIELD.findall(line)})
    return rows


def p90(values: list[float]) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    # Nearest-rank p90: with 10 samples this is the 9th value.
    rank = max(1, -(-9 * len(ordered) // 10))
    return ordered[rank - 1]


def summarize(rows: list[dict[str, object]], keys: list[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for key in keys:
        values = [float(v) for r in rows if isinstance(v := r.get(key), int | float)]
        if values:
            out[key] = {
                "median": round(statistics.median(values), 2),
                "p90": round(p90(values), 2),
                "n": len(values),
            }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True, help="results file name, e.g. before/after")
    parser.add_argument("--server-log", type=Path, help="charm-server log to read timings from")
    parser.add_argument("--only", choices=["en", "es"], help="run one language only")
    parser.add_argument("--timeout", type=float, default=200.0)
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    for language, question, voice in QUESTIONS:
        if args.only and language != args.only:
            continue
        offset = args.server_log.stat().st_size if args.server_log else 0
        row = run_one(language, question, voice, args.timeout)
        if args.server_log:
            time.sleep(0.3)  # let the server flush its timing line
            found = server_timings(args.server_log, offset)
            if found:
                row["server"] = found[-1]
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    client_keys = ["stt", "agent", "tts", "first_audio", "total"]
    summary = {"client": summarize(rows, client_keys)}
    server_rows: list[dict[str, object]] = [
        dict(s) for r in rows if isinstance(s := r.get("server"), dict)
    ]
    if server_rows:
        summary["server"] = summarize(server_rows, sorted({k for s in server_rows for k in s}))
    for language in ("en", "es"):
        subset = [r for r in rows if r["language"] == language]
        if subset:
            summary[f"client_{language}"] = summarize(subset, client_keys)

    results = HERE / "results"
    results.mkdir(exist_ok=True)
    path = results / f"{args.label}.json"
    path.write_text(json.dumps({"rows": rows, "summary": summary}, indent=2, ensure_ascii=False))
    print("\nsummary (seconds):")
    for group, metrics in summary.items():
        for key, stat in metrics.items():
            print(f"  {group:10s} {key:22s} median {stat['median']:6.2f}  p90 {stat['p90']:6.2f}")
    print(f"\nwrote {path}")
    failures = [r for r in rows if r.get("exit") != 0 or "error" in r]
    if failures:
        print(f"{len(failures)} run(s) failed", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
