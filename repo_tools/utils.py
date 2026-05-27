from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path


OBJECT_REF_RE = re.compile(
    r"\b(?:DATA|RESULT|FIG|TABLE|SEC|CHG|RUN|CODE|CFG|DOC)-[A-Za-z0-9][A-Za-z0-9._-]*\b"
)


TYPE_PREFIX = {
    "code": "CODE",
    "dataset": "DATA",
    "result": "RESULT",
    "figure": "FIG",
    "table": "TABLE",
    "section": "SEC",
    "change": "CHG",
    "run": "RUN",
    "config": "CFG",
    "document": "DOC",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(value: str, length: int = 12) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length].upper()


def infer_object_id(object_type: str, stable_key: str) -> str:
    prefix = TYPE_PREFIX.get(object_type, object_type.upper())
    return f"{prefix}-{stable_hash(stable_key)}"


def normalize_path(path: str | Path, root: Path) -> str:
    raw = str(path).replace("/", os.sep)
    p = Path(raw)
    if p.is_absolute():
        return str(p)
    return str((root / p).resolve())


def relpath_str(path: str | Path, root: Path) -> str:
    p = Path(path)
    try:
        return str(p.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path).replace("/", os.sep)


def read_text_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def guess_type_from_path(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith(".py"):
        return "code"
    if lowered.endswith((".md", ".txt", ".docx")):
        return "document"
    if lowered.endswith((".yaml", ".yml", ".json", ".toml", ".ini", ".cfg")):
        return "config"
    if lowered.endswith((".png", ".jpg", ".jpeg", ".svg", ".pdf")):
        return "figure"
    if lowered.endswith((".csv", ".parquet", ".pq", ".feather", ".pkl", ".pickle", ".xlsx", ".xls")):
        return "dataset"
    return "document"


def find_object_refs(text: str) -> list[str]:
    return sorted(set(OBJECT_REF_RE.findall(text)))
