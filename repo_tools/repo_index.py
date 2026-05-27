from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Iterable

import yaml

from .db import connect_db, replace_index
from .graphviz_export import build_dot, render_svg
from .models import ChangeRecord, DependencyRecord, ObjectRecord, RunRecord
from .registry import ensure_registry_templates, load_change_registry, load_object_registry
from .scanners.python_scan import scan_python_file
from .scanners.runtime_scan import load_run_manifests, sync_run_registry, write_run_json, write_run_manifest
from .scanners.text_scan import TEXT_EXTENSIONS, scan_text_file
from .utils import file_sha1, guess_type_from_path, infer_object_id, normalize_path, read_text_utf8, relpath_str, stable_hash, utc_now


ROOT = Path.cwd()
DB_PATH = ROOT / ".sqlite" / "dependency_graph.db"
REGISTRY_DIR = ROOT / "registry"
MANIFEST_DIR = ROOT / "repo_tools" / "manifests"
REPORT_DIR = ROOT / "repo_tools" / "reports"
GRAPH_DIR = ROOT / "repo_tools" / "graph"
INDEX_STATE_PATH = REPORT_DIR / "index_state.json"


def is_repo_managed_path(path: Path) -> bool:
    parts = set(path.parts)
    if ".git" in parts or "__pycache__" in parts:
        return False
    if path.suffix.lower() in {".pyc", ".sqlite", ".db"}:
        return False
    return True


def load_existing_io_cache(root: Path) -> dict[str, dict]:
    cache_path = root / "docs" / "_io_scan_results.json"
    if not cache_path.exists():
        return {}
    try:
        payload = json.loads(read_text_utf8(cache_path))
    except Exception:
        return {}
    return {str(item["path"]): item for item in payload.get("scripts", []) if isinstance(item, dict) and item.get("path")}


def summarize_code(scan_result) -> str:
    parts: list[str] = []
    if scan_result.imports:
        parts.append(f"{len(scan_result.imports)} imports")
    if scan_result.input_paths:
        parts.append(f"{len(scan_result.input_paths)} inputs")
    if scan_result.output_paths:
        parts.append(f"{len(scan_result.output_paths)} outputs")
    if scan_result.config_paths:
        parts.append(f"{len(scan_result.config_paths)} configs")
    return ", ".join(parts) if parts else "Python source file"


def ensure_object(
    objects: dict[str, ObjectRecord],
    path_to_object_id: dict[str, str],
    object_type: str,
    path: str,
    status: str,
    summary: str,
    source: str = "inferred",
) -> str:
    normalized = normalize_path(path, ROOT)
    existing = path_to_object_id.get(normalized)
    if existing:
        return existing
    object_id = infer_object_id(object_type, f"{object_type}:{normalized}")
    objects[object_id] = ObjectRecord(
        object_id=object_id,
        type=object_type,
        path=normalized,
        status=status,
        summary=summary,
        hash=file_sha1(Path(normalized)) if Path(normalized).exists() and Path(normalized).is_file() else "",
        updated_at=utc_now(),
        source=source,
    )
    path_to_object_id[normalized] = object_id
    return object_id


