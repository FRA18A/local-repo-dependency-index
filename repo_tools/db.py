from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import ChangeRecord, DependencyRecord, ObjectRecord, RunRecord


SCHEMA = """
CREATE TABLE IF NOT EXISTS objects(
    object_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    path TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    hash TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS dependencies(
    src_id TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    dep_type TEXT NOT NULL,
    detected_by TEXT NOT NULL,
    confidence REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS runs(
    run_id TEXT PRIMARY KEY,
    script_path TEXT NOT NULL,
    inputs TEXT NOT NULL,
    outputs TEXT NOT NULL,
    git_commit TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS changes(
    change_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    modified_objects TEXT NOT NULL,
    reverts TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_src ON dependencies(src_id);
CREATE INDEX IF NOT EXISTS idx_dst ON dependencies(dst_id);
"""


def connect_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def replace_index(
    conn: sqlite3.Connection,
    objects: list[ObjectRecord],
    dependencies: list[DependencyRecord],
    runs: list[RunRecord],
    changes: list[ChangeRecord],
) -> None:
    with conn:
        conn.execute("DELETE FROM objects")
        conn.execute("DELETE FROM dependencies")
        conn.execute("DELETE FROM runs")
        conn.execute("DELETE FROM changes")
        conn.executemany(
            "INSERT INTO objects(object_id, type, path, status, summary, hash, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(o.object_id, o.type, o.path, o.status, o.summary, o.hash, o.updated_at) for o in objects],
        )
        conn.executemany(
            "INSERT INTO dependencies(src_id, dst_id, dep_type, detected_by, confidence) VALUES (?, ?, ?, ?, ?)",
            [(d.src_id, d.dst_id, d.dep_type, d.detected_by, d.confidence) for d in dependencies],
        )
        conn.executemany(
            "INSERT INTO runs(run_id, script_path, inputs, outputs, git_commit, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [(r.run_id, r.script_path, json.dumps(r.inputs, ensure_ascii=False), json.dumps(r.outputs, ensure_ascii=False), r.git_commit, r.created_at) for r in runs],
        )
        conn.executemany(
            "INSERT INTO changes(change_id, title, modified_objects, reverts, created_at) VALUES (?, ?, ?, ?, ?)",
            [(c.change_id, c.title, json.dumps(c.modified_objects, ensure_ascii=False), json.dumps(c.reverts, ensure_ascii=False), c.created_at) for c in changes],
        )

