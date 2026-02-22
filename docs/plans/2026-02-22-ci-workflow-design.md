# CI Test Workflow + Ruff + Pin Dependencies — Design

**Date:** 2026-02-22
**Bead:** HADES-28z
**Status:** Approved

## Problem

No CI test workflow — tests only run locally via pre-commit hook. Dependencies are unpinned (open ranges like `streamlit>=1.37.0`), so CI and deploy could get different versions than dev. No linter configured.

## Deliverables

### 1. Pin dependencies

- Generate `requirements-lock.txt` from current working environment (`pip freeze`)
- CI and intent-poll install from lock file for reproducibility
- `requirements.txt` stays as-is for local dev (loose ranges)

### 2. GitHub Actions test workflow

**File:** `.github/workflows/test.yml`
- Triggers: push to main, PR targeting main
- Python 3.13, pip cache
- Steps: install from lock file, run ruff, run pytest
- Timeout: 5 minutes

### 3. Ruff linter

**File:** `ruff.toml`
- Default rule set (E + F)
- `per-file-ignores`: `pages/*.py` ignores `E402` (Streamlit requires imports after `st.set_page_config`)
- `E741` ignored globally (ambiguous variable names like `l` are used intentionally in this codebase)
- Added to `requirements.txt` dev section and lock file
- Fix all ~109 violations: 52 auto-fixable, remainder manual

### 4. Update intent-poll.yml

Change `pip install -r requirements.txt` → `pip install -r requirements-lock.txt`.

## What's excluded (YAGNI)

- No multi-version Python matrix (only deploy on 3.13)
- No coverage reporting (no coverage tooling today)
- No Dependabot (can add later)
