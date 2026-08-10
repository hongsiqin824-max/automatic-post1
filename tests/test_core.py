import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from types import SimpleNamespace
from unittest.mock import patch

from app import db, pipeline
from app.config import Settings
from app.dqd_client import DqdClient, build_create_form, build_draft_url
from app.open_platform import build_authorize_url, build_signed_request_url, sign_query_params
from app.web import create_app
from app.utils import canonicalize_url, clean_channels, material_key


class CoreTests(unittest.TestCase):
    def make_settings(self, db_path: Path) -> Settings:
        return Settings(
            db_path=db_path,
            material_api_base_url="https://aigc-core.dongqiudi.com",
            material_api_key="test-key",
            material_api_caller="editor.ai_materials",
            material_api_timeout_seconds=1,
            material_api_hours=6,
            material_api_limit=100,
            material_api_sources=(),
            dqd_open_api_url="https://platform.dongqiudi.com/open/v1/do?api_name=admin-archive-createarticle",
            dqd_open_appid="app-id",
            dqd_open_appsecret="secret",
            dqd_open_redirect_uri="http://127.0.0.1:8900/api/open/auth/callback",
            dqd_enname="hongsiqin",
            dqd_archive_level="B",
            dqd_status=0,
            dqd_timeout_seconds=1,
            dqd_headers={},
            ai_enabled=False,
            llm_api_key="",
            llm_base_url="https://api.openai.com/v1",
            llm_model="gpt-5.5",
            llm_timeout_seconds=1,
            llm_request_retries=1,
            pull_auto_process=False,
            app_host="127.0.0.1",
            app_port=8900,
            app_debug=False,
        )

    def test_url_identity_is_conservative_and_stable(self):
        first = canonicalize_url(" HTTPS://Example.COM:443/news?id=7#fragment ")
        second = canonicalize_url("https://example.com/news?id=7")
        self.assertEqual(first, second)
        self.assertEqual(material_key(first), material_key(second))
        self.assertNotEqual(material_key("https://example.com/news?id=8"), material_key(first))

    def test_channels_are_integer_ids_and_deduplicated(self):
        ids, warnings = clean_channels([3388642, "1638903", 3388642, 0, "bad", True])
        self.assertEqual(ids, [3388642, 1638903])
        self.assertEqual(len(warnings), 3)

    def test_draft_form_uses_tabs_array_and_fixed_draft_level(self):
        settings = Settings(
            db_path=Path("/tmp/material-test.db"), material_api_base_url="", material_api_key="", material_api_caller="",
            material_api_timeout_seconds=1, material_api_hours=6, material_api_limit=100, material_api_sources=(),
            dqd_open_api_url="https://platform.dongqiudi.com/open/v1/do?api_name=admin-archive-createarticle",
            dqd_open_appid="app-id", dqd_open_appsecret="secret", dqd_open_redirect_uri="http://127.0.0.1:8900/api/open/auth/callback",
            dqd_enname="hongsiqin", dqd_archive_level="B", dqd_status=0, dqd_timeout_seconds=1, dqd_headers={},
            ai_enabled=False, llm_api_key="", llm_base_url="", llm_model="", llm_timeout_seconds=1, llm_request_retries=1,
            pull_auto_process=False, app_host="", app_port=1, app_debug=False,
        )
        form = build_create_form({"title_final": "测试标题", "body_html": "<p>这是一段超过三十字的正文，用来验证创建草稿表单编码。</p>", "channels": [11, 22], "litpic": "/fastdfs/x.jpg"}, {"tab_id": 99}, settings)
        self.assertIn(("dqd_enname", "hongsiqin"), form)
        self.assertIn(("archive_level", "B"), form)
        self.assertIn(("status", "0"), form)
        self.assertIn(("tabs[]", "99"), form)
        self.assertIn(("channels", "11,22"), form)

    def test_build_draft_url_uses_configured_template(self):
        settings = Settings(
            db_path=Path("/tmp/material-test.db"), material_api_base_url="", material_api_key="", material_api_caller="",
            material_api_timeout_seconds=1, material_api_hours=6, material_api_limit=100, material_api_sources=(),
            dqd_open_api_url="https://platform.dongqiudi.com/open/v1/do?api_name=admin-archive-createarticle",
            dqd_open_appid="app-id", dqd_open_appsecret="secret", dqd_open_redirect_uri="http://127.0.0.1:8900/api/open/auth/callback",
            dqd_enname="hongsiqin", dqd_archive_level="B", dqd_status=0, dqd_timeout_seconds=1, dqd_headers={},
            ai_enabled=False, llm_api_key="", llm_base_url="", llm_model="", llm_timeout_seconds=1, llm_request_retries=1,
            pull_auto_process=False, app_host="", app_port=1, app_debug=False,
            dqd_draft_url_template="https://dadmin.dongqiudi.com/admin/archives/articlePublish?articleId={archive_id}",
        )
        self.assertEqual(build_draft_url(settings, 6141262), "https://dadmin.dongqiudi.com/admin/archives/articlePublish?articleId=6141262")

    def test_create_draft_accepts_nested_archive_id_response(self):
        settings = Settings(
            db_path=Path("/tmp/material-test.db"), material_api_base_url="", material_api_key="", material_api_caller="",
            material_api_timeout_seconds=1, material_api_hours=6, material_api_limit=100, material_api_sources=(),
            dqd_open_api_url="https://platform.dongqiudi.com/open/v1/do?api_name=admin-archive-createarticle",
            dqd_open_appid="app-id", dqd_open_appsecret="secret", dqd_open_redirect_uri="http://127.0.0.1:8900/api/open/auth/callback",
            dqd_enname="hongsiqin", dqd_archive_level="B", dqd_status=0, dqd_timeout_seconds=1, dqd_headers={},
            ai_enabled=False, llm_api_key="", llm_base_url="", llm_model="", llm_timeout_seconds=1, llm_request_retries=1,
            pull_auto_process=False, app_host="", app_port=1, app_debug=False,
        )
        client = DqdClient(settings)
        client.open_platform = SimpleNamespace(
            post_signed=lambda **kwargs: (
                SimpleNamespace(status_code=200),
                {
                    "code": 0,
                    "data": {
                        "code": 0,
                        "data": {
                            "archive_id": 6141262,
                            "result": {"archive_id": 6141262, "message": "", "success": True},
                        },
                        "message": "ok",
                    },
                },
                "https://platform.dongqiudi.com/open/v1/do?api_name=admin-archive-createarticle",
            )
        )

        result = client.create_draft(
            {"title_final": "测试标题", "body_html": "<p>正文</p>", "channels": [11], "litpic": ""},
            {"tab_id": 99},
        )
        self.assertEqual(result["archive_id"], 6141262)
        self.assertTrue(result["draft_url"].endswith("articleId=6141262"))

    def test_open_platform_sign_and_authorize_url_are_structured(self):
        settings = Settings(
            db_path=Path("/tmp/material-test.db"), material_api_base_url="", material_api_key="", material_api_caller="",
            material_api_timeout_seconds=1, material_api_hours=6, material_api_limit=100, material_api_sources=(),
            dqd_open_api_url="https://platform.dongqiudi.com/open/v1/do?api_name=admin-archive-createarticle",
            dqd_open_appid="app-id", dqd_open_appsecret="secret", dqd_open_redirect_uri="http://127.0.0.1:8900/api/open/auth/callback",
            dqd_enname="hongsiqin", dqd_archive_level="B", dqd_status=0, dqd_timeout_seconds=1, dqd_headers={},
            ai_enabled=False, llm_api_key="", llm_base_url="", llm_model="", llm_timeout_seconds=1, llm_request_retries=1,
            pull_auto_process=False, app_host="", app_port=1, app_debug=False,
        )
        authorize_url, state = build_authorize_url(settings, state="state123")
        parsed = urlsplit(authorize_url)
        params = parse_qs(parsed.query)
        self.assertEqual(state, "state123")
        self.assertEqual(params["appid"][0], "app-id")
        self.assertEqual(params["api_name"][0], "admin-archive-createarticle")
        self.assertEqual(params["redirect_uri"][0], "http://127.0.0.1:8900/api/open/auth/callback")
        self.assertEqual(params["state"][0], "state123")

        signed_url = build_signed_request_url(settings)
        signed_params = parse_qs(urlsplit(signed_url).query)
        self.assertEqual(signed_params["appid"][0], "app-id")
        self.assertEqual(signed_params["api_name"][0], "admin-archive-createarticle")
        self.assertIn("timestamp", signed_params)
        self.assertIn("nonce", signed_params)
        self.assertIn("sign", signed_params)
        self.assertEqual(len(sign_query_params([("api_name", "admin-archive-createarticle"), ("appid", "app-id"), ("timestamp", "1"), ("nonce", "abc")], "secret")), 64)

    def test_material_events_preserve_status_history(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.db"
            db.init_db(db_path)
            material_id, inserted = db.upsert_material(db_path, {
                "material_key": material_key("https://example.com/a"), "source_url": "https://example.com/a",
                "canonical_url": "https://example.com/a", "source": "test", "upstream_archive_id": 0,
                "title_original": "标题", "body_html": "正文", "litpic": "", "channels": [1],
                "channel_warnings": [], "raw": {},
            })
            self.assertTrue(inserted)
            db.transition(db_path, material_id, "TAB_UNMAPPED", event_type="TAB_MAPPING_REQUIRED")
            item = db.get_material(db_path, material_id)
            self.assertEqual(item["status"], "TAB_UNMAPPED")
            self.assertEqual(len(db.list_events(db_path, material_id)), 2)

    def test_settings_accepts_legacy_dqd_env_names(self):
        with patch.dict(os.environ, {"DQD_OPEN_ENNAME": "legacy-user", "DQD_OPEN_ARCHIVE_LEVEL": "A"}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.dqd_enname, "legacy-user")
        self.assertEqual(settings.dqd_archive_level, "A")

    def test_process_pending_create_includes_ready_retry_and_unmapped_statuses(self):
        settings = SimpleNamespace(db_path=Path("/tmp/material-test.db"))
        rows = [
            {"id": 1, "status": "READY_TO_CREATE"},
            {"id": 2, "status": "CREATE_ERROR"},
            {"id": 3, "status": "AUTH_REQUIRED"},
            {"id": 4, "status": "AUTH_EXPIRED"},
            {"id": 5, "status": "RECEIVED"},
            {"id": 6, "status": "TAB_UNMAPPED"},
            {"id": 7, "status": "NEEDS_REVIEW"},
        ]
        created: list[int] = []
        processed: list[tuple[int, bool]] = []

        def fake_create(_settings, material_id):
            created.append(material_id)
            return {"id": material_id, "status": "DRAFT_CREATED"}

        def fake_process(_settings, material_id, *, create=False):
            processed.append((material_id, create))
            return {"id": material_id, "status": "DRAFT_CREATED" if create else "READY_TO_CREATE"}

        with (
            patch.object(pipeline.db, "list_materials", return_value=rows),
            patch.object(pipeline, "create_draft", side_effect=fake_create),
            patch.object(pipeline, "process_material", side_effect=fake_process),
        ):
            result = pipeline.process_pending(settings, limit=10, create=True)

        self.assertEqual(created, [1, 2, 3, 4, 6])
        self.assertEqual(processed, [(5, True)])
        self.assertEqual([item["id"] for item in result], [1, 2, 3, 4, 5, 6])

    def test_process_material_create_runs_full_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.db"
            db.init_db(db_path)
            db.upsert_source(db_path, "sport_es", tab_id=99, tab_name="体育")
            material_id, inserted = db.upsert_material(db_path, {
                "material_key": material_key("https://example.com/article-1"),
                "source_url": "https://example.com/article-1",
                "canonical_url": "https://example.com/article-1",
                "source": "sport_es",
                "upstream_archive_id": 0,
                "title_original": "测试标题",
                "body_html": "<p>这是一段足够长的正文，用来验证处理链路会先做质检、标题检查，再去创建草稿。</p>",
                "litpic": "",
                "channels": [11],
                "channel_warnings": [],
                "raw": {},
            })
            self.assertTrue(inserted)
            settings = self.make_settings(db_path)
            with patch("app.pipeline.DqdClient.create_draft", return_value={
                "archive_id": 6141262,
                "draft_url": "https://dadmin.dongqiudi.com/admin/archives/articlePublish?articleId=6141262",
                "payload": {"code": 0},
                "form_fields": ["title"],
                "request_url": "https://platform.dongqiudi.com/open/v1/do?api_name=admin-archive-createarticle",
            }):
                item = pipeline.process_material(settings, material_id, create=True)

            events = [event["event_type"] for event in db.list_events(db_path, material_id)]
            self.assertEqual(item["status"], "DRAFT_CREATED")
            self.assertEqual(item["dqd_archive_id"], 6141262)
            self.assertIn("QUALITY_STARTED", events)
            self.assertIn("READY_FOR_DRAFT", events)
            self.assertIn("DRAFT_CREATE_SUCCEEDED", events)

    def test_pull_endpoint_can_trigger_auto_process_and_create(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.db"
            settings = self.make_settings(db_path)
            app = create_app(settings)
            with app.test_client() as client, \
                patch("app.web.pull_materials", return_value={"run_id": 1, "sources": ["sport_es"], "fetched": 1, "inserted": 1, "updated": 0, "material_ids": [7], "errors": []}) as pull_mock, \
                patch("app.web.process_material_ids", return_value=[{"id": 7, "status": "DRAFT_CREATED"}]) as process_mock:
                response = client.post("/api/pull", json={"hours": 6, "limit": 100, "process": True, "create": True, "process_limit": 100})

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["processed"][0]["status"], "DRAFT_CREATED")
            pull_mock.assert_called_once()
            process_mock.assert_called_once()
            self.assertTrue(process_mock.call_args.kwargs["create"])
            self.assertEqual(process_mock.call_args.args[1], [7])


if __name__ == "__main__":
    unittest.main()
