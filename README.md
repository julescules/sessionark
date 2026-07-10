# SessionArk

**A semantic `fsck` and recovery layer for local AI coding-agent sessions.**

SessionArk snapshots the continuity data written by Codex and Claude Code, checks the files that make sessions resumable, and restores only into an isolated directory. It is built for the uncomfortable gap between “the transcript probably still exists” and “the app can actually find it.”

The initial release is a dependency-free Python CLI for Windows, macOS, and Linux.

## Why this project exists

Local agent history is valuable work, but it is spread across append-only JSONL files, indexes, and live SQLite state:

- A Claude Code update was reported to delete `sessions-index.json` and, for some projects, every session JSONL file; one affected project represented more than 150 hours of work ([anthropics/claude-code#48334](https://github.com/anthropics/claude-code/issues/48334)).
- Codex users have reported sessions that still exist in `state_5.sqlite` and rollout JSONL but disappear because `session_index.jsonl` is stale ([openai/codex#19822](https://github.com/openai/codex/issues/19822)).
- Other reports show a corrupt state database or malformed JSON history making existing chats appear empty or missing ([openai/codex#20493](https://github.com/openai/codex/issues/20493), [openai/codex#24425](https://github.com/openai/codex/issues/24425)).

Existing tools are strong at browsing, searching, resuming, and measuring usage. SessionArk is deliberately narrower: **immutable snapshots, structural integrity, cross-store consistency, byte-preserving salvage, and restore rehearsal**.

See [the demand research](docs/DEMAND_RESEARCH.md) for the source review and alternatives considered.

## What v0.1 does

- Discovers Codex and Claude Code session stores.
- Audits JSONL as strict UTF-8 JSON, with byte offsets and a distinct truncated-tail finding.
- Runs SQLite `quick_check` and `foreign_key_check` read-only.
- Compares Codex's three continuity surfaces without declaring any one of them the sole source of truth:
  - rollout JSONL files;
  - `state_5.sqlite` threads;
  - `session_index.jsonl`.
- Creates content-addressed snapshots with SHA-256 object and manifest verification.
- Copies the SQLite main/WAL/journal family without opening the provider database, then runs SQLite's online backup API only against that private copy.
- Deduplicates unchanged objects between snapshots.
- Computes Codex consistency from the captured objects and records when the provider file set changes during the capture window.
- Restores through a private sibling staging tree and atomically publishes only to a target that does not exist. Path traversal, drive paths, invalid Windows names, reparse points, and vault overlap are rejected.
- Repairs JSONL into a completion-marked bundle. Invalid records are preserved byte-for-byte as base64; the source is never modified.

SessionArk intentionally does **not** copy `auth.json`, provider settings, caches, attachments, `logs_2.sqlite`, or arbitrary files under the agent home directory.

## Quick start

Python 3.11 or newer is required.

### Windows PowerShell

```powershell
git clone https://github.com/julescules/sessionark.git D:\open-source-projects\sessionark
Set-Location -LiteralPath D:\open-source-projects\sessionark
python -X utf8 -m venv .venv
.\.venv\Scripts\python.exe -X utf8 -m pip install -e .

sessionark discover
sessionark audit --provider codex --report D:\SessionArkReports\codex-audit.md
sessionark snapshot --provider codex --vault D:\SessionArkVault --label "before Codex update"
sessionark list --vault D:\SessionArkVault
sessionark verify --vault D:\SessionArkVault
```

### macOS or Linux

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .

sessionark discover
sessionark audit --provider claude
sessionark snapshot --provider claude --vault /mnt/backup/sessionark
```

## Recovery workflow

First verify the vault, then restore to a path that does not yet exist (its parent must exist):

```powershell
sessionark verify 20260710T120000Z-a1b2c3d4 --vault D:\SessionArkVault
sessionark restore 20260710T120000Z-a1b2c3d4 `
  --vault D:\SessionArkVault `
  --target D:\SessionArkRecovery\20260710T120000Z-a1b2c3d4
```

SessionArk does not write the staged files back into `~/.codex` or `~/.claude`. A live restore needs provider-version-aware rules, application shutdown, a fresh pre-change snapshot, and rollback; that is intentionally outside v0.1.

To salvage a damaged JSONL file without changing the original:

```powershell
sessionark repair-jsonl D:\evidence\damaged.jsonl `
  --output-dir D:\recovery\damaged-repair
```

The bundle contains `repaired.jsonl`, `rejects.jsonl`, `report.json`, and a `COMPLETE` marker whose value is the report hash. The command removes its incomplete bundle if the source changes during analysis, and it never overwrites an existing output directory.

## Commands

| Command | Writes to agent source? | Purpose |
|---|---:|---|
| `discover` | No | Find supported stores and count continuity files. |
| `audit` | No | Check one provider's file and index health. |
| `doctor` | No | Audit every discovered provider. |
| `snapshot` | No | Write an immutable snapshot into a separate vault. |
| `list` | No | List vault snapshots. |
| `verify` | No | Re-hash manifests and all referenced objects. |
| `restore` | No | Atomically publish a verified restore into a new directory. |
| `repair-jsonl` | No | Produce a completion-marked repair bundle with reversible rejects. |

Use `--json` on every command for automation. Snapshot, list, verify, and restore require an explicit `--vault`, so an omitted argument cannot silently write to a system drive. Audit reports never include message bodies.

## Vault layout

```text
vault/
├── VERSION
├── objects/
│   └── sha256/ab/cdef...
├── snapshots/
│   └── 20260710T120000Z-a1b2c3d4/
│       ├── manifest.json
│       └── manifest.sha256
└── tmp/
```

Objects are content-addressed, but they are **not encrypted**. Agent transcripts can contain source code, paths, tool output, and secrets. Put the vault on storage whose access controls and encryption match the sensitivity of your work, and copy it to an independent backup destination.

## Safety model

- Provider roots are read-only.
- File collection is an explicit allowlist.
- Symlinks are skipped during discovery.
- SQLite source files are never opened. A stable private copy of the main database and transaction sidecars is made first, and the backup API runs only there. A main-file raw fallback is allowed only when no WAL/journal data exists.
- A snapshot manifest is published only after all objects are present.
- Restore validates and uses the same manifest object, writes with exclusive creation under a random private staging directory, verifies each restored hash, and renames the complete tree into place.
- Index differences are findings, not automatic repair instructions. Index-only history, subagent threads, and active sessions can all be legitimate.
- No network calls, telemetry, accounts, or cloud service.

Read [SECURITY.md](SECURITY.md) before sharing a vault or reject file.

## Roadmap

- Stable finding codes and a versioned repair-plan format.
- Snapshot diff and retention that never removes the only copy.
- A provider-version capability matrix.
- Optional Cursor, Gemini CLI, OpenCode, and Copilot CLI adapters.
- Codex index reconstruction in a staging copy, never directly against live state.
- Readable redacted export through adapters, without building another session browser.
- Signed release artifacts and native packaging.

## Development

```powershell
$env:TEMP = 'D:\open-source-projects\sessionark\tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$env:PYTHONPATH = 'D:\open-source-projects\sessionark\src'
python -X utf8 -m unittest discover -s tests -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [the architecture notes](docs/ARCHITECTURE.md).

## License

MIT
