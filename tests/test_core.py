import tempfile
import unittest
from pathlib import Path

from app import db
from app.config import Settings
from app.dqd_client import build_create_form
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
            dqd_open_api_url="", dqd_enname="hongsiqin", dqd_archive_level="B", dqd_status=0, dqd_timeout_seconds=1, dqd_headers={},
            ai_enabled=False, llm_api_key="", llm_base_url="", llm_model="", llm_timeout_seconds=1, llm_request_retries=1,
            pull_auto_process=False, app_host="", app_port=1, app_debug=False,
        )
        form = build_create_form({"title_final": "测试标题", "body_html": "<p>这是一段超过三十字的正文，用来验证创建草稿表单编码。</p>", "channels": [11, 22], "litpic": "/fastdfs/x.jpg"}, {"tab_id": 99}, settings)
        self.assertIn(("dqd_enname", "hongsiqin"), form)
        self.assertIn(("archive_level", "B"), form)
        self.assertIn(("status", "0"), form)
        self.assertIn(("tabs[]", "99"), form)
        self.assertIn(("channels", "11,22"), form)

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
