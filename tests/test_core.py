import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from types import SimpleNamespace

from app import db
from app.config import Settings
from app.dqd_client import DqdClient, build_create_form, build_draft_url
from app.open_platform import build_authorize_url, build_signed_request_url, sign_query_params
from app.utils import canonicalize_url, clean_channels, material_key


class CoreTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
