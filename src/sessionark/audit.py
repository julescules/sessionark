from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from .adapters import collect_source_files
from .models import SessionArkError, SourceFile
from .sqlite_safe import capture_sqlite_without_source_writes
from .util import redact_home, utc_now

MAX_REPORTED_ERRORS = 50


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON constant is not allowed: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON object key: {key}")
        value[key] = item
    return value


def strict_json_loads(text: str) -> Any:
    return json.loads(
        text,
        parse_constant=_reject_json_constant,
        object_pairs_hook=_reject_duplicate_keys,
    )


def _status(errors: int, warnings: int) -> str:
    if errors:
        return "error"
    if warnings:
        return "warning"
    return "ok"


def audit_jsonl(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": "jsonl",
        "status": "ok",
        "bytes": path.stat().st_size,
        "records": 0,
        "invalid_records": 0,
        "blank_lines": 0,
        "errors": [],
        "warnings": [],
    }
    offset = 0
    line_number = 0
    last_had_newline = True
    last_line_valid = False
    last_error_position: int | None = None
    last_error_looks_incomplete = False

    try:
        with path.open("rb") as handle:
            for raw_line in handle:
                line_number += 1
                line_offset = offset
                offset += len(raw_line)
                last_had_newline = raw_line.endswith(b"\n")
                payload = raw_line.rstrip(b"\r\n")
                if not payload.strip():
                    result["blank_lines"] += 1
                    last_line_valid = True
                    continue
                try:
                    encoding = "utf-8-sig" if line_number == 1 else "utf-8"
                    text = payload.decode(encoding, errors="strict")
                    value = strict_json_loads(text)
                    if not isinstance(value, dict):
                        result["warnings"].append(
                            {
                                "line": line_number,
                                "category": "non_object_record",
                                "message": "JSONL record is valid JSON but is not an object.",
                            }
                        )
                    result["records"] += 1
                    last_line_valid = True
                    last_error_position = None
                    last_error_looks_incomplete = False
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                    result["invalid_records"] += 1
                    last_line_valid = False
                    last_error_position = None
                    last_error_looks_incomplete = bool(
                        isinstance(error, json.JSONDecodeError)
                        and error.pos >= len(error.doc)
                    )
                    if len(result["errors"]) < MAX_REPORTED_ERRORS:
                        result["errors"].append(
                            {
                                "line": line_number,
                                "byte_offset": line_offset,
                                "category": "invalid_record",
                                "message": str(error),
                            }
                        )
                        last_error_position = len(result["errors"]) - 1
    except OSError as error:
        result["errors"].append(
            {"category": "read_error", "message": str(error)}
        )

    if line_number and not last_had_newline:
        if (
            not last_line_valid
            and last_error_looks_incomplete
            and last_error_position is not None
        ):
            result["errors"][last_error_position]["category"] = "truncated_tail"
            result["truncated_tail"] = True
        elif not last_line_valid and last_error_looks_incomplete:
            result["truncated_tail"] = True
        elif last_line_valid:
            result["warnings"].append(
                {
                    "line": line_number,
                    "category": "missing_final_newline",
                    "message": "Final JSONL record is valid but has no trailing newline.",
                }
            )

    if result["invalid_records"] > len(result["errors"]):
        result["errors_omitted"] = result["invalid_records"] - len(result["errors"])
    result["status"] = _status(result["invalid_records"] + int(bool(
        any(item.get("category") == "read_error" for item in result["errors"])
    )), len(result["warnings"]))
    return result


def audit_json(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": "json",
        "status": "ok",
        "bytes": path.stat().st_size,
        "errors": [],
        "warnings": [],
    }
    try:
        with path.open("r", encoding="utf-8-sig", errors="strict") as handle:
            strict_json_loads(handle.read())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        result["errors"].append({"category": "invalid_json", "message": str(error)})
        result["status"] = "error"
    return result


def _sqlite_private(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=5)
    connection.execute("PRAGMA query_only=ON")
    return connection


