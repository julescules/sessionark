# Operation log — GitHub publication

- Started: 2026-07-10 16:17 +08:00
- Local project: `D:\open-source-projects\sessionark`
- Intended public repository: `https://github.com/julescules/sessionark`
- Objective: install GitHub CLI without using C: for generated data, authenticate, publish `main`, verify CI, and create the v0.1.0 release.

## Evidence before changes

- Local repository was on `main` with no commits, no remote, and 31 staged project files.
- `git diff --cached --check` passed; no unrelated working-tree changes were present.
- The connected GitHub account and subsequent CLI login both identified `julescules` (GitHub user ID 131376318).
- `julescules/sessionark` did not exist or was not accessible before publication.
- `gh` was not installed locally, so publication could not proceed through the required authenticated CLI path.

## Portable GitHub CLI installation

- Queried the official `cli/cli` GitHub Release API and selected `gh 2.96.0`, published 2026-07-02.
- Downloaded the Windows AMD64 ZIP and official checksum file only under `D:\tools\gh-portable\tmp`.
- Verified archive SHA-256: `C2D6ACC935CD2F00E2144D7E036D5CD82E6B6BD5594E8C75AA75EF2A4ED6AAC3`.
- Installed to `D:\tools\gh-portable\releases\2.96.0`.
- Verified `gh.exe` SHA-256: `CD79F16203F1FBE56937C4C96E2B6EADD10549418DCB241D91576AC77AF0AC8B`.
- Kept GitHub CLI configuration under `D:\tools\gh-portable\config` and completed browser device authorization as `julescules`.
- Removed the downloaded ZIP, checksum file, and extraction staging after verification.

Two installation assumptions failed safely before the final successful move:

1. The ZIP used `bin\gh.exe` at its root rather than a versioned wrapper directory.
2. The first corrected move had no pre-created `releases` parent and PowerShell reported a non-terminating error.

No partial release directory was accepted. The retained, checksum-verified staging was reused with strict error handling and an explicit parent directory; no repeated download was required.

## Repository preparation

- Replaced the README clone placeholder with `https://github.com/julescules/sessionark.git`.
- Added Homepage, Repository, Issues, and Changelog URLs to `pyproject.toml`.
- Rebuilt the wheel because those URLs are embedded in package metadata.
- The first strict-mode test invocation stopped because `unittest -v` writes normal progress to stderr; the existing verified candidate was reused under standard native-command handling rather than rebuilt.
- Final wheel: `builds/sessionark-0.1.0-py3-none-any.whl`.
- Final wheel size: 29,212 bytes.
- Final wheel SHA-256: `DCB6504DB8B3B264B3AC864D11C74BC83206CCFD4B958661086B458403630E68`.
- Unit tests: 44/44 passed after the URL and metadata changes.

## Publication status

Publication is in progress. This section will be updated after the repository, push, CI run, tag, and release are verified.
