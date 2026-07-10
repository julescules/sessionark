from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .audit import strict_json_loads
from .models import SessionArkError
from .util import atomic_write_bytes, canonical_json_bytes, sha256_file, utc_now

REPAIRED_NAME = "repaired.jsonl"
REJECTS_NAME = "rejects.jsonl"
REPORT_NAME = "report.json"
COMPLETE_NAME = "COMPLETE"


def _directory_identity(path: Path) -> tuple[int, int]:
    result = path.lstat()
    if not path.is_dir() or path.is_symlink():
        raise SessionArkError(f"Repair bundle is not a real directory: {path}")
    return result.st_dev, result.st_ino


def repair_jsonl(
    source: Path,
    output_directory: Path,
) -> dict[str, Any]:
    """Create a completion-marked repair bundle without modifying the source.

    The directory itself is reserved with an exclusive create. Consumers should
    treat a bundle as published only when COMPLETE exists and matches report.json.
    """

    source = source.expanduser().resolve()
    output_directory = output_directory.expanduser().absolute()
    if not source.is_file():
        raise SessionArkError(f"JSONL source does not exist: {source}")
    if os.path.lexists(output_directory):
        raise SessionArkError("Repair output directory already exists; refusing to overwrite it.")
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    output_directory.mkdir(mode=0o700, exist_ok=False)
    bundle_identity = _directory_identity(output_directory)

    output = output_directory / REPAIRED_NAME
    rejects = output_directory / REJECTS_NAME
    report_path = output_directory / REPORT_NAME
    complete_path = output_directory / COMPLETE_NAME
    valid_records = 0
    rejected_records = 0
    blank_lines = 0
    offset = 0
    source_stat_before = source.stat()
    source_digest_before = sha256_file(source)
    published = False
    try:
        with source.open("rb") as source_handle, output.open("xb") as output_handle, rejects.open(
            "xb"
        ) as rejects_handle:
            for line_number, raw_line in enumerate(source_handle, start=1):
                line_offset = offset
                offset += len(raw_line)
                payload = raw_line.rstrip(b"\r\n")
                if not payload.strip():
                    blank_lines += 1
                    continue
                try:
                    encoding = "utf-8-sig" if line_number == 1 else "utf-8"
                    value = strict_json_loads(payload.decode(encoding, errors="strict"))
                    if not isinstance(value, dict):
                        raise ValueError("JSONL record is not an object")
                    output_handle.write(raw_line)
                    valid_records += 1
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                    rejected = {
                        "line": line_number,
                        "byte_offset": line_offset,
                        "error": str(error),
                        "raw_base64": base64.b64encode(raw_line).decode("ascii"),
                    }
                    rejects_handle.write(canonical_json_bytes(rejected))
                    rejected_records += 1
            output_handle.flush()
            os.fsync(output_handle.fileno())
            rejects_handle.flush()
            os.fsync(rejects_handle.fileno())

        output_digest = sha256_file(output)
        rejects_digest = sha256_file(rejects)
        source_stat_after = source.stat()
        source_digest_after = sha256_file(source)
        if (
            source_digest_before != source_digest_after
            or source_stat_before.st_size != source_stat_after.st_size
            or source_stat_before.st_mtime_ns != source_stat_after.st_mtime_ns
            or source_stat_before.st_dev != source_stat_after.st_dev
            or source_stat_before.st_ino != source_stat_after.st_ino
        ):
            raise SessionArkError(
                "Source changed while the repair plan was being produced; no complete bundle was published."
            )
        if _directory_identity(output_directory) != bundle_identity:
            raise SessionArkError("Repair output directory identity changed during creation.")

        report: dict[str, Any] = {
            "schema_version": 1,
            "status": "ok" if rejected_records == 0 else "repaired_with_rejects",
            "repaired_at": utc_now(),
            "source": str(source),
            "bundle": str(output_directory),
            "output": str(output),
            "rejects": str(rejects),
            "report": str(report_path),
            "complete_marker": str(complete_path),
            "valid_records": valid_records,
            "rejected_records": rejected_records,
            "blank_lines_removed": blank_lines,
            "source_sha256": source_digest_before,
            "output_sha256": output_digest,
            "rejects_sha256": rejects_digest,
        }
        report_bytes = canonical_json_bytes(report)
        report_digest = hashlib.sha256(report_bytes).hexdigest()
        atomic_write_bytes(report_path, report_bytes)
        atomic_write_bytes(complete_path, (report_digest + "\n").encode("ascii"))
        published = True
        report["report_sha256"] = report_digest
        return report
    finally:
        if not published and output_directory.exists():
            try:
                unchanged = _directory_identity(output_directory) == bundle_identity
            except (OSError, SessionArkError):
                unchanged = False
            if unchanged:
                shutil.rmtree(output_directory)