def audit_sqlite(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": "sqlite",
        "status": "ok",
        "bytes": path.stat().st_size,
        "quick_check": None,
        "foreign_key_violations": 0,
        "table_count": 0,
        "capture_mode": None,
        "errors": [],
        "warnings": [],
    }
    try:
        with tempfile.TemporaryDirectory(prefix="sessionark-sqlite-audit-") as temporary:
            private_path = Path(temporary) / "audit.sqlite"
            capture = capture_sqlite_without_source_writes(
                path, private_path, Path(temporary)
            )
            result["capture_mode"] = capture.capture_mode
            if capture.warning:
                result["warnings"].append(
                    {"category": "sqlite_capture_warning", "message": capture.warning}
                )
            connection = _sqlite_private(private_path)
            try:
                check_rows = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
                result["quick_check"] = check_rows[0] if len(check_rows) == 1 else check_rows
                if check_rows != ["ok"]:
                    result["errors"].append(
                        {
                            "category": "sqlite_integrity",
                            "message": "SQLite quick_check did not return ok.",
                            "details": check_rows[:10],
                        }
                    )
                result["table_count"] = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                    ).fetchone()[0]
                )
                foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
                result["foreign_key_violations"] = len(foreign_key_rows)
                if foreign_key_rows:
                    result["errors"].append(
                        {
                            "category": "sqlite_foreign_key",
                            "message": "SQLite foreign_key_check reported violations.",
                            "count": len(foreign_key_rows),
                        }
                    )
            finally:
                connection.close()
    except (SessionArkError, OSError, sqlite3.Error) as error:
        result["errors"].append(
            {"category": "sqlite_open", "message": str(error)}
        )
    result["status"] = _status(len(result["errors"]), len(result["warnings"]))
    return result


def audit_source_file(source: SourceFile) -> dict[str, Any]:
    if source.kind == "jsonl":
        details = audit_jsonl(source.path)
    elif source.kind == "json":
        details = audit_json(source.path)
    elif source.kind == "sqlite":
        details = audit_sqlite(source.path)
    else:
        details = {
            "kind": source.kind,
            "status": "ok",
            "bytes": source.path.stat().st_size,
            "errors": [],
            "warnings": [],
        }
    return {
        "path": source.relative_path,
        "kind": source.kind,
        "status": details["status"],
        "details": details,
    }


def _read_index_ids(index_path: Path) -> tuple[set[str], int, int]:
    identifiers: set[str] = set()
    duplicates = 0
    invalid = 0
    if not index_path.is_file():
        return identifiers, duplicates, invalid
    with index_path.open("r", encoding="utf-8-sig", errors="strict") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = strict_json_loads(line)
                identifier = value.get("id") if isinstance(value, dict) else None
                if not isinstance(identifier, str) or not identifier:
                    invalid += 1
                    continue
                if identifier in identifiers:
                    duplicates += 1
                identifiers.add(identifier)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                invalid += 1
    return identifiers, duplicates, invalid


def _session_ids_from_first_meta_paths(
    artifacts: list[tuple[str, Path]],
) -> tuple[set[str], dict[str, str], int, int]:
    identifiers: set[str] = set()
    identifiers_by_path: dict[str, str] = {}
    total = 0
    unidentified = 0
    for relative_path, path in artifacts:
        if path.is_symlink() or not path.is_file():
            continue
        total += 1
        identifier: str | None = None
        try:
            with path.open("r", encoding="utf-8-sig", errors="strict") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    record = strict_json_loads(line)
                    if isinstance(record, dict) and record.get("type") == "session_meta":
                        payload = record.get("payload")
                        if isinstance(payload, dict) and isinstance(payload.get("id"), str):
                            identifier = payload["id"].lower()
                    break
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            identifier = None
        if identifier:
            identifiers.add(identifier)
            identifiers_by_path[relative_path] = identifier
        else:
            unidentified += 1
    return identifiers, identifiers_by_path, total, unidentified


def _rollout_relative_path(value: str, source_root: Path | None) -> str | None:
    try:
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            if source_root is None:
                return None
            resolved_root = source_root.expanduser().resolve()
            resolved_candidate = candidate.resolve()
            if not resolved_candidate.is_relative_to(resolved_root):
                return None
            return resolved_candidate.relative_to(resolved_root).as_posix()
        parts = candidate.parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            return None
        return Path(*parts).as_posix()
    except (OSError, ValueError):
        return None


