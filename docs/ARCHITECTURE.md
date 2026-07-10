# Architecture

## Positioning

SessionArk is a semantic filesystem checker and reversible recovery layer for agent sessions. It is not a transcript search UI, an agent orchestrator, or a general-purpose backup engine.

## Data flow

```text
provider allowlist
      │
      ▼
read-only audit ─────► structural report
      │
      ▼
stable file capture / private SQLite family copy
      │
      ▼
SHA-256 objects ─────► immutable snapshot manifest
      │
      ├──────────────► full-object verification
      │
      └──────────────► isolated restore directory
```

## Modules

- `adapters.py`: provider discovery and explicit file allowlists.
- `audit.py`: strict JSON/JSONL parsing, SQLite health checks, and Codex three-surface consistency counts.
- `sqlite_safe.py`: stable main/WAL/journal copy followed by logical backup of the private copy.
- `vault.py`: stable capture, content-addressed objects, manifests, verification, and staged atomic restore.
- `repair.py`: byte-preserving JSONL salvage in a completion-marked bundle.
- `render.py`: structural-only JSON and Markdown reports.
- `cli.py`: command-line boundary and stable automation output.

## Codex consistency model

Codex has at least three useful but non-equivalent surfaces:

- **F**: rollout files. A file's identity comes only from its first non-empty `session_meta` record.
- **D**: `state_5.sqlite` thread rows.
- **I**: `session_index.jsonl` entries.

SessionArk reports set differences but does not assume `F = D = I`. Index-only entries can be legitimate history. Database/file entries missing from the index can be active subagents or other non-sidebar sessions. No difference is automatically deleted or merged.

## Snapshot consistency

JSONL files are copied with pre/post size and nanosecond-mtime checks and retried if they change. If a file remains volatile, the complete final copy is retained with an explicit capture warning and audited for a truncated tail.

SessionArk never opens the provider-owned SQLite database. It repeatedly copies the main file plus `-wal`/`-journal` sidecars until the source metadata is stable, opens only that private family, and uses `sqlite3.Connection.backup()` to create the content object. A raw-main fallback is accepted only when transaction sidecars contain no data; otherwise capture fails without publishing a snapshot.

A snapshot spans a capture window rather than one global instant. Every entry records its capture time and the manifest has a separate content-tree digest. Codex cross-store consistency is calculated from the captured CAS objects. A second allowlist discovery records added or removed source paths so the manifest cannot silently claim a closed file set.

## Crash behavior

Objects are written under a temporary name, flushed, hashed, then atomically moved into the object store. The manifest is published after all objects exist. A crash may leave an unreachable object, but must not leave a published manifest pointing to an incomplete object.

## Restore boundary

Restore loads a manifest once, verifies that exact object and every referenced CAS object, then writes to a random private sibling directory with exclusive file creation. It verifies every copied hash and renames the complete tree to the requested target. The target must not exist and its canonical parent must already exist. Windows rejects requested paths containing reparse points; POSIX canonicalizes legitimate symlink ancestors before pinning the real parent identity. The target cannot overlap the vault. Absolute manifest paths, traversal, drive-qualified paths, invalid Windows filename characters, reserved device names (including superscript COM/LPT forms), and trailing-dot/space components are rejected.

## Repair publication

`repair-jsonl` reserves a new output directory, writes byte-preserved valid records and base64 rejects, compares the source identity and hash again, writes `report.json`, and writes `COMPLETE` last. A bundle without a valid completion marker is not published output and is removed when SessionArk still owns the directory.
