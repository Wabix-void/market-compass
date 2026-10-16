"""AI 数字溯源校验的离线单测（不调用模型、不联网）。

覆盖「AI 追问」方案的核心主张：**不要求模型不撒谎，但要求它撒的谎能被抓住。**
重点验证两件事 —— 真实数字（含百分比等价写法）能通过，编造数字一定会被抓住。

运行：python tests/test_ai_grounding.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.ai import advisor  # noqa: E402

# 与真实 market_snapshot() 的字段结构保持一致
SNAPSHOT = {
    "total_sps": 46200.0,
    "growth": -0.055,
    "cr5": 0.8979,
    "hhi": 0.1696,
    "brand_cr3": 1.0,
    "avg_confidence": 0.406,
    "listing_count": 30,
    "days": 56,
    "top_products": [{"sps": 4444.0, "price": 155.0, "confidence": 0.46}],
}


class PassPathTests(unittest.TestCase):
    """真实数字必须全部通过，否则模型正常作答会被冤枉。"""

    def test_real_numbers_pass(self):
        result = advisor.verify_answer_numbers(
            SNAPSHOT, "保温杯怎么样？",
            "该品类 CR5 为 0.8979，HHI 为 0.1696，共 30 个在售商品。")
        self.assertEqual(result["unverified"], [], f"误报：{result['unverified']}")
        self.assertTrue(result["verified"])

    def test_percent_equivalent_passes(self):
        """模型把 0.8979 说成 89.8% 是正常的，不能被判为编造。"""
        result = advisor.verify_answer_numbers(
            SNAPSHOT, "集中度如何？", "CR5 高达 89.8%，说明头部高度集中。")
        self.assertEqual(result["unverified"], [], f"误报：{result['unverified']}")

    def test_metric_name_digits_exempt(self):
        """CR5 / CR3 这类指标标识符里的数字不是数据。"""
        result = advisor.verify_answer_numbers(
            SNAPSHOT, "集中度？", "CR5 与 CR3 都很高，头部占据绝大部分份额。")
        self.assertEqual(result["unverified"], [], f"误报：{result['unverified']}")

    def test_user_question_digits_exempt(self):
        """用户提问里的数字由用户提供，不属于模型生成内容。"""
        result = advisor.verify_answer_numbers(
            SNAPSHOT, "我只有 5 万预算，适合吗？",
            "在 5 万预算下建议先小批量测款。")
        self.assertEqual(result["unverified"], [], f"误报：{result['unverified']}")

    def test_pool_is_not_empty(self):
        result = advisor.verify_answer_numbers(SNAPSHOT, "q", "a")
        self.assertGreater(result["metric_pool_size"], 0)


class FailPathTests(unittest.TestCase):
    """编造的数字必须被抓住 —— 这是整套方案说服力的来源。"""

    def test_fabricated_numbers_caught(self):
        result = advisor.verify_answer_numbers(
            SNAPSHOT, "值得做吗？",
            "该品类 CR5 为 0.8979，月销量约 5000 件，建议准备 8 万元预算。")
        self.assertIn("5000", result["unverified"])
        self.assertIn("8", result["unverified"])
        self.assertFalse(result["verified"])
        # 真实数字仍应被正确识别
        self.assertIn("0.8979", result["citations"])

    def test_close_but_wrong_number_caught(self):
        """0.8979 与 0.95 相对差约 5.8%，超出 2% 容差，必须抓出来。"""
        result = advisor.verify_answer_numbers(
            SNAPSHOT, "集中度？", "CR5 约为 0.95。")
        self.assertIn("0.95", result["unverified"])

    def test_invented_growth_caught(self):
        result = advisor.verify_answer_numbers(
            SNAPSHOT, "趋势如何？", "环比增长 12.5%，处于快速上升期。")
        self.assertIn("12.5", result["unverified"])

    def test_all_numbers_are_accounted_for(self):
        """抽出规则必须完备：citations + unverified = 剥离指标编号后的数字总数。"""
        answer = "CR5 为 0.8979，增长 12.5%，共 30 款，预算 8 万。"
        result = advisor.verify_answer_numbers(SNAPSHOT, "分析一下", answer)
        expected = len(advisor._NUM_RE.findall(advisor._METRIC_TOKEN_RE.sub(" ", answer)))
        self.assertEqual(len(result["citations"]) + len(result["unverified"]), expected)

    def test_metric_token_stripped_before_extraction(self):
        """CR5 / Top12 这类指标编号整体剥离，其中的数字不应进入结果。"""
        result = advisor.verify_answer_numbers(
            SNAPSHOT, "集中度？", "CR5 为 0.8979，Top12 商品里 30 款在售。")
        for token in ("5", "12"):
            self.assertNotIn(token, result["citations"], f"{token} 不该被当成数据")
            self.assertNotIn(token, result["unverified"], f"{token} 不该被判为编造")
        self.assertIn("0.8979", result["citations"])
        self.assertIn("30", result["citations"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
