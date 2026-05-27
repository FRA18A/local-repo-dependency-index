from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import ChangeRecord, ObjectRecord
from .utils import file_sha1, read_text_utf8, utc_now


def _load_yaml_list(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = yaml.safe_load(read_text_utf8(path)) or {}
    items = data.get(key, [])
    if not isinstance(items, list):
        raise ValueError(f"{path} -> {key} must be a list")
    return [item for item in items if isinstance(item, dict)]


def load_object_registry(registry_dir: Path) -> tuple[list[ObjectRecord], dict[str, list[str]]]:
    path = registry_dir / "object_registry.yaml"
    items = _load_yaml_list(path, "objects")
    objects: list[ObjectRecord] = []
    declared_dependencies: dict[str, list[str]] = {}
    for item in items:
        object_id = str(item["object_id"])
        obj_path = str(item.get("path", ""))
        hash_value = ""
        path_obj = Path(obj_path)
        if obj_path and path_obj.exists() and path_obj.is_file():
            hash_value = file_sha1(path_obj)
        objects.append(
            ObjectRecord(
                object_id=object_id,
                type=str(item.get("type", "document")),
                path=obj_path,
                status=str(item.get("status", "active")),
                summary=str(item.get("summary", "")),
                hash=hash_value,
                updated_at=str(item.get("updated_at", utc_now())),
                source="registry",
            )
        )
        deps = item.get("dependencies", [])
        if isinstance(deps, list):
            declared_dependencies[object_id] = [str(dep) for dep in deps]
    return objects, declared_dependencies


def load_change_registry(registry_dir: Path) -> list[ChangeRecord]:
    path = registry_dir / "change_registry.yaml"
    items = _load_yaml_list(path, "changes")
    changes: list[ChangeRecord] = []
    for item in items:
        changes.append(
            ChangeRecord(
                change_id=str(item["change_id"]),
                title=str(item.get("title", "")),
                modified_objects=[str(v) for v in item.get("modified_objects", [])],
                reverts=[str(v) for v in item.get("reverts", [])],
                created_at=str(item.get("created_at", utc_now())),
            )
        )
    return changes


def ensure_registry_templates(registry_dir: Path) -> None:
    registry_dir.mkdir(parents=True, exist_ok=True)
    object_registry = registry_dir / "object_registry.yaml"
    change_registry = registry_dir / "change_registry.yaml"
    run_registry = registry_dir / "run_registry.yaml"

    if not object_registry.exists():
        object_registry.write_text(
            "\n".join(
                [
                    "objects: []",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    if not change_registry.exists():
        change_registry.write_text(
            "\n".join(
                [
                    "changes: []",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    if not run_registry.exists():
        run_registry.write_text("runs: []\n", encoding="utf-8")
