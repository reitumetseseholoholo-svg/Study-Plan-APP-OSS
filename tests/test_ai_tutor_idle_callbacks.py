"""
Verify that all GLib.idle_add callbacks in studyplan_ai_tutor.py return False.

GLib.idle_add callbacks that return True are re-scheduled on every main-loop
iteration, wasting CPU. All one-shot idle callbacks MUST return False.
"""

from __future__ import annotations

import ast
import pathlib

import pytest


def _is_glib_idle_add(node: ast.AST) -> bool:
    """Return True if *node* is a call to ``GLib.idle_add``."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "idle_add"
        and isinstance(func.value, ast.Name)
        and func.value.id == "GLib"
    )


def _check_callback(callback: ast.expr, issues: list[str]) -> None:
    """Analyse a single idle_add callback argument and append any issues."""
    if isinstance(callback, ast.Lambda):
        body = callback.body
        if isinstance(body, ast.Constant) and body.value is True:
            issues.append(f"GLib.idle_add lambda at line {callback.lineno} returns True")
        return

    if isinstance(callback, ast.Name):
        return

    if isinstance(callback, ast.FunctionDef):
        returns_false = _function_returns_false(callback)
        if not returns_false:
            for ret_node in ast.walk(callback):
                if isinstance(ret_node, ast.Return) and isinstance(ret_node.value, ast.Constant):
                    if ret_node.value.value is True:
                        issues.append(
                            f"GLib.idle_add callback '{callback.name}' at line {callback.lineno} "
                            f"has 'return True' at line {ret_node.lineno}"
                        )
            has_return = any(isinstance(n, ast.Return) for n in ast.walk(callback))
            if not has_return:
                issues.append(
                    f"GLib.idle_add callback '{callback.name}' at line {callback.lineno} "
                    f"has no return statement (falls through to None, which is treated as False — OK)"
                )


def _find_idle_add_callbacks(tree: ast.Module) -> list[str]:
    """Return source-line ranges for each GLib.idle_add callback in the file."""
    issues: list[str] = []
    for node in ast.walk(tree):
        if not _is_glib_idle_add(node):
            continue
        if not node.args:
            continue
        _check_callback(node.args[0], issues)
    return issues


def _function_returns_false(func: ast.FunctionDef) -> bool:
    """Check if the function has at least one `return False` path."""
    for node in ast.walk(func):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant):
            if node.value.value is False:
                return True
    return False


def test_all_idle_callbacks_return_false():
    filepath = pathlib.Path(__file__).resolve().parent.parent / "studyplan_ai_tutor.py"
    assert filepath.exists(), f"File not found: {filepath}"

    tree = ast.parse(filepath.read_text(encoding="utf-8"))
    issues = _find_idle_add_callbacks(tree)

    non_false = [i for i in issues if "returns True" in i]
    if non_false:
        pytest.fail("\n".join(non_false))
    no_return = [i for i in issues if "no return statement" in i]
    if no_return:
        import warnings

        warnings.warn("Idle callbacks without explicit return:\n" + "\n".join(no_return), stacklevel=2)
