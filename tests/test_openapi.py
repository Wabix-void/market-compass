"""官方开放平台适配器单元测试（无需真实凭据，不发起任何网络请求）。

运行：python tests/test_openapi.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.collector import openapi_source as api  # noqa: E402


class SignTests(unittest.TestCase):
    def test_deterministic_and_order_independent(self):
        first = api.sign_params({"a": "1", "b": "2"}, "secret")
        second = api.sign_params({"b": "2", "a": "1"}, "secret")
        self.assertEqual(first, second)
        self.assertEqual(first, first.upper())
        self.assertEqual(len(first), 32)

    def test_changes_with_secret_and_params(self):
        self.assertNotEqual(api.sign_params({"a": "1"}, "s1"),
                            api.sign_params({"a": "1"}, "s2"))
        self.assertNotEqual(api.sign_params({"a": "1"}, "s"),
                            api.sign_params({"a": "2"}, "s"))

    def test_ignores_empty_values_and_sign_key(self):
        base = api.sign_params({"a": "1"}, "s")
        self.assertEqual(base, api.sign_params({"a": "1", "b": "", "sign": "xxx"}, "s"))


class ConfigTests(unittest.TestCase):
    def test_load_missing_file_returns_empty(self):
        self.assertEqual(api.load_config(Path("no/such/file.env")), {})

    def test_save_and_load_roundtrip(self):
        # 用工作区内的临时目录（沙箱不允许写系统 temp）
        folder = PROJECT_ROOT / "tests" / ".tmp"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "openapi.env"
        try:
            api.save_config({"PROVIDER": "taobao", "APP_KEY": "abc", "APP_SECRET": "xyz"}, path)
            config = api.load_config(path)
            self.assertEqual(config["PROVIDER"], "taobao")
            self.assertEqual(config["APP_KEY"], "abc")
            self.assertEqual(config["APP_SECRET"], "xyz")
        finally:
            path.unlink(missing_ok=True)
            folder.rmdir()

    def test_missing_keys(self):
        self.assertEqual(api.missing_keys({}, "taobao"), ["app_key", "app_secret"])
        self.assertEqual(api.missing_keys({"APP_KEY": "k"}, "taobao"), ["app_secret"])
        self.assertEqual(api.missing_keys({"APP_KEY": "k", "APP_SECRET": "s"}, "taobao"), [])

    def test_config_hint_mentions_setup_script_and_apply_url(self):
        hint = api.config_hint("pdd")
        self.assertIn("setup_openapi.py", hint)
        self.assertIn(api.PROVIDERS["pdd"]["apply_url"], hint)


class RequestTests(unittest.TestCase):
    def test_taobao_params(self):
        gateway, params = api.build_request("taobao", {"APP_KEY": "k", "APP_SECRET": "s"},
                                            {"q": "保温杯"})
        self.assertIn("taobao.com", gateway)
        self.assertEqual(params["app_key"], "k")
        self.assertEqual(params["method"], "taobao.tbk.item.get")
        self.assertEqual(params["q"], "保温杯")
        self.assertIn("sign", params)
        self.assertNotIn("app_secret", params)      # 密钥绝不进请求

    def test_jd_uses_its_own_method_param(self):
        _, params = api.build_request("jd", {"APP_KEY": "k", "APP_SECRET": "s"})
        self.assertEqual(params["method"], "jingdong.ware.list.get")

    def test_pdd_uses_client_id_and_type(self):
        _, params = api.build_request("pdd", {"APP_KEY": "cid", "APP_SECRET": "s"})
        self.assertEqual(params["client_id"], "cid")
        self.assertEqual(params["type"], "pdd.ddk.goods.search")
        self.assertIsInstance(params["timestamp"], str)
        self.assertTrue(params["timestamp"].isdigit())   # 拼多多用 Unix 秒


class ParseTests(unittest.TestCase):
    def test_parse_count(self):
        self.assertEqual(api.parse_count("1万+"), 10000)
        self.assertEqual(api.parse_count("1.2万+"), 12000)
        self.assertEqual(api.parse_count("9000+"), 9000)
        self.assertEqual(api.parse_count("1,234"), 1234)
        self.assertEqual(api.parse_count(1234), 1234)
        self.assertIsNone(api.parse_count(None))
        self.assertIsNone(api.parse_count("暂无"))

    def test_extract_items_from_nested_payload(self):
        payload = {"resp": {"data": {"items": [{"title": "杯子", "num_iid": 1}]}}}
        self.assertEqual(len(api.extract_items(payload)), 1)
        self.assertEqual(api.extract_items({"resp": {"data": {}}}), [])

    def test_normalize_item_pdd_price_in_cents(self):
        raw = {"goods_id": 9, "goods_name": "保温杯", "min_group_price": 990, "sales_tip": "1万+"}
        item = api.normalize_item(raw, "pdd")
        self.assertEqual(item["product_id"], "pdd_9")
        self.assertEqual(item["price"], 9.9)
        self.assertEqual(item["sales"], 10000)

    def test_normalize_item_skips_incomplete_records(self):
        self.assertIsNone(api.normalize_item({"title": "无 ID"}, "taobao"))
        self.assertIsNone(api.normalize_item({"num_iid": 1}, "taobao"))

    def test_parse_response_filters_bad_rows(self):
        payload = {"items": [{"num_iid": 1, "title": "A", "volume": 10}, {"num_iid": 2}]}
        rows = api.parse_response(payload, "taobao")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "A")


class CredentialGuardTests(unittest.TestCase):
    def test_missing_credentials_returns_actionable_hint(self):
        result = api.collect(keywords=["保温杯"], provider="taobao", config={}, verbose=False)
        self.assertIn("error", result)
        self.assertIn("setup_openapi.py", result["error"])
        self.assertEqual(result["missing_keys"], ["app_key", "app_secret"])

    def test_dry_run_works_without_credentials(self):
        result = api.collect(keywords=["保温杯"], provider="taobao", config={},
                             dry_run=True, verbose=False)
        self.assertNotIn("error", result)
        self.assertEqual(len(result["pages"]), 1)
        preview = result["pages"][0]["request_preview"]
        self.assertIn("sign", preview)
        self.assertTrue(preview["sign"].endswith("…"))   # 签名被脱敏

    def test_unknown_provider_rejected(self):
        result = api.collect(provider="amazon", config={}, verbose=False)
        self.assertIn("未知平台", result["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
