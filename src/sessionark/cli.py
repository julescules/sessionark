from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .adapters import PROVIDERS, default_root, discover
from .audit import audit_source
from .models import SessionArkError
from .render import write_report
from .repair import repair_jsonl
from .util import human_size, redact_home
from .vault import (
    create_snapshot,
    list_snapshots,
    restore_snapshot,
    verify_snapshot,
)


def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True))


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            pass


def _root_for(provider: str, supplied: str | None) -> Path:
    if supplied:
        return Path(supplied).expanduser()
    return default_root(provider)


def _print_audit(result: dict[str, Any]) -> None:
    summary = result["summary"]
    print(f"SessionArk audit: {result['provider']} ({result['status'].upper()})")
    print(f"  root: {result['root']}")
    print(
        "  files: "
        f"{summary['files']} total, {summary['files_with_warnings']} warning, "
        f"{summary['files_with_errors']} error"
    )
    consistency = result.get("consistency")
    if consistency:
        print(
            "  continuity: "
            f"{consistency['missing_from_index']} missing from index, "
            f"{consistency['db_rollouts_missing_on_disk']} rollout files missing, "
            f"{consistency['session_files_missing_from_db']} session files unindexed"
        )
    findings = [item for item in result["files"] if item["status"] != "ok"]
    for item in findings[:10]:
        print(f"  {item['status'].upper():7} {item['path']}")
    if len(findings) > 10:
        print(f"  ... {len(findings) - 10} additional file findings (use --report)")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sessionark",
        description="Backup, verify, and safely recover local AI coding-agent sessions.",
    )
    parser.add_argument("--version", action="version", version=f"sessionark {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    discover_parser = commands.add_parser(
        "discover", help="Find supported local agent session stores without reading transcripts."
    )
    discover_parser.add_argument("--json", action="store_true")

    audit_parser = commands.add_parser(
        "audit", help="Check JSONL, SQLite, and provider index consistency."
    )
    audit_parser.add_argument("--provider", choices=PROVIDERS, required=True)
    audit_parser.add_argument("--root")
    audit_parser.add_argument("--report", type=Path)
    audit_parser.add_argument("--json", action="store_true")

    doctor_parser = commands.add_parser(
        "doctor", help="Audit every supported provider found on this machine."
    )
    doctor_parser.add_argument("--json", action="store_true")

    snapshot_parser = commands.add_parser(
        "snapshot", help="Create an immutable, content-addressed snapshot."
    )
    snapshot_parser.add_argument("--provider", choices=PROVIDERS, required=True)
    snapshot_parser.add_argument("--root")
    snapshot_parser.add_argument("--vault", type=Path, required=True)
    snapshot_parser.add_argument("--label")
    snapshot_parser.add_argument("--json", action="store_true")

    list_parser = commands.add_parser("list", help="List snapshots in a vault.")
    list_parser.add_argument("--vault", type=Path, required=True)
    list_parser.add_argument("--json", action="store_true")

    verify_parser = commands.add_parser(
        "verify", help="Re-hash snapshot manifests and every referenced object."
    )
    verify_parser.add_argument("snapshot_id", nargs="?")
    verify_parser.add_argument("--vault", type=Path, required=True)
    verify_parser.add_argument("--json", action="store_true")

    restore_parser = commands.add_parser(
        "restore", help="Atomically restore a verified snapshot into a new directory."
    )
    restore_parser.add_argument("snapshot_id")
    restore_parser.add_argument("--vault", type=Path, required=True)
    restore_parser.add_argument("--target", type=Path, required=True)
    restore_parser.add_argument("--json", action="store_true")

    repair_parser = commands.add_parser(
        "repair-jsonl",
        help="Create a completion-marked bundle with valid records and reversible rejects.",
    )
    repair_parser.add_argument("source", type=Path)
    repair_parser.add_argument("--output-dir", type=Path, required=True)
    repair_parser.add_argument("--json", action="store_true")
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "discover":
        results = discover()
        for result in results:
            result["root"] = redact_home(str(result["root"]))
        if args.json:
            _json(results)
        else:
            for result in results:
                state = "found" if result["exists"] else "not found"
                print(
                    f"{result['provider']:7} {state:9} {result['root']} "
                    f"({result['file_count']} continuity files)"
                )
        return 0

    if args.command == "audit":
        root = _root_for(args.provider, args.root)
        result = audit_source(args.provider, root)
        if args.report:
            write_report(result, args.report)
        _json(result) if args.json else _print_audit(result)
        return 0 if result["status"] == "ok" else 2

    if args.command == "doctor":
        reports: list[dict[str, Any]] = []
        for provider in discover():
            if provider["exists"]:
                reports.append(audit_source(str(provider["provider"]), Path(str(provider["root"]))))
        aggregate = {
            "status": (
                "error"
                if any(item["status"] == "error" for item in reports)
                else "warning"
                if any(item["status"] == "warning" for item in reports)
                else "ok"
            ),
            "providers": reports,
        }
        if args.json:
            _json(aggregate)
        else:
            if not reports:
                print("No supported local session stores were found.")
            for report in reports:
                _print_audit(report)
        return 0 if aggregate["status"] == "ok" else 2

    if args.command == "snapshot":
        root = _root_for(args.provider, args.root)
        result = create_snapshot(args.provider, root, args.vault, args.label)
        if args.json:
            _json(result)
        else:
            summary = result["summary"]
            print(f"Created snapshot {result['snapshot_id']}")
            print(f"  provider: {result['provider']}")
            print(f"  vault: {result['vault']}")
            print(
                f"  captured: {summary['files']} files / "
                f"{human_size(summary['object_bytes'])}"
            )
            print(f"  deduplicated: {summary['deduplicated_files']} files")
            if (
                summary["files_with_errors"]
                or summary["capture_warnings"]
                or summary["consistency_status"] != "ok"
                or summary["source_set_changed"]
            ):
                print(
                    "  note: snapshot completed with health or capture findings; "
                    "inspect the manifest and run `sessionark audit`."
                )
        return 0

    if args.command == "list":
        snapshots = list_snapshots(args.vault)
        if args.json:
            _json(snapshots)
        elif not snapshots:
            print("No snapshots found.")
        else:
            for snapshot in snapshots:
                summary = snapshot.get("summary", {})
                print(
                    f"{snapshot.get('snapshot_id')}  {snapshot.get('provider', '?'):7}  "
                    f"{summary.get('files', '?')} files  "
                    f"{snapshot.get('status', 'ok'):20}  {snapshot.get('label') or ''}"
                )
        return 0 if all(item.get("status", "ok") == "ok" for item in snapshots) else 2

    if args.command == "verify":
        identifiers = (
            [args.snapshot_id]
            if args.snapshot_id
            else [item["snapshot_id"] for item in list_snapshots(args.vault)]
        )
        if not identifiers:
            raise SessionArkError("No snapshots found to verify.")
        results = [verify_snapshot(args.vault, identifier) for identifier in identifiers]
        if args.json:
            _json(results[0] if args.snapshot_id else results)
        else:
            for result in results:
                print(
                    f"{result['snapshot_id']}: {result['status'].upper()} "
                    f"({result['verified_files']}/{result['files']} objects verified)"
                )
                for error in result["errors"][:10]:
                    print(f"  ERROR {error.get('category')}: {error.get('path', '')}")
        return 0 if all(result["status"] == "ok" for result in results) else 2

    if args.command == "restore":
        result = restore_snapshot(args.vault, args.snapshot_id, args.target)
        if args.json:
            _json(result)
        else:
            print(
                f"Restored {result['restored_files']} files from {result['snapshot_id']} "
                f"into {result['target']}"
            )
        return 0

    if args.command == "repair-jsonl":
        result = repair_jsonl(args.source, args.output_dir)
        if args.json:
            _json(result)
        else:
            print(
                f"Wrote {result['valid_records']} valid records to {result['output']}; "
                f"preserved {result['rejected_records']} rejects in {result['rejects']} "
                f"(bundle: {result['bundle']})"
            )
        return 0 if result["rejected_records"] == 0 else 2

    raise SessionArkError(f"Unsupported command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except (SessionArkError, OSError, sqlite3.Error) as error:
        print(f"sessionark: {error}", file=sys.stderr)
        return 1
