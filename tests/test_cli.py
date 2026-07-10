from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from sessionark.cli import main

from tests.helpers import create_codex_fixture


class CliSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.source = self.base / "codex"
        create_codex_fixture(self.source)
        self.vault = self.base / "vault"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_audit_snapshot_verify_and_restore_commands(self) -> None:
        code, output, error = self.run_cli(
            [
                "audit",
                "--provider",
                "codex",
                "--root",
                str(self.source),
                "--json",
            ]
        )
        self.assertEqual(0, code, error)
        self.assertEqual("ok", json.loads(output)["status"])

        code, output, error = self.run_cli(
            [
                "snapshot",
                "--provider",
                "codex",
                "--root",
                str(self.source),
                "--vault",
                str(self.vault),
                "--json",
            ]
        )
        self.assertEqual(0, code, error)
        snapshot_id = json.loads(output)["snapshot_id"]

        code, output, error = self.run_cli(
            ["verify", snapshot_id, "--vault", str(self.vault), "--json"]
        )
        self.assertEqual(0, code, error)
        self.assertEqual("ok", json.loads(output)["status"])

        target = self.base / "restore"
        code, output, error = self.run_cli(
            [
                "restore",
                snapshot_id,
                "--vault",
                str(self.vault),
                "--target",
                str(target),
                "--json",
            ]
        )
        self.assertEqual(0, code, error)
        self.assertEqual(3, json.loads(output)["restored_files"])
        self.assertEqual(3, sum(path.is_file() for path in target.rglob("*")))

    def test_repair_findings_use_nonzero_finding_exit(self) -> None:
        source = self.base / "damaged.jsonl"
        source.write_bytes(b'{"ok":true}\nbad\n')
        bundle = self.base / "repair-bundle"
        code, output, error = self.run_cli(
            [
                "repair-jsonl",
                str(source),
                "--output-dir",
                str(bundle),
                "--json",
            ]
        )
        self.assertEqual(2, code, error)
        self.assertEqual(1, json.loads(output)["rejected_records"])

    def test_json_output_reconfigures_a_legacy_windows_stream_to_utf8(self) -> None:
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp936", errors="strict")
        with patch("sys.stdout", stream):
            code = main(
                [
                    "snapshot",
                    "--provider",
                    "codex",
                    "--root",
                    str(self.source),
                    "--vault",
                    str(self.vault),
                    "--label",
                    "日本語会话",
                    "--json",
                ]
            )
            stream.flush()
        payload = raw.getvalue().decode("utf-8")
        stream.detach()
        self.assertEqual(0, code)
        self.assertEqual("日本語会话", json.loads(payload)["label"])
