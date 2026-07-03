# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **single-script automation tool** (`update_projects.py`) that performs recurring maintenance updates across all packages in the sibling `../ambient-packages/` directory. It renders templates, locks/syncs dependencies, runs linters, bumps patch versions, updates changelogs, and pushes maintenance branches to GitHub. PRs must be created manually afterward (noted in the script).

## Commands

**Run the updater:**
```bash
python update_projects.py
```

**Lint this repo:**
```bash
pre-commit run --all-files
```

**Install pre-commit hooks:**
```bash
pre-commit install
```

## Architecture

The entire logic lives in `update_projects.py` as the `PackageUpdater` class:

- `PACKAGE_DIR` points to `../ambient-packages/` — only subdirectories containing `.ambient-package-update/` are processed.
- Each package must have a `.venv/Scripts/python.exe` (Windows venv) for the updater to proceed.
- Per-package config is read from `.ambient-package-update/metadata.py` — the script extracts `main_branch`, `module_name`/`package_name`, and `optional_dependencies` from it.
- Branch naming convention: `maintenance/v{next_patch_version}`. If the branch already exists, version/changelog are not bumped again (idempotent re-runs).
- `_run_command()` exits the entire process on non-zero return codes unless `ignore_return_code=True` (used for pre-commit).

## Tooling

- **Python 3.13+** required (enforced by pyupgrade in pre-commit)
- **uv** for dependency management (lock/sync commands run directly as `uv lock` / `uv sync`)
- **Ruff** for formatting and linting (via pre-commit hooks)
- **GitHub token** must be set in `.env` as `GITHUB_ACCESS_TOKEN` for git push to work
