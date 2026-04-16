"""CLI entrypoint for CodePilot."""

from __future__ import annotations

import argparse
from pathlib import Path

from codepilot.core.config import load_config
from codepilot.integrations.deepseek import DeepSeekPlannerClient
from codepilot.runtime.session import run_task_session
from codepilot.storage.session_store import SessionStore, WorkspaceSnapshotManager


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="codepilot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a CodePilot session")
    run_parser.add_argument("description", help="Natural-language task description")
    run_parser.add_argument("--workdir", default=".")
    run_parser.add_argument("--mode", choices=("plan", "auto"), default="plan")

    history_parser = subparsers.add_parser("history", help="List previous sessions")
    history_parser.add_argument("--workdir", default=".")

    restore_parser = subparsers.add_parser("restore", help="Restore a workspace snapshot")
    restore_parser.add_argument("snapshot_id")
    restore_parser.add_argument("--workdir", default=".")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI command."""
    args = build_parser().parse_args(argv)
    workdir = Path(args.workdir).resolve()
    config = load_config(workdir)

    if args.command == "run":
        planner_client = None
        if config.deepseek_enabled:
            planner_client = DeepSeekPlannerClient(
                api_key=config.deepseek_api_key or "",
                base_url=config.deepseek_base_url,
                model=config.deepseek_model,
            )
        result = run_task_session(
            description=args.description,
            workdir=workdir,
            mode=args.mode,
            planner_client=planner_client,
            storage_dir=config.storage_dir,
        )
        print(f"session_id: {result.session_id}")
        print(f"status: {result.plan.status}")
        print(f"summary: {result.plan.summary}")
        print("steps:")
        for step in result.plan.steps:
            print(f"- {step}")
        print(f"risk: {result.plan.risk.level} ({result.plan.risk.reason})")
        if result.github_snapshot is not None:
            print(f"github: {result.github_snapshot.full_name}")
        for command_result in result.command_results:
            print(f"command: {command_result.command} => {command_result.exit_code}")
        if result.rollback_snapshot_id:
            print(f"rollback_snapshot: {result.rollback_snapshot_id}")
        return 0

    if args.command == "history":
        store = SessionStore(config.storage_dir)
        for record in store.list_sessions():
            print(f"{record.session_id}\t{record.status}\t{record.description}")
        return 0

    snapshot_manager = WorkspaceSnapshotManager(config.storage_dir)
    restored_files = snapshot_manager.restore_snapshot(args.snapshot_id)
    print(f"restored {len(restored_files)} files")
    for path in restored_files:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
