"""Smoke test: every Streamlit page's module-level code holds together.

Streamlit runs each file in ``pages/`` as an INDEPENDENT top-to-bottom script,
so a module-level ``NameError``/``ImportError``/syntax error from a half-finished
refactor is invisible to the rest of the suite — pytest never imports these
files. The only place such a break surfaces today is a user clicking the page
in production (insurance M4, HADES-0h1).

Two complementary layers, neither of which needs a database or a network:

1. **Static** (``static_problems``) — covers 100% of every page. Compiles the
   file, resolves every module-level import *and* checks each imported name
   actually exists in the target module, then scope-checks module-level name
   loads for ``NameError``.

2. **Execution** (``execution_problem``) — covers the import prologue for real.
   Executes the page with a stand-in ``streamlit`` whose ``stop()`` raises a
   sentinel, so the script halts inside ``require_auth()`` at exactly the point
   Streamlit Cloud halts it for a signed-out visitor — after every import has
   genuinely run, before any DB access.

The negative tests below are the load-bearing ones: they prove the harness
actually fails on a broken page, and that its diagnostic names the cause.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import functools
import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest


ROOT = Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "pages"

# Names Python injects into every module namespace.
_MODULE_DUNDERS = {
    "__file__", "__name__", "__doc__", "__spec__", "__package__",
    "__loader__", "__builtins__", "__annotations__", "__dict__",
}
_BUILTIN_NAMES = set(dir(builtins)) | _MODULE_DUNDERS


def _iter_pages() -> list[Path]:
    return sorted(p for p in PAGES_DIR.glob("*.py") if not p.name.startswith("_"))


# --------------------------------------------------------------------------
# Isolation from the rest of the suite
#
# Fifteen test modules used to run ``sys.modules["streamlit"] = MagicMock()``
# at import time and never restore it, so whichever pytest imported first won
# the session and both layers here broke: a MagicMock is not a package, so
# ``import streamlit.components.v1`` (via keyboard_shortcuts) raised, and a
# mocked ``st.stop()`` does not halt the page.
#
# That root cause is fixed (HADES-w1k) and
# ``test_no_test_module_replaces_streamlit_globally`` keeps it fixed. The
# machinery below is retained as defence in depth — it costs one cached import
# and makes these layers correct regardless of what any future fixture or
# plugin leaves in sys.modules.
# --------------------------------------------------------------------------

def _snapshot_streamlit_modules() -> dict[str, object]:
    return {
        name: mod for name, mod in sys.modules.items()
        if name == "streamlit" or name.startswith("streamlit.")
    }


def _restore_streamlit_modules(snapshot: dict[str, object]) -> None:
    for name in list(sys.modules):
        if name == "streamlit" or name.startswith("streamlit."):
            del sys.modules[name]
    sys.modules.update(snapshot)


@functools.lru_cache(maxsize=1)
def _real_streamlit() -> ModuleType:
    """The genuine streamlit package, imported past whatever mock is installed."""
    snapshot = _snapshot_streamlit_modules()
    try:
        for name in list(sys.modules):
            if name == "streamlit" or name.startswith("streamlit."):
                del sys.modules[name]
        return importlib.import_module("streamlit")
    finally:
        real_entries = _snapshot_streamlit_modules()
        _restore_streamlit_modules(snapshot)
        # Keep the genuine submodules importable for later lookups without
        # letting them shadow another test's mock of the top-level package.
        for name, mod in real_entries.items():
            sys.modules.setdefault(name, mod)


@contextlib.contextmanager
def _genuine_streamlit():
    """Install the real streamlit package for the duration of the block."""
    real = _real_streamlit()
    snapshot = _snapshot_streamlit_modules()
    sys.modules["streamlit"] = real
    try:
        yield real
    finally:
        _restore_streamlit_modules(snapshot)


# --------------------------------------------------------------------------
# Layer 1 — static analysis (covers 100% of the file, executes nothing)
# --------------------------------------------------------------------------

# Import resolution is process-wide, so cache it: 11 pages share most imports.
_import_cache: dict[str, object | str] = {}


def _resolve_module(name: str) -> object | str:
    """Import `name`, returning the module or a diagnostic string on failure."""
    if name not in _import_cache:
        try:
            with _genuine_streamlit():
                _import_cache[name] = importlib.import_module(name)
        except Exception as exc:  # ImportError, or anything an import triggers
            _import_cache[name] = f"{type(exc).__name__}: {exc}"
    return _import_cache[name]


def _collect_module_level(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Return (names bound at module level, names loaded at module level).

    Function/class/lambda *bodies* are pruned: their bindings are local and
    their loads are deferred to call time, so neither belongs to module scope.
    Decorators, default arguments and base classes are kept — those do evaluate
    at module level.
    """
    bound: set[str] = set()
    loaded: set[str] = set()

    def visit_signature(args: ast.arguments) -> None:
        for default in [*args.defaults, *(d for d in args.kw_defaults if d)]:
            visit(default)
        every = [*args.posonlyargs, *args.args, *args.kwonlyargs,
                 args.vararg, args.kwarg]
        for arg in every:
            if arg is not None and arg.annotation is not None:
                visit(arg.annotation)

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)
            for dec in node.decorator_list:
                visit(dec)
            visit_signature(node.args)
            if node.returns is not None:
                visit(node.returns)
            return  # prune body
        if isinstance(node, ast.ClassDef):
            bound.add(node.name)
            for dec in node.decorator_list:
                visit(dec)
            for base in node.bases:
                visit(base)
            for kw in node.keywords:
                visit(kw.value)
            return  # prune body
        if isinstance(node, ast.Lambda):
            visit_signature(node.args)
            return  # prune body
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound.add(alias.asname or alias.name.split(".")[0])
            return
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                loaded.add(node.id)
            else:  # Store / Del
                bound.add(node.id)
            return
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
            return
        if isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        for child in ast.iter_child_nodes(node):
            visit(child)

    for stmt in tree.body:
        visit(stmt)
    return bound, loaded


