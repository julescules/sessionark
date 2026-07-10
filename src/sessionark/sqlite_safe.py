from __future__ import annotations

import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .models import SessionArkError


@dataclass(frozen=True, slots=True)
class SQLiteCaptureResult:
    path: Path
    capture_mode: str
    warning: str | None
    source_had_wal: bool
    source_had_journal: bool


def _signature(path: Path) -> tuple[object, ...]:
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return (False,)
    return (
        True,
        stat_result.st_size,
        stat_result.st_mtime_ns,
        stat_result.st_dev,
        stat_result.st_ino,
    )


def _family_signature(source: Path) -> tuple[tuple[object, ...], ...]:
    return tuple(
        _signature(path)
        for path in (source, Path(str(source) + "-wal"), Path(str(source) + "-journal"))
    )


def _stable_family_copy(
    source: Path,
    workspace: Path,
    attempts: int,
) -> tuple[Path, Path | None, Path | None]:
    for attempt in range(attempts):
        attempt_directory = workspace / f"attempt-{attempt + 1}"
        attempt_directory.mkdir()
        raw_main = attempt_directory / "raw.sqlite"
        raw_wal = attempt_directory / "raw.sqlite-wal"
        raw_journal = attempt_directory / "raw.sqlite-journal"
        before = _family_signature(source)
        if not before[0][0]:
            raise SessionArkError(f"SQLite source disappeared: {source}")
        try:
            shutil.copyfile(source, raw_main)
            if before[1][0]:
                shutil.copyfile(Path(str(source) + "-wal"), raw_wal)
            if before[2][0]:
                shutil.copyfile(Path(str(source) + "-journal"), raw_journal)
        except (FileNotFoundError, PermissionError, OSError):
            shutil.rmtree(attempt_directory, ignore_errors=True)
            continue
        after = _family_signature(source)
        if before == after:
            return (
                raw_main,
                raw_wal if raw_wal.is_file() else None,
                raw_journal if raw_journal.is_file() else None,
            )
        shutil.rmtree(attempt_directory, ignore_errors=True)
    raise SessionArkError(
        "SQLite database family remained volatile during capture; no snapshot was published."
    )


def capture_sqlite_without_source_writes(
    source: Path,
    destination: Path,
    scratch_root: Path | None = None,
    attempts: int = 3,
) -> SQLiteCaptureResult:
    """Create a logical SQLite copy without ever opening the provider database.

    The main database and transaction sidecars are first copied during a stable
    metadata window. SQLite is then opened only against that private copy, where
    WAL/journal recovery and the backup API are safe to run.
    """

    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.is_file():
        raise SessionArkError(f"SQLite source does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    scratch_parent = scratch_root.expanduser().resolve() if scratch_root else None
    if scratch_parent:
        scratch_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="sessionark-sqlite-", dir=scratch_parent
    ) as temporary:
        workspace = Path(temporary)
        raw_main, raw_wal, raw_journal = _stable_family_copy(
            source, workspace, attempts
        )
        working_main = workspace / "working.sqlite"
        working_wal = Path(str(working_main) + "-wal")
        working_journal = Path(str(working_main) + "-journal")
        shutil.copyfile(raw_main, working_main)
        if raw_wal:
            shutil.copyfile(raw_wal, working_wal)
        if raw_journal:
            shutil.copyfile(raw_journal, working_journal)

        source_connection: sqlite3.Connection | None = None
        destination_connection: sqlite3.Connection | None = None
        try:
            source_connection = sqlite3.connect(working_main, timeout=10)
            destination_connection = sqlite3.connect(destination)
            source_connection.backup(destination_connection)
            destination_connection.commit()
            destination_connection.close()
            destination_connection = None
            source_connection.close()
            source_connection = None
            return SQLiteCaptureResult(
                path=destination,
                capture_mode="sqlite_backup",
                warning=None,
                source_had_wal=raw_wal is not None,
                source_had_journal=raw_journal is not None,
            )
        except (OSError, sqlite3.Error) as error:
            if destination_connection is not None:
                destination_connection.close()
            if source_connection is not None:
                source_connection.close()
            destination.unlink(missing_ok=True)
            sidecar_has_data = any(
                path is not None and path.stat().st_size > 0
                for path in (raw_wal, raw_journal)
            )
            if sidecar_has_data:
                raise SessionArkError(
                    "SQLite logical backup failed while committed/recovery data existed in a "
                    f"transaction sidecar; refusing a main-file-only fallback: {error}"
                ) from error
            shutil.copyfile(raw_main, destination)
            return SQLiteCaptureResult(
                path=destination,
                capture_mode="raw_fallback",
                warning=f"SQLite backup API failed on the private copy; preserved stable raw main file: {error}",
                source_had_wal=raw_wal is not None,
                source_had_journal=raw_journal is not None,
            )
