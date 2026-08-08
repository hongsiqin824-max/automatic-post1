"""SQLite persistence and status timeline operations."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .status import STATUS_LABELS
from .utils import now_iso


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  source TEXT PRIMARY KEY,
  display_name TEXT NOT NULL DEFAULT '',
  tab_id INTEGER,
  tab_name TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS open_platform_auth (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  auth_status TEXT NOT NULL DEFAULT 'UNAUTHORIZED',
  pending_state TEXT NOT NULL DEFAULT '',
  pending_state_expires_at TEXT,
  access_token TEXT NOT NULL DEFAULT '',
  refresh_token TEXT NOT NULL DEFAULT '',
  token_type TEXT NOT NULL DEFAULT 'Bearer',
  token_expires_at TEXT,
  refresh_token_expires_at TEXT,
  authorized_user_json TEXT NOT NULL DEFAULT '{}',
  last_authorize_url TEXT NOT NULL DEFAULT '',
  last_error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS materials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  material_key TEXT NOT NULL UNIQUE,
  source_url TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  source TEXT NOT NULL,
  upstream_archive_id INTEGER NOT NULL DEFAULT 0,
  dqd_archive_id INTEGER,
  title_original TEXT NOT NULL DEFAULT '',
  title_final TEXT NOT NULL DEFAULT '',
  body_html TEXT NOT NULL DEFAULT '',
  litpic TEXT NOT NULL DEFAULT '',
  channels_json TEXT NOT NULL DEFAULT '[]',
  channel_warnings_json TEXT NOT NULL DEFAULT '[]',
  quality_json TEXT NOT NULL DEFAULT '{}',
  title_check_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL,
  error_message TEXT NOT NULL DEFAULT '',
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  processed_at TEXT,
  created_draft_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_materials_status ON materials(status);
CREATE INDEX IF NOT EXISTS idx_materials_source ON materials(source);
CREATE INDEX IF NOT EXISTS idx_materials_updated ON materials(updated_at DESC);
CREATE TABLE IF NOT EXISTS material_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  material_id INTEGER NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  event_type TEXT NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY(material_id) REFERENCES materials(id)
);
CREATE INDEX IF NOT EXISTS idx_events_material ON material_events(material_id, id DESC);
CREATE TABLE IF NOT EXISTS pull_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  requested_sources_json TEXT NOT NULL DEFAULT '[]',
  hours INTEGER NOT NULL,
  limit_count INTEGER NOT NULL,
  fetched_count INTEGER NOT NULL DEFAULT 0,
  inserted_count INTEGER NOT NULL DEFAULT 0,
  updated_count INTEGER NOT NULL DEFAULT 0,
  error_message TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'RUNNING'
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | str) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        current = now_iso()
        conn.execute(
            """INSERT OR IGNORE INTO open_platform_auth
               (id,auth_status,pending_state,pending_state_expires_at,access_token,refresh_token,token_type,token_expires_at,refresh_token_expires_at,authorized_user_json,last_authorize_url,last_error,created_at,updated_at)
               VALUES(1,'UNAUTHORIZED','','', '','','Bearer',NULL,NULL,'{}','','',?,?)""",
            (current, current),
        )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode_material(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    for field, fallback in (
        ("channels_json", []),
        ("channel_warnings_json", []),
        ("quality_json", {}),
        ("title_check_json", {}),
        ("raw_json", {}),
    ):
        try:
            item[field.removesuffix("_json")] = json.loads(item.pop(field) or _json(fallback))
        except json.JSONDecodeError:
            item[field.removesuffix("_json")] = fallback
    item["status_label"] = STATUS_LABELS.get(item["status"], item["status"])
    return item


def _decode_source(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _decode_open_platform_auth(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    try:
        item["authorized_user"] = json.loads(item.pop("authorized_user_json") or "{}")
    except json.JSONDecodeError:
        item["authorized_user"] = {}
    return item


def list_sources(db_path: Path | str, enabled_only: bool = False) -> list[dict[str, Any]]:
    query = "SELECT * FROM sources"
    params: tuple[Any, ...] = ()
    if enabled_only:
        query += " WHERE enabled=1"
    query += " ORDER BY source"
    with connect(db_path) as conn:
        return [_decode_source(row) for row in conn.execute(query, params)]


def get_source(db_path: Path | str, source: str) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        return _decode_source(conn.execute("SELECT * FROM sources WHERE source=?", (source,)).fetchone())


def upsert_source(db_path: Path | str, source: str, display_name: str = "", tab_id: int | None = None, tab_name: str = "", enabled: bool = True) -> dict[str, Any]:
    source = str(source or "").strip()
    if not source:
        raise ValueError("source 不能为空")
    if tab_id in ("", None):
        tab_value = None
    else:
        try:
            tab_value = int(tab_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("tab_id 必须是整数") from exc
    current = now_iso()
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO sources(source,display_name,tab_id,tab_name,enabled,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(source) DO UPDATE SET display_name=excluded.display_name,
                 tab_id=excluded.tab_id, tab_name=excluded.tab_name,
                 enabled=excluded.enabled, updated_at=excluded.updated_at""",
            (source, str(display_name or "").strip(), tab_value, str(tab_name or "").strip(), int(bool(enabled)), current, current),
        )
        return _decode_source(conn.execute("SELECT * FROM sources WHERE source=?", (source,)).fetchone())


