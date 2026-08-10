"""Environment-only configuration for the new material workflow.

No credentials are stored in this module.  Copy ``.env.example`` to a local
environment file or export the variables from the shell before starting the
server.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DQD_DRAFT_URL_TEMPLATE = "https://dadmin.dongqiudi.com/admin/archives/articlePublish?articleId={archive_id}"


def _load_dotenv() -> None:
    """Load .env when python-dotenv is installed; environment wins."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


_load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是整数") from exc


def _float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是数字") from exc


def _json_object(name: str) -> dict[str, str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    try:
        value: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"环境变量 {name} 必须是 JSON 对象") from exc
    if not isinstance(value, dict):
        raise ValueError(f"环境变量 {name} 必须是 JSON 对象")
    return {str(key): str(val) for key, val in value.items()}


def _sources() -> tuple[str, ...]:
    raw = os.getenv("MATERIAL_API_SOURCES", "")
    return tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))


@dataclass(frozen=True)
class Settings:
    db_path: Path
    material_api_base_url: str
    material_api_key: str
    material_api_caller: str
    material_api_timeout_seconds: float
    material_api_hours: int
    material_api_limit: int
    material_api_sources: tuple[str, ...]
    dqd_open_api_url: str
    dqd_open_appid: str
    dqd_open_appsecret: str
    dqd_open_redirect_uri: str
    dqd_enname: str
    dqd_archive_level: str
    dqd_status: int
    dqd_timeout_seconds: float
    dqd_headers: dict[str, str]
    ai_enabled: bool
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    llm_timeout_seconds: float
    llm_request_retries: int
    pull_auto_process: bool
    app_host: str
    app_port: int
    app_debug: bool
    dqd_draft_url_template: str = DEFAULT_DQD_DRAFT_URL_TEMPLATE

    @classmethod
    def from_env(cls) -> "Settings":
        db_raw = os.getenv("MATERIAL_WORKFLOW_DB", "data/material_workflow.db")
        db_path = Path(db_raw)
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path
        dqd_enname = (os.getenv("DQD_ENNAME") or os.getenv("DQD_OPEN_ENNAME") or "hongsiqin").strip()
        level = (os.getenv("DQD_ARCHIVE_LEVEL") or os.getenv("DQD_OPEN_ARCHIVE_LEVEL") or "B").strip().upper() or "B"
        if level not in {"S", "A", "B", "C"}:
            raise ValueError("DQD_ARCHIVE_LEVEL 必须是 S、A、B 或 C")
        return cls(
            db_path=db_path,
            material_api_base_url=os.getenv(
                "MATERIAL_API_BASE_URL",
                "https://aigc-core.dongqiudi.com",
            ).rstrip("/"),
            material_api_key=os.getenv("MATERIAL_API_KEY", "").strip(),
            material_api_caller=os.getenv("MATERIAL_API_CALLER", "editor.ai_materials").strip(),
            material_api_timeout_seconds=_float("MATERIAL_API_TIMEOUT_SECONDS", 30.0),
            material_api_hours=_int("MATERIAL_API_HOURS", 6),
            material_api_limit=_int("MATERIAL_API_LIMIT", 100),
            material_api_sources=_sources(),
            dqd_open_api_url=os.getenv(
                "DQD_OPEN_API_URL",
                "https://platform.dongqiudi.com/open/v1/do?api_name=admin-archive-createarticle",
            ).strip(),
            dqd_open_appid=os.getenv("DQD_OPEN_APPID", "").strip(),
            dqd_open_appsecret=os.getenv("DQD_OPEN_APPSECRET", "").strip(),
            dqd_open_redirect_uri=os.getenv(
                "DQD_OPEN_REDIRECT_URI",
                "http://127.0.0.1:8900/api/open/auth/callback",
            ).strip(),
            dqd_enname=dqd_enname,
            dqd_archive_level=level,
            dqd_status=_int("DQD_CREATE_STATUS", 0),
            dqd_timeout_seconds=_float("DQD_CREATE_TIMEOUT_SECONDS", 30.0),
            dqd_headers=_json_object("DQD_OPEN_API_HEADERS_JSON"),
            ai_enabled=_bool("AI_ENABLED", False),
            llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            llm_model=os.getenv("LLM_MODEL", "gpt-5.5").strip(),
            llm_timeout_seconds=_float("LLM_TIMEOUT_SECONDS", 45.0),
            llm_request_retries=_int("LLM_REQUEST_RETRIES", 2),
            pull_auto_process=_bool("PULL_AUTO_PROCESS", False),
            app_host=os.getenv("APP_HOST", "127.0.0.1"),
            app_port=_int("APP_PORT", 8900),
            app_debug=_bool("APP_DEBUG", False),
            dqd_draft_url_template=os.getenv("DQD_DRAFT_URL_TEMPLATE", DEFAULT_DQD_DRAFT_URL_TEMPLATE).strip(),
        )


def get_settings() -> Settings:
    return Settings.from_env()
