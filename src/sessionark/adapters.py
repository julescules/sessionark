from __future__ import annotations

import os
from pathlib import Path

from .models import SessionArkError, SourceFile, UnsafePathError
from .util import normalize_relative_path

PROVIDERS = ("codex", "claude", "custom")


def default_root(provider: str, home: Path | None = None) -> Path:
    home = home or Path.home()
    if provider == "codex":
        return home / ".codex"
    if provider == "claude":
        return home / ".claude"
    raise SessionArkError("The custom provider requires an explicit --root.")


def discover(home: Path | None = None) -> list[dict[str, object]]:
    home = home or Path.home()
    providers: list[dict[str, object]] = []
    for name in ("codex", "claude"):
        root = default_root(name, home)
        providers.append(
            {
                "provider": name,
                "root": str(root),
                "exists": root.is_dir(),
                "file_count": len(collect_source_files(name, root)) if root.is_dir() else 0,
            }
        )
    return providers


def _kind_for(path: Path) -> str:
    lowered = path.name.casefold()
    if lowered.endswith(".jsonl"):
        return "jsonl"
    if lowered.endswith(".sqlite") or lowered.endswith(".db"):
        return "sqlite"
    if lowered.endswith(".json"):
        return "json"
    return "binary"


def _ensure_real_file(root: Path, path: Path) -> SourceFile | None:
    if path.is_symlink() or not path.is_file():
        return None
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise UnsafePathError(f"Source file escaped provider root: {path}")
    relative = normalize_relative_path(resolved_path.relative_to(resolved_root))
    return SourceFile("", resolved_root, resolved_path, relative, _kind_for(path))


def _walk_selected(root: Path, start: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if not start.is_dir() or start.is_symlink():
        return []
    selected: list[Path] = []
    for directory, dirnames, filenames in os.walk(start, followlinks=False):
        directory_path = Path(directory)
        dirnames[:] = [
            name for name in dirnames if not (directory_path / name).is_symlink()
        ]
        for name in filenames:
            path = directory_path / name
            if path.is_symlink():
                continue
            lowered = name.casefold()
            if any(lowered.endswith(suffix) for suffix in suffixes):
                selected.append(path)
    return selected


def collect_source_files(provider: str, root: Path) -> list[SourceFile]:
    if provider not in PROVIDERS:
        raise SessionArkError(f"Unknown provider: {provider}")
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise SessionArkError(f"Provider root does not exist: {root}")

    candidates: list[Path] = []
    if provider == "codex":
        # Deliberately exclude auth.json, config.toml, logs, cache, attachments,
        # and other unrelated data. SessionArk snapshots only continuity data.
        candidates.extend(_walk_selected(root, root / "sessions", (".jsonl",)))
        candidates.extend(_walk_selected(root, root / "archived_sessions", (".jsonl",)))
        for name in ("session_index.jsonl", "state_5.sqlite"):
            path = root / name
            if path.is_file() and not path.is_symlink():
                candidates.append(path)
    elif provider == "claude":
        candidates.extend(_walk_selected(root, root / "projects", (".jsonl",)))
        candidates.extend(
            _walk_selected(root, root / "projects", ("sessions-index.json",))
        )
    else:
        candidates.extend(_walk_selected(root, root, (".jsonl", ".json", ".sqlite", ".db")))

    unique: dict[str, SourceFile] = {}
    for candidate in candidates:
        checked = _ensure_real_file(root, candidate)
        if checked is None:
            continue
        item = SourceFile(
            provider=provider,
            root=checked.root,
            path=checked.path,
            relative_path=checked.relative_path,
            kind=checked.kind,
        )
        unique[item.relative_path] = item
    return sorted(
        unique.values(), key=lambda item: (item.relative_path.casefold(), item.relative_path)
    )