def get_open_platform_auth(db_path: Path | str) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        return _decode_open_platform_auth(conn.execute("SELECT * FROM open_platform_auth WHERE id=1").fetchone())


def update_open_platform_auth(db_path: Path | str, **fields: Any) -> dict[str, Any]:
    allowed = {
        "auth_status",
        "pending_state",
        "pending_state_expires_at",
        "access_token",
        "refresh_token",
        "token_type",
        "token_expires_at",
        "refresh_token_expires_at",
        "authorized_user",
        "last_authorize_url",
        "last_error",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        current = get_open_platform_auth(db_path)
        if current is None:
            raise KeyError("open_platform_auth 不存在")
        return current
    encoded: dict[str, Any] = {}
    for key, value in updates.items():
        if key == "authorized_user":
            encoded["authorized_user_json"] = _json(value or {})
        else:
            encoded[key] = value
    encoded["updated_at"] = now_iso()
    assignments = ", ".join(f"{key}=?" for key in encoded)
    with connect(db_path) as conn:
        conn.execute(f"UPDATE open_platform_auth SET {assignments} WHERE id=1", [*encoded.values()])
    current = get_open_platform_auth(db_path)
    if current is None:
        raise KeyError("open_platform_auth 不存在")
    return current


def reset_open_platform_auth(db_path: Path | str) -> dict[str, Any]:
    current = now_iso()
    with connect(db_path) as conn:
        conn.execute(
            """UPDATE open_platform_auth
               SET auth_status='UNAUTHORIZED', pending_state='', pending_state_expires_at=NULL,
                   access_token='', refresh_token='', token_type='Bearer', token_expires_at=NULL,
                   refresh_token_expires_at=NULL, authorized_user_json='{}',
                   last_authorize_url='', last_error='', updated_at=?
               WHERE id=1""",
            (current,),
        )
    current_row = get_open_platform_auth(db_path)
    if current_row is None:
        raise KeyError("open_platform_auth 不存在")
    return current_row


def create_pull_run(db_path: Path | str, sources: Iterable[str], hours: int, limit_count: int) -> int:
    with connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO pull_runs(started_at,requested_sources_json,hours,limit_count) VALUES(?,?,?,?)",
            (now_iso(), _json(list(sources)), hours, limit_count),
        )
        return int(cursor.lastrowid)


def finish_pull_run(db_path: Path | str, run_id: int, *, fetched: int, inserted: int, updated: int, error_message: str = "", status: str = "SUCCEEDED") -> None:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE pull_runs SET finished_at=?,fetched_count=?,inserted_count=?,updated_count=?,error_message=?,status=? WHERE id=?",
            (now_iso(), fetched, inserted, updated, error_message[:1000], status, run_id),
        )


def get_material(db_path: Path | str, material_id: int) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM materials WHERE id=?", (int(material_id),)).fetchone()
    return _decode_material(row)


def get_material_by_key(db_path: Path | str, key: str) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM materials WHERE material_key=?", (key,)).fetchone()
    return _decode_material(row)


def list_materials(db_path: Path | str, *, status: str = "", source: str = "", search: str = "", limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status=?")
        params.append(status)
    if source:
        clauses.append("source=?")
        params.append(source)
    if search:
        clauses.append("(title_original LIKE ? OR source_url LIKE ? OR material_key LIKE ?)")
        term = f"%{search}%"
        params.extend([term, term, term])
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM materials{where} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?", params
        ).fetchall()
    return [_decode_material(row) for row in rows]


def count_materials(db_path: Path | str, *, status: str = "", source: str = "", search: str = "") -> int:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status=?")
        params.append(status)
    if source:
        clauses.append("source=?")
        params.append(source)
    if search:
        clauses.append("(title_original LIKE ? OR source_url LIKE ? OR material_key LIKE ?)")
        term = f"%{search}%"
        params.extend([term, term, term])
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM materials{where}", params).fetchone()[0])


