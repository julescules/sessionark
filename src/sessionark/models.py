from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceFile:
    """A provider-owned file that is safe and useful to archive."""

    provider: str
    root: Path
    path: Path
    relative_path: str
    kind: str


class SessionArkError(RuntimeError):
    """Base class for expected, user-facing SessionArk errors."""


class UnsafePathError(SessionArkError):
    """Raised when a path escapes its declared root."""


class VaultCorruptionError(SessionArkError):
    """Raised when a content-addressed object fails verification."""
