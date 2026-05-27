from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ObjectRecord:
    object_id: str
    type: str
    path: str
    status: str
    summary: str
    hash: str = ""
    updated_at: str = ""
    source: str = "inferred"


@dataclass(frozen=True)
class DependencyRecord:
    src_id: str
    dst_id: str
    dep_type: str
    detected_by: str
    confidence: float = 1.0


@dataclass
class RunRecord:
    run_id: str
    script_path: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    git_commit: str | None = None
    created_at: str = ""


@dataclass
class ChangeRecord:
    change_id: str
    title: str
    modified_objects: list[str] = field(default_factory=list)
    reverts: list[str] = field(default_factory=list)
    created_at: str = ""