def _import_problems(tree: ast.Module) -> list[str]:
    """Every module-level import must resolve, and every imported name exist."""
    problems: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = _resolve_module(alias.name)
                if isinstance(resolved, str):
                    problems.append(f"import {alias.name!r} fails — {resolved}")
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import — package-internal, skip
                continue
            module_name = node.module or ""
            resolved = _resolve_module(module_name)
            if isinstance(resolved, str):
                problems.append(f"import of {module_name!r} fails — {resolved}")
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if hasattr(resolved, alias.name):
                    continue
                # It may be a submodule that has not been imported yet.
                if isinstance(_resolve_module(f"{module_name}.{alias.name}"), str):
                    problems.append(
                        f"{module_name!r} has no attribute {alias.name!r} "
                        f"(renamed or removed?)"
                    )
    return problems


def static_problems(path: Path) -> list[str]:
    """Return every module-level defect found in `path`, newest concern first.

    Catches syntax errors, unresolvable imports, imported names that no longer
    exist in their module, and module-level NameErrors. Nothing is executed.

    Binding order is deliberately ignored — a name bound anywhere at module
    level counts as known — so conditional definitions do not produce false
    positives. Use-before-assignment is therefore out of scope.
    """
    source = path.read_text()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"SyntaxError at line {exc.lineno}: {exc.msg}"]

    problems = _import_problems(tree)

    # A star import makes module scope unknowable; skip the NameError pass
    # rather than emit noise.
    has_star = any(
        isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)
        for n in tree.body
    )
    if not has_star:
        bound, loaded = _collect_module_level(tree)
        unknown = sorted(loaded - bound - _BUILTIN_NAMES)
        problems.extend(
            f"module-level NameError: {name!r} is never bound" for name in unknown
        )
    return problems


# --------------------------------------------------------------------------
# Layer 2 — execute the prologue for real, halting at the auth gate
# --------------------------------------------------------------------------

class _AuthGateReached(Exception):
    """Raised by the stand-in ``st.stop()`` — the success signal."""


