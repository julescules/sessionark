from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sessionark.models import SessionArkError
from sessionark.repair import repair_jsonl
from sessionark.util import sha256_file as real_sha256_file


class RepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_repair_is_byte_preserving_and_reversible(self) -> None:
        source = self.root / "damaged.jsonl"
        original = b'\xef\xbb\xbf{"a":1}\r\nnot-json\n{"b":2}'
        source.write_bytes(original)
        bundle = self.root / "repair-bundle"

        result = repair_jsonl(source, bundle)
        output = bundle / "repaired.jsonl"
        rejects = bundle / "rejects.jsonl"

        self.assertEqual("repaired_with_rejects", result["status"])
        self.assertEqual(2, result["valid_records"])
        self.assertEqual(1, result["rejected_records"])
        self.assertEqual(b'\xef\xbb\xbf{"a":1}\r\n{"b":2}', output.read_bytes())
        rejected = json.loads(rejects.read_text(encoding="utf-8"))
        self.assertEqual(b"not-json\n", base64.b64decode(rejected["raw_base64"]))
        self.assertEqual(original, source.read_bytes())
        self.assertEqual(real_sha256_file(source), result["source_sha256"])
        self.assertEqual(real_sha256_file(output), result["output_sha256"])
        report = bundle / "report.json"
        complete = bundle / "COMPLETE"
        self.assertTrue(report.is_file())
        self.assertEqual(real_sha256_file(report), complete.read_text(encoding="ascii").strip())

    def test_existing_bundle_is_not_overwritten(self) -> None:
        source = self.root / "source.jsonl"
        source.write_text('{"ok":true}\n', encoding="utf-8")
        bundle = self.root / "bundle"
        bundle.mkdir()
        sentinel = bundle / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaises(SessionArkError):
            repair_jsonl(source, bundle)
        self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))

    def test_source_change_prevents_output_publication(self) -> None:
        source = self.root / "source.jsonl"
        source.write_text('{"ok":true}\n', encoding="utf-8")
        bundle = self.root / "bundle"
        source_calls = 0

        def changing_digest(path: Path) -> str:
            nonlocal source_calls
            if Path(path) == source:
                source_calls += 1
                return "a" * 64 if source_calls == 1 else "b" * 64
            return real_sha256_file(Path(path))

        with patch("sessionark.repair.sha256_file", side_effect=changing_digest):
            with self.assertRaises(SessionArkError):
                repair_jsonl(source, bundle)
        self.assertFalse(bundle.exists())
