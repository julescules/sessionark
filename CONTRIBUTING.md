# Contributing

SessionArk accepts small, evidence-backed changes. A provider adapter must be based on documented behavior or sanitized fixtures from a real released version; do not infer writable formats from filenames alone.

## Development rules

1. Provider homes remain read-only in tests and production code.
2. New collected paths must be allowlisted and justified. Authentication files, raw logs, caches, and unrelated app state are out of scope.
3. Every repair produces a derivative or a reviewable plan. No in-place repair.
4. Manifest paths are untrusted input.
5. Tests must cover malformed data and rollback behavior, not only happy paths.
6. Reports and test fixtures must not contain real conversations or credentials.

Run the standard-library test suite:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Pull requests should describe the observed provider version, the evidence for the format, the failure mode, and how the change avoids harming unknown future formats.
