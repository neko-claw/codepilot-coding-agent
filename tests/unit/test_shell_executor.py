from pathlib import Path

from codepilot.executor.shell import PersistentShellSession


def test_persistent_shell_session_keeps_workdir_between_commands(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    session = PersistentShellSession(workdir=tmp_path)

    change_result = session.run(f"cd {nested} && pwd")
    pwd_result = session.run("pwd")

    assert change_result.exit_code == 0
    assert pwd_result.stdout.strip() == str(nested)


def test_shell_session_truncates_long_output(tmp_path: Path) -> None:
    session = PersistentShellSession(workdir=tmp_path, max_output_lines=6)

    result = session.run("python - <<'PY'\nfor index in range(12):\n    print(index)\nPY")

    assert result.exit_code == 0
    assert "[output truncated" in result.stdout
    assert "0" in result.stdout
    assert "11" in result.stdout
