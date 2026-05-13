"""Pipeline analysis_mode 参数单元测试。

验证：
1. 默认 rule 模式使用规则版 Agent
2. LLM 模式使用 LLM Agent
3. 预注入 Agent 不受 analysis_mode 影响
"""

from __future__ import annotations

import sys
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
import tempfile
import unittest
from unittest.mock import patch

from src.agents import InsightAgent, SentimentAgent
from src.agents.llm_insight_agent import LLMInsightAgent
from src.agents.llm_sentiment_agent import LLMSentimentAgent
from src.llm.client import MockLLMClient
from src.pipeline.pipeline import Pipeline
from src.schemas import AnalysisRequest


class TestPipelineDefaultMode(unittest.TestCase):
    """默认模式 (rule) 使用规则版 Agent。"""

    def test_default_analysis_mode_is_rule(self):
        """默认 analysis_mode='rule'。"""
        pipeline = Pipeline()
        self.assertEqual(pipeline._analysis_mode, "rule")

    def test_rule_mode_uses_rule_sentiment_agent(self):
        """rule 模式使用 SentimentAgent（而非 LLM）。"""
        pipeline = Pipeline(analysis_mode="rule")
        # 内部验证：默认创建 SentimentAgent（不访问 LLM）
        # 我们无法直接断言类型，但可验证能正常运行
        req = AnalysisRequest(
            topic="测试",
            product_direction="测试方向",
            industry_question="测试问题",
        )
        # Mock source 数据以避免真实采集
        with patch.object(pipeline, "_source_agent") as mock_source:
            mock_source.execute.return_value.__class__.__name__ = "RawDataset"
            # 给一个空的有 raw 属性
            mock_ret = unittest.mock.MagicMock()
            mock_ret.posts = []
            mock_ret.comments = []
            mock_source.execute.return_value = mock_ret

            # Mock normalize
            with patch.object(pipeline, "_normalize_agent") as mock_norm:
                mock_norm.execute.return_value.posts = []
                mock_norm.execute.return_value.comments = []
                # 验证 run 不会因 LLM 相关失败
                result = pipeline.run(req)
                # 预期失败是因为数据为空（sentiment_agent 会 raise）
                self.assertFalse(result.success)


class TestPipelineLLMMode(unittest.TestCase):
    """LLM 模式使用 LLM Agent。"""

    def test_llm_mode_accepts_llm_client(self):
        """LLM 模式接受 llm_client 参数。"""
        mock = MockLLMClient()
        pipeline = Pipeline(analysis_mode="llm", llm_client=mock)
        self.assertEqual(pipeline._analysis_mode, "llm")
        self.assertIs(pipeline._llm_client, mock)

    def test_llm_mode_creates_llm_sentiment_agent(self):
        """LLM 模式创建 LLMSentimentAgent。"""
        mock = MockLLMClient()
        pipeline = Pipeline(analysis_mode="llm", llm_client=mock)

        # 验证，如果 _sentiment_agent 未被注入，
        # run 方法会在 analysis_mode=="llm" 时创建 LLMSentimentAgent
        req = AnalysisRequest(
            topic="测试",
            product_direction="测试方向",
            industry_question="测试问题",
        )

        # 模拟采集和标准化阶段正常
        with patch.object(pipeline, "_source_agent") as mock_source, \
             patch.object(pipeline, "_normalize_agent") as mock_norm, \
             patch("src.agents.llm_sentiment_agent.LLMSentimentAgent.execute") as mock_llm_sent:

            mock_source.execute.return_value.posts = []
            mock_source.execute.return_value.comments = []
            mock_norm.execute.return_value.posts = []
            mock_norm.execute.return_value.comments = []

            # 让 LLM sentiment agent 正常返回
            from src.schemas import SentimentResult
            mock_llm_sent.return_value = SentimentResult(overall_sentiment="neutral")

            # 让 LLM insight agent 也正常返回
            with patch("src.agents.llm_insight_agent.LLMInsightAgent.execute") as mock_llm_insight:
                from src.schemas import InsightRecord
                mock_llm_insight.return_value = InsightRecord()

                # 此时评分和报告仍会失败（空数据），但不会因为 LLM Agent 类型错误
                result = pipeline.run(req)
                # LLMSentimentAgent.execute 应被调用
                mock_llm_sent.assert_called_once()
                mock_llm_insight.assert_called_once()


class TestPipelineInjectedAgents(unittest.TestCase):
    """预注入的 Agent 不受 analysis_mode 影响。"""

    def test_injected_sentiment_agent_used_regardless_of_mode(self):
        """注入的 sentiment_agent 即使 mode=llm 也不被替换。"""
        custom_agent = SentimentAgent()
        pipeline = Pipeline(
            analysis_mode="llm",
            sentiment_agent=custom_agent,
        )
        # 验证 _sentiment_agent 没有被替换
        self.assertIs(pipeline._sentiment_agent, custom_agent)

    def test_injected_insight_agent_used_regardless_of_mode(self):
        """注入的 insight_agent 即使 mode=llm 也不被替换。"""
        custom_agent = InsightAgent()
        pipeline = Pipeline(
            analysis_mode="llm",
            insight_agent=custom_agent,
        )
        self.assertIs(pipeline._insight_agent, custom_agent)

    def test_rule_mode_with_injected_agents(self):
        """rule 模式下注入 agent 仍生效。"""
        custom_sentiment = SentimentAgent()
        custom_insight = InsightAgent()
        pipeline = Pipeline(
            analysis_mode="rule",
            sentiment_agent=custom_sentiment,
            insight_agent=custom_insight,
        )
        self.assertIs(pipeline._sentiment_agent, custom_sentiment)
        self.assertIs(pipeline._insight_agent, custom_insight)


class TestPipelineQuickRun(unittest.TestCase):
    """完整的快速运行测试（使用 mock 数据）。"""

    def setUp(self):
        # 准备测试数据目录
        self.temp_dir = tempfile.mkdtemp()
        self.data_root = os.path.join(self.temp_dir, "data")
        os.makedirs(os.path.join(self.data_root, "raw"))
        os.makedirs(os.path.join(self.data_root, "normalized"))
        os.makedirs(os.path.join(self.data_root, "outputs"))

    def tearDown(self):
        # 清理
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_raw_data(self):
        """写入 mock raw 数据。"""
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

    def test_llm_mode_with_mock_client_runs(self):
        """LLM mode + mock client + mock 数据能运行。"""
        self._write_raw_data()
        from src.utils import AppPaths
        app_paths = AppPaths.from_data_root(self.data_root)
        mock = MockLLMClient(mock_response={
            "sentiment": "positive",
            "confidence": 0.9,
            "emotion_tags": [],
            "evidence_text": "确实不错",
            "reason": "正面评价",
        })
        pipeline = Pipeline(
            analysis_mode="llm",
            llm_client=mock,
            paths=app_paths,
        )
        req = AnalysisRequest(
            topic="测试主题",
            product_direction="测试产品",
            industry_question="测试问题",
        )
        result = pipeline.run(req)
        # LLM mode with MockLLMClient does not crash on empty data
        self.assertTrue(result.success, "LLM mode + mock 不应崩溃")


if __name__ == "__main__":
    unittest.main()
