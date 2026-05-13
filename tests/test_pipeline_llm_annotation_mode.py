"""Pipeline llm_annotation 模式单元测试。

验证：
1. llm_annotation 模式使用 LLMCommentAnalyzerAgent
2. 默认 rule 模式不变
3. 注入 agent 时记录警告
"""

from __future__ import annotations

import sys
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
import logging
import tempfile
import unittest
from unittest.mock import patch

from src.agents import InsightAgent, SentimentAgent
from src.llm.client import MockLLMClient
from src.pipeline.pipeline import Pipeline
from src.schemas import AnalysisRequest, CommentRecord, PostRecord
from src.schemas.llm_records import CommentAnnotationRecord


class TestPipelineLLMAnnotationMode(unittest.TestCase):
    """llm_annotation 模式测试。"""

    def setUp(self):
        # 准备测试数据目录
        self.temp_dir = tempfile.mkdtemp()
        self.data_root = os.path.join(self.temp_dir, "data")
        os.makedirs(os.path.join(self.data_root, "raw"))
        os.makedirs(os.path.join(self.data_root, "normalized"))
        os.makedirs(os.path.join(self.data_root, "outputs"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_raw_data(self):
        """写入 mock raw 数据。"""
        raw_posts = [
            {
                "platform": "xhs", "post_id": "p1", "title": "控油推荐",
                "content": "有没有好用的控油洗发水推荐", "author": "u1",
                "publish_time": "2026-01-01T00:00:00", "likes": 10,
                "comments": 2, "favorites": 5, "shares": 1, "url": "",
                "tags": [],
            }
        ]
        raw_comments = [
            {
                "platform": "xhs", "comment_id": "c1", "post_id": "p1",
                "content": "这个控油效果不错", "author": "u2",
                "publish_time": "2026-01-01T01:00:00", "likes": 3,
                "parent_comment_id": None,
            },
            {
                "platform": "xhs", "comment_id": "c2", "post_id": "p1",
                "content": "就是太贵了，性价比不高", "author": "u3",
                "publish_time": "2026-01-01T02:00:00", "likes": 1,
                "parent_comment_id": None,
            },
        ]
        with open(os.path.join(self.data_root, "raw", "raw_posts.json"), "w", encoding="utf-8") as f:
            json.dump(raw_posts, f, ensure_ascii=False)
        with open(os.path.join(self.data_root, "raw", "raw_comments.json"), "w", encoding="utf-8") as f:
            json.dump(raw_comments, f, ensure_ascii=False)

    def test_pipeline_llm_annotation_mode_uses_comment_analyzer(self):
        """llm_annotation 模式使用 LLMCommentAnalyzerAgent。"""
        self._write_raw_data()
        from src.utils import AppPaths
        app_paths = AppPaths.from_data_root(self.data_root)

        # Mock LLM 返回固定 annotation
        mock_llm = MockLLMClient(mock_response={
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
                    "reason": "正面评价",
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
                    "reason": "吐槽价格",
                },
            ]
        })

        pipeline = Pipeline(
            analysis_mode="llm_annotation",
            llm_client=mock_llm,
            paths=app_paths,
        )
        req = AnalysisRequest(
            topic="控油洗发水",
            product_direction="氨基酸控油洗发水",
            industry_question="用户对控油洗发水的需求",
        )
        result = pipeline.run(req)
        self.assertTrue(result.success, "llm_annotation mode should succeed")

        # 验证产物路径
        self.assertTrue(os.path.exists(result.insights_path), "insights.json should exist")
        self.assertTrue(os.path.exists(result.scorecard_path), "scorecard.json should exist")
        self.assertTrue(os.path.exists(result.report_path), "report.html should exist")

    def test_pipeline_default_rule_mode_still_unchanged(self):
        """默认 rule 模式仍然不受影响。"""
        self._write_raw_data()
        from src.utils import AppPaths
        app_paths = AppPaths.from_data_root(self.data_root)

        pipeline = Pipeline(
            analysis_mode="rule",
            paths=app_paths,
        )
        req = AnalysisRequest(
            topic="控油洗发水",
            product_direction="氨基酸控油洗发水",
            industry_question="用户对控油洗发水的需求",
        )
        result = pipeline.run(req)
        self.assertTrue(result.success, "rule mode should work unchanged")

    def test_injected_agents_log_warning_in_llm_annotation_mode(self):
        """llm_annotation 模式注入 agent 时记录警告。"""
        self._write_raw_data()
        from src.utils import AppPaths
        app_paths = AppPaths.from_data_root(self.data_root)

        mock_llm = MockLLMClient(mock_response={
            "annotations": [
                {
                    "index": 0,
                    "sentiment": "positive",
                    "pain_point_labels": [],
                    "need_labels": [],
                    "complaint_labels": [],
                    "solution_labels": [],
                    "market_signal_labels": [],
                    "intent_labels": [],
                    "reason": "",
                },
                {
                    "index": 1,
                    "sentiment": "negative",
                    "pain_point_labels": [],
                    "need_labels": [],
                    "complaint_labels": [],
                    "solution_labels": [],
                    "market_signal_labels": [],
                    "intent_labels": [],
                    "reason": "",
                },
            ]
        })

        pipeline = Pipeline(
            analysis_mode="llm_annotation",
            llm_client=mock_llm,
            paths=app_paths,
            sentiment_agent=SentimentAgent(),  # 注入会被忽略
            insight_agent=InsightAgent(),  # 注入会被忽略
        )

        # 捕获日志
        logger = logging.getLogger("src.pipeline.pipeline")
        with self.assertLogs(logger, level="WARNING") as log_cm:
            req = AnalysisRequest(
                topic="控油洗发水",
                product_direction="氨基酸控油洗发水",
                industry_question="用户对控油洗发水的需求",
            )
            result = pipeline.run(req)

        # 验证警告被记录
        warning_found = any(
            "ignores injected" in msg for msg in log_cm.output
        )
        self.assertTrue(warning_found, "Warning about injected agents should be logged")
        self.assertTrue(result.success, "Pipeline should still succeed")

    def test_llm_annotation_mode_without_llm_client(self):
        """llm_annotation 模式不提供 llm_client 时使用 MockLLMClient。"""
        from src.utils import AppPaths
        app_paths = AppPaths.from_data_root(self.data_root)

        # 需要 mock source 和 normalize，但我们仍需 mock LLMCommentAnalyzerAgent
        # 因为 MockLLMClient 的默认返回值格式不对
        with patch('src.agents.llm_comment_analyzer_agent.LLMCommentAnalyzerAgent') as MockAnalyzer:
            mock_instance = MockAnalyzer.return_value
            mock_instance.execute.return_value = [
                CommentAnnotationRecord(
                    comment_id="c1", post_id="p1", sentiment="positive",
                ),
                CommentAnnotationRecord(
                    comment_id="c2", post_id="p1", sentiment="negative",
                ),
            ]

            pipeline = Pipeline(
                analysis_mode="llm_annotation",
                paths=app_paths,
                # 没有 llm_client
            )
            req = AnalysisRequest(
                topic="测试",
                product_direction="测试产品",
                industry_question="测试问题",
            )

            # mock source 和 normalize
            with patch.object(pipeline, "_source_agent") as mock_source, \
                 patch.object(pipeline, "_normalize_agent") as mock_norm:

                mock_source.execute.return_value.posts = []
                mock_source.execute.return_value.comments = []
                mock_norm.execute.return_value.posts = []
                mock_norm.execute.return_value.comments = []

                result = pipeline.run(req)
                # 预期失败因为空数据下 scoring 可能会失败
                # 但 LLMCommentAnalyzerAgent 应被创建和调用
                mock_instance.execute.assert_called_once()


