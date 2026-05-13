"""Rule vs LLM 对比脚本离线测试。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


class TestRuleVsLLMAnalysisMockLLM(unittest.TestCase):
    """对比脚本测试（--mock-llm 模式）。"""

    def setUp(self):
        # 备份原始数据路径
        self.raw_posts = os.path.join(_PROJECT_ROOT, "data", "raw", "raw_posts.json")
        self.raw_comments = os.path.join(_PROJECT_ROOT, "data", "raw", "raw_comments.json")

    def test_mock_llm_generates_report(self):
        """--mock-llm 可生成对比报告且不访问真实 LLM。"""
        if not os.path.exists(self.raw_posts) or not os.path.exists(self.raw_comments):
            self.skipTest("需要 data/raw/raw_posts.json 和 data/raw/raw_comments.json")

        from scripts.run_rule_vs_llm_analysis import main as script_main

        with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w") as f:
            output_path = f.name

        test_args = ["--mock-llm", "--output", output_path]
        try:
            with patch("sys.argv", ["run_rule_vs_llm_analysis.py"] + test_args):
                try:
                    script_main()
                except SystemExit as e:
                    self.assertEqual(e.code, 0)

            self.assertTrue(os.path.exists(output_path))
            with open(output_path, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Rule vs LLM", content)
            self.assertIn("人工评价", content)
            self.assertIn("Evidence 检查", content)
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_llm_annotation_mode_supports_mock_llm(self):
        """--analysis-mode llm_annotation --mock-llm 可运行。"""
        if not os.path.exists(self.raw_posts) or not os.path.exists(self.raw_comments):
            self.skipTest("需要 data/raw/raw_posts.json 和 data/raw/raw_comments.json")

        from scripts.run_rule_vs_llm_analysis import main as script_main

        with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w") as f:
            output_path = f.name

        test_args = ["--analysis-mode", "llm_annotation", "--mock-llm", "--output", output_path]
        try:
            with patch("sys.argv", ["run_rule_vs_llm_analysis.py"] + test_args):
                try:
                    script_main()
                except SystemExit as e:
                    self.assertEqual(e.code, 0)

            self.assertTrue(os.path.exists(output_path))
            with open(output_path, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Rule vs LLM (annotation)", content)
            self.assertIn("LLM 分析模式：llm_annotation", content)
            self.assertIn("人工评价", content)
            self.assertIn("Evidence 检查", content)
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_report_contains_rule_and_llm_sections(self):
        """报告包含 Rule 和 LLM 两个版本的比较。"""
        if not os.path.exists(self.raw_posts) or not os.path.exists(self.raw_comments):
            self.skipTest("需要 data/raw/raw_posts.json 和 data/raw/raw_comments.json")

        from scripts.run_rule_vs_llm_analysis import _generate_report

        rule_result = {
            "sentiment": {"overall_sentiment": "positive"},
            "insight": {
                "pain_points": ["产品太油"],
                "user_needs": ["需要控油"],
                "complaints": ["不好用"],
                "solutions": ["推荐回购"],
                "market_signals": ["有购买意向"],
                "evidence_post_ids": ["p1"],
                "evidence_comment_ids": ["c1"],
            },
        }
        llm_result = {
            "sentiment": {"overall_sentiment": "neutral"},
            "insight": {
                "pain_points": ["产品导致过敏", "瓶身设计差"],
                "user_needs": ["需要温和配方"],
                "complaints": ["物流太慢"],
                "solutions": ["换品牌"],
                "market_signals": ["需求上升"],
                "evidence_post_ids": ["p2"],
                "evidence_comment_ids": ["c2", "c3"],
            },
        }

        with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w") as f:
            output_path = f.name

        try:
            _generate_report(
                rule_result, llm_result, output_path, use_mock=True,
                posts_count=1, comments_count=3,
            )
            with open(output_path, encoding="utf-8") as f:
                content = f.read()

            # 检查包含规则版和 LLM 版的痛点
            self.assertIn("产品太油", content)
            self.assertIn("产品导致过敏", content)
            self.assertIn("Rule 版", content)
            self.assertIn("LLM 版", content)
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_parse_args_defaults(self):
        """默认参数解析正确。"""
        from scripts.run_rule_vs_llm_analysis import parse_args
        with patch("sys.argv", ["run_rule_vs_llm_analysis.py"]):
            args = parse_args()
            self.assertFalse(args.mock_llm)
            self.assertEqual(args.output, "docs/rule_vs_llm_review.md")
            self.assertEqual(args.max_comments, 50)
            self.assertEqual(args.analysis_mode, "llm")

    def test_parse_args_mock_llm(self):
        """--mock-llm 参数被正确解析。"""
        from scripts.run_rule_vs_llm_analysis import parse_args
        with patch("sys.argv", ["run_rule_vs_llm_analysis.py", "--mock-llm", "--output", "test.md"]):
            args = parse_args()
            self.assertTrue(args.mock_llm)
            self.assertEqual(args.output, "test.md")
            self.assertEqual(args.analysis_mode, "llm")

    def test_parse_args_analysis_mode(self):
        """--analysis-mode 参数被正确解析。"""
        from scripts.run_rule_vs_llm_analysis import parse_args
        with patch("sys.argv", ["run_rule_vs_llm_analysis.py", "--analysis-mode", "llm_annotation"]):
            args = parse_args()
            self.assertEqual(args.analysis_mode, "llm_annotation")

    def test_parse_args_invalid_analysis_mode(self):
        """非法的 --analysis-mode 值会报错。"""
        from scripts.run_rule_vs_llm_analysis import parse_args
        with patch("sys.argv", ["run_rule_vs_llm_analysis.py", "--analysis-mode", "invalid"]):
            with self.assertRaises(SystemExit):
                parse_args()


class TestRuleVsLLMAnalysisWithoutData(unittest.TestCase):
    """无原始数据时脚本行为测试。"""

    def test_load_raw_data_exits_on_missing(self):
        """无 raw 数据时脚本退出。"""
        from scripts.run_rule_vs_llm_analysis import _load_raw_data

        # 临时 rename raw 文件
        raw_posts = os.path.join(_PROJECT_ROOT, "data", "raw", "raw_posts.json")
        raw_comments = os.path.join(_PROJECT_ROOT, "data", "raw", "raw_comments.json")

        if not os.path.exists(raw_posts) or not os.path.exists(raw_comments):
            self.skipTest("需要原始数据存在才能测试缺失情况")

        # 暂时重命名 raw 文件
        os.rename(raw_posts, raw_posts + ".bak")
        os.rename(raw_comments, raw_comments + ".bak")
        try:
            with self.assertRaises(SystemExit):
                _load_raw_data()
        finally:
            os.rename(raw_posts + ".bak", raw_posts)
            os.rename(raw_comments + ".bak", raw_comments)


if __name__ == "__main__":
    unittest.main()