def audit_codex_artifacts(
    index_path: Path | None,
    state_path: Path | None,
    session_artifacts: list[tuple[str, Path]],
    source_root: Path | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "ok",
        "index_present": bool(index_path and index_path.is_file()),
        "state_db_present": bool(state_path and state_path.is_file()),
        "state_db_capture_mode": None,
        "index_entries": 0,
        "index_duplicates": 0,
        "index_invalid_records": 0,
        "db_threads": 0,
        "db_visible_threads": 0,
        "missing_from_index": 0,
        "index_entries_missing_from_db": 0,
        "db_rollouts_missing_on_disk": 0,
        "db_rollouts_outside_root": 0,
        "db_rollout_identity_mismatches": 0,
        "db_threads_without_rollout_path": 0,
        "session_files_missing_from_db": 0,
        "session_files": 0,
        "session_files_unidentified": 0,
        "errors": [],
        "warnings": [],
    }

    try:
        index_ids, duplicates, invalid = (
            _read_index_ids(index_path) if index_path else (set(), 0, 0)
        )
    except (OSError, UnicodeDecodeError) as error:
        index_ids, duplicates, invalid = set(), 0, 0
        result["errors"].append({"category": "index_read", "message": str(error)})
    result["index_entries"] = len(index_ids)
    result["index_duplicates"] = duplicates
    result["index_invalid_records"] = invalid
    if not result["index_present"]:
        result["warnings"].append(
            {"category": "missing_index", "message": "session_index.jsonl is missing."}
        )
    if duplicates:
        result["warnings"].append(
            {"category": "duplicate_index_ids", "count": duplicates}
        )
    if invalid:
        result["errors"].append(
            {"category": "invalid_index_records", "count": invalid}
        )

    database_ids: set[str] = set()
    visible_ids: set[str] = set()
    declared_rollouts: list[tuple[str, str]] = []
    database_loaded = False
    if not state_path or not state_path.is_file():
        result["warnings"].append(
            {"category": "missing_state_db", "message": "state_5.sqlite is missing."}
        )
    else:
        try:
            with tempfile.TemporaryDirectory(prefix="sessionark-codex-state-") as temporary:
                private_state = Path(temporary) / "state.sqlite"
                capture = capture_sqlite_without_source_writes(
                    state_path, private_state, Path(temporary)
                )
                result["state_db_capture_mode"] = capture.capture_mode
                if capture.warning:
                    result["warnings"].append(
                        {"category": "state_db_capture_warning", "message": capture.warning}
                    )
                connection = _sqlite_private(private_state)
                try:
                    check = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
                    if check != ["ok"]:
                        result["errors"].append(
                            {"category": "state_db_integrity", "details": check[:10]}
                        )
                    table_exists = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='threads'"
                    ).fetchone()
                    if not table_exists:
                        result["errors"].append(
                            {"category": "missing_threads_table", "message": "threads table is absent."}
                        )
                    else:
                        columns = {
                            str(row[1]) for row in connection.execute("PRAGMA table_info(threads)")
                        }
                        if "id" not in columns:
                            result["errors"].append(
                                {"category": "missing_thread_id_column"}
                            )
                        else:
                            database_loaded = True
                            rollout_expression = "rollout_path" if "rollout_path" in columns else "NULL"
                            archived_expression = "archived" if "archived" in columns else "0"
                            user_expression = (
                                "has_user_event" if "has_user_event" in columns else "1"
                            )
                            rows = connection.execute(
                                "SELECT id, "
                                f"{rollout_expression}, {archived_expression}, {user_expression} "
                                "FROM threads"
                            )
                            for identifier, rollout_path, archived, has_user_event in rows:
                                if not isinstance(identifier, str) or not identifier:
                                    continue
                                normalized_id = identifier.lower()
                                database_ids.add(normalized_id)
                                if not archived and has_user_event:
                                    visible_ids.add(normalized_id)
                                if isinstance(rollout_path, str) and rollout_path.strip():
                                    declared_rollouts.append((normalized_id, rollout_path))
                                else:
                                    result["db_threads_without_rollout_path"] += 1
                            result["db_threads"] = len(database_ids)
                            result["db_visible_threads"] = len(visible_ids)
                finally:
                    connection.close()
        except (SessionArkError, sqlite3.Error) as error:
            result["errors"].append(
                {"category": "state_db_open", "message": str(error)}
            )

    normalized_index_ids = {identifier.lower() for identifier in index_ids}
    (
        session_ids,
        session_ids_by_path,
        session_file_count,
        unidentified,
    ) = _session_ids_from_first_meta_paths(
        session_artifacts
    )
    result["session_files"] = session_file_count
    result["session_files_unidentified"] = unidentified
    if database_loaded:
        result["missing_from_index"] = len(visible_ids - normalized_index_ids)
        result["index_entries_missing_from_db"] = len(normalized_index_ids - database_ids)
        result["session_files_missing_from_db"] = len(session_ids - database_ids)
        for database_id, declared_path in declared_rollouts:
            relative_path = _rollout_relative_path(declared_path, source_root)
            if relative_path is None:
                result["db_rollouts_outside_root"] += 1
                continue
            captured_id = session_ids_by_path.get(relative_path)
            if captured_id is None:
                result["db_rollouts_missing_on_disk"] += 1
            elif captured_id != database_id:
                result["db_rollout_identity_mismatches"] += 1

    if result["missing_from_index"]:
        result["warnings"].append(
            {
                "category": "stale_index",
                "count": result["missing_from_index"],
                "message": "Visible database threads are absent from session_index.jsonl.",
            }
        )
    if result["index_entries_missing_from_db"]:
        result["warnings"].append(
            {
                "category": "index_only_entries",
                "count": result["index_entries_missing_from_db"],
                "message": "Index entries are absent from the current state database; they may be legitimate history and are never deleted automatically.",
            }
        )
    if result["db_rollouts_missing_on_disk"]:
        result["errors"].append(
            {
                "category": "missing_rollout_files",
                "count": result["db_rollouts_missing_on_disk"],
            }
        )
    if result["db_rollouts_outside_root"]:
        result["errors"].append(
            {
                "category": "rollout_paths_outside_provider_root",
                "count": result["db_rollouts_outside_root"],
            }
        )
    if result["db_rollout_identity_mismatches"]:
        result["errors"].append(
            {
                "category": "rollout_identity_mismatches",
                "count": result["db_rollout_identity_mismatches"],
            }
        )
    if result["db_threads_without_rollout_path"]:
        result["warnings"].append(
            {
                "category": "threads_without_rollout_path",
                "count": result["db_threads_without_rollout_path"],
            }
        )
    if result["session_files_unidentified"]:
        result["warnings"].append(
            {
                "category": "unidentified_session_files",
                "count": result["session_files_unidentified"],
                "message": "Session JSONL files do not begin with a recognizable session_meta record.",
            }
        )
    if result["session_files_missing_from_db"]:
        result["warnings"].append(
            {
                "category": "unindexed_session_files",
                "count": result["session_files_missing_from_db"],
            }
        )
    result["status"] = _status(len(result["errors"]), len(result["warnings"]))
    return result


