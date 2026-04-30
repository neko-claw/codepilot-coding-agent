#!/usr/bin/env python3
"""Bootstrap a fresh CodePilot checkout into a working virtual environment."""

from __future__ import annotations

import argparse
import subprocess
import sys
import venv
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VENV_DIR = PROJECT_ROOT / ".venv"
PROFILE_TO_REQUIREMENTS = {
    "runtime": PROJECT_ROOT / "requirements" / "runtime.txt",
    "dev": PROJECT_ROOT / "requirements" / "dev.txt",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bootstrap.py")
    parser.add_argument(
        "--profile",
        choices=tuple(PROFILE_TO_REQUIREMENTS),
        default="dev",
        help="Installation profile to apply",
    )
    parser.add_argument(
        "--venv",
        type=Path,
        default=DEFAULT_VENV_DIR,
        help="Target virtual environment directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the bootstrap steps without executing them",
    )
    return parser


def bootstrap(profile: str, venv_dir: Path, *, dry_run: bool = False) -> list[str]:
    requirements = PROFILE_TO_REQUIREMENTS[profile]
    python_path = _venv_python_path(venv_dir)
    commands = [
        f"python -m venv {venv_dir}",
        f"{python_path} -m pip install --upgrade pip setuptools wheel",
        f"{python_path} -m pip install -r {requirements}",
    ]
    if dry_run:
        return commands
    if not venv_dir.exists():
        venv.EnvBuilder(with_pip=True, clear=False).create(venv_dir)
    _run([str(python_path), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    _run([str(python_path), "-m", "pip", "install", "-r", str(requirements)])
    return commands


def _venv_python_path(venv_dir: Path) -> Path:
    bin_dir = "Scripts" if sys.platform == "win32" else "bin"
    return venv_dir / bin_dir / ("python.exe" if sys.platform == "win32" else "python")


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    steps = bootstrap(args.profile, args.venv, dry_run=args.dry_run)
    for step in steps:
        print(step)
    if args.dry_run:
        return 0
    print(f"bootstrap complete: profile={args.profile} venv={args.venv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
