"""Session history, logs, and rollback snapshots."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SessionRecord:  # pylint: disable=too-many-instance-attributes
    """Stored metadata for a CodePilot session."""

    session_id: str
    description: str
    mode: str
    status: str
    workdir: str
    created_at: str
    risk_level: str
    commands: list[str]


class SessionStore:
    """Filesystem-backed store for session history and logs."""

    def __init__(self, storage_dir: str | Path) -> None:
        self.storage_dir = Path(storage_dir)
        self.history_dir = self.storage_dir / "history"
        self.logs_dir = self.storage_dir / "logs"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def save_session(self, record: SessionRecord) -> None:
        path = self.history_dir / f"{record.session_id}.json"
        path.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2), encoding="utf-8")

    def list_sessions(self) -> list[SessionRecord]:
        records: list[SessionRecord] = []
        for path in sorted(self.history_dir.glob("*.json"), reverse=True):
            payload = json.loads(path.read_text(encoding="utf-8"))
            records.append(SessionRecord(**payload))
        return records

    def append_log(self, session_id: str, line: str) -> None:
        path = self.logs_dir / f"{session_id}.log"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")

    def read_log(self, session_id: str) -> list[str]:
        path = self.logs_dir / f"{session_id}.log"
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8").splitlines()


class WorkspaceSnapshotManager:
    """Create and restore lightweight workspace snapshots."""

    def __init__(self, storage_dir: str | Path) -> None:
        self.snapshots_dir = Path(storage_dir) / "snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def create_snapshot(self, paths: list[str | Path]) -> str:
        snapshot_id = datetime.now(tz=UTC).strftime("snapshot-%Y%m%d%H%M%S%f")
        snapshot_dir = self.snapshots_dir / snapshot_id
        snapshot_dir.mkdir(parents=True, exist_ok=False)
        manifest: list[dict[str, str]] = []
        for raw_path in paths:
            source = Path(raw_path).resolve()
            if not source.exists() or not source.is_file():
                continue
            destination = snapshot_dir / f"file-{len(manifest)}"
            shutil.copy2(source, destination)
            manifest.append({"original": str(source), "copy": destination.name})
        (snapshot_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return snapshot_id

    def restore_snapshot(self, snapshot_id: str) -> list[str]:
        snapshot_dir = self.snapshots_dir / snapshot_id
        manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
        restored_files: list[str] = []
        for item in manifest:
            original = Path(item["original"])
            copied_text = (snapshot_dir / item["copy"]).read_text(encoding="utf-8")
            original.write_text(copied_text, encoding="utf-8")
            restored_files.append(str(original))
        return restored_files
