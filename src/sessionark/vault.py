from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .adapters import collect_source_files
from .audit import (
    audit_codex_artifacts,
    audit_json,
    audit_jsonl,
    audit_sqlite,
    strict_json_loads,
)
from .models import SessionArkError, SourceFile, VaultCorruptionError
from .sqlite_safe import capture_sqlite_without_source_writes
from .util import (
    atomic_write_bytes,
    atomic_write_text,
    canonical_json_bytes,
    normalize_relative_path,
    path_has_reparse_component,
    paths_overlap,
    portable_path_key,
    safe_join,
    sha256_file,
    snapshot_timestamp,
    utc_now,
)

VAULT_SCHEMA_VERSION = 1


def default_vault() -> Path:
    override = os.environ.get("SESSIONARK_HOME")
    if override:
        return Path(override).expanduser() / "vault"
    raise SessionArkError(
        "No vault location was supplied. Pass --vault explicitly or set SESSIONARK_HOME."
    )


def initialize_vault(vault: Path) -> Path:
    vault = vault.expanduser().resolve()
    version_path = vault / "VERSION"
    if version_path.exists():
        opened = open_vault(vault)
        (opened / "tmp").mkdir(parents=True, exist_ok=True)
        return opened
    if vault.exists() and any(vault.iterdir()):
        raise SessionArkError(
            f"Refusing to initialize a non-empty directory that is not a SessionArk vault: {vault}"
        )
    vault_preexisted = vault.exists()
    try:
        (vault / "objects" / "sha256").mkdir(parents=True, exist_ok=True)
        (vault / "snapshots").mkdir(parents=True, exist_ok=True)
        (vault / "tmp").mkdir(parents=True, exist_ok=True)
        atomic_write_text(version_path, f"{VAULT_SCHEMA_VERSION}\n")
    except Exception:
        if not version_path.exists():
            for directory in (
                vault / "objects" / "sha256",
                vault / "objects",
                vault / "snapshots",
                vault / "tmp",
            ):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            if not vault_preexisted:
                try:
                    vault.rmdir()
                except OSError:
                    pass
        raise
    return vault


def open_vault(vault: Path) -> Path:
    vault = vault.expanduser().resolve()
    version_path = vault / "VERSION"
    if not version_path.is_file():
        raise SessionArkError(f"SessionArk vault not found: {vault}")
    try:
        value = version_path.read_text(encoding="utf-8", errors="strict").strip()
    except (OSError, UnicodeError) as error:
        raise VaultCorruptionError(f"Vault VERSION is unreadable: {error}") from error
    if value != str(VAULT_SCHEMA_VERSION):
        raise SessionArkError(
            f"Unsupported vault schema {value!r}; expected {VAULT_SCHEMA_VERSION}."
        )
    if not (vault / "objects" / "sha256").is_dir() or not (vault / "snapshots").is_dir():
        raise VaultCorruptionError(f"Vault structure is incomplete: {vault}")
    return vault


def _temporary_path(vault: Path, suffix: str = ".tmp") -> Path:
    descriptor, name = tempfile.mkstemp(prefix="capture-", suffix=suffix, dir=vault / "tmp")
    os.close(descriptor)
    return Path(name)


