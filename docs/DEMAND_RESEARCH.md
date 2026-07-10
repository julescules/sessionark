# Demand research — 2026-07-10

## Method

The project direction was selected after reviewing current GitHub Issues and repositories, Reddit, Hacker News, Lobsters, Stack Overflow, Product Hunt, publicly indexed X posts, and publicly reachable Facebook pages/groups.

Signals were scored on:

1. repeated independent reports;
2. severity and time lost;
3. a specific gap in existing open-source tools;
4. ability to ship a useful, testable MVP;
5. long-term community contribution surface;
6. maintenance and platform-dependency risk.

Facebook group content was commonly blocked by login walls, and X search exposed far fewer verifiable original posts than GitHub, Reddit, and HN. Those platforms were included when an original public page was readable, but inaccessible or promotional results were not counted as demand evidence.

## Shortlist

| Direction | Demand | Gap | MVP | Reach | Maintenance | Total / 25 |
|---|---:|---:|---:|---:|---:|---:|
| SessionArk — agent session integrity and recovery | 5.0 | 4.5 | 4.5 | 4.5 | 4.0 | **22.5** |
| IssueGarden — evidence-first issue triage | 4.5 | 4.0 | 3.5 | 4.0 | 3.0 | 19.0 |
| Windows First-Run Doctor | 4.5 | 4.5 | 4.5 | 3.5 | 3.0 | 20.0 |
| OpenCabinet — folder-preserving local OCR | 5.0 | 3.5 | 2.5 | 5.0 | 2.5 | 18.5 |
| StatementBridge — local bank-format converter | 4.0 | 4.0 | 4.0 | 4.0 | 2.5 | 18.5 |
| RestoreSpec — declarative backup restore drills | 4.0 | 3.5 | 4.0 | 3.5 | 3.0 | 18.0 |

SessionArk won because the pain is severe, current, and directly evidenced, while the missing layer can be implemented locally without a hosted service, platform credentials, OCR toolchain, or bank-specific parser maintenance.

## Primary need evidence

- [Claude Code #48334](https://github.com/anthropics/claude-code/issues/48334) — desktop update deletes indexes and JSONL history across projects; two projects lost all history and one represented 150+ hours.
- [Codex #19822](https://github.com/openai/codex/issues/19822) — state database and rollout JSONL exist, but a stale index prevents recent sessions from appearing or resuming.
- [Codex #20493](https://github.com/openai/codex/issues/20493) — chats disappear after update/import, a state database is corrupt, and manual JSONL viewing is needed.
- [Codex #24425](https://github.com/openai/codex/issues/24425) — malformed JSON history makes a session disappear until damaged records are manually removed.

These are different failure modes with the same user outcome: continuity appears lost, and recovery requires risky manual work.

## Existing tools and the remaining gap

- [Agent Sessions](https://github.com/jazzyalex/agent-sessions) is a mature local-first macOS browser/search/resume application with saved-session features.
- [coding_agent_session_search](https://github.com/Dicklesworthstone/coding_agent_session_search) provides broad multi-provider CLI/TUI indexing and search.
- [claude-session-backup](https://pypi.org/project/claude-session-backup/) focuses on Claude session backup.
- Usage tools such as [ccusage](https://github.com/ryoppippi/ccusage) analyze tokens and cost.

The chosen gap is not another viewer. It is a cross-platform, provider-aware integrity and recovery core with:

- content-addressed immutable snapshots;
- stable capture of SQLite main/WAL/journal files followed by backup of the private copy;
- strict JSONL health with reversible rejects;
- Codex file/database/index set comparison;
- full-object verification and isolated restore rehearsal;
- no transcript upload and no dependency on a hosted control plane.

## Why the other strong ideas were deferred

### IssueGarden

Maintainers report being overwhelmed by issue volume and AI-generated noise, while stale bots can close valid reports without human review ([HN discussion](https://news.ycombinator.com/item?id=44225352), [Lobsters discussion](https://lobste.rs/s/bkw5u0/no_stale_bots)). The opportunity is real, but a useful MVP needs GitHub authentication, repository-specific policy, and careful classification quality.

### Windows First-Run Doctor

Windows/WSL developers repeatedly lose hours to PATH, quoting, SDK, container, proxy, and encoding failures ([Reddit discussion](https://www.reddit.com/r/webdev/comments/1jgrdgl/guys_im_tired_of_spending_hours_configuring_my/)). It has a strong gap, but ongoing signature maintenance across many toolchains is larger than SessionArk's first release.

### OpenCabinet

Users want OCR/full-text search over existing folders without Docker or surrendering file organization ([Reddit](https://www.reddit.com/r/selfhosted/comments/1szhaug/indexing_and_ocr_solution_for_documents_that/), [HN](https://news.ycombinator.com/item?id=41700504)). A polished native OCR desktop app is valuable but substantially larger than a trustworthy first MVP.

### Community migration from Facebook

There is clear demand for preserving and moving community history when Facebook groups/chats are removed ([HN](https://news.ycombinator.com/item?id=42779776), [public Facebook post](https://www.facebook.com/marismith/posts/community-chats-in-facebook-groups-are-going-away-next-week-facebook-wants-you-t/1361622065331553/)). It was deferred because official export coverage is incomplete, identity cannot be migrated automatically, and platform/network effects dominate the engineering.

## MVP success criteria

The first release is successful when it can, on synthetic Codex and Claude stores:

1. exclude an `auth.json` sentinel and all symlinks;
2. find malformed or truncated JSONL without printing message text;
3. capture an active WAL database without opening or creating sidecars beside the provider database;
4. deduplicate a second unchanged snapshot;
5. detect object or manifest tampering;
6. atomically restore only to a new safe directory and reproduce every object hash;
7. salvage valid JSONL lines without changing the source and preserve rejected bytes;
8. report Codex file/database/index differences without automatically changing any of them.
