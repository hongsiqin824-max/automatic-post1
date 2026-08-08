"""Client for the DQD open-platform article creation endpoint."""

from __future__ import annotations

from typing import Any

import requests

from .config import Settings
from .open_platform import (
    OpenPlatformAuthError,
    OpenPlatformClient,
    OpenPlatformConfigError,
    OpenPlatformError,
    OpenPlatformRequestError,
)


class DqdAPIError(RuntimeError):
    def __init__(self, message: str, *, payload: Any = None, status_code: int | None = None):
        super().__init__(message)
        self.payload = payload
        self.status_code = status_code


class DqdAuthError(DqdAPIError):
    def __init__(self, message: str, *, auth_status: str, authorize_url: str | None = None, payload: Any = None, status_code: int | None = None):
        super().__init__(message, payload=payload, status_code=status_code)
        self.auth_status = auth_status
        self.authorize_url = authorize_url


def _extract_archive_id(payload: Any) -> Any:
    """Best-effort extract archive_id from DQD responses.

    The open-platform response shape is not perfectly consistent across
    environments.  Some responses expose ``data.archive_id`` directly, while
    others wrap the real payload one or two levels deeper, for example:

    ``{"code": 0, "data": {"code": 0, "data": {"archive_id": 123}}}``

    This helper follows the common nesting patterns and returns the first
    non-empty ``archive_id`` it finds.
    """

    def walk(value: Any, depth: int = 0) -> Any:
        if not isinstance(value, dict):
            return None
        archive_id = value.get("archive_id")
        if archive_id not in (None, ""):
            return archive_id
        if depth >= 4:
            return None
        for key in ("data", "result"):
            found = walk(value.get(key), depth + 1)
            if found not in (None, ""):
                return found
        return None

    return walk(payload)


def build_draft_url(settings: Settings, archive_id: Any) -> str:
    template = str(getattr(settings, "dqd_draft_url_template", "") or "").strip()
    if not template or archive_id in (None, ""):
        return ""
    try:
        archive_id_int = int(archive_id)
    except (TypeError, ValueError):
        return ""
    if "{archive_id}" not in template:
        return ""
    try:
        return template.format(archive_id=archive_id_int)
    except (KeyError, IndexError, ValueError):
        return ""


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
        self.open_platform = OpenPlatformClient(settings, self.session)

    def create_draft(self, material: dict[str, Any], source_config: dict[str, Any]) -> dict[str, Any]:
        form = build_create_form(material, source_config, self.settings)
        try:
            response, payload, request_url = self.open_platform.post_signed(data=form, require_login=True)
        except OpenPlatformAuthError as exc:
            raise DqdAuthError(str(exc), auth_status=exc.status, authorize_url=exc.authorize_url, payload=exc.payload) from exc
        except OpenPlatformConfigError as exc:
            raise DqdAuthError(str(exc), auth_status="AUTH_REQUIRED") from exc
        except OpenPlatformRequestError as exc:
            raise DqdAPIError(f"创建文章接口请求失败: {str(exc)[:500]}", payload=exc.payload, status_code=exc.status_code) from exc
        except (requests.RequestException, ValueError, OpenPlatformError) as exc:
            raise DqdAPIError(f"创建文章接口请求失败: {str(exc)[:500]}") from exc
        if int(payload.get("code", 0)) != 0:
            message = payload.get("message") or payload.get("msg") or "创建文章接口返回业务错误"
            if int(payload.get("code", 0)) == 10007:
                raise DqdAuthError(str(message), auth_status="AUTH_EXPIRED", payload=payload, authorize_url=self.open_platform.start_authorization()["authorize_url"])
            raise DqdAPIError(str(message), payload=payload, status_code=response.status_code)
        archive_id = _extract_archive_id(payload)
        if archive_id in (None, ""):
            raise DqdAPIError("创建接口成功但没有返回 data.archive_id", payload=payload, status_code=response.status_code)
        try:
            archive_id_int = int(archive_id)
        except (TypeError, ValueError) as exc:
            raise DqdAPIError("创建接口返回的 archive_id 不是整数", payload=payload, status_code=response.status_code) from exc
        return {
            "archive_id": archive_id_int,
            "draft_url": build_draft_url(self.settings, archive_id_int),
            "payload": payload,
            "form_fields": [key for key, _ in form],
            "request_url": request_url,
        }