def build_index(root: Path) -> tuple[list[ObjectRecord], list[DependencyRecord], list[RunRecord], list[ChangeRecord], dict]:
    ensure_registry_templates(REGISTRY_DIR)
    registry_objects, declared_dependencies = load_object_registry(REGISTRY_DIR)
    changes = load_change_registry(REGISTRY_DIR)
    run_manifests = load_run_manifests(MANIFEST_DIR)
    existing_io_cache = load_existing_io_cache(root)

    objects: dict[str, ObjectRecord] = {}
    path_to_object_id: dict[str, str] = {}
    dependencies: dict[tuple[str, str, str, str], DependencyRecord] = {}
    diagnostics: dict[str, list[str]] = defaultdict(list)

    for obj in registry_objects:
        normalized = normalize_path(obj.path, root) if obj.path else ""
        stored = ObjectRecord(
            object_id=obj.object_id,
            type=obj.type,
            path=normalized or obj.path,
            status=obj.status,
            summary=obj.summary,
            hash=obj.hash,
            updated_at=obj.updated_at,
            source="registry",
        )
        objects[obj.object_id] = stored
        if normalized:
            path_to_object_id[normalized] = obj.object_id

    for path in sorted(root.rglob("*")):
        if not path.is_file() or not is_repo_managed_path(path):
            continue
        rel = relpath_str(path, root)
        suffix = path.suffix.lower()
        normalized = str(path.resolve())

        if suffix == ".py":
            code_id = path_to_object_id.get(normalized) or infer_object_id("code", f"code:{normalized}")
            objects[code_id] = ObjectRecord(
                object_id=code_id,
                type="code",
                path=normalized,
                status="active",
                summary="Python code object",
                hash=file_sha1(path),
                updated_at=utc_now(),
                source="inferred",
            )
            path_to_object_id[normalized] = code_id
            scan_result = scan_python_file(path)
            if scan_result.parse_error:
                diagnostics["parse_errors"].append(f"{rel}: {scan_result.parse_error}")
                cached = existing_io_cache.get(rel)
                if cached:
                    for item in cached.get("io", []):
                        hit_path = item.get("path")
                        if item.get("kind") == "input" and hit_path:
                            scan_result.input_paths.append(hit_path)
                        if item.get("kind") == "output" and hit_path:
                            scan_result.output_paths.append(hit_path)
            objects[code_id] = ObjectRecord(
                object_id=code_id,
                type="code",
                path=normalized,
                status="active",
                summary=summarize_code(scan_result),
                hash=file_sha1(path),
                updated_at=utc_now(),
                source="inferred",
            )

            for imported in scan_result.imports:
                dep_id = infer_object_id("code", f"module:{imported}")
                if dep_id not in objects:
                    objects[dep_id] = ObjectRecord(
                        object_id=dep_id,
                        type="code",
                        path=imported,
                        status="external",
                        summary=f"Imported module: {imported}",
                        hash="",
                        updated_at=utc_now(),
                        source="inferred",
                    )
                dependencies[(code_id, dep_id, "imports", "ast_import")] = DependencyRecord(code_id, dep_id, "imports", "ast_import", 0.95)

            for input_path in sorted(set(scan_result.input_paths + scan_result.config_paths)):
                dep_type = "loads_config" if input_path in scan_result.config_paths else "reads"
                dep_object_type = "config" if input_path in scan_result.config_paths else guess_type_from_path(input_path)
                input_id = ensure_object(objects, path_to_object_id, dep_object_type, input_path, "active", f"{dep_object_type} inferred from code I/O")
                dependencies[(code_id, input_id, dep_type, "ast_io")] = DependencyRecord(code_id, input_id, dep_type, "ast_io", 0.95)

            for output_path in scan_result.output_paths:
                output_type = guess_type_from_path(output_path)
                if output_type == "dataset" and output_path.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".pdf")):
                    output_type = "figure"
                output_id = ensure_object(objects, path_to_object_id, output_type, output_path, "active", f"{output_type} inferred from code output")
                dependencies[(output_id, code_id, "generated_by", "ast_io")] = DependencyRecord(output_id, code_id, "generated_by", "ast_io", 0.95)
                for input_path in sorted(set(scan_result.input_paths + scan_result.config_paths)):
                    dep_object_type = "config" if input_path in scan_result.config_paths else guess_type_from_path(input_path)
                    input_id = ensure_object(objects, path_to_object_id, dep_object_type, input_path, "active", f"{dep_object_type} inferred from code I/O")
                    dependencies[(output_id, input_id, "derived_from", "ast_io")] = DependencyRecord(output_id, input_id, "derived_from", "ast_io", 0.9)
        elif suffix in TEXT_EXTENSIONS:
            doc_type = guess_type_from_path(str(path))
            doc_id = path_to_object_id.get(normalized) or infer_object_id(doc_type, f"{doc_type}:{normalized}")
            if doc_id not in objects:
                objects[doc_id] = ObjectRecord(
                    object_id=doc_id,
                    type=doc_type,
                    path=normalized,
                    status="active",
                    summary=f"{doc_type.capitalize()} object",
                    hash=file_sha1(path),
                    updated_at=utc_now(),
                    source="inferred",
                )
                path_to_object_id[normalized] = doc_id
            for ref in scan_text_file(path):
                dependencies[(doc_id, ref, "references", "regex_text_ref")] = DependencyRecord(doc_id, ref, "references", "regex_text_ref", 0.9)

    for object_id, refs in declared_dependencies.items():
        for dep_id in refs:
            dependencies[(object_id, dep_id, "declared", "registry")] = DependencyRecord(object_id, dep_id, "declared", "registry", 1.0)

    for run in run_manifests:
        script_id = ensure_object(objects, path_to_object_id, "code", run.script_path, "active", "Script recorded in run manifest")
        run_object = ObjectRecord(
            object_id=run.run_id,
            type="run",
            path=str((MANIFEST_DIR / f"{run.run_id}.yaml").resolve()),
            status="recorded",
            summary=f"Run manifest for {run.script_path}",
            hash="",
            updated_at=run.created_at,
            source="manifest",
        )
        objects[run.run_id] = run_object
        dependencies[(run.run_id, script_id, "executed_script", "run_manifest")] = DependencyRecord(run.run_id, script_id, "executed_script", "run_manifest", 1.0)
        for input_path in run.inputs:
            input_id = ensure_object(objects, path_to_object_id, guess_type_from_path(input_path), input_path, "active", "Run input")
            dependencies[(run.run_id, input_id, "used_input", "run_manifest")] = DependencyRecord(run.run_id, input_id, "used_input", "run_manifest", 1.0)
        for output_path in run.outputs:
            output_id = ensure_object(objects, path_to_object_id, guess_type_from_path(output_path), output_path, "active", "Run output")
            dependencies[(output_id, run.run_id, "produced_in_run", "run_manifest")] = DependencyRecord(output_id, run.run_id, "produced_in_run", "run_manifest", 1.0)

    all_objects = list(objects.values())
    all_dependencies = list(dependencies.values())
    return all_objects, all_dependencies, run_manifests, changes, diagnostics


