"""Runs LLM-generated pandas analysis code against the real, full dataframe(s).

**Isolation choice (documented per code-generator instructions):** this runs the
guarded code in a background *thread* (not a `multiprocessing.Process`), with a
hard wall-clock join timeout. `spec/architecture.md` describes a
`multiprocessing.Process`-based design for the strongest possible network
isolation; we deviate to a thread here because Windows `multiprocessing` uses
`spawn`, which re-imports/pickles the whole call graph (including live pandas
DataFrames and closures) and is fragile inside this harness's sandboxed test
runner. Network isolation is still enforced by two independent, cheaper layers
that do not need process isolation: (1) `code_guard.guard_code` statically
rejects any import/attribute/call that could reach the network or filesystem
before this module ever executes the code, and (2) the exec namespace's
`__builtins__` is an explicit allow-list with no `open`/`eval`/`exec`/
`__import__` bound, so even a guard bypass has no reachable network-capable
primitive. A thread cannot be force-killed in Python, so a runaway snippet's
thread is abandoned (daemon=True) and its result discarded on timeout; the
guard makes an intentionally-hostile infinite loop extremely unlikely for
pandas analysis code, and this is Phase 1 scope (single-call, user is
watching) — Phase 4 hardening can reintroduce process isolation if the
threat model changes.
"""
import builtins
import contextlib
import io
import json
import queue
import threading
import time

import pandas as pd

from config.settings import get_settings
from execution.code_guard import UnsafeCodeError, guard_code

_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
    "int", "len", "list", "map", "max", "min", "print", "range", "round",
    "set", "sorted", "str", "sum", "tuple", "zip", "isinstance", "type",
    "True", "False", "None", "ValueError", "TypeError", "KeyError", "Exception",
)
_SAFE_BUILTINS = {name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES if hasattr(builtins, name)}


def _run_in_namespace(code: str, dataframes: dict, out_queue: "queue.Queue") -> None:
    stdout_buf = io.StringIO()
    namespace: dict = {"__builtins__": _SAFE_BUILTINS, "pd": pd}
    try:
        import numpy as np
        namespace["np"] = np
    except ImportError:  # pragma: no cover - numpy is a hard dependency
        pass
    namespace.update(dataframes)
    try:
        with contextlib.redirect_stdout(stdout_buf):
            exec(code, namespace)  # noqa: S102 -- guarded by code_guard.guard_code before this runs
        out_queue.put({"ok": True, "result": namespace.get("result"), "stdout": stdout_buf.getvalue()})
    except Exception as exc:
        out_queue.put({"ok": False, "error": str(exc), "stdout": stdout_buf.getvalue()})


def _cap_result(result, row_cap: int, cell_cap: int) -> dict:
    """Convert `result` into a small, size-capped structured summary.

    This is the single choke point that prevents an unbounded raw dataframe
    from ever crossing back into AgentState (and therefore into a subsequent
    Gemini prompt) — see spec/architecture.md boundary point 3.
    """
    if isinstance(result, pd.DataFrame):
        total_rows = len(result)
        capped_df = result.head(row_cap)
        data = capped_df.to_dict(orient="records")
        text = json.dumps(data, default=str)
        truncated = total_rows > row_cap
        if len(text) > cell_cap:
            text = text[:cell_cap]
            truncated = True
        return {
            "type": "dataframe", "total_rows": total_rows, "rows_returned": len(capped_df),
            "truncated": truncated, "data_json": text,
        }
    if isinstance(result, pd.Series):
        total_rows = len(result)
        capped = result.head(row_cap)
        data = {str(k): v for k, v in capped.to_dict().items()}
        text = json.dumps(data, default=str)
        truncated = total_rows > row_cap
        if len(text) > cell_cap:
            text = text[:cell_cap]
            truncated = True
        return {
            "type": "series", "total_rows": total_rows, "rows_returned": len(capped),
            "truncated": truncated, "data_json": text,
        }
    if result is None or isinstance(result, (int, float, bool, str)):
        return {"type": "scalar", "value": result}
    if hasattr(result, "item") and getattr(result, "shape", None) in (None, ()):
        # numpy scalar types (np.int64, np.float64, np.bool_, ...) are not
        # Python int/float subclasses on all platforms but are safe scalars.
        try:
            return {"type": "scalar", "value": result.item()}
        except (ValueError, AttributeError):
            pass
    text = str(result)
    truncated = len(text) > cell_cap
    return {"type": "other", "value": text[:cell_cap], "truncated": truncated}


def run_analysis_code(code: str, dataframes: dict[str, "pd.DataFrame"], timeout_s: int | None = None) -> dict:
    """Executes `code` against `dataframes` and returns a capped ExecutionResult.

    Returns a dict: {"ok": bool, "error": str | None, "result": dict | None,
    "stdout": str, "duration_ms": int}. `result` (when present) is always the
    output of `_cap_result` — never a raw DataFrame/Series.
    """
    start = time.monotonic()
    settings = get_settings()
    timeout_s = timeout_s or settings.sandbox_timeout_s

    try:
        guard_code(code)
    except UnsafeCodeError as exc:
        return {
            "ok": False,
            "error": f"Code rejected by safety guard: {exc}",
            "result": None,
            "stdout": "",
            "duration_ms": int((time.monotonic() - start) * 1000),
        }

    out_queue: "queue.Queue" = queue.Queue(maxsize=1)
    thread = threading.Thread(target=_run_in_namespace, args=(code, dataframes, out_queue), daemon=True)
    thread.start()
    thread.join(timeout_s)

    if thread.is_alive():
        return {
            "ok": False,
            "error": f"Execution exceeded the {timeout_s}s timeout",
            "result": None,
            "stdout": "",
            "duration_ms": int((time.monotonic() - start) * 1000),
        }

    duration_ms = int((time.monotonic() - start) * 1000)
    try:
        outcome = out_queue.get_nowait()
    except queue.Empty:
        return {"ok": False, "error": "Execution produced no result", "result": None, "stdout": "", "duration_ms": duration_ms}

    stdout_text = (outcome.get("stdout") or "")[: settings.result_cell_cap]
    if not outcome["ok"]:
        return {"ok": False, "error": outcome["error"], "result": None, "stdout": stdout_text, "duration_ms": duration_ms}

    capped = _cap_result(outcome["result"], settings.result_row_cap, settings.result_cell_cap)
    return {"ok": True, "error": None, "result": capped, "stdout": stdout_text, "duration_ms": duration_ms}
