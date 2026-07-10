from __future__ import annotations

import json
import hashlib
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sessionark.models import SessionArkError, VaultCorruptionError
from sessionark.vault import (
    create_snapshot,
    initialize_vault,
    list_snapshots,
    restore_snapshot,
    verify_snapshot,
)

from tests.helpers import SESSION_ONE, create_codex_fixture, write_jsonl


class VaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.source = self.base / "codex"
        self.paths = create_codex_fixture(self.source)
        self.vault = self.base / "vault"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _object_path(vault: Path, digest: str) -> Path:
        return vault / "objects" / "sha256" / digest[:2] / digest[2:]

    @staticmethod
    def _resign_manifest(directory: Path, manifest: object) -> None:
        payload = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        (directory / "manifest.json").write_bytes(payload)
        (directory / "manifest.sha256").write_text(
            hashlib.sha256(payload).hexdigest() + "\n", encoding="utf-8"
        )

    def test_snapshot_deduplicates_verifies_and_restores(self) -> None:
        (self.source / "auth.json").write_text('{"token":"do-not-copy"}', encoding="utf-8")
        first = create_snapshot("codex", self.source, self.vault, "first")
        second = create_snapshot("codex", self.source, self.vault, "second")

        self.assertEqual(3, first["summary"]["files"])
        self.assertEqual(3, second["summary"]["deduplicated_files"])
        self.assertTrue(all(entry["path"] != "auth.json" for entry in first["files"]))
        sqlite_entry = next(entry for entry in first["files"] if entry["kind"] == "sqlite")
        self.assertEqual("sqlite_backup", sqlite_entry["capture_mode"])

        verification = verify_snapshot(self.vault, first["snapshot_id"])
        self.assertEqual("ok", verification["status"])
        self.assertEqual(3, verification["verified_files"])

        target = self.base / "restore"
        report = restore_snapshot(self.vault, first["snapshot_id"], target)
        self.assertEqual(3, report["restored_files"])
        restored_rollout = target / self.paths["rollout"].relative_to(self.source)
        self.assertEqual(self.paths["rollout"].read_bytes(), restored_rollout.read_bytes())
        restored_state = target / "state_5.sqlite"
        connection = sqlite3.connect(restored_state)
        try:
            count = connection.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(1, count)

    def test_active_wal_database_is_captured_as_logical_backup(self) -> None:
        state = self.paths["state"]
        state.unlink()
        connection = sqlite3.connect(state)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, archived INTEGER, has_user_event INTEGER)"
        )
        connection.execute(
            "INSERT INTO threads VALUES (?, ?, 0, 1)",
            (SESSION_ONE, str(self.paths["rollout"])),
        )
        connection.commit()
        # Keep the WAL connection open while SessionArk takes its logical copy.
        family = [
            state,
            Path(str(state) + "-wal"),
            Path(str(state) + "-shm"),
            Path(str(state) + "-journal"),
        ]

        def family_signature() -> dict[str, tuple[int, int, str] | None]:
            signature: dict[str, tuple[int, int, str] | None] = {}
            for path in family:
                if path.is_file():
                    stat_result = path.stat()
                    signature[path.name] = (
                        stat_result.st_size,
                        stat_result.st_mtime_ns,
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                else:
                    signature[path.name] = None
            return signature

        before = family_signature()
        try:
            snapshot = create_snapshot("codex", self.source, self.vault)
            after = family_signature()
        finally:
            connection.close()
        self.assertEqual(before, after)
        entry = next(item for item in snapshot["files"] if item["path"] == "state_5.sqlite")
        self.assertEqual("sqlite_backup", entry["capture_mode"])
        object_path = self._object_path(self.vault, entry["sha256"])
        copy = sqlite3.connect(object_path)
        try:
            self.assertEqual(1, copy.execute("SELECT COUNT(*) FROM threads").fetchone()[0])
            self.assertEqual("ok", copy.execute("PRAGMA quick_check").fetchone()[0])
        finally:
            copy.close()

    def test_wal_without_source_shm_is_captured_without_creating_one(self) -> None:
        state = self.paths["state"]
        for path in (
            state,
            Path(str(state) + "-wal"),
            Path(str(state) + "-shm"),
            Path(str(state) + "-journal"),
        ):
            path.unlink(missing_ok=True)
        donor = self.base / "donor.sqlite"
        connection = sqlite3.connect(donor)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, archived INTEGER, has_user_event INTEGER)"
        )
        connection.execute(
            "INSERT INTO threads VALUES (?, ?, 0, 1)",
            (SESSION_ONE, str(self.paths["rollout"])),
        )
        connection.commit()
        try:
            shutil.copyfile(donor, state)
            shutil.copyfile(Path(str(donor) + "-wal"), Path(str(state) + "-wal"))
            self.assertFalse(Path(str(state) + "-shm").exists())
            snapshot = create_snapshot("codex", self.source, self.vault)
            self.assertFalse(Path(str(state) + "-shm").exists())
        finally:
            connection.close()
        entry = next(item for item in snapshot["files"] if item["path"] == "state_5.sqlite")
        object_path = self._object_path(self.vault, entry["sha256"])
        copy = sqlite3.connect(object_path)
        try:
            self.assertEqual(1, copy.execute("SELECT COUNT(*) FROM threads").fetchone()[0])
        finally:
            copy.close()

    def test_object_tampering_blocks_restore(self) -> None:
        snapshot = create_snapshot("codex", self.source, self.vault)
        entry = snapshot["files"][0]
        object_path = self._object_path(self.vault, entry["sha256"])
        with object_path.open("ab") as handle:
            handle.write(b"tamper")
        result = verify_snapshot(self.vault, snapshot["snapshot_id"])
        self.assertEqual("error", result["status"])
        with self.assertRaises(VaultCorruptionError):
            restore_snapshot(
                self.vault, snapshot["snapshot_id"], self.base / "blocked-restore"
            )

    def test_manifest_path_traversal_is_rejected_even_with_valid_sidecar(self) -> None:
        snapshot = create_snapshot("codex", self.source, self.vault)
        directory = self.vault / "snapshots" / snapshot["snapshot_id"]
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][0]["path"] = "../escape.jsonl"
        payload = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        manifest_path.write_bytes(payload)
        import hashlib

        (directory / "manifest.sha256").write_text(
            hashlib.sha256(payload).hexdigest() + "\n", encoding="utf-8"
        )
        result = verify_snapshot(self.vault, snapshot["snapshot_id"])
        self.assertEqual("error", result["status"])
        self.assertEqual("invalid_manifest_entry", result["errors"][0]["category"])

    def test_nonempty_restore_target_is_never_overwritten(self) -> None:
        snapshot = create_snapshot("codex", self.source, self.vault)
        target = self.base / "nonempty"
        target.mkdir()
        sentinel = target / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaises(SessionArkError):
            restore_snapshot(self.vault, snapshot["snapshot_id"], target)
        self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))

    def test_existing_empty_restore_target_is_refused(self) -> None:
        snapshot = create_snapshot("codex", self.source, self.vault)
        target = self.base / "empty"
        target.mkdir()
        with self.assertRaises(SessionArkError):
            restore_snapshot(self.vault, snapshot["snapshot_id"], target)
        self.assertEqual([], list(target.iterdir()))

    def test_failed_restore_does_not_publish_partial_tree(self) -> None:
        snapshot = create_snapshot("codex", self.source, self.vault)
        target = self.base / "failed-restore"
        with patch("sessionark.vault.shutil.copyfileobj", side_effect=OSError("copy failed")):
            with self.assertRaises(OSError):
                restore_snapshot(self.vault, snapshot["snapshot_id"], target)
        self.assertFalse(target.exists())
        self.assertEqual([], list(self.base.glob(".failed-restore.sessionark-staging-*")))

    def test_restore_does_not_depend_on_unverified_source_mtime(self) -> None:
        snapshot = create_snapshot("codex", self.source, self.vault)
        directory = self.vault / "snapshots" / snapshot["snapshot_id"]
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            entry.pop("source_mtime_ns", None)
        self._resign_manifest(directory, manifest)
        target = self.base / "mtime-free-restore"
        report = restore_snapshot(self.vault, snapshot["snapshot_id"], target)
        self.assertEqual(3, report["restored_files"])

    def test_list_uses_directory_id_and_flags_manifest_id_mismatch(self) -> None:
        snapshot = create_snapshot("codex", self.source, self.vault)
        directory = self.vault / "snapshots" / snapshot["snapshot_id"]
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        manifest["snapshot_id"] = "forged-id"
        self._resign_manifest(directory, manifest)
        listed = list_snapshots(self.vault)
        self.assertEqual(snapshot["snapshot_id"], listed[0]["snapshot_id"])
        self.assertEqual("snapshot_id_mismatch", listed[0]["status"])
        verification = verify_snapshot(self.vault, snapshot["snapshot_id"])
        self.assertEqual("error", verification["status"])
        self.assertIn(
            "snapshot_id_mismatch",
            {item["category"] for item in verification["errors"]},
        )

    def test_invalid_utf8_digest_is_reported_without_exception(self) -> None:
        snapshot = create_snapshot("codex", self.source, self.vault)
        directory = self.vault / "snapshots" / snapshot["snapshot_id"]
        (directory / "manifest.sha256").write_bytes(b"\xff\xfe")
        result = verify_snapshot(self.vault, snapshot["snapshot_id"])
        self.assertEqual("error", result["status"])
        self.assertIn(
            "invalid_manifest_digest",
            {item["category"] for item in result["errors"]},
        )

    def test_snapshot_consistency_is_computed_from_captured_objects(self) -> None:
        import sessionark.vault as vault_module

        real_capture = vault_module._capture_source_file

        def capture_then_mutate(vault: Path, source: object) -> dict[str, object]:
            result = real_capture(vault, source)
            if source.relative_path == "session_index.jsonl":
                write_jsonl(source.path, [])
            return result

        with patch("sessionark.vault._capture_source_file", side_effect=capture_then_mutate):
            snapshot = create_snapshot("codex", self.source, self.vault)
        self.assertEqual("ok", snapshot["consistency"]["status"])
        self.assertEqual(0, snapshot["consistency"]["missing_from_index"])

    def test_source_set_change_is_visible_in_manifest_summary(self) -> None:
        import sessionark.vault as vault_module

        real_capture = vault_module._capture_source_file
        added = False

        def capture_then_add(vault: Path, source: object) -> dict[str, object]:
            nonlocal added
            result = real_capture(vault, source)
            if not added:
                added = True
                write_jsonl(self.source / "sessions" / "arrived-during-capture.jsonl", [{"x": 1}])
            return result

        with patch("sessionark.vault._capture_source_file", side_effect=capture_then_add):
            snapshot = create_snapshot("codex", self.source, self.vault)
        self.assertTrue(snapshot["summary"]["source_set_changed"])
        self.assertEqual(
            ["sessions/arrived-during-capture.jsonl"],
            snapshot["source_set_change"]["added"],
        )

    def test_symlink_to_secret_is_not_collected(self) -> None:
        secret = self.source / "auth.json"
        secret.write_text('{"token":"secret"}', encoding="utf-8")
        link = self.source / "sessions" / "linked.jsonl"
        try:
            os.symlink(secret, link)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable: {error}")
        snapshot = create_snapshot("codex", self.source, self.vault)
        self.assertNotIn("sessions/linked.jsonl", {entry["path"] for entry in snapshot["files"]})

    def test_custom_restore_does_not_overwrite_a_snapshotted_report_name(self) -> None:
        custom = self.base / "custom"
        write_jsonl(custom / "SESSIONARK_RESTORE_REPORT.json", [{"original": True}])
        snapshot = create_snapshot("custom", custom, self.vault)
        target = self.base / "custom-restore"
        restore_snapshot(self.vault, snapshot["snapshot_id"], target)
        self.assertEqual(
            (custom / "SESSIONARK_RESTORE_REPORT.json").read_bytes(),
            (target / "SESSIONARK_RESTORE_REPORT.json").read_bytes(),
        )

    def test_casefold_colliding_sources_are_not_silently_deduplicated(self) -> None:
        custom = self.base / "colliding"
        write_jsonl(custom / "straße.jsonl", [{"id": 1}])
        write_jsonl(custom / "strasse.jsonl", [{"id": 2}])
        from sessionark.adapters import collect_source_files

        collected = collect_source_files("custom", custom)
        self.assertEqual(2, len(collected))
        with self.assertRaises(SessionArkError):
            create_snapshot("custom", custom, self.vault)


