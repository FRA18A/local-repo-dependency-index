from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ..models import RunRecord
from ..utils import read_text_utf8


def load_run_manifests(manifest_dir: Path) -> list[RunRecord]:
    runs: list[RunRecord] = []
    if not manifest_dir.exists():
        return runs
    for path in sorted(manifest_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        run_id = data.get("run_id")
        if not run_id:
            continue
        runs.append(
            RunRecord(
                run_id=str(run_id),
                script_path=str(data.get("script", "")),
                inputs=[str(v) for v in data.get("inputs", [])],
                outputs=[str(v) for v in data.get("outputs", [])],
                git_commit=str(data["git_commit"]) if data.get("git_commit") is not None else None,
                created_at=str(data.get("created_at", "")),
            )
        )
    return runs


def sync_run_registry(run_registry_path: Path, payload: dict[str, Any]) -> None:
    if run_registry_path.exists():
        data = yaml.safe_load(read_text_utf8(run_registry_path)) or {}
    else:
        data = {}
    runs = data.get("runs", [])
    if not isinstance(runs, list):
        runs = []
    run_id = payload["run_id"]
    filtered = [item for item in runs if isinstance(item, dict) and item.get("run_id") != run_id]
    filtered.append(payload)
    data["runs"] = filtered
    run_registry_path.parent.mkdir(parents=True, exist_ok=True)
    run_registry_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def write_run_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def write_run_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
