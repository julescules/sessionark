from __future__ import annotations

import json
import sqlite3
from pathlib import Path


SESSION_ONE = "11111111-1111-4111-8111-111111111111"
SESSION_TWO = "22222222-2222-4222-8222-222222222222"
SESSION_THREE = "33333333-3333-4333-8333-333333333333"


def write_jsonl(path: Path, records: list[dict], final_newline: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(record, separators=(",", ":")) for record in records)
    if final_newline:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")


def create_codex_state(path: Path, rows: list[tuple[str, str, int, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE threads ("
            "id TEXT PRIMARY KEY, rollout_path TEXT, archived INTEGER, has_user_event INTEGER"
            ")"
        )
        connection.executemany(
            "INSERT INTO threads(id, rollout_path, archived, has_user_event) VALUES (?, ?, ?, ?)",
            rows,
        )
        connection.commit()
    finally:
        connection.close()


def create_codex_fixture(root: Path) -> dict[str, Path]:
    rollout = root / "sessions" / "2026" / "07" / "10" / f"rollout-{SESSION_ONE}.jsonl"
    write_jsonl(
        rollout,
        [
            {
                "timestamp": "2026-07-10T00:00:00Z",
                "type": "session_meta",
                "payload": {"id": SESSION_ONE, "cwd": "D:/fixture"},
            },
            {"timestamp": "2026-07-10T00:00:01Z", "type": "event_msg", "payload": {}},
        ],
    )
    index = root / "session_index.jsonl"
    write_jsonl(index, [{"id": SESSION_ONE, "thread_name": "fixture", "updated_at": "now"}])
    state = root / "state_5.sqlite"
    create_codex_state(state, [(SESSION_ONE, str(rollout), 0, 1)])
    return {"rollout": rollout, "index": index, "state": state}
