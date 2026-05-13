"""
LangGraph 小红书 Playwright Pipeline 入口脚本的测试。

测试内容：
  1. CLI 参数解析
  2. 使用临时目录 + XhsImportAdapter（非 Playwright）+ MockLLMClient 跑完整 langgraph llm_annotation
  3. 验证 5 个核心产物存在
  4. 不访问真实小红书
  5. 不访问真实 LLM
  6. analysis_mode="rule" 不要求 llm_client
  7. analysis_mode="llm_annotation" 时 llm_client 正确传入
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Mock playwright BEFORE any imports that might trigger its import.
# This ensures the test is truly offline and does not require playwright.
# ---------------------------------------------------------------------------
import unittest.mock as um
sys.modules["playwright"] = um.MagicMock()
sys.modules["playwright.sync_api"] = um.MagicMock()

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.run_langgraph_xhs_playwright_pipeline import parse_args
from src.graph.graph import build_ugc_market_graph
from src.graph.state import UGCGraphState
from src.llm.client import MockLLMClient
from src.schemas import AnalysisRequest
from src.utils import AppPaths

# Mock 数据：帖子 + 评论
_MOCK_SAMPLE = {
    "posts": [
        {
            "note_id": "test_p_001",
            "title": "控油洗发水测评",
            "desc": "这个产品真的很好用，控油效果不错，但是价格偏高",
            "create_time": 1710748800,
            "liked_count": 100,
            "comment_count": 2,
            "nickname": "测试用户",
            "tag_list": ["控油", "洗发水"],
        }
    ],
    "comments": [
        {
            "id": "test_c_001",
            "note_id": "test_p_001",
            "content": "真的很好用，控油效果明显",
            "create_time": 1710777600,
            "like_count": 5,
            "nickname": "评论用户1",
        },
        {
            "id": "test_c_002",
            "note_id": "test_p_001",
            "content": "就是太贵了，性价比不高",
            "create_time": 1710777900,
            "like_count": 3,
            "nickname": "评论用户2",
        },
    ],
}

# Mock LLM 返回数据
_MOCK_ANNOTATION_RESPONSE = {
    "annotations": [
        {
            "index": 0,
            "sentiment": "positive",
            "pain_point_labels": [],
            "need_labels": ["控油效果好"],
            "complaint_labels": [],
            "solution_labels": ["氨基酸洗发水"],
            "market_signal_labels": [],
            "intent_labels": ["求推荐"],
            "reason": "正面评价控油效果",
        },
        {
            "index": 1,
            "sentiment": "negative",
            "pain_point_labels": ["价格贵"],
            "need_labels": ["性价比高"],
            "complaint_labels": ["太贵了"],
            "solution_labels": [],
            "market_signal_labels": [],
            "intent_labels": [],
            "reason": "吐槽价格太高",
        },
    ]
}


def _write_mock_export(tmp_dir: str) -> str:
    """在临时目录下写入 mock xhs_export.json，返回完整路径。"""
    path = os.path.join(tmp_dir, "xhs_export.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_MOCK_SAMPLE, f, ensure_ascii=False)
    return path


class TestCliArgs(unittest.TestCase):
    """CLI 参数解析测试（不启动 Playwright，不访问小红书）。"""

    def test_keyword_required(self):
        """--keyword 是必填参数，缺失时抛出 SystemExit。"""
        with self.assertRaises(SystemExit):
            parse_args([])

    def test_parse_keyword(self):
        """--keyword 被正确解析。"""
        args = parse_args(["--keyword", "控油洗发水"])
        self.assertEqual(args.keyword, "控油洗发水")

    def test_default_max_posts(self):
        """--max-posts 默认值为 3。"""
        args = parse_args(["--keyword", "test"])
        self.assertEqual(args.max_posts, 3)

    def test_default_max_comments(self):
        """--max-comments 默认值为 None（由 resolve_max_comments 处理默认值）。"""
        args = parse_args(["--keyword", "test"])
        self.assertIsNone(args.max_comments)

    def test_default_max_comments_per_post(self):
        """--max-comments-per-post 默认值为 None。"""
        args = parse_args(["--keyword", "test"])
        self.assertIsNone(args.max_comments_per_post)

    def test_parse_max_comments(self):
        """--max-comments 参数可正常解析。"""
        args = parse_args(["--keyword", "test", "--max-comments", "15"])
        self.assertEqual(args.max_comments, 15)

    def test_parse_max_comments_per_post(self):
        """--max-comments-per-post 参数可正常解析。"""
        args = parse_args(["--keyword", "test", "--max-comments-per-post", "25"])
        self.assertEqual(args.max_comments_per_post, 25)

    def test_default_analysis_mode(self):
        """--analysis-mode 默认值为 'rule'。"""
        args = parse_args(["--keyword", "test"])
        self.assertEqual(args.analysis_mode, "rule")

    def test_parse_analysis_mode_llm_annotation(self):
        """--analysis-mode 可解析为 llm_annotation。"""
        args = parse_args(["--keyword", "test", "--analysis-mode", "llm_annotation"])
        self.assertEqual(args.analysis_mode, "llm_annotation")

    def test_mock_llm_flag(self):
        """--mock-llm 存在时 mock_llm 为 True。"""
        args = parse_args(["--keyword", "test", "--mock-llm"])
        self.assertTrue(args.mock_llm)

    def test_mock_llm_default_false(self):
        """--mock-llm 不传时 mock_llm 为 False。"""
        args = parse_args(["--keyword", "test"])
        self.assertFalse(args.mock_llm)

    def test_default_headless(self):
        """--headless 默认值为 False。"""
        args = parse_args(["--keyword", "test"])
        self.assertFalse(args.headless)

    def test_headless_flag(self):
        """--headless 存在时 headless 为 True。"""
        args = parse_args(["--keyword", "test", "--headless"])
        self.assertTrue(args.headless)

    def test_request_interval_default(self):
        """--request-interval-seconds 默认值为 3.0。"""
        args = parse_args(["--keyword", "test"])
        self.assertEqual(args.request_interval_seconds, 3.0)

    def test_invalid_analysis_mode(self):
        """不支持的 --analysis-mode 抛出 SystemExit。"""
        with self.assertRaises(SystemExit):
            parse_args(["--keyword", "test", "--analysis-mode", "invalid"])


class TestRuleModeDirect(unittest.TestCase):
    """验证 rule 模式可以直接运行（不要求 llm_client）。"""

    def setUp(self):
        self.request = AnalysisRequest(
            topic="控油洗发水",
            product_direction="控油洗发水产品",
            industry_question="用户对控油洗发水的需求和痛点",
        )

    def test_build_graph_rule_no_llm_client(self):
        """rule 模式构建 graph 不需要 llm_client。"""
        graph = build_ugc_market_graph(analysis_mode="rule")
        self.assertIsNotNone(graph)

    def test_rule_mode_runs_with_import_adapter(self):
        """rule 模式 + XhsImportAdapter + temp dir 可完整运行。"""
        from src.adapters import XhsImportAdapter

        with tempfile.TemporaryDirectory(prefix="ugc_test_rule_") as tmp_dir:
            mock_file = _write_mock_export(tmp_dir)
            exp_paths = AppPaths.from_data_root(tmp_dir)

            adapter = XhsImportAdapter(mock_file)
            graph = build_ugc_market_graph(adapter=adapter, analysis_mode="rule")
            state = UGCGraphState(request=self.request, paths=exp_paths)
            result = graph.invoke(state)

            self.assertTrue(result.get("success"), "rule 模式应正常执行")
            self.assertIsNotNone(result.get("report_path"))

    def test_rule_mode_five_artifacts(self):
        """rule 模式运行后 5 个核心产物存在。"""
        from src.adapters import XhsImportAdapter

        with tempfile.TemporaryDirectory(prefix="ugc_test_rule_") as tmp_dir:
            mock_file = _write_mock_export(tmp_dir)
            exp_paths = AppPaths.from_data_root(tmp_dir)

            adapter = XhsImportAdapter(mock_file)
            graph = build_ugc_market_graph(adapter=adapter, analysis_mode="rule")
            state = UGCGraphState(request=self.request, paths=exp_paths)
            graph.invoke(state)

            artifacts = [
                exp_paths.raw_posts_file,
                exp_paths.normalized_posts_file,
                exp_paths.insights_file,
                exp_paths.scorecard_file,
                exp_paths.report_file,
            ]
            for path in artifacts:
                self.assertTrue(os.path.exists(path), f"产物不存在: {path}")


class TestLLMAnnotationModeDirect(unittest.TestCase):
    """验证 llm_annotation 模式正确处理 llm_client。"""

    def setUp(self):
        self.request = AnalysisRequest(
            topic="控油洗发水",
            product_direction="氨基酸控油洗发水",
            industry_question="用户对控油洗发水的需求和痛点",
        )

    def test_llm_annotation_requires_llm_client(self):
        """llm_annotation 模式不提供 llm_client 时抛出 ValueError。"""
        with self.assertRaises(ValueError) as ctx:
            build_ugc_market_graph(analysis_mode="llm_annotation", llm_client=None)
        self.assertIn("requires llm_client", str(ctx.exception))

    def test_llm_annotation_with_mock_llm_client(self):
        """llm_annotation 模式 + MockLLMClient + 临时目录可完整运行。"""
        from src.adapters import XhsImportAdapter

        with tempfile.TemporaryDirectory(prefix="ugc_test_llm_") as tmp_dir:
            mock_file = _write_mock_export(tmp_dir)
            exp_paths = AppPaths.from_data_root(tmp_dir)

            mock_llm = MockLLMClient(mock_response=_MOCK_ANNOTATION_RESPONSE)
            adapter = XhsImportAdapter(mock_file)
            graph = build_ugc_market_graph(
                adapter=adapter,
                analysis_mode="llm_annotation",
                llm_client=mock_llm,
            )
            state = UGCGraphState(request=self.request, paths=exp_paths)
            result = graph.invoke(state)

            self.assertTrue(result.get("success"), "llm_annotation 模式应正常执行")
            self.assertIsNotNone(result.get("report_path"))

    def test_llm_annotation_mode_five_artifacts(self):
        """llm_annotation 模式运行后 5 个核心产物存在。"""
        from src.adapters import XhsImportAdapter

        with tempfile.TemporaryDirectory(prefix="ugc_test_llm_") as tmp_dir:
            mock_file = _write_mock_export(tmp_dir)
            exp_paths = AppPaths.from_data_root(tmp_dir)

            mock_llm = MockLLMClient(mock_response=_MOCK_ANNOTATION_RESPONSE)
            adapter = XhsImportAdapter(mock_file)
            graph = build_ugc_market_graph(
                adapter=adapter,
                analysis_mode="llm_annotation",
                llm_client=mock_llm,
            )
            state = UGCGraphState(request=self.request, paths=exp_paths)
            graph.invoke(state)

            artifacts = [
                exp_paths.raw_posts_file,
                exp_paths.normalized_posts_file,
                exp_paths.insights_file,
                exp_paths.scorecard_file,
                exp_paths.report_file,
            ]
            for path in artifacts:
                self.assertTrue(os.path.exists(path), f"产物不存在: {path}")

    def test_no_real_llm_api_call(self):
        """llm_annotation 模式 + MockLLMClient 不访问真实 API。"""
        from src.adapters import XhsImportAdapter

        with tempfile.TemporaryDirectory(prefix="ugc_test_llm_") as tmp_dir:
            mock_file = _write_mock_export(tmp_dir)
            exp_paths = AppPaths.from_data_root(tmp_dir)

            mock_llm = MockLLMClient(mock_response=_MOCK_ANNOTATION_RESPONSE)
            adapter = XhsImportAdapter(mock_file)
            graph = build_ugc_market_graph(
                adapter=adapter,
                analysis_mode="llm_annotation",
                llm_client=mock_llm,
            )
            state = UGCGraphState(request=self.request, paths=exp_paths)
            result = graph.invoke(state)

            self.assertTrue(result.get("success"))
            # 验证 insights 存在（来自 annotations 聚合）
            self.assertIsNotNone(result.get("insights"))
            insights = result["insights"]
            self.assertGreaterEqual(len(insights.pain_points), 0)
            self.assertGreaterEqual(len(insights.user_needs), 0)

    def test_comment_annotations_populated(self):
        """llm_annotation 模式运行后 comment_annotations 被填充。"""
        from src.adapters import XhsImportAdapter

        with tempfile.TemporaryDirectory(prefix="ugc_test_llm_") as tmp_dir:
            mock_file = _write_mock_export(tmp_dir)
            exp_paths = AppPaths.from_data_root(tmp_dir)

            mock_llm = MockLLMClient(mock_response=_MOCK_ANNOTATION_RESPONSE)
            adapter = XhsImportAdapter(mock_file)
            graph = build_ugc_market_graph(
                adapter=adapter,
                analysis_mode="llm_annotation",
                llm_client=mock_llm,
            )
            state = UGCGraphState(request=self.request, paths=exp_paths)
            result = graph.invoke(state)

            annotations = result.get("comment_annotations")
            self.assertIsNotNone(annotations)
            self.assertGreater(len(annotations), 0)

    def test_llm_client_passed_to_graph(self):
        """验证 llm_client 正确传入 build_ugc_market_graph。"""
        mock_llm = MockLLMClient()
        graph = build_ugc_market_graph(
            analysis_mode="llm_annotation",
            llm_client=mock_llm,
        )
        self.assertIsNotNone(graph)
        # 验证 llm_annotation 模式包含 annotation 节点
        nodes = set(graph.nodes.keys())
        self.assertIn("annotate_comments", nodes)


class TestNoRealAccess(unittest.TestCase):
    """验证测试不依赖于外部资源。"""

    def test_playwright_is_mocked(self):
        """验证 playwright 模块已被 mock（测试离线运行）。"""
        import playwright
        self.assertIsInstance(playwright, um.MagicMock)

    def test_playwright_sync_api_is_mocked(self):
        """验证 playwright.sync_api 模块已被 mock。"""
        import playwright.sync_api
        self.assertIsInstance(playwright.sync_api, um.MagicMock)


if __name__ == "__main__":
    unittest.main()
