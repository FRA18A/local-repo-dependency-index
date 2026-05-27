# Local Repo Dependency Index Package

This folder is the portable GitHub-ready distribution of the local dependency index engine.

## Included

- `repo_tools/` engine source
- `repo_index.py` entrypoint
- `pyproject.toml` package metadata
- `PACKAGE_INSTALL.md` install guide
- `scripts/install_local_dep_engine.ps1` Windows install helper
- `skills/local-dependency-index/SKILL.md` Codex skill
- `registry/` empty registry templates

## Not included

- local SQLite databases
- generated reports
- generated graphs
- `__pycache__`
- machine-specific scan outputs

## Quick start

```powershell
python -m pip install -e .
repo-index init
repo-index index
repo-index risk-report
```
OR...
Just ask AI agent to install it


## GitHub use

Commit this folder or its zip artifact to a repository release. On another machine, unpack it into a repository root and run the install script or `python -m pip install -e .`.