def refresh_db() -> dict:
    objects, dependencies, runs, changes, diagnostics = build_index(ROOT)
    conn = connect_db(DB_PATH)
    replace_index(conn, objects, dependencies, runs, changes)
    conn.close()
    summary = {
        "objects": len(objects),
        "dependencies": len(dependencies),
        "runs": len(runs),
        "changes": len(changes),
        "diagnostics": diagnostics,
        "indexed_at": utc_now(),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_STATE_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def load_graph(conn):
    objects = {row["object_id"]: dict(row) for row in conn.execute("SELECT * FROM objects")}
    reverse: dict[str, list[sqlite3.Row]] = defaultdict(list)  # type: ignore[name-defined]
    forward: dict[str, list[sqlite3.Row]] = defaultdict(list)  # type: ignore[name-defined]
    edges = list(conn.execute("SELECT src_id, dst_id, dep_type, detected_by, confidence FROM dependencies"))
    for edge in edges:
        forward[edge["src_id"]].append(edge)
        reverse[edge["dst_id"]].append(edge)
    return objects, forward, reverse, edges


def resolve_to_object_ids(conn, values: Iterable[str]) -> tuple[list[str], list[str]]:
    objects = {row["object_id"]: row for row in conn.execute("SELECT object_id, path FROM objects")}
    path_map = {str(row["path"]).lower(): row["object_id"] for row in objects.values()}
    resolved: list[str] = []
    missing: list[str] = []
    for value in values:
        if value in objects:
            resolved.append(value)
            continue
        path = Path(value)
        candidate = str((ROOT / path).resolve()) if not path.is_absolute() else str(path.resolve())
        object_id = path_map.get(candidate.lower())
        if object_id:
            resolved.append(object_id)
        else:
            missing.append(value)
    return resolved, missing


def print_impact_tree(conn, object_id: str, depth: int, include_code: bool) -> int:
    objects, _, reverse, _ = load_graph(conn)
    if object_id not in objects:
        print(f"Object not found: {object_id}")
        return 1
    print(object_id)
    visited = {object_id}

    def walk(node_id: str, level: int) -> None:
        if level >= depth:
            return
        children = []
        for edge in sorted(reverse.get(node_id, []), key=lambda item: (item["src_id"], item["dep_type"])):
            child_id = edge["src_id"]
            child = objects.get(child_id)
            if child is None:
                continue
            if not include_code and child["type"] == "code":
                walk(child_id, level)
                continue
            children.append(child_id)
        for child_id in children:
            indent = "  " * (level + 1)
            print(f"{indent}→ {child_id}")
            if child_id not in visited:
                visited.add(child_id)
                walk(child_id, level + 1)

    walk(object_id, 0)
    return 0


def revert_impact(conn, change_id: str, recursive: bool, include_code: bool) -> int:
    row = conn.execute("SELECT * FROM changes WHERE change_id = ?", (change_id,)).fetchone()
    if row is None:
        print(f"Change not found: {change_id}")
        return 1
    modified_objects = json.loads(row["modified_objects"])
    print(f"Change {change_id} modified:")
    for object_id in modified_objects:
        print(f"  - {object_id}")
    objects, _, reverse, _ = load_graph(conn)
    affected: set[str] = set()
    queue = deque(modified_objects)
    seen = set(modified_objects)
    while queue:
        current = queue.popleft()
        for edge in reverse.get(current, []):
            child_id = edge["src_id"]
            child = objects.get(child_id)
            if child is None:
                continue
            if not include_code and child["type"] == "code":
                if recursive and child_id not in seen:
                    seen.add(child_id)
                    queue.append(child_id)
                continue
            if child_id not in affected:
                affected.add(child_id)
            if recursive and child_id not in seen:
                seen.add(child_id)
                queue.append(child_id)
    print("")
    print("Affected downstream objects:")
    for object_id in sorted(affected):
        print(f"  - {object_id}")
    print("")
    print("Likely actions:")
    for object_id in sorted(affected):
        print(f"  - rerun/review {object_id}")
    return 0


def impact_set(conn, values: list[str], depth: int, include_code: bool) -> int:
    resolved, missing = resolve_to_object_ids(conn, values)
    if missing:
        print("Unresolved inputs:")
        for item in missing:
            print(f"  - {item}")
        if not resolved:
            return 1
        print("")
    print("Seed objects:")
    for object_id in resolved:
        print(f"  - {object_id}")
    print("")
    for object_id in resolved:
        print_impact_tree(conn, object_id, depth, include_code)
        print("")
    return 0


def commit_impact(conn, commit_ref: str, depth: int, include_code: bool) -> int:
    git_dir = ROOT / ".git"
    if not git_dir.exists():
        print("Current directory is not a git repository. Use impact-set with explicit file paths instead.")
        return 1
    try:
        completed = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_ref],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        print(exc.stderr.strip() or exc.stdout.strip() or f"Failed to read commit {commit_ref}")
        return 1
    files = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not files:
        print(f"No files found for commit: {commit_ref}")
        return 1
    print(f"Commit {commit_ref} files:")
    for path in files:
        print(f"  - {path}")
    print("")
    return impact_set(conn, files, depth, include_code)


