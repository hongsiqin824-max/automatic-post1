"""Ingest, process, and draft creation orchestration."""

from __future__ import annotations

from typing import Any

from . import db
from .config import Settings
from .dqd_client import DqdAPIError, DqdAuthError, DqdClient
from .llm import LLMClient, LLMError
from .material_client import MaterialAPIError, MaterialClient
from .quality import check_and_fix_title, run_quality
from .status import TERMINAL_STATUSES
from .utils import canonicalize_url, clean_channels, material_key, now_iso


def _llm(settings: Settings) -> LLMClient | None:
    if not settings.ai_enabled:
        return None
    try:
        return LLMClient(settings)
    except LLMError:
        return None


def _normalise_item(item: dict[str, Any]) -> dict[str, Any]:
    source_url = str(item.get("source_url") or "").strip()
    canonical = canonicalize_url(source_url)
    channels, warnings = clean_channels(item.get("channels"))
    return {
        "material_key": material_key(source_url),
        "source_url": source_url,
        "canonical_url": canonical,
        "source": str(item.get("source") or "").strip(),
        "upstream_archive_id": int(item.get("archive_id") or 0),
        "title_original": str(item.get("translate_title") or "").strip(),
        "body_html": str(item.get("translate_body") or ""),
        "litpic": str(item.get("dqd_litpic") or ""),
        "channels": channels,
        "channel_warnings": warnings,
        "raw": item,
    }


def pull_materials(settings: Settings, sources: list[str] | None = None, *, hours: int | None = None, limit: int | None = None) -> dict[str, Any]:
    source_values = [str(value).strip() for value in (sources or []) if str(value).strip()]
    if not source_values:
        source_values = [row["source"] for row in db.list_sources(settings.db_path, enabled_only=True)]
    if not source_values:
        source_values = list(settings.material_api_sources)
    if not source_values:
        raise MaterialAPIError("没有可拉取的 source，请先在界面配置 source 或设置 MATERIAL_API_SOURCES")
    client = MaterialClient(settings)
    run_id = db.create_pull_run(settings.db_path, source_values, hours or settings.material_api_hours, limit or settings.material_api_limit)
    fetched = inserted = updated = 0
    material_ids: list[int] = []
    errors: list[str] = []
    try:
        for source in source_values:
            existing = db.get_source(settings.db_path, source)
            if existing is None:
                db.upsert_source(settings.db_path, source, display_name=source, enabled=True)
            try:
                items = client.fetch_all(source, hours=hours, limit=limit)
                fetched += len(items)
                for raw in items:
                    normalised = _normalise_item(raw)
                    if not normalised["source"]:
                        normalised["source"] = source
                    if not normalised["source_url"]:
                        continue
                    material_id, was_inserted = db.upsert_material(settings.db_path, normalised)
                    if material_id not in material_ids:
                        material_ids.append(material_id)
                    inserted += int(was_inserted)
                    updated += int(not was_inserted)
            except MaterialAPIError as exc:
                errors.append(f"{source}: {exc}")
        status = "SUCCEEDED" if not errors else ("PARTIAL" if fetched else "FAILED")
        db.finish_pull_run(settings.db_path, run_id, fetched=fetched, inserted=inserted, updated=updated, error_message="; ".join(errors), status=status)
    except Exception as exc:
        db.finish_pull_run(settings.db_path, run_id, fetched=fetched, inserted=inserted, updated=updated, error_message=str(exc), status="FAILED")
        raise
    return {"run_id": run_id, "sources": source_values, "fetched": fetched, "inserted": inserted, "updated": updated, "material_ids": material_ids, "errors": errors}


def _process_material_record(settings: Settings, material: dict[str, Any], *, create: bool) -> dict[str, Any]:
    status = str(material.get("status") or "")
    if status in TERMINAL_STATUSES:
        return material
    if create:
        if status in {"READY_TO_CREATE", "TAB_UNMAPPED", "CREATE_ERROR", "AUTH_REQUIRED", "AUTH_EXPIRED"}:
            return create_draft(settings, int(material["id"]))
        return process_material(settings, int(material["id"]), create=True)
    if status in {"RECEIVED", "CREATE_ERROR", "TAB_UNMAPPED"}:
        return process_material(settings, int(material["id"]), create=False)
    return material


def process_material_ids(settings: Settings, material_ids: list[int], *, create: bool = False) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw_id in material_ids:
        try:
            material_id = int(raw_id)
        except (TypeError, ValueError):
            results.append({"id": raw_id, "status": "ERROR", "error": f"无效的 material id: {raw_id}"})
            continue
        if material_id in seen:
            continue
        seen.add(material_id)
        material = db.get_material(settings.db_path, material_id)
        if material is None:
            results.append({"id": material_id, "status": "ERROR", "error": f"material {material_id} 不存在"})
            continue
        try:
            results.append(_process_material_record(settings, material, create=create))
        except Exception as exc:
            results.append({"id": material_id, "status": "ERROR", "error": str(exc)})
    return results


