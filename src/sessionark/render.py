from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .util import atomic_write_bytes, atomic_write_text, human_size


def audit_markdown(result: dict[str, Any]) -> str:
    summary = result.get("summary", {})
    lines = [
        "# SessionArk audit report",
        "",
        f"- Provider: `{result.get('provider', 'unknown')}`",
        f"- Root: `{result.get('root', 'unknown')}`",
        f"- Audited: `{result.get('audited_at', 'unknown')}`",
        f"- Status: **{str(result.get('status', 'unknown')).upper()}**",
        f"- Files: {summary.get('files', 0)}",
        f"- Files with warnings: {summary.get('files_with_warnings', 0)}",
        f"- Files with errors: {summary.get('files_with_errors', 0)}",
        "",
    ]
    consistency = result.get("consistency")
    if consistency:
        lines.extend(
            [
                "## Codex continuity checks",
                "",
                f"- Index entries: {consistency.get('index_entries', 0)}",
                f"- Database threads: {consistency.get('db_threads', 0)}",
                f"- Visible threads absent from index: {consistency.get('missing_from_index', 0)}",
                f"- Database rollout files missing: {consistency.get('db_rollouts_missing_on_disk', 0)}",
                f"- Session files absent from database: {consistency.get('session_files_missing_from_db', 0)}",
                "",
            ]
        )
    problems = [item for item in result.get("files", []) if item.get("status") != "ok"]
    lines.extend(["## File findings", ""])
    if not problems:
        lines.append("No file-level findings.")
    else:
        lines.append("| Status | Path | Size |")
        lines.append("|---|---|---:|")
        for item in problems:
            size = int(item.get("details", {}).get("bytes", 0))
            lines.append(
                f"| {str(item.get('status')).upper()} | `{item.get('path')}` | {human_size(size)} |"
            )
    lines.append("")
    lines.append(
        "This report contains structural metadata only; SessionArk does not include conversation text in audit reports."
    )
    lines.append("")
    return "\n".join(lines)


def write_report(result: dict[str, Any], path: Path) -> None:
    path = path.expanduser().resolve()
    if path.suffix.casefold() in {".md", ".markdown"}:
        atomic_write_text(path, audit_markdown(result))
    else:
        atomic_write_bytes(
            path,
            (json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
        )