class VaultOverlapTests(unittest.TestCase):
    def test_source_and_vault_must_not_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            create_codex_fixture(root)
            with self.assertRaises(SessionArkError):
                create_snapshot("codex", root, root / "vault")
            self.assertFalse((root / "vault").exists())

    def test_read_only_list_does_not_create_a_missing_vault(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "missing"
            with self.assertRaises(SessionArkError):
                list_snapshots(vault)
            self.assertFalse(vault.exists())

    def test_non_vault_directory_is_not_adopted_or_modified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            create_codex_fixture(source)
            vault = base / "existing"
            vault.mkdir()
            sentinel = vault / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            with self.assertRaises(SessionArkError):
                create_snapshot("codex", source, vault)
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))
            self.assertEqual(["keep.txt"], [item.name for item in vault.iterdir()])

    def test_failed_manifest_publish_never_exposes_partial_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            create_codex_fixture(source)
            vault = base / "vault"
            initialize_vault(vault)
            with patch("sessionark.vault.atomic_write_text", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    create_snapshot("codex", source, vault)
            snapshots = vault / "snapshots"
            self.assertEqual([], list(snapshots.iterdir()))
            self.assertEqual([], list((vault / "tmp").iterdir()))

    def test_list_tolerates_non_object_and_invalid_utf8_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            initialize_vault(vault)
            first = vault / "snapshots" / "first"
            first.mkdir()
            (first / "manifest.json").write_text("[]", encoding="utf-8")
            second = vault / "snapshots" / "second"
            second.mkdir()
            (second / "manifest.json").write_bytes(b"\xff\xfe")
            listed = list_snapshots(vault)
            self.assertEqual(2, len(listed))
            self.assertTrue(all(item["status"] == "invalid_manifest" for item in listed))

    def test_invalid_utf8_vault_version_is_reported_as_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            initialize_vault(vault)
            (vault / "VERSION").write_bytes(b"\xff\xfe")
            with self.assertRaises(VaultCorruptionError):
                list_snapshots(vault)
