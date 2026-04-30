from __future__ import annotations

from pathlib import Path

from codepilot.executor.shell import PersistentShellSession


def test_persistent_shell_session_tracks_cd_commands(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    session = PersistentShellSession(workdir=tmp_path)

    result = session.run("cd nested && false")

    assert result.exit_code != 0
    assert session.cwd == nested.resolve()
