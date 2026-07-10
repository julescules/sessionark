# Security policy

## Data sensitivity

SessionArk vault objects are byte-preserving copies of local agent continuity files. They may contain proprietary source code, personal paths, prompts, command output, credentials pasted into a conversation, or secrets printed by a tool.

SessionArk provides integrity, not encryption or authenticity:

- SHA-256 detects accidental or malicious object changes after capture.
- The vault is not encrypted.
- The manifest digest is not a digital signature.
- Reject files from `repair-jsonl` preserve invalid source bytes as base64 and are just as sensitive as the original.

Keep vaults and reports on access-controlled storage. Use full-disk encryption or an established encrypted backup tool rather than adding custom encryption to SessionArk.

## Safe reporting

Built-in audit reports contain structural metadata, counts, relative file paths, and parser errors. They do not contain conversation bodies. Before filing a bug, still inspect reports for private directory names and avoid attaching vault objects or reject files.

## Supported write boundaries

The v0.1 CLI never writes into the provider source root. It may write only to:

- the explicitly selected vault;
- an explicitly selected restore target that does not yet exist;
- an explicit, new `repair-jsonl` output bundle directory;
- an explicit audit report path.

Live index or database repair is not supported.

## Reporting a vulnerability

Until a public repository security contact is configured, do not include real session data in a public report. Provide a minimal synthetic fixture and a description of the affected command and version.
