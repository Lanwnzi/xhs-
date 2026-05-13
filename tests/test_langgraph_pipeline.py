"""LangGraph 编排层的单元测试。

测试内容：
  1. graph 可 compile
  2. graph 包含 6 个预期节点
  3. 使用 mock 数据跑通完整 pipeline（隔离临时目录）
  4. 验证 5 个核心产物存在（隔离临时目录）
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
from src.schemas import AnalysisRequest
from src.utils import AppPaths

# 用于 graph compile 和 node wiring 测试的 mock 数据
_MOCK_SAMPLE = {
    "posts": [
        {
            "note_id": "test_p_001",
            "title": "测试帖",
            "desc": "这个产品真的很好用，控油效果不错",
            "create_time": 1710748800,
            "liked_count": 100,
            "comment_count": 10,
            "nickname": "测试用户",
            "tag_list": ["测试"],
        }
    ],
    "comments": [
        {
            "id": "test_c_001",
            "note_id": "test_p_001",
            "content": "真的很好用，推荐",
            "create_time": 1710777600,
            "like_count": 5,
            "nickname": "评论用户",
        }
    ],
}


def _write_mock_export(tmp_dir: str) -> str:
    """在临时目录下写入 mock xhs_export.json，返回完整路径。"""
    path = os.path.join(tmp_dir, "xhs_export.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_MOCK_SAMPLE, f, ensure_ascii=False)
    return path


class TestLangGraphPipeline(unittest.TestCase):

    def setUp(self):
        self.request = AnalysisRequest(
            topic="测试",
            product_direction="测试产品",
            industry_question="测试问题",
        )

    def test_graph_compiles(self):
        """验证 graph 可以 compile。"""
        graph = build_ugc_market_graph()
        self.assertIsNotNone(graph)

    def test_graph_has_all_nodes(self):
        """验证 graph 包含 6 个预期节点。"""
        graph = build_ugc_market_graph()
        expected = {"collect", "normalize", "sentiment", "insight", "score", "report"}
        actual = set(graph.nodes.keys())
        for name in expected:
            self.assertIn(name, actual, f"缺少节点: {name}")

    def test_graph_runs_with_mock_data(self):
        """在隔离临时目录中使用 mock 数据跑通 LangGraph pipeline。"""
        from src.adapters import XhsImportAdapter

        with tempfile.TemporaryDirectory(prefix="ugc_test_") as tmp_dir:
            mock_file = _write_mock_export(tmp_dir)
            exp_paths = AppPaths.from_data_root(tmp_dir)

            adapter = XhsImportAdapter(mock_file)
            graph = build_ugc_market_graph(adapter=adapter)
            state = UGCGraphState(request=self.request, paths=exp_paths)
            result = graph.invoke(state)

            self.assertTrue(result.get("success"), "Graph 应成功执行")
            self.assertIsNotNone(result.get("report_path"), "report_path 不应为空")
            self.assertTrue(os.path.exists(result["report_path"]), "报告文件应存在")

    def test_five_core_artifacts_exist(self):
        """在隔离临时目录中验证运行后 5 个核心产物存在。"""
        from src.adapters import XhsImportAdapter

        with tempfile.TemporaryDirectory(prefix="ugc_test_") as tmp_dir:
            mock_file = _write_mock_export(tmp_dir)
            exp_paths = AppPaths.from_data_root(tmp_dir)

            adapter = XhsImportAdapter(mock_file)
            graph = build_ugc_market_graph(adapter=adapter)
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

    def test_error_on_missing_state(self):
        """验证节点在必要输入缺失时抛出 ValueError。"""
        from src.graph.nodes import create_collect_node

        paths = AppPaths.from_data_root(tempfile.mkdtemp(prefix="ugc_test_"))
        state = UGCGraphState(request=self.request, paths=paths)
        state.request = None  # type: ignore[assignment]

        node = create_collect_node()
        with self.assertRaises(ValueError):
            node(state)


if __name__ == "__main__":
    unittest.main()
