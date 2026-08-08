"""Flask application factory and JSON endpoints for the dashboard."""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, render_template, request

from . import db
from .config import Settings, get_settings
from .pipeline import create_draft, process_material, process_pending, pull_materials
from .status import STATUS_LABELS


def _json_payload() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or get_settings()
    db.init_db(settings.db_path)
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["SETTINGS"] = settings

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "db_path": str(settings.db_path)})

    @app.get("/api/config")
    def config_info():
        return jsonify({
            "status_labels": STATUS_LABELS,
            "sources": db.list_sources(settings.db_path),
            "material_api": {
                "base_url": settings.material_api_base_url,
                "caller": settings.material_api_caller,
                "key_configured": bool(settings.material_api_key),
                "env_sources": list(settings.material_api_sources),
            },
            "dqd": {
                "url": settings.dqd_open_api_url,
                "dqd_enname": settings.dqd_enname,
                "archive_level": settings.dqd_archive_level,
                "status": settings.dqd_status,
                "headers_configured": bool(settings.dqd_headers),
            },
            "ai": {"enabled": settings.ai_enabled, "key_configured": bool(settings.llm_api_key), "model": settings.llm_model},
        })

    @app.get("/api/dashboard")
    def dashboard():
        return jsonify({
            "counts": db.status_counts(settings.db_path),
            "total": db.count_materials(settings.db_path),
            "runs": db.recent_pull_runs(settings.db_path),
        })

    @app.get("/api/sources")
    def sources():
        return jsonify({"items": db.list_sources(settings.db_path)})

    @app.post("/api/sources")
    def save_source():
        payload = _json_payload()
        try:
            item = db.upsert_source(
                settings.db_path,
                payload.get("source", ""),
                display_name=payload.get("display_name", ""),
                tab_id=payload.get("tab_id"),
                tab_name=payload.get("tab_name", ""),
                enabled=payload.get("enabled", True),
            )
            return jsonify({"item": item})
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/sources/<path:source>/enabled")
    def set_source_enabled(source: str):
        current = db.get_source(settings.db_path, source)
        if current is None:
            return jsonify({"error": "source 不存在"}), 404
        payload = _json_payload()
        try:
            item = db.upsert_source(settings.db_path, source, display_name=current["display_name"], tab_id=current["tab_id"], tab_name=current["tab_name"], enabled=bool(payload.get("enabled", True)))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"item": item})

    @app.get("/api/materials")
    def materials():
        status = request.args.get("status", "").strip()
        source = request.args.get("source", "").strip()
        search = request.args.get("search", "").strip()
        try:
            limit = int(request.args.get("limit", 100))
            offset = int(request.args.get("offset", 0))
        except ValueError:
            return jsonify({"error": "limit/offset 必须是整数"}), 400
        return jsonify({
            "items": db.list_materials(settings.db_path, status=status, source=source, search=search, limit=limit, offset=offset),
            "total": db.count_materials(settings.db_path, status=status, source=source, search=search),
        })

    @app.get("/api/materials/<int:material_id>")
    def material_detail(material_id: int):
        item = db.get_material(settings.db_path, material_id)
        if item is None:
            return jsonify({"error": "素材不存在"}), 404
        item["events"] = db.list_events(settings.db_path, material_id)
        item["source_config"] = db.get_source(settings.db_path, item["source"])
        return jsonify({"item": item})

    @app.post("/api/pull")
    def pull():
        payload = _json_payload()
        sources_value = payload.get("sources")
        if sources_value is not None and not isinstance(sources_value, list):
            return jsonify({"error": "sources 必须是数组"}), 400
        try:
            result = pull_materials(
                settings,
                sources=sources_value,
                hours=payload.get("hours"),
                limit=payload.get("limit"),
            )
            if payload.get("process", settings.pull_auto_process):
                result["processed"] = process_pending(settings, limit=int(payload.get("process_limit", 50)), create=False)
            return jsonify(result)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/process")
    def process_batch():
        payload = _json_payload()
        try:
            results = process_pending(settings, limit=int(payload.get("limit", 50)), create=bool(payload.get("create", False)))
            return jsonify({"items": results, "count": len(results)})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/materials/<int:material_id>/process")
    def process_one(material_id: int):
        payload = _json_payload()
        try:
            item = process_material(settings, material_id, create=bool(payload.get("create", False)))
            return jsonify({"item": item})
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/materials/<int:material_id>/create-draft")
    def create_one(material_id: int):
        try:
            item = create_draft(settings, material_id)
            return jsonify({"item": item})
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "接口不存在"}), 404
        return error

    return app

