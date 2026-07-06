#!/usr/bin/env python3
"""
agent.py — verify local setup or run the agent

Usage:
  python agent.py        # verify all tools, .env, deps, and tests
  python agent.py --run  # verify + build frontend + start server
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Enable ANSI escape codes on Windows (no-op on Unix)
if sys.platform == "win32":
    os.system("")

# ── colours ──────────────────────────────────────────────────────────────────
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg: str)     -> None: print(f"  {GREEN}✓{RESET}  {msg}")
def fail(msg: str)   -> None: print(f"  {RED}✗{RESET}  {msg}"); _failures.append(msg)
def warn(msg: str)   -> None: print(f"  {YELLOW}!{RESET}  {msg}")
def info(msg: str)   -> None: print(f"  {CYAN}→{RESET}  {msg}")
def header(msg: str) -> None: print(f"\n{BOLD}{msg}{RESET}")

_failures: list[str] = []


# ── helpers ───────────────────────────────────────────────────────────────────
def run(cmd: list[str], *, cwd: Path = ROOT, capture: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True)
    except OSError:
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="")

def which(name: str) -> bool:
    return shutil.which(name) is not None

def cmd_version(cmd: list[str]) -> str | None:
    r = run(cmd)
    return r.stdout.strip().splitlines()[0] if r.returncode == 0 else None


# ── checks ────────────────────────────────────────────────────────────────────
def check_tools() -> None:
    header("Tools")

    v = cmd_version(["git", "--version"])
    if v: ok(v)
    else: fail("git not found — install git")

    vi = sys.version_info
    if vi >= (3, 11):
        ok(f"Python {vi.major}.{vi.minor}.{vi.micro}")
    else:
        fail(f"Python {vi.major}.{vi.minor} found — need 3.11+")

    v = cmd_version(["uv", "--version"])
    if v: ok(v)
    elif sys.platform == "win32":
        fail('uv not found — install: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"')
    else:
        fail("uv not found — install: curl -LsSf https://astral.sh/uv/install.sh | sh")

    v = cmd_version(["claude", "--version"])
    if v: ok(v)
    else: fail("claude CLI not found — install Claude Code")

    if which("node"):
        nv = cmd_version(["node", "--version"]) or ""
        try:
            major = int(nv.lstrip("v").split(".")[0])
            if major >= 20:
                ok(f"node {nv}")
            else:
                fail(f"node {nv} found — need 20+; install from https://nodejs.org/")
        except ValueError:
            warn(f"could not parse node version: {nv}")
        v = cmd_version(["pnpm", "--version"])
        if v: ok(f"pnpm {v}")
        else: warn("pnpm not found — needed for frontend build: npm install -g pnpm")
    else:
        warn("node not found — needed for frontend build only; API works without it")


def check_env() -> None:
    header("Environment (.env)")

    # This tool is fully local: no API keys, no database. .env is optional
    # (all settings have defaults); it needs no provider or database entries.
    env = ROOT / ".env"
    if env.exists():
        ok(".env present (optional — no API keys required)")
    else:
        ok("no .env needed — defaults apply (no API keys, no database)")


def check_python_env() -> None:
    header("Python environment")

    if not (ROOT / ".venv").exists():
        fail(".venv not found — run: uv sync")
        return
    ok(".venv present")

    r = run(["uv", "run", "python", "-c", "import fastapi, langgraph, pandas, openpyxl, rapidfuzz"])
    if r.returncode == 0:
        ok("core packages importable (fastapi, langgraph, pandas, openpyxl, rapidfuzz)")
    else:
        fail("missing packages — run: uv sync")


def check_tests() -> None:
    header("Unit tests")

    r = run(["uv", "run", "pytest", "tests/unit/", "-q", "--tb=short"])
    if r.returncode == 0:
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        ok(lines[-1] if lines else "tests passed")
    else:
        fail("unit tests failed:\n" + r.stdout[-800:])


def check_frontend() -> None:
    header("Frontend")

    fe = ROOT / "frontend"
    if not fe.exists():
        warn("frontend/ not found — skipping")
        return

    if not (fe / "node_modules").exists():
        warn("node_modules missing — run: cd frontend && pnpm install")
        return
    ok("node_modules present")

    if (fe / "out").exists():
        ok("frontend/out/ built — will serve UI at /app/")
    else:
        warn("frontend not built — will build on next run")


# ── run ───────────────────────────────────────────────────────────────────────
def do_run() -> None:
    # No database and no migrations — the tool is stateless.

    # frontend build
    fe = ROOT / "frontend"
    if which("pnpm") and fe.exists():
        info("building frontend...")
        r = run(["pnpm", "build"], cwd=fe, capture=False)
        if r.returncode != 0:
            print(f"\n{RED}frontend build failed.{RESET}")
            sys.exit(1)

    # start
    print(f"\n{GREEN}{BOLD}Starting…{RESET}")
    print(f"  {CYAN}http://localhost:8001{RESET}       (API)")
    if (ROOT / "frontend" / "out").exists():
        print(f"  {CYAN}http://localhost:8001/app/{RESET}  (UI)")
    print()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        ["uv", "run", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8001"],
        env=env,
    )
    sys.exit(result.returncode)


# ── main ──────────────────────────────────────────────────────────────────────
def do_check() -> None:
    print(f"\n{BOLD}=== Setup Check ==={RESET}")
    check_tools()
    check_env()
    check_python_env()
    check_tests()
    check_frontend()
    print()
    if _failures:
        print(f"{RED}{BOLD}{len(_failures)} issue(s) found — fix before running.{RESET}")
        for f in _failures:
            print(f"  {RED}✗{RESET}  {f}")
        sys.exit(1)
    else:
        print(f"{GREEN}{BOLD}All checks passed. Run: python agent.py --run{RESET}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify local setup or run the agent")
    parser.add_argument("--run", action="store_true", help="build frontend and start server")
    args = parser.parse_args()

    if args.run:
        do_run()
    else:
        do_check()


if __name__ == "__main__":
    main()
