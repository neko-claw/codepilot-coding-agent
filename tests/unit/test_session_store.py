from pathlib import Path

from codepilot.storage.session_store import SessionRecord, SessionStore, WorkspaceSnapshotManager


def test_session_store_persists_history_and_logs(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / ".codepilot")
    record = SessionRecord(
        session_id="session-1",
        description="审查质量门禁",
        mode="auto",
        status="completed",
        workdir="/repo",
        created_at="2026-04-16T22:00:00Z",
        risk_level="low",
        commands=["pytest -q"],
    )

    store.save_session(record)
    store.append_log("session-1", "pytest -q => exit 0")

    history = store.list_sessions()
    assert history[0].session_id == "session-1"
    assert store.read_log("session-1") == ["pytest -q => exit 0"]


def test_workspace_snapshot_manager_restores_original_content(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("before\n", encoding="utf-8")
    manager = WorkspaceSnapshotManager(tmp_path / ".codepilot")

    snapshot_id = manager.create_snapshot([target])
    target.write_text("after\n", encoding="utf-8")
    restored_files = manager.restore_snapshot(snapshot_id)

    assert restored_files == [str(target)]
    assert target.read_text(encoding="utf-8") == "before\n"