def process_material(settings: Settings, material_id: int, *, create: bool = False) -> dict[str, Any]:
    material = db.get_material(settings.db_path, material_id)
    if material is None:
        raise KeyError(f"material {material_id} 不存在")
    if material["upstream_archive_id"]:
        if material["status"] != "ALREADY_HAS_ARCHIVE":
            db.transition(settings.db_path, material_id, "ALREADY_HAS_ARCHIVE", event_type="UPSTREAM_ARCHIVE_PRESENT", detail={"archive_id": material["upstream_archive_id"]})
        return db.get_material(settings.db_path, material_id) or material
    db.transition(settings.db_path, material_id, "QUALITY_CHECKING", event_type="QUALITY_STARTED")
    quality = run_quality(material["title_original"], material["body_html"], _llm(settings))
    db.update_material(settings.db_path, material_id, quality_json=quality)
    if quality.get("reject"):
        db.transition(settings.db_path, material_id, "REJECTED", event_type="QUALITY_REJECTED", detail=quality)
        return db.get_material(settings.db_path, material_id) or material
    if not quality.get("pass"):
        db.transition(settings.db_path, material_id, "NEEDS_REVIEW", event_type="QUALITY_REVIEW_REQUIRED", detail=quality)
        return db.get_material(settings.db_path, material_id) or material
    db.transition(settings.db_path, material_id, "TITLE_CHECKING", event_type="QUALITY_PASSED", detail=quality)
    final_title, title_result = check_and_fix_title(material["title_original"], material["body_html"], _llm(settings))
    db.update_material(settings.db_path, material_id, title_final=final_title, title_check_json=title_result, processed_at=now_iso())
    source_config = db.get_source(settings.db_path, material["source"])
    if not source_config or not source_config.get("enabled", 0) or source_config.get("tab_id") is None:
        db.transition(settings.db_path, material_id, "TAB_UNMAPPED", event_type="TAB_MAPPING_REQUIRED", detail={"source": material["source"]})
        return db.get_material(settings.db_path, material_id) or material
    db.transition(settings.db_path, material_id, "READY_TO_CREATE", event_type="READY_FOR_DRAFT", detail={"tab_id": source_config["tab_id"]})
    if create:
        return create_draft(settings, material_id)
    return db.get_material(settings.db_path, material_id) or material


def create_draft(settings: Settings, material_id: int) -> dict[str, Any]:
    material = db.get_material(settings.db_path, material_id)
    if material is None:
        raise KeyError(f"material {material_id} 不存在")
    if material["dqd_archive_id"]:
        return material
    allowed_statuses = {"READY_TO_CREATE", "TAB_UNMAPPED", "CREATE_ERROR", "AUTH_REQUIRED", "AUTH_EXPIRED"}
    if material["status"] not in allowed_statuses:
        raise ValueError(f"当前状态为 {material['status_label']}，不能创建草稿")
    source_config = db.get_source(settings.db_path, material["source"])
    if not source_config or source_config.get("tab_id") is None:
        db.transition(settings.db_path, material_id, "TAB_UNMAPPED", event_type="TAB_MAPPING_REQUIRED")
        return db.get_material(settings.db_path, material_id) or material
    db.transition(settings.db_path, material_id, "DRAFT_CREATING", event_type="DRAFT_CREATE_STARTED")
    try:
        result = DqdClient(settings).create_draft(material, source_config)
        db.transition(settings.db_path, material_id, "DRAFT_CREATED", event_type="DRAFT_CREATE_SUCCEEDED", detail=result, dqd_archive_id=result["archive_id"], created_draft_at=now_iso(), error_message="")
    except DqdAuthError as exc:
        next_status = "AUTH_REQUIRED" if exc.auth_status == "AUTH_REQUIRED" else "AUTH_EXPIRED"
        db.transition(
            settings.db_path,
            material_id,
            next_status,
            event_type="OPEN_PLATFORM_AUTH_REQUIRED" if next_status == "AUTH_REQUIRED" else "OPEN_PLATFORM_AUTH_EXPIRED",
            detail={"error": str(exc), "authorize_url": exc.authorize_url, "payload": exc.payload},
            error_message=str(exc),
        )
    except DqdAPIError as exc:
        db.transition(settings.db_path, material_id, "CREATE_ERROR", event_type="DRAFT_CREATE_FAILED", detail={"error": str(exc), "payload": exc.payload}, error_message=str(exc))
    return db.get_material(settings.db_path, material_id) or material


def process_pending(settings: Settings, *, limit: int = 50, create: bool = False) -> list[dict[str, Any]]:
    rows = db.list_materials(settings.db_path, limit=limit)
    candidate_statuses = {"RECEIVED", "CREATE_ERROR", "TAB_UNMAPPED"}
    if create:
        candidate_statuses |= {"READY_TO_CREATE", "AUTH_REQUIRED", "AUTH_EXPIRED"}
    candidates = [row for row in rows if row["status"] in candidate_statuses]
    results = []
    for material in candidates[:limit]:
        try:
            results.append(_process_material_record(settings, material, create=create))
        except Exception as exc:
            results.append({"id": material["id"], "status": "ERROR", "error": str(exc)})
    return results