def _hash_copy(source: Path, destination: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as source_handle, destination.open("wb") as destination_handle:
        while chunk := source_handle.read(1024 * 1024):
            destination_handle.write(chunk)
            digest.update(chunk)
        destination_handle.flush()
        os.fsync(destination_handle.fileno())
    return digest.hexdigest()


def _capture_regular(source: Path, vault: Path, attempts: int = 3) -> tuple[Path, str, bool]:
    changed = False
    last_temporary: Path | None = None
    last_digest = ""
    for attempt in range(attempts):
        temporary = _temporary_path(vault)
        last_temporary = temporary
        before = source.stat()
        digest = _hash_copy(source, temporary)
        after = source.stat()
        last_digest = digest
        stable = (
            before.st_size == after.st_size
            and before.st_mtime_ns == after.st_mtime_ns
            and before.st_dev == after.st_dev
            and before.st_ino == after.st_ino
        )
        if stable:
            return temporary, digest, changed
        changed = True
        if attempt + 1 < attempts:
            temporary.unlink(missing_ok=True)
    if last_temporary is None:
        raise SessionArkError(f"Unable to capture source file: {source}")
    return last_temporary, last_digest, changed


def _capture_sqlite(source: Path, vault: Path) -> tuple[Path, str, str, str | None]:
    temporary = _temporary_path(vault, suffix=".sqlite")
    try:
        capture = capture_sqlite_without_source_writes(
            source,
            temporary,
            scratch_root=vault / "tmp",
        )
        return (
            temporary,
            sha256_file(temporary),
            capture.capture_mode,
            capture.warning,
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _object_path(vault: Path, digest: str) -> Path:
    return vault / "objects" / "sha256" / digest[:2] / digest[2:]


def _store_object(vault: Path, temporary: Path, digest: str) -> tuple[Path, bool]:
    destination = _object_path(vault, digest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_file() or sha256_file(destination) != digest:
            raise VaultCorruptionError(
                f"Existing object does not match its content address: {destination}"
            )
        temporary.unlink(missing_ok=True)
        return destination, True
    os.replace(temporary, destination)
    return destination, False


def _audit_object(kind: str, object_path: Path) -> dict[str, Any]:
    if kind == "jsonl":
        return audit_jsonl(object_path)
    if kind == "json":
        return audit_json(object_path)
    if kind == "sqlite":
        return audit_sqlite(object_path)
    return {
        "kind": kind,
        "status": "ok",
        "bytes": object_path.stat().st_size,
        "errors": [],
        "warnings": [],
    }


def _capture_source_file(vault: Path, source: SourceFile) -> dict[str, Any]:
    source_stat = source.path.stat()
    capture_error: str | None = None
    changed_during_capture = False
    if source.kind == "sqlite":
        temporary, digest, capture_mode, capture_error = _capture_sqlite(source.path, vault)
    else:
        temporary, digest, changed_during_capture = _capture_regular(source.path, vault)
        capture_mode = "stable_copy"
    try:
        object_path, deduplicated = _store_object(vault, temporary, digest)
    finally:
        temporary.unlink(missing_ok=True)
    object_size = object_path.stat().st_size
    audit = _audit_object(source.kind, object_path)
    warnings: list[str] = []
    if changed_during_capture:
        warnings.append("Source changed during capture; the final complete copy was retained.")
    if capture_error:
        warnings.append(capture_error)
    return {
        "path": normalize_relative_path(source.relative_path),
        "kind": source.kind,
        "sha256": digest,
        "source_size": source_stat.st_size,
        "object_size": object_size,
        "source_mtime_ns": source_stat.st_mtime_ns,
        "capture_mode": capture_mode,
        "captured_at": utc_now(),
        "deduplicated": deduplicated,
        "capture_warnings": warnings,
        "audit": audit,
    }


def _ensure_unique_source_paths(sources: list[SourceFile]) -> None:
    seen: dict[str, str] = {}
    for source in sources:
        key = portable_path_key(source.relative_path)
        previous = seen.get(key)
        if previous is not None and previous != source.relative_path:
            raise SessionArkError(
                "Source contains paths that collide on a portable restore target: "
                f"{previous!r} and {source.relative_path!r}"
            )
        seen[key] = source.relative_path


def _captured_codex_consistency(
    vault: Path,
    root: Path,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    index_path: Path | None = None
    state_path: Path | None = None
    session_artifacts: list[tuple[str, Path]] = []
    for entry in entries:
        relative_path = str(entry["path"])
        object_path = _object_path(vault, str(entry["sha256"]))
        if relative_path == "session_index.jsonl":
            index_path = object_path
        elif relative_path == "state_5.sqlite":
            state_path = object_path
        elif relative_path.startswith(("sessions/", "archived_sessions/")):
            session_artifacts.append((relative_path, object_path))
    return audit_codex_artifacts(
        index_path,
        state_path,
        session_artifacts,
        source_root=root,
    )


def create_snapshot(
    provider: str,
    root: Path,
    vault: Path,
    label: str | None = None,
) -> dict[str, Any]:
    root = root.expanduser().resolve()
    requested_vault = vault.expanduser().resolve()
    if paths_overlap(root, requested_vault):
        raise SessionArkError("The vault and provider root must not overlap.")
    sources = collect_source_files(provider, root)
    if not sources:
        raise SessionArkError(f"No supported session files found under {root}")
    _ensure_unique_source_paths(sources)
    vault = initialize_vault(requested_vault)

    snapshot_id = f"{snapshot_timestamp()}-{secrets.token_hex(4)}"
    capture_started_at = utc_now()
    entries = [_capture_source_file(vault, source) for source in sources]
    capture_finished_at = utc_now()
    original_paths = {normalize_relative_path(source.relative_path) for source in sources}
    current_sources = collect_source_files(provider, root)
    current_paths = {
        normalize_relative_path(source.relative_path) for source in current_sources
    }
    added_during_capture = sorted(current_paths - original_paths)
    removed_during_capture = sorted(original_paths - current_paths)
    source_set_changed = bool(added_during_capture or removed_during_capture)
    audit_errors = sum(entry["audit"]["status"] == "error" for entry in entries)
    audit_warnings = sum(entry["audit"]["status"] == "warning" for entry in entries)
    capture_warnings = sum(bool(entry["capture_warnings"]) for entry in entries)
    consistency = (
        _captured_codex_consistency(vault, root, entries)
        if provider == "codex"
        else None
    )

    content_tree = [
        {"path": entry["path"], "sha256": entry["sha256"], "kind": entry["kind"]}
        for entry in entries
    ]
    content_digest = hashlib.sha256(canonical_json_bytes(content_tree)).hexdigest()
    manifest: dict[str, Any] = {
        "schema_version": VAULT_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "created_at": utc_now(),
        "capture_started_at": capture_started_at,
        "capture_finished_at": capture_finished_at,
        "provider": provider,
        "source_root": str(root),
        "label": label,
        "content_digest": content_digest,
        "summary": {
            "files": len(entries),
            "source_bytes": sum(entry["source_size"] for entry in entries),
            "object_bytes": sum(entry["object_size"] for entry in entries),
            "deduplicated_files": sum(entry["deduplicated"] for entry in entries),
            "files_with_errors": audit_errors,
            "files_with_warnings": audit_warnings,
            "capture_warnings": capture_warnings,
            "consistency_status": consistency["status"] if consistency else "not_applicable",
            "source_set_changed": source_set_changed,
        },
        "source_set_change": {
            "changed": source_set_changed,
            "added": added_during_capture,
            "removed": removed_during_capture,
        },
        "consistency": consistency,
        "files": entries,
    }
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    snapshot_directory = vault / "snapshots" / snapshot_id
    staging_directory = vault / "tmp" / f"snapshot-{snapshot_id}-{secrets.token_hex(4)}"
    staging_directory.mkdir(parents=False, exist_ok=False)
    try:
        atomic_write_bytes(staging_directory / "manifest.json", manifest_bytes)
        atomic_write_text(staging_directory / "manifest.sha256", manifest_digest + "\n")
        os.replace(staging_directory, snapshot_directory)
    finally:
        if staging_directory.exists():
            shutil.rmtree(staging_directory)
    manifest["manifest_sha256"] = manifest_digest
    manifest["vault"] = str(vault)
    return manifest


def list_snapshots(vault: Path) -> list[dict[str, Any]]:
    vault = open_vault(vault)
    snapshots: list[dict[str, Any]] = []
    for directory in sorted((vault / "snapshots").iterdir(), reverse=True):
        if not directory.is_dir():
            continue
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            snapshots.append(
                {
                    "snapshot_id": directory.name,
                    "status": "invalid_manifest",
                    "error": "manifest.json is missing",
                }
            )
            continue
        try:
            manifest = strict_json_loads(
                manifest_path.read_text(encoding="utf-8", errors="strict")
            )
            if not isinstance(manifest, dict):
                raise ValueError("manifest root must be a JSON object")
            summary = manifest.get("summary")
            if not isinstance(summary, dict):
                summary = {}
            status = (
                "ok"
                if manifest.get("snapshot_id") == directory.name
                else "snapshot_id_mismatch"
            )
            snapshots.append(
                {
                    "snapshot_id": directory.name,
                    "status": status,
                    "created_at": manifest.get("created_at"),
                    "provider": manifest.get("provider"),
                    "label": manifest.get("label"),
                    "summary": summary,
                }
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            snapshots.append(
                {
                    "snapshot_id": directory.name,
                    "status": "invalid_manifest",
                    "error": str(error),
                }
            )
    return snapshots


def _load_manifest(vault: Path, snapshot_id: str) -> tuple[dict[str, Any], Path]:
    normalized = normalize_relative_path(snapshot_id)
    if "/" in normalized:
        raise SessionArkError("Snapshot ID must not contain path separators.")
    snapshot_directory = vault / "snapshots" / normalized
    manifest_path = snapshot_directory / "manifest.json"
    if not manifest_path.is_file():
        raise SessionArkError(f"Snapshot not found: {snapshot_id}")
    try:
        value = strict_json_loads(
            manifest_path.read_text(encoding="utf-8", errors="strict")
        )
        if not isinstance(value, dict):
            raise ValueError("manifest root must be a JSON object")
        return value, snapshot_directory
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise VaultCorruptionError(f"Invalid snapshot manifest: {error}") from error


def _verification_failure(snapshot_id: str, error: Exception) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot_id,
        "status": "error",
        "files": 0,
        "verified_files": 0,
        "errors": [
            {"category": "invalid_or_missing_manifest", "message": str(error)}
        ],
    }


def _verify_snapshot_loaded(
    vault: Path,
    snapshot_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        manifest, snapshot_directory = _load_manifest(vault, snapshot_id)
    except SessionArkError as error:
        return _verification_failure(snapshot_id, error), None
    errors: list[dict[str, Any]] = []
    if manifest.get("schema_version") != VAULT_SCHEMA_VERSION:
        errors.append(
            {
                "category": "unsupported_manifest_schema",
                "value": manifest.get("schema_version"),
            }
        )
    if manifest.get("snapshot_id") != snapshot_id:
        errors.append(
            {
                "category": "snapshot_id_mismatch",
                "value": manifest.get("snapshot_id"),
            }
        )
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        errors.append({"category": "invalid_files_collection"})
        files: list[Any] = []
    else:
        files = raw_files
    manifest_path = snapshot_directory / "manifest.json"
    sidecar_path = snapshot_directory / "manifest.sha256"
    if not sidecar_path.is_file():
        errors.append({"category": "missing_manifest_digest"})
    else:
        try:
            expected_manifest_digest = sidecar_path.read_text(
                encoding="utf-8", errors="strict"
            ).strip()
            if len(expected_manifest_digest) != 64 or any(
                character not in "0123456789abcdef"
                for character in expected_manifest_digest
            ):
                raise ValueError("manifest.sha256 is not a lowercase SHA-256 digest")
            actual_manifest_digest = sha256_file(manifest_path)
        except (OSError, UnicodeError, ValueError) as error:
            errors.append(
                {
                    "category": "invalid_manifest_digest",
                    "message": str(error),
                }
            )
        else:
            if expected_manifest_digest != actual_manifest_digest:
                errors.append(
                    {
                        "category": "manifest_digest_mismatch",
                        "expected": expected_manifest_digest,
                        "actual": actual_manifest_digest,
                    }
                )

    verified = 0
    seen_paths: dict[str, str] = {}
    for entry in files:
        try:
            raw_path = entry["path"]
            normalized_path = normalize_relative_path(raw_path)
            if raw_path != normalized_path:
                raise ValueError("manifest path is not canonical")
            path_key = portable_path_key(normalized_path)
            previous_path = seen_paths.get(path_key)
            if previous_path is not None:
                errors.append(
                    {
                        "category": "path_collision",
                        "path": raw_path,
                        "collides_with": previous_path,
                    }
                )
                continue
            seen_paths[path_key] = raw_path
            digest = str(entry["sha256"])
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("invalid sha256")
            object_path = _object_path(vault, digest)
            if not object_path.is_file():
                errors.append(
                    {"category": "missing_object", "path": entry.get("path"), "sha256": digest}
                )
                continue
            actual_digest = sha256_file(object_path)
            if actual_digest != digest:
                errors.append(
                    {
                        "category": "object_digest_mismatch",
                        "path": entry.get("path"),
                        "expected": digest,
                        "actual": actual_digest,
                    }
                )
                continue
            if object_path.stat().st_size != int(entry["object_size"]):
                errors.append(
                    {"category": "object_size_mismatch", "path": entry.get("path")}
                )
                continue
            verified += 1
        except (KeyError, TypeError, ValueError, SessionArkError) as error:
            errors.append(
                {
                    "category": "invalid_manifest_entry",
                    "path": entry.get("path") if isinstance(entry, dict) else None,
                    "message": str(error),
                }
            )
    content_tree = [
        {"path": entry.get("path"), "sha256": entry.get("sha256"), "kind": entry.get("kind")}
        for entry in files
        if isinstance(entry, dict)
    ]
    actual_content_digest = hashlib.sha256(canonical_json_bytes(content_tree)).hexdigest()
    if manifest.get("content_digest") != actual_content_digest:
        errors.append(
            {
                "category": "content_digest_mismatch",
                "expected": manifest.get("content_digest"),
                "actual": actual_content_digest,
            }
        )
    result = {
        "snapshot_id": snapshot_id,
        "status": "ok" if not errors else "error",
        "files": len(files),
        "verified_files": verified,
        "errors": errors,
    }
    return result, manifest


def verify_snapshot(vault: Path, snapshot_id: str) -> dict[str, Any]:
    opened_vault = open_vault(vault)
    result, _ = _verify_snapshot_loaded(opened_vault, snapshot_id)
    return result


def _directory_identity(path: Path) -> tuple[int, int]:
    stat_result = path.lstat()
    if not path.is_dir() or path.is_symlink():
        raise SessionArkError(f"Expected a real directory, got: {path}")
    return stat_result.st_dev, stat_result.st_ino


def _assert_directory_identity(path: Path, identity: tuple[int, int]) -> None:
    if path_has_reparse_component(path) or _directory_identity(path) != identity:
        raise SessionArkError(f"Directory identity changed during restore: {path}")


def restore_snapshot(vault: Path, snapshot_id: str, target: Path) -> dict[str, Any]:
    vault = open_vault(vault)
    requested_target = target.expanduser().absolute()
    if os.path.lexists(requested_target):
        raise SessionArkError("Restore target must not already exist.")
    if os.name == "nt" and path_has_reparse_component(requested_target):
        raise SessionArkError("Restore target or one of its parents is a symlink/reparse point.")
    target = requested_target.resolve(strict=False)
    if paths_overlap(vault, target):
        raise SessionArkError("Restore target must not overlap the vault.")
    verification, manifest = _verify_snapshot_loaded(vault, snapshot_id)
    if verification["status"] != "ok" or manifest is None:
        raise VaultCorruptionError("Snapshot verification failed; restore was not started.")
    if os.path.lexists(target):
        raise SessionArkError("Restore target must not already exist.")
    parent = target.parent
    if not parent.is_dir():
        raise SessionArkError("Restore target parent must already exist and be a directory.")
    if path_has_reparse_component(parent):
        raise SessionArkError("Restore target parent contains a symlink/reparse point.")
    parent_identity = _directory_identity(parent)
    staging = parent / f".{target.name}.sessionark-staging-{secrets.token_hex(8)}"
    staging.mkdir(mode=0o700, exist_ok=False)
    staging_identity = _directory_identity(staging)

    restored = 0
    published = False
    try:
        for entry in manifest["files"]:
            _assert_directory_identity(parent, parent_identity)
            _assert_directory_identity(staging, staging_identity)
            destination = safe_join(staging, entry["path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            if path_has_reparse_component(destination.parent):
                raise SessionArkError(
                    "A symlink/reparse point appeared inside the restore staging tree."
                )
            object_path = _object_path(vault, entry["sha256"])
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            descriptor = os.open(destination, flags, 0o600)
            try:
                destination_handle = os.fdopen(descriptor, "wb")
                descriptor = -1
                with destination_handle, object_path.open("rb") as object_handle:
                    shutil.copyfileobj(object_handle, destination_handle, 1024 * 1024)
                    destination_handle.flush()
                    os.fsync(destination_handle.fileno())
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            if sha256_file(destination) != entry["sha256"]:
                raise VaultCorruptionError(
                    f"Restored file failed verification: {entry['path']}"
                )
            restored += 1

        _assert_directory_identity(parent, parent_identity)
        _assert_directory_identity(staging, staging_identity)
        if os.path.lexists(target):
            raise SessionArkError("Restore target appeared before publication.")
        os.rename(staging, target)
        published = True
    finally:
        if not published and staging.exists():
            try:
                _assert_directory_identity(staging, staging_identity)
            except (OSError, SessionArkError):
                pass
            else:
                shutil.rmtree(staging)

    report = {
        "snapshot_id": snapshot_id,
        "status": "ok",
        "restored_at": utc_now(),
        "restored_files": restored,
        "target": str(target),
    }
    return report
