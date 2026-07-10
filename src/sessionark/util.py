from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unicodedata
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .models import UnsafePathError

WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
    "com¹",
    "com²",
    "com³",
    "lpt¹",
    "lpt²",
    "lpt³",
}
WINDOWS_INVALID_FILENAME_CHARACTERS = set('<>:"|?*')


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def snapshot_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def normalize_relative_path(value: str | Path) -> str:
    raw = str(value).replace("\\", "/")
    relative = PurePosixPath(raw)
    if relative.is_absolute() or not relative.parts:
        raise UnsafePathError(f"Expected a non-empty relative path, got: {value}")
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise UnsafePathError(f"Unsafe relative path: {value}")
        if any(character in WINDOWS_INVALID_FILENAME_CHARACTERS for character in part) or any(
            ord(character) < 32 for character in part
        ):
            raise UnsafePathError(f"Unsafe path component: {part!r}")
        if part.endswith((" ", ".")):
            raise UnsafePathError(f"Trailing spaces or dots are not allowed: {part!r}")
        device_name = part.split(".", 1)[0].casefold()
        if device_name in WINDOWS_RESERVED_NAMES:
            raise UnsafePathError(f"Reserved Windows device name: {part!r}")
    return relative.as_posix()


def safe_join(root: Path, relative_path: str | Path) -> Path:
    normalized = normalize_relative_path(relative_path)
    resolved_root = root.resolve()
    candidate = (resolved_root / Path(*PurePosixPath(normalized).parts)).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise UnsafePathError(f"Path escapes target root: {relative_path}")
    return candidate


def portable_path_key(value: str | Path) -> str:
    """Conservative collision key for Windows/macOS/case-sensitive restores."""

    normalized = normalize_relative_path(value)
    return "/".join(
        unicodedata.normalize("NFC", part).casefold()
        for part in PurePosixPath(normalized).parts
    )


def paths_overlap(first: Path, second: Path) -> bool:
    first_resolved = first.resolve()
    second_resolved = second.resolve()
    return first_resolved == second_resolved or first_resolved.is_relative_to(
        second_resolved
    ) or second_resolved.is_relative_to(first_resolved)


def path_has_reparse_component(path: Path) -> bool:
    """Return True when an existing path component is a symlink or Windows reparse point."""

    absolute = path.expanduser().absolute()
    components = [absolute, *absolute.parents]
    for component in components:
        if not component.exists():
            continue
        try:
            stat_result = component.lstat()
        except OSError:
            continue
        if component.is_symlink():
            return True
        attributes = getattr(stat_result, "st_file_attributes", 0)
        if attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            return True
    return False


def redact_home(path: Path | str) -> str:
    value = str(path)
    home = str(Path.home())
    if value.casefold() == home.casefold():
        return "~"
    prefix = home + os.sep
    if value.casefold().startswith(prefix.casefold()):
        return "~" + os.sep + value[len(prefix) :]
    return value


def human_size(size: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(size)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{size} B"