def validate(conn) -> int:
    objects, forward, reverse, _ = load_graph(conn)
    registry_objects, declared = load_object_registry(REGISTRY_DIR)
    issues: list[str] = []
    registry_ids = {obj.object_id for obj in registry_objects}

    for obj in registry_objects:
        if not obj.path:
            issues.append(f"[missing-path] {obj.object_id} has empty path")
        elif not Path(normalize_path(obj.path, ROOT)).exists():
            issues.append(f"[path-not-found] {obj.object_id} -> {obj.path}")

    for object_id, deps in declared.items():
        detected = {edge["dst_id"] for edge in forward.get(object_id, [])}
        for dep in deps:
            if dep not in detected:
                issues.append(f"[declared-mismatch] {object_id} declares {dep} but scanner did not detect it")

    for object_id, obj in objects.items():
        if object_id not in registry_ids and obj["type"] in {"dataset", "result", "figure", "table", "section"}:
            if not reverse.get(object_id) and not forward.get(object_id):
                issues.append(f"[orphan-object] {object_id} has no dependencies")

    for object_id in registry_ids:
        obj = objects.get(object_id)
        if obj and obj["status"] == "deprecated":
            if reverse.get(object_id):
                dependents = ", ".join(sorted({edge["src_id"] for edge in reverse[object_id]}))
                issues.append(f"[deprecated-referenced] {object_id} is still referenced by {dependents}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "validate_report.txt"
    report_lines = ["Validation report", "=================", ""] + (issues or ["No issues found."])
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print("\n".join(report_lines))
    print("")
    print(f"Report: {report_path}")
    return 0 if not issues else 2


def build_risk_report(conn) -> dict[str, list[dict[str, object]]]:
    risks: dict[str, list[dict[str, object]]] = {
        "registry_declared_mismatch": [],
        "registry_path_not_found": [],
        "multi_producer_outputs": [],
        "static_runtime_output_mismatch": [],
    }

    registry_objects, declared = load_object_registry(REGISTRY_DIR)
    objects, forward, _, _ = load_graph(conn)

    for obj in registry_objects:
        if obj.path and not Path(normalize_path(obj.path, ROOT)).exists():
            risks["registry_path_not_found"].append(
                {"object_id": obj.object_id, "path": obj.path}
            )

    for object_id, deps in declared.items():
        detected = {edge["dst_id"] for edge in forward.get(object_id, [])}
        missing = [dep for dep in deps if dep not in detected]
        if missing:
            risks["registry_declared_mismatch"].append(
                {"object_id": object_id, "declared_but_not_detected": missing}
            )

    producer_map: dict[str, set[str]] = defaultdict(set)
    for row in conn.execute(
        "SELECT src_id, dst_id, dep_type FROM dependencies WHERE dep_type IN ('generated_by', 'produced_in_run')"
    ):
        output_id = row["src_id"]
        producer_id = row["dst_id"]
        producer_map[output_id].add(producer_id)
    for output_id, producers in sorted(producer_map.items()):
        if len(producers) > 1:
            risks["multi_producer_outputs"].append(
                {
                    "object_id": output_id,
                    "output_path": objects.get(output_id, {}).get("path", ""),
                    "producers": sorted(producers),
                }
            )

    static_outputs_by_script: dict[str, set[str]] = defaultdict(set)
    runtime_outputs_by_script: dict[str, set[str]] = defaultdict(set)
    script_paths: dict[str, str] = {}
    run_to_script: dict[str, str] = {}

    for row in conn.execute("SELECT object_id, path, type FROM objects"):
        if row["type"] == "code":
            script_paths[row["object_id"]] = row["path"]

    for row in conn.execute("SELECT src_id, dst_id FROM dependencies WHERE dep_type = 'generated_by'"):
        output_id = row["src_id"]
        code_id = row["dst_id"]
        static_outputs_by_script[code_id].add(output_id)

    for row in conn.execute("SELECT src_id, dst_id FROM dependencies WHERE dep_type = 'executed_script'"):
        run_to_script[row["src_id"]] = row["dst_id"]

    for row in conn.execute("SELECT src_id, dst_id FROM dependencies WHERE dep_type = 'produced_in_run'"):
        output_id = row["src_id"]
        run_id = row["dst_id"]
        script_id = run_to_script.get(run_id)
        if script_id:
            runtime_outputs_by_script[script_id].add(output_id)

    all_scripts = sorted(set(static_outputs_by_script) | set(runtime_outputs_by_script))
    for script_id in all_scripts:
        static_outputs = static_outputs_by_script.get(script_id, set())
        runtime_outputs = runtime_outputs_by_script.get(script_id, set())
        if runtime_outputs and static_outputs != runtime_outputs:
            risks["static_runtime_output_mismatch"].append(
                {
                    "script_id": script_id,
                    "script_path": script_paths.get(script_id, ""),
                    "static_only": sorted(static_outputs - runtime_outputs),
                    "runtime_only": sorted(runtime_outputs - static_outputs),
                }
            )

    return risks


def print_risk_report(conn) -> int:
    risks = build_risk_report(conn)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / "risk_report.json"
    txt_path = REPORT_DIR / "risk_report.txt"
    json_path.write_text(json.dumps(risks, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["Risk report", "===========", ""]
    total = 0
    for key, items in risks.items():
        total += len(items)
        lines.append(f"{key}: {len(items)}")
        for item in items[:20]:
            lines.append(f"  - {json.dumps(item, ensure_ascii=False)}")
        if len(items) > 20:
            lines.append(f"  - ... {len(items) - 20} more")
        lines.append("")
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"JSON: {json_path}")
    print(f"Text: {txt_path}")
    return 0 if total == 0 else 2


def graph_object(conn, object_id: str, reverse_mode: bool, depth: int, collapse_code: bool) -> int:
    objects, forward, reverse, _ = load_graph(conn)
    if object_id not in objects:
        print(f"Object not found: {object_id}")
        return 1
    visited = {object_id}
    queue = deque([(object_id, 0)])
    nodes = {object_id}
    edges: set[tuple[str, str, str]] = set()
    adjacency = reverse if reverse_mode else forward
    edge_src_key = "src_id"
    edge_dst_key = "dst_id"

    while queue:
        node_id, level = queue.popleft()
        if level >= depth:
            continue
        for edge in adjacency.get(node_id, []):
            next_id = edge[edge_src_key] if reverse_mode else edge[edge_dst_key]
            current_left = edge[edge_src_key]
            current_right = edge[edge_dst_key]
            next_obj = objects.get(next_id)
            if next_obj is None:
                continue
            if collapse_code and next_obj["type"] == "code":
                continue
            nodes.add(next_id)
            edges.add((current_left, current_right, edge["dep_type"]))
            if next_id not in visited:
                visited.add(next_id)
                queue.append((next_id, level + 1))

    node_payload = [objects[node_id] for node_id in sorted(nodes)]
    dot_text = build_dot(node_payload, sorted(edges), reverse=reverse_mode)
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    dot_path = GRAPH_DIR / f"{object_id}.dot"
    svg_path = GRAPH_DIR / "dependency_graph.svg"
    ok, message = render_svg(dot_text, dot_path, svg_path)
    print(message)
    print(f"DOT: {dot_path}")
    if ok:
        print(f"SVG: {svg_path}")
    return 0


def detect_git_commit(root: Path) -> str | None:
    git_dir = root / ".git"
    if not git_dir.exists():
        return None
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return completed.stdout.strip() or None


def run_script(args) -> int:
    script_path = Path(args.script)
    if not script_path.is_absolute():
        script_path = ROOT / script_path
    if not script_path.exists():
        print(f"Script not found: {script_path}")
        return 1
    scan = scan_python_file(script_path)
    run_id = args.run_id or f"RUN-{stable_hash(f'{script_path}:{utc_now()}', 10)}"
    payload = {
        "run_id": run_id,
        "script": str(script_path.resolve()),
        "inputs": scan.input_paths,
        "outputs": scan.output_paths,
        "git_commit": detect_git_commit(ROOT),
        "created_at": utc_now(),
    }
    manifest_path = MANIFEST_DIR / f"{run_id}.yaml"
    write_run_manifest(manifest_path, payload)
    json_path = MANIFEST_DIR / f"{run_id}.json"
    write_run_json(json_path, payload)
    sync_run_registry(REGISTRY_DIR / "run_registry.yaml", payload)

    command = [sys.executable, str(script_path.resolve()), *args.script_args]
    completed = subprocess.run(command, cwd=ROOT)
    print(f"Run manifest: {manifest_path}")
    print(f"Run metadata: {json_path}")
    return completed.returncode


def status(conn) -> int:
    counts = {}
    for table in ("objects", "dependencies", "runs", "changes"):
        counts[table] = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
    if INDEX_STATE_PATH.exists():
        try:
            counts["indexed_at"] = json.loads(read_text_utf8(INDEX_STATE_PATH)).get("indexed_at")
        except Exception:
            pass
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local non-LLM repository dependency indexer")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create registry templates and database directories")
    sub.add_parser("index", help="Scan repository and rebuild SQLite dependency index")
    sub.add_parser("status", help="Show current database object counts")
    sub.add_parser("risk-report", help="Report dependency risks from the current index")

    impact = sub.add_parser("impact", help="Reverse dependency impact analysis")
    impact.add_argument("object_id")
    impact.add_argument("--depth", type=int, default=6)
    impact.add_argument("--include-code", action="store_true")

    impact_set_parser = sub.add_parser("impact-set", help="Impact analysis for multiple object IDs or file paths")
    impact_set_parser.add_argument("items", nargs="+")
    impact_set_parser.add_argument("--depth", type=int, default=4)
    impact_set_parser.add_argument("--include-code", action="store_true")

    commit = sub.add_parser("commit-impact", help="Impact analysis for a git commit")
    commit.add_argument("commit_ref")
    commit.add_argument("--depth", type=int, default=4)
    commit.add_argument("--include-code", action="store_true")

    revert = sub.add_parser("revert-impact", help="Impact analysis for a change object")
    revert.add_argument("change_id")
    revert.add_argument("--direct-only", action="store_true")
    revert.add_argument("--include-code", action="store_true")

    sub.add_parser("validate", help="Validate registry and dependency consistency")

    graph = sub.add_parser("graph", help="Export Graphviz dependency graph")
    graph.add_argument("object_id")
    graph.add_argument("--depth", type=int, default=4)
    graph.add_argument("--reverse", action="store_true")
    graph.add_argument("--collapse-code", action="store_true")

    run = sub.add_parser("run-script", help="Run a Python script and record a run manifest")
    run.add_argument("script")
    run.add_argument("--run-id")
    args, unknown = parser.parse_known_args()
    if args.command == "run-script":
        args.script_args = unknown
    return args


def main() -> int:
    args = parse_args()
    if args.command == "init":
        ensure_registry_templates(REGISTRY_DIR)
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        GRAPH_DIR.mkdir(parents=True, exist_ok=True)
        connect_db(DB_PATH).close()
        print(f"Initialized registry and database at {DB_PATH}")
        return 0

    if args.command == "run-script":
        return run_script(args)

    if args.command == "index":
        summary = refresh_db()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        conn = connect_db(DB_PATH)
        risks = build_risk_report(conn)
        non_empty = {k: len(v) for k, v in risks.items() if v}
        if non_empty:
            print("")
            print("risk-report summary:")
            print(json.dumps(non_empty, ensure_ascii=False, indent=2))
        return 0

    conn = connect_db(DB_PATH)
    if args.command == "status":
        return status(conn)
    if args.command == "risk-report":
        return print_risk_report(conn)
    if args.command == "impact":
        return print_impact_tree(conn, args.object_id, args.depth, args.include_code)
    if args.command == "impact-set":
        return impact_set(conn, args.items, args.depth, args.include_code)
    if args.command == "revert-impact":
        return revert_impact(conn, args.change_id, recursive=not args.direct_only, include_code=args.include_code)
    if args.command == "commit-impact":
        return commit_impact(conn, args.commit_ref, args.depth, args.include_code)
    if args.command == "validate":
        return validate(conn)
    if args.command == "graph":
        return graph_object(conn, args.object_id, args.reverse, args.depth, args.collapse_code)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