def status_counts(db_path: Path | str) -> dict[str, int]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT status,COUNT(*) AS count FROM materials GROUP BY status").fetchall()
    counts = {key: 0 for key in STATUS_LABELS}
    counts.update({str(row["status"]): int(row["count"]) for row in rows})
    return counts


def upsert_material(db_path: Path | str, material: dict[str, Any]) -> tuple[int, bool]:
    """Insert an upstream item or refresh its raw fields. Return (id, inserted)."""
    current = now_iso()
    with connect(db_path) as conn:
        existing = conn.execute("SELECT * FROM materials WHERE material_key=?", (material["material_key"],)).fetchone()
        channels = material.get("channels", [])
        warnings = material.get("channel_warnings", [])
        raw = material.get("raw", {})
        if existing is None:
            initial = "ALREADY_HAS_ARCHIVE" if int(material.get("upstream_archive_id") or 0) > 0 else "RECEIVED"
            cursor = conn.execute(
                """INSERT INTO materials(material_key,source_url,canonical_url,source,upstream_archive_id,title_original,title_final,body_html,litpic,channels_json,channel_warnings_json,raw_json,status,created_at,updated_at,first_seen_at,last_seen_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (material["material_key"], material["source_url"], material["canonical_url"], material["source"], int(material.get("upstream_archive_id") or 0), material.get("title_original", ""), material.get("title_original", ""), material.get("body_html", ""), material.get("litpic", ""), _json(channels), _json(warnings), _json(raw), initial, current, current, current, current),
            )
            material_id = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO material_events(material_id,from_status,to_status,event_type,detail_json,created_at) VALUES(?,?,?,?,?,?)",
                (material_id, None, initial, "INGESTED", _json({"source": material["source"]}), current),
            )
            return material_id, True
        conn.execute(
            """UPDATE materials SET source_url=?,canonical_url=?,source=?,upstream_archive_id=?,title_original=?,body_html=?,litpic=?,channels_json=?,channel_warnings_json=?,raw_json=?,updated_at=?,last_seen_at=? WHERE id=?""",
            (material["source_url"], material["canonical_url"], material["source"], int(material.get("upstream_archive_id") or 0), material.get("title_original", ""), material.get("body_html", ""), material.get("litpic", ""), _json(channels), _json(warnings), _json(raw), current, current, int(existing["id"])),
        )
        return int(existing["id"]), False


def update_material(db_path: Path | str, material_id: int, **fields: Any) -> None:
    allowed = {
        "title_final", "dqd_archive_id", "quality_json", "title_check_json",
        "status", "error_message", "processed_at", "created_draft_at",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    encoded = {}
    for key, value in updates.items():
        if key in {"quality_json", "title_check_json"}:
            encoded[key] = _json(value)
        else:
            encoded[key] = value
    encoded["updated_at"] = now_iso()
    assignments = ", ".join(f"{key}=?" for key in encoded)
    with connect(db_path) as conn:
        conn.execute(f"UPDATE materials SET {assignments} WHERE id=?", [*encoded.values(), int(material_id)])


def transition(db_path: Path | str, material_id: int, to_status: str, *, event_type: str = "STATUS_CHANGED", detail: dict[str, Any] | None = None, **fields: Any) -> None:
    current = get_material(db_path, material_id)
    if current is None:
        raise KeyError(f"material {material_id} 不存在")
    update_material(db_path, material_id, status=to_status, **fields)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO material_events(material_id,from_status,to_status,event_type,detail_json,created_at) VALUES(?,?,?,?,?,?)",
            (material_id, current["status"], to_status, event_type, _json(detail or {}), now_iso()),
        )


def list_events(db_path: Path | str, material_id: int) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM material_events WHERE material_id=? ORDER BY id", (int(material_id),)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["detail"] = json.loads(item.pop("detail_json") or "{}")
        except json.JSONDecodeError:
            item["detail"] = {}
        item["from_status_label"] = STATUS_LABELS.get(item.get("from_status"), item.get("from_status") or "")
        item["to_status_label"] = STATUS_LABELS.get(item["to_status"], item["to_status"])
        result.append(item)
    return result


def recent_pull_runs(db_path: Path | str, limit: int = 20) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM pull_runs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 100)),)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["requested_sources"] = json.loads(item.pop("requested_sources_json") or "[]")
        except json.JSONDecodeError:
            item["requested_sources"] = []
        result.append(item)
    return result
