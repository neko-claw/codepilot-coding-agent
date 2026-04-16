from pathlib import Path

from codepilot.cli import main


class _FakeSessionResult:
    def __init__(self) -> None:
        self.plan = type(
            "Plan",
            (),
            {
                "status": "ready_to_execute",
                "summary": "generated plan",
                "steps": ("Read files", "Run tests"),
                "candidate_commands": ["pytest -q"],
                "risk": type("Risk", (), {"level": "low", "reason": "safe"})(),
            },
        )()
        self.github_snapshot = None
        self.command_results = []
        self.session_id = "session-1"
        self.rollback_snapshot_id = None


class _FakeStore:
    def list_sessions(self):
        record = type(
            "Record",
            (),
            {"session_id": "session-1", "description": "demo", "status": "completed"},
        )()
        return [record]


def test_cli_run_command_prints_plan_summary(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr("codepilot.cli.run_task_session", lambda **kwargs: _FakeSessionResult())

    exit_code = main([
        "run",
        "--workdir",
        str(tmp_path),
        "--mode",
        "plan",
        "为项目补充计划",
    ])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "generated plan" in output
    assert "ready_to_execute" in output


def test_cli_history_command_lists_sessions(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr("codepilot.cli.SessionStore", lambda storage_dir: _FakeStore())
    monkeypatch.setattr(
        "codepilot.cli.load_config",
        lambda project_root: type(
            "Config",
            (),
            {"storage_dir": tmp_path / ".codepilot"},
        )(),
    )

    exit_code = main(["history", "--workdir", str(tmp_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "session-1" in output
    assert "demo" in output
