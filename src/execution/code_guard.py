"""Static AST guard for LLM-generated pandas analysis code.

This is the first of two independent defenses (see `spec/architecture.md` ->
"The Raw-Data-Never-Leaves-The-Machine Boundary") that stop generated code from
reading the network or the filesystem before it ever runs: this module rejects
dangerous constructs statically; `execution/sandbox.py` additionally runs the
code with a restricted builtins namespace as defense-in-depth.
"""
import ast

# Only pure, non-I/O, non-network-capable modules may be imported by generated code.
ALLOWED_MODULES = {"pandas", "numpy", "math", "statistics", "datetime", "re", "json", "collections"}

# Names/attributes that must never appear anywhere in generated code, whether as a
# bare name, an attribute access, or a call target.
FORBIDDEN_NAMES = {
    "os", "sys", "socket", "subprocess", "shutil", "pathlib", "requests", "urllib",
    "http", "ftplib", "__import__", "eval", "exec", "compile", "open", "input",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
}


class UnsafeCodeError(Exception):
    """Raised when generated code fails the static safety guard."""


def guard_code(code: str) -> None:
    """Raise UnsafeCodeError if `code` contains any disallowed construct.

    Returns None (does not execute anything) when the code passes.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise UnsafeCodeError(f"Generated code has a syntax error: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in ALLOWED_MODULES:
                    raise UnsafeCodeError(f"Import of module '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top not in ALLOWED_MODULES:
                raise UnsafeCodeError(f"Import of module '{node.module}' is not allowed")
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES:
                raise UnsafeCodeError(f"Use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_NAMES:
                raise UnsafeCodeError(f"Access to attribute '{node.attr}' is not allowed")
            if node.attr.startswith("__") and node.attr.endswith("__"):
                raise UnsafeCodeError(f"Dunder attribute access '{node.attr}' is not allowed")
        elif isinstance(node, ast.Call):
            func = node.func
            fname = getattr(func, "id", None) or getattr(func, "attr", None)
            if fname in {"eval", "exec", "compile", "__import__", "open", "input"}:
                raise UnsafeCodeError(f"Call to '{fname}' is not allowed")
