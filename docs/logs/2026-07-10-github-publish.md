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

- Configured the local commit identity as `julescules <131376318+julescules@users.noreply.github.com>`.
- Created initial commit `f4c174e3934d0a1007ba6ac3f6bca9d2d541255e` (`Initial release of SessionArk`).
- Created the public repository `https://github.com/julescules/sessionark`.
- The first push was rejected because the OAuth token lacked the `workflow` scope; the repository remained empty. Browser authorization added only that scope, after which `main` pushed successfully and the remote head matched the local commit.
- Enabled Issues, disabled the unused wiki, set the repository homepage, and added the topics `ai-agents`, `backup`, `claude-code`, `codex`, `jsonl`, and `recovery`.
- Removed 166 D:-local intermediate files totaling 2,037,475 bytes after the final wheel and tests were verified. The current wheel was preserved.

GitHub Actions run `29080014418` then failed on macOS while Ubuntu 3.11 passed the full build/install/test/version flow. The evidence-backed causes were:

1. macOS temporary paths use the system `/var` -> `/private/var` symlink; restore rejected this legitimate ancestor before canonicalizing the requested target.
2. One source-change test compared the lexical `/var` path with the canonical `/private/var` path.
3. One collision test relied on two Unicode casefold-colliding filenames coexisting on the default APFS filesystem.

No v0.1.0 tag or GitHub Release has been created. The focused cross-platform fix was explicitly approved and implemented: POSIX restore targets are canonicalized before parent identity checks, the source-change test compares canonical paths, and the collision test uses synthetic source descriptors instead of filesystem-dependent Unicode names. Windows reparse rejection and staged restore protections remain enabled.

Post-fix verification before the second push:

- Local tests: 46 total; 45 passed and the POSIX-only symlink test was skipped on Windows as designed.
- Independent read-only validation found no blocking issue and confirmed that existing/dangling targets, Windows reparse checks, overlap checks, parent/staging identities, and publication-time checks remain intact.
- Rebuilt and isolated-installed the wheel; installed `vault.py` matched the source byte-for-byte.
- CI-fix wheel size: 29,278 bytes.
- CI-fix wheel SHA-256: `83412D9B8636E4AC3073D916BE4F3FE6DFEFBB3B2E50DB9E6E6E61D050EA4F21`.
- Removed 146 D:-local build/intermediate files totaling 1,857,319 bytes and verified the new wheel remained present.
