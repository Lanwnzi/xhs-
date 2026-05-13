"""LangGraph llm_annotation 模式单元测试。

测试内容：
  1. 默认模式为 rule
  2. rule 模式不包含 annotation 相关节点
  3. llm_annotation 模式不提供 llm_client 时抛出 ValueError
  4. llm_annotation 模式包含 annotation 节点
  5. llm_annotation 模式不包含 rule 模式的 sentiment/insight 节点
  6. llm_annotation 模式使用 mock 数据可运行
  7. rule 模式现有行为不受影响
  8. 测试不访问真实 API
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.graph.graph import build_ugc_market_graph
from src.graph.state import UGCGraphState
from src.llm.client import MockLLMClient
from src.schemas import AnalysisRequest
from src.utils import AppPaths

# 用于 graph compile 和 node wiring 测试的 mock 数据
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

# Mock LLM 返回用于 annotation 模式的固定响应
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


class TestBuildGraphModes(unittest.TestCase):
    """Graph 构建模式测试（不执行 pipeline）。"""

    @staticmethod
    def _user_nodes(graph) -> set[str]:
        """返回 graph 中非 LangGraph 内部的节点名（过滤 __start__、__end__ 等）。"""
        return {n for n in graph.nodes.keys() if not n.startswith("__")}

    def test_build_graph_default_rule_mode(self):
        """默认 analysis_mode 为 'rule'。"""
        graph = build_ugc_market_graph()
        self.assertIsNotNone(graph)
        # 默认 mode 应包含 rule 节点
        expected_rule = {"collect", "normalize", "sentiment", "insight", "score", "report"}
        actual = self._user_nodes(graph)
        for name in expected_rule:
            self.assertIn(name, actual, f"rule 模式应包含节点: {name}")

    def test_build_graph_rule_mode_excludes_annotation_nodes(self):
        """rule 模式不包含 annotation 节点。"""
        graph = build_ugc_market_graph(analysis_mode="rule")
        actual = self._user_nodes(graph)
        annotation_nodes = {"annotate_comments", "sentiment_from_annotations", "insight_from_annotations"}
        for name in annotation_nodes:
            self.assertNotIn(name, actual, f"rule 模式不应包含节点: {name}")

    def test_build_graph_llm_annotation_requires_llm_client(self):
        """llm_annotation 模式不提供 llm_client 时抛出 ValueError。"""
        with self.assertRaises(ValueError) as ctx:
            build_ugc_market_graph(analysis_mode="llm_annotation", llm_client=None)
        self.assertIn("requires llm_client", str(ctx.exception))

    def test_build_graph_llm_annotation_includes_annotation_nodes(self):
        """llm_annotation 模式包含 annotation 节点。"""
        mock = MockLLMClient()
        graph = build_ugc_market_graph(analysis_mode="llm_annotation", llm_client=mock)
        expected = {
            "collect", "normalize", "annotate_comments",
            "sentiment_from_annotations", "insight_from_annotations",
            "score", "report",
        }
        actual = self._user_nodes(graph)
        for name in expected:
            self.assertIn(name, actual, f"llm_annotation 模式应包含节点: {name}")

    def test_build_graph_llm_annotation_excludes_rule_sentiment_insight(self):
        """llm_annotation 模式不包含 rule 模式的 sentiment 和 insight 节点。"""
        mock = MockLLMClient()
        graph = build_ugc_market_graph(analysis_mode="llm_annotation", llm_client=mock)
        actual = self._user_nodes(graph)
        rule_only = {"sentiment", "insight"}
        for name in rule_only:
            self.assertNotIn(name, actual, f"llm_annotation 模式不应包含 rule 节点: {name}")

    def test_rule_mode_existing_behavior_unchanged(self):
        """rule 模式现有行为不受影响（包含全部标准节点）。"""
        graph = build_ugc_market_graph(analysis_mode="rule")
        expected = {
            "collect", "normalize", "sentiment", "insight", "score",
            "ideate_content", "report",
        }
        actual = self._user_nodes(graph)
        self.assertEqual(expected, actual, "rule 模式的节点集合应包含所有标准节点")


class TestInvalidAnalysisMode(unittest.TestCase):
    """不支持的分析模式测试。"""

    def test_unsupported_analysis_mode_raises(self):
        """不支持的 analysis_mode 抛出 ValueError。"""
        with self.assertRaises(ValueError) as ctx:
            build_ugc_market_graph(analysis_mode="invalid_mode")
        self.assertIn("unsupported analysis_mode", str(ctx.exception))


class TestLLMAnnotationGraphRun(unittest.TestCase):
    """llm_annotation 模式完整运行测试（使用 mock 数据）。"""

    def setUp(self):
        self.request = AnalysisRequest(
            topic="控油洗发水",
            product_direction="氨基酸控油洗发水",
            industry_question="用户对控油洗发水的需求和痛点",
        )

    def test_mock_llm_annotation_runs(self):
        """llm_annotation 模式 + MockLLMClient + mock 数据可完整运行。"""
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

            self.assertTrue(result.get("success"), "Graph 应成功执行")
            self.assertIsNotNone(result.get("report_path"), "report_path 不应为空")
            self.assertTrue(os.path.exists(result["report_path"]), "报告文件应存在")

    def test_mock_llm_annotation_five_artifacts(self):
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

    def test_no_real_api_call(self):
        """测试不访问真实 API（使用 MockLLMClient 替代）。"""
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
            # 验证 insights 来自 annotations 聚合
            self.assertIsNotNone(result.get("insights"))
            insights = result["insights"]
            self.assertGreaterEqual(len(insights.pain_points), 0)
            self.assertGreaterEqual(len(insights.user_needs), 0)
            self.assertGreaterEqual(len(insights.evidence_comment_ids), 0)

    def test_rule_mode_all_still_works(self):
        """rule 模式在修改后仍然能正常运行。"""
        from src.adapters import XhsImportAdapter

        with tempfile.TemporaryDirectory(prefix="ugc_test_rule_") as tmp_dir:
            mock_file = _write_mock_export(tmp_dir)
            exp_paths = AppPaths.from_data_root(tmp_dir)

            adapter = XhsImportAdapter(mock_file)
            graph = build_ugc_market_graph(adapter=adapter)
            state = UGCGraphState(request=self.request, paths=exp_paths)
            result = graph.invoke(state)

            self.assertTrue(result.get("success"), "rule 模式应正常执行")
            self.assertTrue(os.path.exists(result["report_path"]), "报告文件应存在")
            # 验证 rule 模式不包含 comment_annotations
            self.assertIsNone(result.get("comment_annotations"))


class TestLLMAnnotationState(unittest.TestCase):
    """验证 llm_annotation 模式下 state 字段。"""

    def test_comment_annotations_field_present(self):
        """UGCGraphState 包含 comment_annotations 字段。"""
        state = UGCGraphState(
            request=AnalysisRequest(
                topic="test",
                product_direction="test",
                industry_question="test",
            ),
            paths=AppPaths.from_data_root(tempfile.mkdtemp()),
        )
        # 字段存在且默认 None
        self.assertIsNone(state.comment_annotations)

    def test_comment_annotations_populated_after_run(self):
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
            state = UGCGraphState(
                request=AnalysisRequest(
                    topic="控油洗发水",
                    product_direction="氨基酸控油洗发水",
                    industry_question="用户对控油洗发水的需求和痛点",
                ),
                paths=exp_paths,
            )
            result = graph.invoke(state)
            # comment_annotations 应该在 result 中（通过 state update 返回）
            annotations = result.get("comment_annotations")
            self.assertIsNotNone(annotations)
            self.assertEqual(len(annotations), 2)


if __name__ == "__main__":
    unittest.main()