class TestPipelineLLMAnnotationWithQuickRun(unittest.TestCase):
    """完整的快速运行测试（使用 mock 数据和 mock LLM）。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.data_root = os.path.join(self.temp_dir, "data")
        os.makedirs(os.path.join(self.data_root, "raw"))
        os.makedirs(os.path.join(self.data_root, "normalized"))
        os.makedirs(os.path.join(self.data_root, "outputs"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_raw_data(self):
        raw_posts = [
            {
                "platform": "xhs", "post_id": "p1", "title": "测试",
                "content": "这个产品很好用", "author": "u1",
                "publish_time": "2026-01-01T00:00:00", "likes": 10,
                "comments": 2, "favorites": 5, "shares": 1, "url": "",
                "tags": [],
            }
        ]
        raw_comments = [
            {
                "platform": "xhs", "comment_id": "c1", "post_id": "p1",
                "content": "确实不错", "author": "u2",
                "publish_time": "2026-01-01T01:00:00", "likes": 3,
                "parent_comment_id": None,
            }
        ]
        with open(os.path.join(self.data_root, "raw", "raw_posts.json"), "w", encoding="utf-8") as f:
            json.dump(raw_posts, f, ensure_ascii=False)
        with open(os.path.join(self.data_root, "raw", "raw_comments.json"), "w", encoding="utf-8") as f:
            json.dump(raw_comments, f, ensure_ascii=False)

    def test_llm_annotation_mode_with_mock_client_runs(self):
        """llm_annotation mode + mock client + mock 数据能运行。"""
        self._write_raw_data()
        from src.utils import AppPaths
        app_paths = AppPaths.from_data_root(self.data_root)

        mock = MockLLMClient(mock_response={
            "annotations": [
                {
                    "index": 0,
                    "sentiment": "positive",
                    "pain_point_labels": [],
                    "need_labels": ["效果好"],
                    "complaint_labels": [],
                    "solution_labels": [],
                    "market_signal_labels": [],
                    "intent_labels": [],
                    "reason": "好评",
                },
            ]
        })

        pipeline = Pipeline(
            analysis_mode="llm_annotation",
            llm_client=mock,
            paths=app_paths,
        )
        req = AnalysisRequest(
            topic="测试主题",
            product_direction="测试产品",
            industry_question="测试问题",
        )
        result = pipeline.run(req)
        self.assertTrue(result.success, "llm_annotation mode with mock should not crash")


if __name__ == "__main__":
    unittest.main()
