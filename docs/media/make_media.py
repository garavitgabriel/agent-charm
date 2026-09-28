"""Regenerate the README visuals in docs/media/ from the real code and sprite sources.

    uvx --with pillow python docs/media/make_media.py            # GIFs + hero from docs/media/screens
    uvx --with pillow python docs/media/make_media.py --shots    # first re-render docs/media/screens

`--shots` copies the repo to a temp dir, swaps the simulator's demo data for neutral sample data
(`SYNTHETIC` below: no real shops, places or projects), builds the sim there and runs
`charm-sim --shots`. The repo itself is never modified. Everything is drawn on black.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[2]
MEDIA = REPO / "docs" / "media"
SCREENS = MEDIA / "screens"
DEX = REPO / "ui" / "assets-src" / "dex"
COACH_RENDERS = REPO / "docs" / "design" / "final" / "coach"

# Demo strings in sim/src/sim_script.cpp → neutral sample data (C-escaped, as in the source).
SYNTHETIC = [
    ("Pause the side project?", "Pause the side project?"),
    ("Chicken crepe", "Chicken crepe"),
    ("Coconut lemonade", "Coconut lemonade"),
    ('\\"total\\":58400,\\"currency\\":\\"COP\\"', '\\"total\\":18.4,\\"currency\\":\\"USD\\"'),
    ("Home", "Home"),
    ("Which Corner Bistro, Downtown or Riverside?", "Which Corner Bistro, Downtown or Riverside?"),
    ('\\"Downtown\\"', '\\"Downtown\\"'),
    ('\\"Riverside\\"', '\\"Riverside\\"'),
    ("Corner Bistro \\xC2\\xB7 DeliveryCo", "Corner Bistro \\xC2\\xB7 Delivery"),
    ("Corner Bistro", "Corner Bistro"),
    ("America/Chicago", "America/Chicago"),
]
KEEP = [
    "01-home", "02-listening", "03-working", "04-answer", "05-decision", "06-money-preview",
    "07-money-mid-hold", "08-done", "09-live-tracker", "10-pocket-edition", "11-job-done",
    "12-night", "13-offline", "14-needs-more", "r1-home", "r2-lead", "r3-detail", "r4-speak",
    "r5-size-large", "r6-saved",
]


def shots() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "repo"
        shutil.copytree(REPO, copy, ignore=shutil.ignore_patterns(".git", "build", "out", ".pio", ".venv"))
        script = copy / "sim" / "src" / "sim_script.cpp"
        text = script.read_text()
        for old, new in SYNTHETIC:
            text = text.replace(old, new)
        script.write_text(text)
        build = copy / "build" / "sim"
        subprocess.run(["cmake", "-S", copy / "sim", "-B", build], check=True)
        subprocess.run(["cmake", "--build", build, "-j", "--target", "charm-sim"], check=True)
        out = Path(tmp) / "shots"
        subprocess.run([build / "charm-sim", "--shots", out], check=True)
        SCREENS.mkdir(parents=True, exist_ok=True)
        for name in KEEP:
            shutil.copy(out / f"{name}.png", SCREENS / f"{name}.png")


def screen(name: str) -> Image.Image:
    return Image.open(SCREENS / f"{name}.png").convert("RGB")


def save_gif(path: Path, frames: list[Image.Image], durations: list[int]) -> None:
    # Merge identical neighbours so a still stretch is one frame.
    merged: list[tuple[Image.Image, int]] = []
    for im, ms in zip(frames, durations):
        if merged and merged[-1][0].tobytes() == im.tobytes():
            merged[-1] = (merged[-1][0], merged[-1][1] + ms)
        else:
            merged.append((im, ms))
    pal = [im.convert("P", palette=Image.Palette.ADAPTIVE, colors=255) for im, _ in merged]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=[ms for _, ms in merged],
                loop=0, optimize=True, disposal=1)
    print(f"{path.relative_to(REPO)}: {len(merged)} frames, {path.stat().st_size / 1e6:.2f} MB")


def slideshow(path: Path, stills: list[Image.Image], hold: int = 1400, fade: int = 4) -> None:
    frames, durations = [], []
    for i, im in enumerate(stills):
        frames.append(im)
        durations.append(hold)
        nxt = stills[(i + 1) % len(stills)]
        for k in range(1, fade + 1):
            frames.append(Image.blend(im, nxt, k / (fade + 1)))
            durations.append(50)
    save_gif(path, frames, durations)


def dex_idle(path: Path, scale: int = 2, seconds: float = 8.0) -> None:
    """Idle as the player runs it: 3 frames at 250 ms, the 4 s day breath (0/−1/−2/−2/−1/0 px),
    blinks (half 60 ms, closed 90 ms) with one double, and one sip."""
    manifest = json.loads((DEX / "manifest.json").read_text())["sprites"]
    idle = next(a for a in manifest["animations"] if a["pose"] == "idle")
    frame_file = {k: DEX / v["file"] for k, v in manifest["frames"].items()}
    cache: dict[str, Image.Image] = {}

    def img(key: str) -> Image.Image:
        if key not in cache:
            cache[key] = Image.open(frame_file[key]).convert("RGB")
        return cache[key]

    breath_ms = manifest["motion"]["breath"]["day"]
    offsets = [0, -1, -2, -2, -1, 0]

    def breath(t: int) -> int:
        t %= sum(breath_ms)
        for ms, off in zip(breath_ms, offsets):
            if t < ms:
                return off
            t -= ms
        return 0

    blinks = [1800, 4700, 4700 + 150 + 210]  # the third is the double
    sip_at, sip = 5600, [(f["frame"], f["ms"]) for f in idle["sip"]]
    w, h = manifest["cell"]
    frames, durations = [], []
    tick = manifest["motion"]["tick_ms"]
    for t in range(0, int(seconds * 1000), tick):
        step = (t // idle["frames"][0]["ms"]) % len(idle["frames"])
        key = idle["frames"][step]["frame"]
        for b in blinks:
            if b <= t < b + 60 or b + 150 <= t < b + 210:
                key = idle["blink"][step][0]
            elif b + 60 <= t < b + 150:
                key = idle["blink"][step][1]
        if sip_at <= t < sip_at + sum(ms for _, ms in sip):
            acc = sip_at
            for k, ms in sip:
                if t < acc + ms:
                    key = k
                    break
                acc += ms
        canvas = Image.new("RGB", (w, h + 4))
        canvas.paste(img(key), (0, 2 + breath(t)))
        frames.append(canvas.resize((w * scale, (h + 4) * scale), Image.Resampling.LANCZOS))
        durations.append(tick)
    save_gif(path, frames, durations)


def hero(path: Path) -> None:
    names = ["01-home", "04-answer", "05-decision", "r2-lead", "07-money-mid-hold"]
    ims = [screen(n) for n in names]
    gap, pad = 24, 32
    w, h = ims[0].size
    sheet = Image.new("RGB", (pad * 2 + len(ims) * w + (len(ims) - 1) * gap, pad * 2 + h))
    for i, im in enumerate(ims):
        sheet.paste(im, (pad + i * (w + gap), pad))
    sheet.save(path, optimize=True)
    print(f"{path.relative_to(REPO)}: {path.stat().st_size / 1e6:.2f} MB")


def main() -> None:
    if "--shots" in sys.argv:
        shots()
    dex_idle(MEDIA / "dex-idle.gif")
    slideshow(MEDIA / "screen-tour.gif", [screen(n) for n in (
        "01-home", "02-listening", "04-answer", "05-decision", "06-money-preview",
        "07-money-mid-hold", "08-done")])
    slideshow(MEDIA / "reading.gif", [screen(n) for n in (
        "r1-home", "r2-lead", "r3-detail", "r5-size-large", "r6-saved")], hold=1800)
    coach = [Image.open(COACH_RENDERS / f"{n}.png").convert("RGB") for n in ("c0-home", "c1-on-it", "c2-call")]
    slideshow(MEDIA / "dex-coach.gif", [screen("01-home"), screen("03-working"), *coach])
    hero(MEDIA / "hero.png")


if __name__ == "__main__":
    main()
