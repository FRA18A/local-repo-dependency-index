from __future__ import annotations

import subprocess
from pathlib import Path


TYPE_COLORS = {
    "code": "#8ecae6",
    "dataset": "#219ebc",
    "result": "#ffb703",
    "figure": "#fb8500",
    "table": "#f4a261",
    "section": "#90be6d",
    "change": "#d62828",
    "run": "#6d597a",
    "config": "#577590",
    "document": "#adb5bd",
}


def build_dot(nodes: list[dict[str, str]], edges: list[tuple[str, str, str]], reverse: bool = False) -> str:
    lines = [
        "digraph repo_dependencies {",
        "  rankdir=LR;",
        "  graph [fontname=\"Helvetica\"];",
        "  node [shape=box style=filled fontname=\"Helvetica\"];",
        "  edge [fontname=\"Helvetica\"];",
    ]
    for node in nodes:
        color = TYPE_COLORS.get(node["type"], "#cccccc")
        label = f'{node["object_id"]}\\n{node["type"]}'
        lines.append(f'  "{node["object_id"]}" [fillcolor="{color}" label="{label}"];')
    for src_id, dst_id, dep_type in edges:
        left, right = (dst_id, src_id) if reverse else (src_id, dst_id)
        lines.append(f'  "{left}" -> "{right}" [label="{dep_type}"];')
    lines.append("}")
    return "\n".join(lines)


def render_svg(dot_text: str, dot_path: Path, svg_path: Path) -> tuple[bool, str]:
    dot_path.parent.mkdir(parents=True, exist_ok=True)
    dot_path.write_text(dot_text, encoding="utf-8")
    command = ["dot", "-Tsvg", str(dot_path), "-o", str(svg_path)]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        return False, "Graphviz 'dot' command not found. Wrote DOT file only."
    except subprocess.CalledProcessError as exc:
        return False, exc.stderr.strip() or exc.stdout.strip() or "Graphviz rendering failed."
    return True, completed.stderr.strip() or "Rendered SVG successfully."

