from __future__ import annotations

from pathlib import Path

from ..utils import find_object_refs, read_text_utf8


TEXT_EXTENSIONS = {".md", ".yaml", ".yml", ".txt", ".json", ".toml", ".ini", ".cfg", ".log", ".out"}


def scan_text_file(path: Path) -> list[str]:
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return []
    text = read_text_utf8(path)
    return find_object_refs(text)

