from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from ..utils import read_text_utf8


READ_LIKE = {
    "read_csv",
    "read_parquet",
    "read_feather",
    "read_pickle",
    "read_excel",
    "load",
}
WRITE_LIKE = {
    "to_csv",
    "to_parquet",
    "to_feather",
    "to_pickle",
    "to_excel",
    "dump",
    "savefig",
}
CONFIG_READ_LIKE = {"safe_load", "load", "loads"}


@dataclass
class PythonScanResult:
    imports: list[str]
    input_paths: list[str]
    output_paths: list[str]
    config_paths: list[str]
    call_names: list[str]
    unresolved_inputs: list[str]
    unresolved_outputs: list[str]
    parse_error: str | None = None


def _attr_chain(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _attr_chain(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _eval_str(node: ast.AST, consts: dict[str, str]) -> str | None:
    const = _const_str(node)
    if const is not None:
        return const
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _eval_str(node.left, consts)
        right = _eval_str(node.right, consts)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                inner = _eval_str(value.value, consts)
                if inner is None:
                    return None
                parts.append(inner)
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.Call):
        func = _attr_chain(node.func)
        if func.endswith("os.path.join") or func.endswith("path.join"):
            parts: list[str] = []
            for arg in node.args:
                value = _eval_str(arg, consts)
                if value is None:
                    return None
                parts.append(value)
            return str(Path(parts[0]).joinpath(*parts[1:]))
        if func.endswith("Path") and node.args:
            return _eval_str(node.args[0], consts)
    return None


def _collect_consts(tree: ast.AST) -> dict[str, str]:
    consts: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            key = node.targets[0].id
            value = _eval_str(node.value, consts)
            if value is not None:
                consts[key] = value
    return consts


def _classify_io(func_chain: str) -> tuple[str, str] | None:
    leaf = func_chain.split(".")[-1]
    if leaf in READ_LIKE:
        return "input", leaf
    if leaf in WRITE_LIKE:
        return "output", leaf
    if leaf in {"csv", "parquet", "json", "text"}:
        if ".read." in func_chain:
            return "input", f"spark_{leaf}"
        if ".write." in func_chain:
            return "output", f"spark_{leaf}"
    return None


def scan_python_file(path: Path) -> PythonScanResult:
    text = read_text_utf8(path)
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return PythonScanResult([], [], [], [], [], [], [], parse_error=str(exc))

    consts = _collect_consts(tree)
    imports: set[str] = set()
    inputs: set[str] = set()
    outputs: set[str] = set()
    configs: set[str] = set()
    call_names: set[str] = set()
    unresolved_inputs: set[str] = set()
    unresolved_outputs: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.add(f"{module}.{alias.name}" if module else alias.name)
        elif isinstance(node, ast.Call):
            func_chain = _attr_chain(node.func)
            if func_chain:
                call_names.add(func_chain)

            classified = _classify_io(func_chain)
            if classified and node.args:
                kind, _ = classified
                resolved = _eval_str(node.args[0], consts)
                if resolved is not None:
                    (inputs if kind == "input" else outputs).add(resolved)
                else:
                    (unresolved_inputs if kind == "input" else unresolved_outputs).add(ast.unparse(node.args[0]))

            if isinstance(node.func, ast.Name) and node.func.id == "open" and node.args:
                resolved = _eval_str(node.args[0], consts)
                mode = _const_str(node.args[1]) if len(node.args) > 1 else None
                for kw in node.keywords:
                    if kw.arg == "mode":
                        mode = _const_str(kw.value)
                if resolved is not None:
                    if mode and ("w" in mode or "a" in mode or "+" in mode):
                        outputs.add(resolved)
                    else:
                        inputs.add(resolved)

            leaf = func_chain.split(".")[-1] if func_chain else ""
            if leaf in CONFIG_READ_LIKE and node.args:
                resolved = _eval_str(node.args[0], consts)
                if resolved and resolved.lower().endswith((".yaml", ".yml", ".json", ".toml", ".ini", ".cfg")):
                    configs.add(resolved)
            if func_chain.endswith(("json.load", "json.loads", "yaml.safe_load", "yaml.load")):
                for arg in node.args:
                    resolved = _eval_str(arg, consts)
                    if resolved and resolved.lower().endswith((".yaml", ".yml", ".json")):
                        configs.add(resolved)

    return PythonScanResult(
        imports=sorted(imports),
        input_paths=sorted(inputs),
        output_paths=sorted(outputs),
        config_paths=sorted(configs),
        call_names=sorted(call_names),
        unresolved_inputs=sorted(unresolved_inputs),
        unresolved_outputs=sorted(unresolved_outputs),
        parse_error=None,
    )
