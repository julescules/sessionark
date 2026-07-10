from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sessionark.audit import (
    audit_codex_consistency,
    audit_jsonl,
    audit_source,
    audit_sqlite,
)

from tests.helpers import (
    SESSION_ONE,
    SESSION_THREE,
    SESSION_TWO,
    create_codex_state,
    write_jsonl,
)


class JsonlAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_valid_jsonl_is_healthy(self) -> None:
        path = self.root / "valid.jsonl"
        write_jsonl(path, [{"type": "a"}, {"type": "b"}])
        result = audit_jsonl(path)
        self.assertEqual("ok", result["status"])
        self.assertEqual(2, result["records"])
        self.assertEqual(0, result["invalid_records"])

    def test_valid_final_record_without_newline_is_warning(self) -> None:
        path = self.root / "no-newline.jsonl"
        write_jsonl(path, [{"type": "a"}], final_newline=False)
        result = audit_jsonl(path)
        self.assertEqual("warning", result["status"])
        self.assertEqual("missing_final_newline", result["warnings"][0]["category"])

    def test_invalid_final_fragment_is_classified_as_truncated_tail(self) -> None:
        path = self.root / "truncated.jsonl"
        path.write_bytes(b'{"ok":true}\n{"broken":')
        result = audit_jsonl(path)
        self.assertEqual("error", result["status"])
        self.assertEqual(1, result["records"])
        self.assertEqual("truncated_tail", result["errors"][0]["category"])

    def test_internal_bad_record_is_not_called_tail_truncation(self) -> None:
        path = self.root / "internal.jsonl"
        path.write_bytes(b'{"ok":1}\nnot-json\n{"ok":2}\n')
        result = audit_jsonl(path)
        self.assertEqual("error", result["status"])
        self.assertEqual(2, result["records"])
        self.assertEqual("invalid_record", result["errors"][0]["category"])

    def test_complete_invalid_final_record_is_not_called_truncated(self) -> None:
        path = self.root / "complete-invalid.jsonl"
        path.write_bytes(b"not-json")
        result = audit_jsonl(path)
        self.assertEqual("error", result["status"])
        self.assertEqual("invalid_record", result["errors"][0]["category"])
        self.assertNotIn("truncated_tail", result)

    def test_duplicate_keys_and_nan_are_rejected(self) -> None:
        duplicate = self.root / "duplicate.jsonl"
        duplicate.write_bytes(b'{"a":1,"a":2}\n')
        nonstandard = self.root / "nan.jsonl"
        nonstandard.write_bytes(b'{"value":NaN}\n')
        self.assertEqual("error", audit_jsonl(duplicate)["status"])
        self.assertEqual("error", audit_jsonl(nonstandard)["status"])


class SqliteAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_valid_database_passes_quick_and_foreign_key_checks(self) -> None:
        path = self.root / "valid.sqlite"
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY)")
        connection.commit()
        connection.close()
        result = audit_sqlite(path)
        self.assertEqual("ok", result["status"])
        self.assertEqual("ok", result["quick_check"])
        self.assertEqual(0, result["foreign_key_violations"])

    def test_non_database_is_reported(self) -> None:
        path = self.root / "broken.sqlite"
        path.write_bytes(b"not a database")
        result = audit_sqlite(path)
        self.assertEqual("error", result["status"])
        self.assertEqual("sqlite_open", result["errors"][0]["category"])


class CodexConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.rollout = (
            self.root
            / "sessions"
            / "2026"
            / "07"
            / "10"
            / f"rollout-{SESSION_ONE}.jsonl"
        )
        write_jsonl(
            self.rollout,
            [
                {"type": "session_meta", "payload": {"id": SESSION_ONE}},
                # A later session_meta must not redefine the file identity.
                {"type": "session_meta", "payload": {"id": SESSION_THREE}},
            ],
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_three_surface_differences_are_reported_without_mutation(self) -> None:
        index = self.root / "session_index.jsonl"
        write_jsonl(index, [{"id": SESSION_TWO}])
        state = self.root / "state_5.sqlite"
        create_codex_state(state, [(SESSION_ONE, str(self.rollout), 0, 1)])

        before_index = index.read_bytes()
        before_state = state.read_bytes()
        result = audit_codex_consistency(self.root)

        self.assertEqual(1, result["missing_from_index"])
        self.assertEqual(1, result["index_entries_missing_from_db"])
        self.assertEqual(0, result["session_files_missing_from_db"])
        self.assertEqual(0, result["session_files_unidentified"])
        self.assertEqual(before_index, index.read_bytes())
        self.assertEqual(before_state, state.read_bytes())

    def test_missing_rollout_is_an_error(self) -> None:
        write_jsonl(self.root / "session_index.jsonl", [{"id": SESSION_ONE}])
        create_codex_state(
            self.root / "state_5.sqlite",
            [(SESSION_ONE, str(self.root / "missing.jsonl"), 0, 1)],
        )
        result = audit_codex_consistency(self.root)
        self.assertEqual("error", result["status"])
        self.assertEqual(1, result["db_rollouts_missing_on_disk"])

    def test_rollout_outside_provider_root_is_an_error(self) -> None:
        write_jsonl(self.root / "session_index.jsonl", [{"id": SESSION_ONE}])
        create_codex_state(
            self.root / "state_5.sqlite",
            [(SESSION_ONE, str(self.root.parent / "external.jsonl"), 0, 1)],
        )
        result = audit_codex_consistency(self.root)
        self.assertEqual("error", result["status"])
        self.assertEqual(1, result["db_rollouts_outside_root"])

    def test_empty_threads_table_still_reports_index_and_file_differences(self) -> None:
        write_jsonl(self.root / "session_index.jsonl", [{"id": SESSION_TWO}])
        create_codex_state(self.root / "state_5.sqlite", [])
        result = audit_codex_consistency(self.root)
        self.assertEqual("warning", result["status"])
        self.assertEqual(1, result["index_entries_missing_from_db"])
        self.assertEqual(1, result["session_files_missing_from_db"])

    def test_source_audit_excludes_authentication_and_logs(self) -> None:
        write_jsonl(self.root / "session_index.jsonl", [{"id": SESSION_ONE}])
        create_codex_state(
            self.root / "state_5.sqlite", [(SESSION_ONE, str(self.rollout), 0, 1)]
        )
        (self.root / "auth.json").write_text('{"token":"secret"}', encoding="utf-8")
        (self.root / "logs_2.sqlite").write_bytes(b"large private logs")
        result = audit_source("codex", self.root)
        paths = {item["path"] for item in result["files"]}
        self.assertNotIn("auth.json", paths)
        self.assertNotIn("logs_2.sqlite", paths)
