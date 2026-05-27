---
name: local-dependency-index
description: Build and use a local non-LLM repository dependency index for Python-heavy repositories. Use when Codex needs to scan a repo, build SQLite dependency metadata, run impact analysis, query dependencies for one file or a set of files, inspect change or commit impact, validate object registries, or use dependency evidence to maintain, refactor, add, or delete project artifacts safely.
---

# Local Dependency Index

Use `repo-index` before making structural changes to a repository when dependency uncertainty is non-trivial.

## Quick workflow

1. Run `repo-index init` once in the target repository root.
2. Run `repo-index index` to rebuild the local SQLite graph.
3. Run `repo-index validate` before trusting registry-linked objects.
4. For one object, use `repo-index impact OBJECT_ID`.
5. For several files or objects, use `repo-index impact-set <item1> <item2> ...`.
6. For a git commit, use `repo-index commit-impact <commit>`.

## Mandatory rule before commit

- Before creating a commit that changes code, run `repo-index index`.
- Before creating a commit that changes one file, run `repo-index impact-set <that-file> --include-code`.
- Before creating a commit that changes several files, run `repo-index impact-set <file1> <file2> ... --include-code`.
- If the repository is a git repo and the commit already exists locally, run `repo-index commit-impact <commit> --include-code`.
- Do not commit structural code changes without checking dependency impact first.

## Re-index policy

- Re-index after code edits, registry edits, file moves, file additions, or script runs that may change outputs.
- Re-index before commit.
- Re-index if the current index is older than one day, even when changes are uncertain.
- If no repository content changed and the index is still fresh, reuse the existing index for queries.
- After every re-index, run `repo-index risk-report`.
- If `risk-report` is non-empty, mention that fact briefly in the answer.

## Single-file dependency query

Use this exact pattern for one file:

```bash
repo-index impact-set path\to\file.py --depth 3 --include-code
```

Use this pattern when the user gives an object ID instead of a path:

```bash
repo-index impact OBJECT_ID --depth 3 --include-code
```

If the user asks for a picture, run:

```bash
repo-index graph OBJECT_ID --reverse --depth 3
```

If the file was just edited, re-run:

```bash
repo-index index
```

before trusting the query result.

## How to read results

- `Seed objects:` are the starting files or object IDs that were resolved successfully.
- `CODE-*` means a code object. Map it to the real file path through the SQLite `objects` table or by reading the `path` field in follow-up queries.
- `DATA-*` means a dataset object.
- `RESULT-*`, `FIG-*`, `TABLE-*`, `SEC-*` are registered semantic objects when the registry is populated.
- `CFG-*` means a config object such as YAML/JSON/TOML/INI.
- In impact output, `A -> B` means `B` is downstream of `A` in the reverse-dependency view.
- `reads` means code reads an input object.
- `generated_by` means an output object is produced by a code object.
- `derived_from` means an output object is derived from an input object.
- `declared` means the relation came from the object registry.
- `references` means a text/config/document file mentions an object ID by regex match.

## Fast follow-up checks

- Run `repo-index validate` if the result depends on registry-declared objects.
- Run `repo-index graph ...` if the user wants a local visual subgraph.
- Run `repo-index risk-report` after re-index and mention any non-empty result briefly.
- Run `repo-index run-script ...` when executing scripts whose provenance should be tracked.
- Re-run `repo-index index` after code edits, file moves, registry changes, or script execution that changes outputs.

## Preferred usage

- Use `impact-set` when the user describes a bundle of scripts, a feature slice, or a small patch set.
- Use `commit-impact` only inside a git repository.
- Use `run-script` when you execute a repository script and want a local provenance manifest.
- Use `graph` when the user wants a picture; mention if Graphviz `dot` is missing.

## Interpretation rules

- Treat `reads` as code-to-input evidence.
- Treat `generated_by` as output-to-script evidence.
- Treat `derived_from` as output-to-input lineage.
- Treat `declared` as registry evidence.
- Treat `references` as text/document citation evidence.

## Good maintenance pattern

1. Re-index.
2. Query the target object/file/set.
3. Inspect downstream objects before editing.
4. After edits, re-index and re-run the same impact query.
5. Before commit, run dependency impact again on the exact changed file set.
6. If scripts were executed, record them with `run-script`.

## Registry guidance

- Put stable human IDs in `registry/object_registry.yaml` for important datasets, results, figures, sections, and tables.
- Put rollback groups in `registry/change_registry.yaml` when the user reasons in named changes rather than file paths.
- Keep `registry/run_registry.yaml` machine-managed.
