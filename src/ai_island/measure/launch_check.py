"""The ``launch-check`` command: three safety checks before the real run.

The checks read the files as they are on disk (the raw ``run.toml`` and ``git status``), not the
loaded settings, so a default value can never hide a missing line.
"""

from __future__ import annotations

import math
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LaunchCheck:
    name: str
    passed: bool
    detail: str


def _config_clean(root: Path, config_dir: Path) -> LaunchCheck:
    name = "config_clean"
    try:
        shown = config_dir.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        shown = str(config_dir)
    try:
        done = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", shown + "/"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return LaunchCheck(name, False, f"git could not be run: {exc}")
    if done.returncode != 0:
        reason = (done.stderr or "").strip().splitlines()
        return LaunchCheck(
            name, False, "git status failed: " + (reason[0] if reason else "not a git folder")
        )
    changed = [line for line in done.stdout.splitlines() if line.strip()]
    if changed:
        return LaunchCheck(
            name, False, f"{len(changed)} uncommitted change(s) in {shown}/: {changed[0].strip()}"
        )
    return LaunchCheck(name, True, f"no uncommitted changes in {shown}/")


def _run_toml(config_dir: Path) -> tuple[dict | None, str]:
    path = config_dir / "run.toml"
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh), ""
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return None, f"{path.name} could not be read: {exc}"


def _spend_cap(raw: dict | None, problem: str) -> LaunchCheck:
    name = "spend_cap"
    if raw is None:
        return LaunchCheck(name, False, problem)
    cap = raw.get("spend_cap_usd")
    if cap is None:
        return LaunchCheck(name, False, "run.toml has no spend_cap_usd")
    if isinstance(cap, bool) or not isinstance(cap, (int, float)):
        return LaunchCheck(name, False, f"spend_cap_usd must be a number, not {cap!r}")
    if not math.isfinite(cap) or cap <= 0:
        return LaunchCheck(name, False, f"spend_cap_usd must be above 0, it is {cap!r}")
    return LaunchCheck(name, True, f"spend_cap_usd is {cap:g}")


def _seed(raw: dict | None, problem: str) -> LaunchCheck:
    name = "seed"
    if raw is None:
        return LaunchCheck(name, False, problem)
    seed = raw.get("seed")
    if seed is None:
        return LaunchCheck(name, False, "run.toml has no seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        return LaunchCheck(name, False, f"seed must be a whole number, not {seed!r}")
    return LaunchCheck(name, True, f"seed is {seed}")


def launch_checks(root: Path, config_dir: Path) -> list[LaunchCheck]:
    """config_clean, spend_cap and seed, in that order."""
    root = Path(root)
    config_dir = Path(config_dir)
    raw, problem = _run_toml(config_dir)
    return [_config_clean(root, config_dir), _spend_cap(raw, problem), _seed(raw, problem)]


def format_launch_checks(checks: list[LaunchCheck]) -> str:
    """One "[PASS] name: detail" / "[FAIL] name: detail" line per check."""
    return "\n".join(f"[{'PASS' if c.passed else 'FAIL'}] {c.name}: {c.detail}" for c in checks)


def run_launch_check(root: Path, config_dir: Path) -> int:
    """Print the checks and return the exit code: 0 when all pass, else 1."""
    checks = launch_checks(root, config_dir)
    print(format_launch_checks(checks))
    if all(c.passed for c in checks):
        print("Ready: all launch checks passed.")
        return 0
    print("Not ready: fix the lines marked FAIL, then run launch-check again.")
    return 1