def _gated_streamlit(real: ModuleType) -> ModuleType:
    """A streamlit stand-in that halts the script inside require_auth().

    A real ``ModuleType`` carrying the genuine package's ``__path__``, so
    ``import streamlit.components.v1`` still resolves, with a PEP 562
    ``__getattr__`` delegating everything un-overridden to the real module.
    Only the calls the prologue and the auth gate actually make are replaced.

    Configuring ``secrets`` with a password and ``button`` with False drives
    require_auth() down its signed-out branch, which ends in ``st.stop()``.
    """
    st = ModuleType("streamlit")
    for attr in ("__path__", "__spec__", "__loader__", "__package__", "__file__"):
        if hasattr(real, attr):
            setattr(st, attr, getattr(real, attr))
    st.__getattr__ = lambda name: getattr(real, name)  # type: ignore[method-assign]

    st.stop = MagicMock(name="stop", side_effect=_AuthGateReached())
    st.session_state = {}
    st.secrets = MagicMock(name="secrets")
    st.secrets.get.side_effect = (
        lambda key, default=None: "smoke-test-password"
        if key == "APP_PASSWORD" else default
    )
    st.button = MagicMock(name="button", return_value=False)
    st.text_input = MagicMock(name="text_input", return_value="")
    st.set_page_config = MagicMock(name="set_page_config")
    st.markdown = MagicMock(name="markdown")
    st.error = MagicMock(name="error")
    st.warning = MagicMock(name="warning")
    # Cache decorators must pass the function through untouched.
    st.cache_resource = lambda fn=None, **kw: fn if fn is not None else (lambda f: f)
    st.cache_data = lambda fn=None, **kw: fn if fn is not None else (lambda f: f)
    return st


def _repo_modules_holding_streamlit() -> list[ModuleType]:
    """Already-imported repo modules with a module-level ``st`` reference.

    ``require_auth`` and ``inject_base_styles`` resolve ``st`` through their own
    module globals, so swapping ``sys.modules['streamlit']`` alone would miss
    them. The held value may be the real module *or* another test's MagicMock,
    and both must be redirected — checking for a module type alone would skip
    exactly the poisoned case this needs to handle.
    """
    root = str(ROOT)
    found = []
    for module in list(sys.modules.values()):
        file = getattr(module, "__file__", None)
        if not file or not file.startswith(root) or "/site-packages/" in file:
            continue
        held = getattr(module, "st", None)
        is_streamlit = (
            isinstance(held, ModuleType) and getattr(held, "__name__", "") == "streamlit"
        )
        if is_streamlit or isinstance(held, MagicMock):
            found.append(module)
    return found


def execution_problem(path: Path) -> str | None:
    """Execute `path` until its auth gate. Return a diagnostic, or None if clean.

    Success means the script reached ``require_auth()``'s ``st.stop()`` — every
    import ran for real, and the run halted exactly where Streamlit Cloud halts
    it for a signed-out visitor, before any database access.
    """
    with _genuine_streamlit() as real:
        gated = _gated_streamlit(real)
        patched = {mod: mod.st for mod in _repo_modules_holding_streamlit()}

        sys.modules["streamlit"] = gated
        for module in patched:
            module.st = gated
        try:
            namespace = {"__name__": "__hades_page_smoke__", "__file__": str(path)}
            exec(compile(path.read_text(), str(path), "exec"), namespace)
        except _AuthGateReached:
            return None
        except BaseException as exc:  # noqa: BLE001 — the diagnostic is the point
            return f"{type(exc).__name__}: {exc}"
        else:
            return (
                "ran to completion without reaching require_auth()'s st.stop() — "
                "the page is missing its auth gate, or the gate no longer halts"
            )
        finally:
            for module, previous in patched.items():
                module.st = previous


# --------------------------------------------------------------------------
# Negative tests — a deliberately broken page MUST be caught, with a
# diagnostic that names the cause.
# --------------------------------------------------------------------------

def test_static_catches_syntax_error(tmp_path):
    page = tmp_path / "broken_syntax.py"
    page.write_text("import streamlit as st\n\nif True\n    st.write('oops')\n")

    problems = static_problems(page)

    assert problems, "syntax error went undetected"
    assert any("SyntaxError" in p for p in problems), problems


def test_static_catches_unresolvable_import(tmp_path):
    page = tmp_path / "broken_import.py"
    page.write_text("import definitely_not_a_real_module_xyz\n")

    problems = static_problems(page)

    assert problems, "unresolvable import went undetected"
    assert any("definitely_not_a_real_module_xyz" in p for p in problems), problems


def test_static_catches_missing_name_in_real_module(tmp_path):
    """The incomplete-refactor case: the module exists, the symbol no longer does."""
    page = tmp_path / "broken_from_import.py"
    page.write_text("from ui_components import totally_missing_helper\n")

    problems = static_problems(page)

    assert problems, "missing imported name went undetected"
    assert any("totally_missing_helper" in p for p in problems), problems


