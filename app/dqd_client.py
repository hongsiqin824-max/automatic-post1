"""Client for the DQD open-platform article creation endpoint."""

from __future__ import annotations

from typing import Any

import requests

from .config import Settings


class DqdAPIError(RuntimeError):
    def __init__(self, message: str, *, payload: Any = None, status_code: int | None = None):
        super().__init__(message)
        self.payload = payload
        self.status_code = status_code


def build_create_form(material: dict[str, Any], source_config: dict[str, Any], settings: Settings) -> list[tuple[str, str]]:
    """Build form tuples so requests encodes tabs[]=... correctly."""
    title = (material.get("title_final") or material.get("title_original") or "").strip()
    body = material.get("body_html") or ""
    tab_id = source_config.get("tab_id")
    if not title:
        raise DqdAPIError("标题为空，不能创建草稿")
    if not body.strip():
        raise DqdAPIError("正文为空，不能创建草稿")
    if tab_id in (None, ""):
        raise DqdAPIError("source 尚未配置后台栏目 tab")
    fields: list[tuple[str, str]] = [
        ("dqd_enname", settings.dqd_enname),
        ("title", title),
        ("body", body),
        ("archive_level", settings.dqd_archive_level),
        ("status", str(settings.dqd_status)),
        ("tabs[]", str(int(tab_id))),
    ]
    channels = material.get("channels") or []
    if channels:
        fields.append(("channels", ",".join(str(int(value)) for value in channels)))
    litpic = str(material.get("litpic") or "").strip()
    if litpic:
        fields.append(("litpic", litpic))
    return fields


class DqdClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()

    def create_draft(self, material: dict[str, Any], source_config: dict[str, Any]) -> dict[str, Any]:
        form = build_create_form(material, source_config, self.settings)
        try:
            response = self.session.post(
                self.settings.dqd_open_api_url,
                data=form,
                headers=self.settings.dqd_headers,
                timeout=self.settings.dqd_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise DqdAPIError(f"创建文章接口请求失败: {str(exc)[:500]}") from exc
        if int(payload.get("code", 0)) != 0:
            message = payload.get("message") or payload.get("msg") or "创建文章接口返回业务错误"
            raise DqdAPIError(str(message), payload=payload, status_code=response.status_code)
        archive_id = ((payload.get("data") or {}).get("archive_id"))
        if archive_id in (None, ""):
            raise DqdAPIError("创建接口成功但没有返回 data.archive_id", payload=payload, status_code=response.status_code)
        return {"archive_id": int(archive_id), "payload": payload, "form_fields": [key for key, _ in form]}

