"""Small deterministic helpers shared by API clients and the pipeline."""

from __future__ import annotations

import hashlib
import re
from html import unescape
from urllib.parse import SplitResult, urlsplit, urlunsplit


def canonicalize_url(source_url: str) -> str:
    """Return a conservative v1 URL representation for identity purposes."""
    value = str(source_url or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value
    hostname = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = hostname
    if ":" in hostname and not hostname.startswith("["):
        netloc = f"[{hostname}]"
    if parsed.username:
        auth = parsed.username
        if parsed.password is not None:
            auth += f":{parsed.password}"
        netloc = f"{auth}@{netloc}"
    if port and not ((parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)):
        netloc = f"{netloc}:{port}"
    normalized = SplitResult(
        parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""
    )
    return urlunsplit(normalized)


def material_key(source_url: str) -> str:
    canonical = canonicalize_url(source_url)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"url:v1:{digest}"


def clean_channels(value: object) -> tuple[list[int], list[str]]:
    """Deduplicate integer tag IDs while returning validation warnings."""
    if value is None:
        return [], []
    if not isinstance(value, (list, tuple)):
        return [], ["channels 不是数组"]
    ids: list[int] = []
    warnings: list[str] = []
    seen: set[int] = set()
    for raw in value:
        if isinstance(raw, bool):
            warnings.append(f"忽略非法标签 ID: {raw}")
            continue
        try:
            tag_id = int(raw)
        except (TypeError, ValueError):
            warnings.append(f"忽略非法标签 ID: {raw}")
            continue
        if tag_id <= 0:
            warnings.append(f"忽略非正标签 ID: {tag_id}")
            continue
        if tag_id not in seen:
            seen.add(tag_id)
            ids.append(tag_id)
    return ids, warnings


def html_to_text(html: str) -> str:
    value = re.sub(r"<[^>]+>", " ", str(html or ""))
    return re.sub(r"\s+", " ", unescape(value)).strip()


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")