def test_static_catches_module_level_name_error(tmp_path):
    page = tmp_path / "broken_name.py"
    page.write_text("import streamlit as st\n\nvalue = undefined_thing + 1\n")

    problems = static_problems(page)

    assert problems, "module-level NameError went undetected"
    assert any("undefined_thing" in p for p in problems), problems


def test_static_passes_a_clean_page(tmp_path):
    """Guards the other direction: no false positives on ordinary page code."""
    page = tmp_path / "clean.py"
    page.write_text(
        "import streamlit as st\n"
        "from ui_components import inject_base_styles\n"
        "\n"
        "TITLE = 'Clean'\n"
        "\n"
        "@st.cache_data\n"
        "def helper(rows):\n"
        "    return [r for r in rows if r]\n"
        "\n"
        "inject_base_styles()\n"
        "for item in helper([TITLE]):\n"
        "    st.write(item)\n"
    )

    assert static_problems(page) == []


def test_execution_catches_broken_prologue(tmp_path):
    """A page that raises before the auth gate must be reported."""
    page = tmp_path / "explodes.py"
    page.write_text(
        "import streamlit as st\n"
        "raise RuntimeError('boom in prologue')\n"
    )

    problem = execution_problem(page)

    assert problem is not None, "prologue exception went undetected"
    assert "boom in prologue" in problem, problem


def test_execution_reports_page_that_never_reaches_auth_gate(tmp_path):
    """A page missing require_auth() runs past the gate — that itself is a defect."""
    page = tmp_path / "no_gate.py"
    page.write_text("import streamlit as st\nst.write('ungated')\n")

    problem = execution_problem(page)

    assert problem is not None, "page without an auth gate went undetected"
    assert "require_auth" in problem, problem


# --------------------------------------------------------------------------
# The real pages
# --------------------------------------------------------------------------

def test_no_test_module_replaces_streamlit_globally():
    """Guard the convention that HADES-w1k established.

    Assigning ``sys.modules["streamlit"]`` at test-module import time is never
    undone, so whichever module pytest imports first wins the entire session:
    every repo module imported afterwards binds THAT mock as its ``st``. Fifteen
    modules used to do it, and it broke this file in two ways — a MagicMock is
    not a package, so ``import streamlit.components.v1`` raised, and a mocked
    ``st.stop()`` does not halt, so pages ran past the auth gate into DB code.

    Thirteen of those mocks turned out to be unnecessary (streamlit is a real
    installed dependency) and were deleted; the one genuine stub, in
    test_ui_components.py, now patches that module's own ``st`` global via
    monkeypatch, which is restored per test.

    Stub streamlit by patching the module under test, not the interpreter.
    """
    def _is_sys_modules(node) -> bool:
        return isinstance(node, ast.Attribute) and node.attr == "modules"

    offenders = []
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:  # module level only — a fixture body is fine
            # sys.modules["streamlit"] = ...
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and _is_sys_modules(target.value)
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value == "streamlit"
                    ):
                        offenders.append(f"{path.name}:{node.lineno}")
            # sys.modules.setdefault("streamlit", ...) — only a no-op if
            # streamlit happens to be imported already, which is not a
            # guarantee any test may rely on.
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                func = node.value.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "setdefault"
                    and _is_sys_modules(func.value)
                    and node.value.args
                    and isinstance(node.value.args[0], ast.Constant)
                    and node.value.args[0].value == "streamlit"
                ):
                    offenders.append(f"{path.name}:{node.lineno} (setdefault)")

    assert not offenders, (
        "These test modules replace sys.modules['streamlit'] at import time, "
        "which leaks into every module imported afterwards:\n"
        + "\n".join(f"  - {o}" for o in offenders)
        + "\n\nPatch the module under test instead (monkeypatch.setattr("
        "the_module, 'st', mock)), so the stub is scoped and restored."
    )


def test_pages_directory_is_discovered():
    pages = _iter_pages()
    assert len(pages) >= 10, f"expected the full page set, found {len(pages)}"


@pytest.mark.parametrize("page", _iter_pages(), ids=lambda p: p.name)
def test_page_module_level_code_is_sound(page):
    problems = static_problems(page)
    assert not problems, f"{page.name} has module-level defects:\n" + "\n".join(
        f"  - {p}" for p in problems
    )


@pytest.mark.parametrize("page", _iter_pages(), ids=lambda p: p.name)
def test_page_executes_to_auth_gate(page):
    problem = execution_problem(page)
    assert problem is None, f"{page.name} fails before its auth gate:\n  {problem}"
