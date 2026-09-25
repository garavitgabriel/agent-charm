"""Small helpers for writing deterministic generated C++."""

from __future__ import annotations

from pathlib import Path

REGEN = "cd tools && uv run charm-assets"


def banner(what: str, command: str, sources: list[str]) -> str:
    lines = [
        f"// GENERATED — do not edit. {what}",
        f"// Regenerate: {REGEN} {command}",
        "// Sources (relative to tools/):",
        *(f"//   {s}" for s in sources),
    ]
    return "\n".join(lines) + "\n"


def byte_array(data: bytes, indent: str = "    ", per_line: int = 16) -> str:
    rows = []
    for i in range(0, len(data), per_line):
        rows.append(indent + ", ".join(f"0x{b:02X}" for b in data[i : i + per_line]) + ",")
    return "\n".join(rows)


def rel_to_tools(path: Path, tools_dir: Path) -> str:
    try:
        return path.resolve().relative_to(tools_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def write_if_changed(path: Path, text: str) -> bool:
    """Write `text` (LF, UTF-8). Returns True when the file changed."""
    data = text.encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return False
    path.write_bytes(data)
    return True
