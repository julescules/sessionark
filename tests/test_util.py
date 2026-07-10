from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sessionark.models import UnsafePathError
from sessionark.util import normalize_relative_path, safe_join


class SafePathTests(unittest.TestCase):
    def test_unicode_relative_path_is_supported(self) -> None:
        self.assertEqual(
            "会话/日本語/session.jsonl", normalize_relative_path("会话/日本語/session.jsonl")
        )

    def test_traversal_absolute_ads_and_devices_are_rejected(self) -> None:
        unsafe = [
            "../escape",
            "/absolute/path",
            "C:/drive/path",
            "folder/file:stream",
            "CON",
            "folder/NUL.txt",
            "folder/trailing.",
            "folder/trailing ",
            "folder/name?.jsonl",
            "folder/name*.jsonl",
            "folder/name|.jsonl",
            "folder/name<.jsonl",
            "folder/name>.jsonl",
            'folder/name".jsonl',
            "folder/COM¹.txt",
            "folder/LPT²",
        ]
        for value in unsafe:
            with self.subTest(value=value), self.assertRaises(UnsafePathError):
                normalize_relative_path(value)

    def test_safe_join_stays_below_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = safe_join(root, "nested/file.jsonl")
            self.assertTrue(candidate.is_relative_to(root.resolve()))
