# Operation log — initial SessionArk build

- Time: 2026-07-10 15:34:26 +08:00
- Finalized: 2026-07-10 16:09:48 +08:00
- Target: `D:\open-source-projects\sessionark`
- Objective: research a repeated unmet need, create a useful open-source MVP, verify it, and keep all generated project data off C:.

## Evidence gathered before changes

- Checked C: and D: free space; D: had about 84.14 GiB free at the start of work.
- Confirmed the available runtime paths: Python on `D:\python\python.exe`, Node.js on D:, and Git available.
- Inspected only structural metadata from the local agent stores:
  - Codex root exists with 146 rollout JSONL files at the time of inspection.
  - The first Codex record exposes the keys `timestamp`, `type`, and `payload`; no conversation values were printed.
  - `state_5.sqlite` passed `PRAGMA quick_check` and contains a `threads` table.
  - Claude Code root exists with three project JSONL files at the time of inspection.
- Did not print, export, copy, or modify any real conversation body.

## Research and selection

- Reviewed current GitHub Issues, repositories, Reddit, Hacker News, Lobsters, Stack Overflow, Product Hunt, public X results, and public Facebook results.
- X and Facebook results hidden behind login walls were excluded from demand counts.
- Selected SessionArk over IssueGarden, Windows First-Run Doctor, OpenCabinet, StatementBridge, and RestoreSpec because session loss has repeated current reports and the missing integrity/recovery layer can be delivered as a local, testable MVP.
- Detailed sources and scoring are recorded in `docs/DEMAND_RESEARCH.md`.

## Key operations

1. Created `D:\open-source-projects\sessionark` after resolving and confirming the target was on D: and did not already exist.
2. Added the Python package, CLI, tests, GitHub Actions workflow, documentation, security policy, contribution guide, and PowerShell scheduling example using patch-based file edits.
3. Ran UTF-8 compile and unit-test passes with `TEMP`, `TMP`, and `PYTHONPATH` explicitly pointed to D:.
4. Exercised JSONL corruption, strict JSON, SQLite integrity, live WAL backup, CAS deduplication, tamper detection, traversal rejection, non-empty restore rejection, symlink exclusion, repair reversibility, and CLI end-to-end flows.
5. Attempted a wheel build with the existing local packaging stack. It failed because setuptools 68.2.2 had no `bdist_wheel`; the follow-on PowerShell selection also used an unavailable `Select-Object -Single` parameter.
6. Switched paths instead of repeating the failure:
   - verified the current PyPA `wheel` release on PyPI;
   - installed `wheel==0.47.0` and its packaging dependency only into `D:\open-source-projects\sessionark\tmp\build-deps`;
   - rebuilt with no build isolation and no dependency resolution;
   - installed the resulting wheel only into a D:-resident temporary target and ran `python -m sessionark --version`.
7. Removed only the explicitly verified generated intermediates listed below.
8. Applied independent review fixes for source-write-free SQLite/WAL capture, captured-object consistency, strict manifest handling, staged atomic restore, portable Windows path checks, UTF-8 CLI output, and completion-marked repair bundles.
9. Initialized a local Git repository on branch `main`, staged the complete initial tree, and passed `git diff --cached --check`; no commit or remote was created.
10. Expanded CI to Python 3.11/3.13 on Ubuntu, Windows, and macOS, building and installing the wheel before running tests.
11. Rebuilt the final wheel from the reviewed source. A PowerShell array-matching expression initially misclassified the new `--output-dir` help as stale; direct inspection confirmed the option and all 11 modules, so the already-built candidate was used without repeating the build.
12. Atomically replaced the stale retained wheel only after isolated install checks, then independently installed and tested the published path.

## Changed paths

- Retained source and project metadata:
  - `src/sessionark/`
  - `tests/`
  - `docs/`
  - `examples/`
  - `.github/workflows/test.yml`
  - `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `LICENSE`, `pyproject.toml`, `.gitignore`
- Retained the current verified build:
  - `builds/sessionark-0.1.0-py3-none-any.whl`
  - Final size after the cross-platform CI fix: 29,278 bytes
  - Final SHA-256 after the cross-platform CI fix: `83412D9B8636E4AC3073D916BE4F3FE6DFEFBB3B2E50DB9E6E6E61D050EA4F21`

## Generated intermediates removed

The following paths were resolved again, confirmed to remain under the project root, then removed with literal paths:

- `tmp/build-deps`
- `tmp/wheel-install-test`
- `tmp/pip-cache`
- `build`
- `src/sessionark.egg-info`
- `src/sessionark/__pycache__`
- `tests/__pycache__`

Removed: 124 files totaling 1,733,460 bytes (about 1.65 MiB).

After final validation, a second whitelist cleanup removed:

- `tmp/` (D:-local build dependencies, pip cache, candidate install checks, and validation data)
- `build/`
- `src/sessionark.egg-info/`
- `src/sessionark/__pycache__/`
- `tests/__pycache__/`
- `builds/sessionark-0.1.0-py3-none-any.whl.pre-final-backup` (the superseded 24,046-byte wheel)

Second cleanup: 196 files totaling 2,331,217 bytes. Both path-existence checks and D: free-space checks were run afterward. D: free space after cleanup was 90,315,862,016 bytes; the instantaneous free-space delta was 2,215,936 bytes because other processes can allocate concurrently.

## Validation results at this checkpoint

- Python compile: passed.
- Unit tests: 44/44 passed in the final local run and in independent validation.
- Wheel build: passed after using the D:-local temporary build dependency.
- Wheel isolated import/version smoke test: `sessionark 0.1.0` passed.
- Published-wheel probes confirmed `sqlite_safe.py`, the completion-bundle API, console entry point, and all 11 runtime modules.
- Source files, tests, local Git metadata, and the retained wheel were verified present after cleanup; all listed intermediates and the stale backup were verified absent.
- Independent validation found no blocking functional defects and confirmed that active WAL audit/snapshot did not alter source hashes, mtimes, directory entries, or create a source `-shm` file.

## Explicitly not done

- No files under `~/.codex` or `~/.claude` were modified.
- No real session snapshot was created from the user's history.
- No live index, SQLite, or provider state repair was attempted.
- No GitHub repository, release, package publication, account action, or external message was created.
- No registry, service, proxy, browser profile, or system setting was changed.
- No C:-resident project artifact was generated intentionally.

## Remaining work / risk

- GitHub publication details are recorded separately in `docs/logs/2026-07-10-github-publish.md`.
- Migrate the setuptools license metadata to the newer SPDX form before its announced 2027 deprecation deadline; the current metadata builds successfully.
- Session data can contain secrets; vault objects provide integrity but are not encrypted or signed.
- Provider formats can change. Unknown formats must remain read-only and must not trigger automatic repair.