def audit_codex_consistency(root: Path) -> dict[str, Any]:
    root = root.resolve()
    session_artifacts: list[tuple[str, Path]] = []
    for directory_name in ("sessions", "archived_sessions"):
        directory = root / directory_name
        if directory.is_dir() and not directory.is_symlink():
            session_artifacts.extend(
                (path.relative_to(root).as_posix(), path)
                for path in directory.rglob("*.jsonl")
                if path.is_file() and not path.is_symlink()
            )
    return audit_codex_artifacts(
        root / "session_index.jsonl",
        root / "state_5.sqlite",
        session_artifacts,
        source_root=root,
    )


def audit_source(provider: str, root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    files = collect_source_files(provider, root)
    file_results = [audit_source_file(item) for item in files]
    errors = sum(item["status"] == "error" for item in file_results)
    warnings = sum(item["status"] == "warning" for item in file_results)
    consistency = audit_codex_consistency(root) if provider == "codex" else None
    if consistency:
        errors += int(consistency["status"] == "error")
        warnings += int(consistency["status"] == "warning")
    return {
        "schema_version": 1,
        "audited_at": utc_now(),
        "provider": provider,
        "root": redact_home(root),
        "status": _status(errors, warnings),
        "summary": {
            "files": len(file_results),
            "healthy_files": sum(item["status"] == "ok" for item in file_results),
            "files_with_warnings": sum(
                item["status"] == "warning" for item in file_results
            ),
            "files_with_errors": sum(item["status"] == "error" for item in file_results),
        },
        "consistency": consistency,
        "files": file_results,
    }
