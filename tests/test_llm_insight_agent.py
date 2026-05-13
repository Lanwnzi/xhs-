"""LLM 洞察抽取 Agent 单元测试。"""

from __future__ import annotations

import sys
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import unittest

from src.agents.llm_insight_agent import LLMInsightAgent, _build_insight_prompt
from src.llm.client import MockLLMClient
from src.schemas import (
    CommentRecord, InsightRecord, NormalizedDataset, PostRecord,
    SentimentResult,
)


class TestLLMInsightAgent(unittest.TestCase):
    """LLM 洞察抽取 Agent 测试。"""

    def setUp(self):
        self.dataset = NormalizedDataset(
            posts=[
                PostRecord(
                    platform="xhs", post_id="p1", title="控油测评",
                    content="这个控油洗发水真的很好用", author="u1",
                    publish_time="2026-01-01T00:00:00",
                ),
                PostRecord(
                    platform="xhs", post_id="p2", title="踩雷",
                    content="太差了完全没用还长痘", author="u2",
                    publish_time="2026-01-02T00:00:00",
                ),
            ],
            comments=[
                CommentRecord(
                    platform="xhs", comment_id="c1", post_id="p1",
                    content="确实不错，回购了", author="u3",
                    publish_time="2026-01-01T01:00:00",
                ),
                CommentRecord(
                    platform="xhs", comment_id="c2", post_id="p1",
                    content="不好用，太油了", author="u4",
                    publish_time="2026-01-01T02:00:00",
                ),
                CommentRecord(
                    platform="xhs", comment_id="c3", post_id="p2",
                    content="求链接，想买", author="u5",
                    publish_time="2026-01-02T01:00:00",
                ),
            ],
        )
        self.sentiment = SentimentResult(overall_sentiment="neutral")
        self.valid_mock_response = {
            "pain_points": [
                {"text": "产品太油", "evidence_comment_ids": ["c2"], "evidence_post_ids": [], "evidence_text": "太油了"},
                {"text": "产品致痘", "evidence_comment_ids": [], "evidence_post_ids": ["p2"], "evidence_text": "长痘"},
            ],
            "user_needs": [
                {"text": "需要控油产品", "evidence_comment_ids": ["c3"], "evidence_post_ids": [], "evidence_text": "想买"},
            ],
            "complaints": [
                {"text": "产品不好用", "evidence_comment_ids": ["c2"], "evidence_post_ids": [], "evidence_text": "不好用"},
            ],
            "solutions": [
                {"text": "推荐回购", "evidence_comment_ids": ["c1"], "evidence_post_ids": [], "evidence_text": "回购了"},
            ],
            "market_signals": [
                {"text": "用户有购买意向", "evidence_comment_ids": ["c3"], "evidence_post_ids": [], "evidence_text": "求链接"},
            ],
            "sentiment": "neutral",
        }

    def test_execute_returns_insight_record(self):
        """使用 MockLLMClient 返回 InsightRecord。"""
        mock = MockLLMClient(mock_response=self.valid_mock_response)
        agent = LLMInsightAgent(llm_client=mock)
        result = agent.execute(self.dataset, self.sentiment)
        self.assertIsInstance(result, InsightRecord)

    def test_pain_points_extracted(self):
        """痛点被正确抽取。"""
        mock = MockLLMClient(mock_response=self.valid_mock_response)
        agent = LLMInsightAgent(llm_client=mock)
        result = agent.execute(self.dataset, self.sentiment)
        self.assertIn("产品太油", result.pain_points)
        self.assertIn("产品致痘", result.pain_points)

    def test_user_needs_extracted(self):
        """用户需求被正确抽取。"""
        mock = MockLLMClient(mock_response=self.valid_mock_response)
        agent = LLMInsightAgent(llm_client=mock)
        result = agent.execute(self.dataset, self.sentiment)
        self.assertIn("需要控油产品", result.user_needs)

    def test_market_signals_extracted(self):
        """市场信号被正确抽取。"""
        mock = MockLLMClient(mock_response=self.valid_mock_response)
        agent = LLMInsightAgent(llm_client=mock)
        result = agent.execute(self.dataset, self.sentiment)
        self.assertIn("用户有购买意向", result.market_signals)

    def test_evidence_ids_collected(self):
        """evidence IDs 被正确收集。"""
        mock = MockLLMClient(mock_response=self.valid_mock_response)
        agent = LLMInsightAgent(llm_client=mock)
        result = agent.execute(self.dataset, self.sentiment)
        self.assertIn("c1", result.evidence_comment_ids)
        self.assertIn("c2", result.evidence_comment_ids)
        self.assertIn("c3", result.evidence_comment_ids)
        self.assertIn("p2", result.evidence_post_ids)

    def test_insight_without_evidence_removed(self):
        """无证据的洞察被过滤调。"""
        response = {
            "pain_points": [
                {"text": "无证据的痛点", "evidence_comment_ids": [], "evidence_post_ids": [], "evidence_text": ""},
                {"text": "有证据的痛点", "evidence_comment_ids": ["c2"], "evidence_post_ids": [], "evidence_text": "太油了"},
            ],
            "user_needs": [],
            "complaints": [],
            "solutions": [],
            "market_signals": [],
            "sentiment": "neutral",
        }
        mock = MockLLMClient(mock_response=response)
        agent = LLMInsightAgent(llm_client=mock)
        result = agent.execute(self.dataset, self.sentiment)
        # 只有有证据的留在列表中
        self.assertNotIn("无证据的痛点", result.pain_points)
        self.assertIn("有证据的痛点", result.pain_points)

    def test_all_items_without_evidence_empty_result(self):
        """所有洞察都没有证据时应有相应处理。"""
        response = {
            "pain_points": [
                {"text": "无证据痛点", "evidence_comment_ids": [], "evidence_post_ids": [], "evidence_text": ""},
            ],
            "user_needs": [],
            "complaints": [],
            "solutions": [],
            "market_signals": [],
            "sentiment": "neutral",
        }
        mock = MockLLMClient(mock_response=response)
        agent = LLMInsightAgent(llm_client=mock)
        result = agent.execute(self.dataset, self.sentiment)
        # 无证据时列表为空
        self.assertEqual(len(result.pain_points), 0)
        # 但不应崩溃
        self.assertIsInstance(result, InsightRecord)

    def test_fallback_on_llm_failure(self):
        """LLM 失败时 fallback 到规则版。"""
        class FailingMock(MockLLMClient):
            def generate(self, prompt: str = "") -> str:
                raise RuntimeError("LLM 调用失败")

        agent = LLMInsightAgent(llm_client=FailingMock())
        result = agent.execute(self.dataset, self.sentiment)
        # fallback 应仍返回有效结果（使用规则版）
        self.assertIsInstance(result, InsightRecord)

    def test_sentiment_passed_through(self):
        """整体情感来自 SentimentResult。"""
        mock = MockLLMClient(mock_response=self.valid_mock_response)
        agent = LLMInsightAgent(llm_client=mock)
        result = agent.execute(self.dataset, SentimentResult(overall_sentiment="positive"))
        self.assertEqual(result.sentiment, "positive")

    def test_build_insight_prompt_includes_data(self):
        """prompt 包含帖子和评论内容。"""
        prompt = _build_insight_prompt(self.dataset)
        self.assertIn("控油测评", prompt)
        self.assertIn("确实不错", prompt)
        self.assertIn("pain_points", prompt)

    def test_parse_insight_result(self):
        """_parse_insight_result 正确解析 LLM 输出。"""
        result = LLMInsightAgent._parse_insight_result(self.valid_mock_response)
        self.assertEqual(len(result.pain_points), 2)
        self.assertEqual(len(result.user_needs), 1)
        self.assertEqual(result.pain_points[0].text, "产品太油")
        self.assertEqual(result.pain_points[0].evidence_comment_ids, ["c2"])

    def test_parse_insight_result_empty(self):
        """空响应解析不崩溃。"""
        result = LLMInsightAgent._parse_insight_result({})
        self.assertEqual(len(result.pain_points), 0)
        self.assertEqual(len(result.user_needs), 0)
        self.assertEqual(result.sentiment, "")

    def test_evidence_verifier_filters_by_existing_ids(self):
        """不存在的 comment_id 的洞察被过滤。"""
        response = {
            "pain_points": [
                {"text": "目标痛点", "evidence_comment_ids": ["c2"], "evidence_post_ids": [], "evidence_text": "太油了"},
                {"text": "虚假痛点", "evidence_comment_ids": ["nonexistent"], "evidence_post_ids": [], "evidence_text": "不存在的评论"},
            ],
            "user_needs": [],
            "complaints": [],
            "solutions": [],
            "market_signals": [],
            "sentiment": "neutral",
        }
        mock = MockLLMClient(mock_response=response)
        agent = LLMInsightAgent(llm_client=mock)
        result = agent.execute(self.dataset, self.sentiment)
        self.assertIn("目标痛点", result.pain_points)
        self.assertNotIn("虚假痛点", result.pain_points)


if __name__ == "__main__":
    unittest.main()
