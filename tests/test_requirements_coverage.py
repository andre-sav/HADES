"""Static check: every third-party import in production code is declared in requirements.txt.

Guards against the bug class where a page imports a library, the library is in
requirements-lock.txt (so CI and local-dev both pass), but it's missing from
requirements.txt — which is the only file Streamlit Cloud installs from.
That gap silently breaks one deploy target while every other check stays green.

The test discovers package metadata at runtime via importlib.metadata, so it
adapts when new packages are added to requirements.txt without needing a
hand-maintained mapping.
"""

from __future__ import annotations

import ast
import importlib.metadata as md
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

# Directories that contain production code. A file's third-party imports must
# be backed by a declared dep in requirements.txt.
PROD_DIRS: tuple[str, ...] = ("", "db", "pages", "scripts")

# Directories to skip entirely — tooling, tests, vendored frameworks, etc.
EXCLUDE_DIR_PARTS = {
    "tests", "__pycache__", "_bmad", "system-test", ".beads", "node_modules",
    "docs",  # docs/briefing/build_pdf.py uses fpdf but is not production code
}

# HADES-internal top-level package/module names — these are not third-party.
# Derived dynamically from the repo so a new module doesn't need a code change.
def _internal_modules() -> set[str]:
    names: set[str] = set()
    # Top-level .py files in the repo root
    for p in ROOT.glob("*.py"):
        names.add(p.stem)
    # First-level package directories
    for d in ROOT.iterdir():
        if d.is_dir() and (d / "__init__.py").exists():
            names.add(d.name)
    # Recognize pages/ and scripts/ as packages even without __init__.py.
    # scripts/ files are also importable as top-level modules because running
    # `python scripts/foo.py` auto-adds scripts/ to sys.path — so a sibling
    # script can `from _credentials import ...` directly.
    for extra in ("pages", "scripts"):
        if (ROOT / extra).is_dir():
            names.add(extra)
    for p in (ROOT / "scripts").glob("*.py"):
        names.add(p.stem)
    return names


INTERNAL_MODULES = _internal_modules()

# Python stdlib module names (3.10+ ships with sys.stdlib_module_names)
STDLIB = set(sys.stdlib_module_names)


def _read_declared_packages() -> set[str]:
    """Parse requirements.txt and return the set of declared package names (lowercased)."""
    declared: set[str] = set()
    req_path = ROOT / "requirements.txt"
    for line in req_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip version specifiers / extras
        # e.g. "streamlit>=1.37.0" -> "streamlit"
        for sep in ("==", ">=", "<=", "~=", "!=", "<", ">", ";", "["):
            line = line.split(sep, 1)[0]
        declared.add(line.strip().lower())
    return declared


def _build_import_to_package_map() -> dict[str, str]:
    """Walk installed distributions and build {import_name: pip_package_name}.

    Works because pytest runs in an env where requirements have been installed.
    Uses top_level.txt where available, falling back to the dist name itself.
    """
    mapping: dict[str, str] = {}
    for dist in md.distributions():
        pkg_name = (dist.metadata["Name"] or "").strip()
        if not pkg_name:
            continue
        # top_level.txt lists the importable module names provided by the dist
        top_level = dist.read_text("top_level.txt")
        if top_level:
            for module in top_level.strip().splitlines():
                module = module.strip()
                if module and not module.startswith("_"):
                    mapping[module] = pkg_name
        else:
            # Fallback: normalize the dist name into a likely import name
            mapping[pkg_name.lower().replace("-", "_")] = pkg_name
    return mapping


def _collect_imports_from_file(path: Path) -> set[str]:
    """Return the set of top-level module names imported by `path`."""
    imports: set[str] = set()
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            # Relative imports (level > 0) are always internal
            if node.level and node.level > 0:
                continue
            if node.module:
                imports.add(node.module.split(".", 1)[0])
    return imports


def _iter_prod_files():
    for prod in PROD_DIRS:
        base = ROOT / prod if prod else ROOT
        if not base.exists():
            continue
        if prod == "":
            # Top-level .py files only — don't recurse into subdirs from root
            for p in base.glob("*.py"):
                yield p
        else:
            for p in base.rglob("*.py"):
                if any(part in EXCLUDE_DIR_PARTS for part in p.parts):
                    continue
                yield p


def _collect_used_third_party_imports() -> dict[str, set[Path]]:
    """Return {import_name: {files that import it}} for non-stdlib non-internal imports."""
    by_import: dict[str, set[Path]] = {}
    for path in _iter_prod_files():
        for imp in _collect_imports_from_file(path):
            if imp in STDLIB:
                continue
            if imp in INTERNAL_MODULES:
                continue
            by_import.setdefault(imp, set()).add(path.relative_to(ROOT))
    return by_import


def test_requirements_covers_all_production_imports():
    """Every third-party import in production code must trace to a package in requirements.txt.

    Diagnostic failure: the message lists each missing import and which files
    use it, so the fix is obvious.
    """
    declared = _read_declared_packages()
    import_to_pkg = _build_import_to_package_map()
    used = _collect_used_third_party_imports()

    missing: list[str] = []
    for imp, files in sorted(used.items()):
        pkg = import_to_pkg.get(imp)
        if pkg is None:
            missing.append(
                f"  - {imp!r}: installed dist not discoverable "
                f"(used by: {sorted(str(f) for f in files)[:3]})"
            )
            continue
        if pkg.lower() not in declared:
            missing.append(
                f"  - {imp!r} (package {pkg!r}): not declared in requirements.txt "
                f"(used by: {sorted(str(f) for f in files)[:3]})"
            )

    assert not missing, (
        "Third-party imports in production code not satisfied by requirements.txt:\n"
        + "\n".join(missing)
        + "\n\nAdd the missing package(s) to requirements.txt to keep Streamlit Cloud "
        "in sync with local dev and CI."
    )


def test_requirements_file_is_well_formed():
    """Sanity: requirements.txt parses cleanly and contains the core deps."""
    declared = _read_declared_packages()
    for must_have in ("streamlit", "pandas", "httpx", "plotly"):
        assert must_have in declared, f"requirements.txt missing core dep: {must_have}"
