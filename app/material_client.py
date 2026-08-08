"""Client for the upstream translated-materials endpoint."""

from __future__ import annotations

import time
from typing import Any

import requests

from .config import Settings


class MaterialAPIError(RuntimeError):
    pass


class MaterialClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()

    def fetch_page(self, source: str, *, hours: int | None = None, limit: int | None = None, offset: int = 0) -> dict[str, Any]:
        if not self.settings.material_api_key:
            raise MaterialAPIError("未配置 MATERIAL_API_KEY")
        hours = self.settings.material_api_hours if hours is None else int(hours)
        limit = self.settings.material_api_limit if limit is None else int(limit)
        if not 1 <= hours <= 24:
            raise MaterialAPIError("hours 必须在 1-24 之间")
        if not 1 <= limit <= 500:
            raise MaterialAPIError("limit 必须在 1-500 之间")
        params = {
            "source": source,
            "caller": self.settings.material_api_caller,
            "hours": hours,
            "limit": limit,
            "offset": int(offset),
        }
        url = f"{self.settings.material_api_base_url}/v1/url_ingest/ai_materials"
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers={"X-API-Key": self.settings.material_api_key},
                    timeout=self.settings.material_api_timeout_seconds,
                )
                if response.status_code == 429 and attempt < 2:
                    retry_after = response.headers.get("Retry-After", "")
                    try:
                        wait = min(30.0, max(1.0, float(retry_after)))
                    except ValueError:
                        wait = 2 ** attempt
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                payload = response.json()
                if int(payload.get("code", 0)) != 0:
                    raise MaterialAPIError(payload.get("msg") or "素材接口返回业务错误")
                data = payload.get("data") or {}
                items = data.get("items")
                if not isinstance(items, list):
                    raise MaterialAPIError("素材接口响应缺少 data.items 数组")
                return {
                    "items": items,
                    "total": int(data.get("total") or 0),
                    "has_more": bool(data.get("has_more")),
                    "meta": {"cost_time": payload.get("cost_time"), "timestamp": payload.get("timestamp")},
                }
            except (requests.RequestException, ValueError, MaterialAPIError) as exc:
                last_error = exc
                if isinstance(exc, MaterialAPIError) and "返回业务错误" not in str(exc):
                    break
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise MaterialAPIError(f"素材接口请求失败: {str(last_error)[:500]}") from last_error

    def fetch_all(self, source: str, *, hours: int | None = None, limit: int | None = None, max_pages: int = 20) -> list[dict[str, Any]]:
        limit = self.settings.material_api_limit if limit is None else int(limit)
        offset = 0
        result: list[dict[str, Any]] = []
        for _ in range(max_pages):
            page = self.fetch_page(source, hours=hours, limit=limit, offset=offset)
            batch = page["items"]
            result.extend(batch)
            offset += len(batch)
            if not page["has_more"] or not batch:
                break
        return result

