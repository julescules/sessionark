# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project uses semantic versioning.

## [0.1.0] - 2026-07-10

### Added

- Read-only discovery and structural audit for Codex and Claude Code session stores.
- Strict JSON/JSONL checks and Codex file/database/index consistency findings.
- Source-write-free SQLite main/WAL/journal capture through a private logical copy.
- SHA-256 content-addressed snapshots, deduplication, manifest verification, and tamper detection.
- Staged, verified restore into a new directory without changing live provider state.
- Completion-marked JSONL repair bundles with byte-preserving base64 rejects.
- Windows-safe path validation, UTF-8 CLI output, synthetic fixtures, and cross-platform CI.
