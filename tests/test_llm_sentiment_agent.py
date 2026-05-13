"""LLM 情感分析 Agent 单元测试。"""

from __future__ import annotations

import sys
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import unittest

from src.agents.llm_sentiment_agent import LLMSentimentAgent, _parse_llm_response, _build_sentiment_prompt
from src.llm.client import MockLLMClient
from src.schemas import (
    CommentRecord, NormalizedDataset, PostRecord, SentimentResult,
)


class TestLLMSentimentAgent(unittest.TestCase):
    """LLM 情感分析 Agent 测试。"""

    def setUp(self):
        self.dataset = NormalizedDataset(
            posts=[
                PostRecord(
                    platform="xhs", post_id="p1", title="测试帖子",
                    content="这个产品真的很好用", author="u1",
                    publish_time="2026-01-01T00:00:00",
                ),
            ],
            comments=[
                CommentRecord(
                    platform="xhs", comment_id="c1", post_id="p1",
                    content="确实不错，回购了", author="u2",
                    publish_time="2026-01-01T01:00:00",
                ),
                CommentRecord(
                    platform="xhs", comment_id="c2", post_id="p1",
                    content="不好用，太油了", author="u3",
                    publish_time="2026-01-01T02:00:00",
                ),
            ],
        )

    def test_with_mock_client_returns_correct_type(self):
        """使用 MockLLMClient 返回 SentimentResult。"""
        mock = MockLLMClient()
        agent = LLMSentimentAgent(llm_client=mock)
        result = agent.execute(self.dataset)
        self.assertIsInstance(result, SentimentResult)
        self.assertIn(result.overall_sentiment, ["positive", "negative", "neutral"])

    def test_execute_has_comment_sentiments(self):
        """结果应包含评论情感列表。"""
        mock = MockLLMClient()
        agent = LLMSentimentAgent(llm_client=mock)
        result = agent.execute(self.dataset)
        self.assertEqual(len(result.comment_sentiments), 2)
        for cs in result.comment_sentiments:
            self.assertIn(cs.comment_id, ["c1", "c2"])
            self.assertIn(cs.label, ["positive", "negative", "neutral"])
            self.assertGreaterEqual(cs.score, 0.0)
            self.assertLessEqual(cs.score, 1.0)

    def test_custom_mock_response(self):
        """自定义 mock_response 影响结果。"""
        custom_mock = MockLLMClient(mock_response={
            "sentiment": "negative",
            "confidence": 0.75,
            "emotion_tags": ["失望"],
            "evidence_text": "不好用",
            "reason": "负面评价",
        })
        agent = LLMSentimentAgent(llm_client=custom_mock)
        result = agent.execute(self.dataset)

        # 两条评论都返回预设的 negative
        for cs in result.comment_sentiments:
            self.assertEqual(cs.label, "negative")
            self.assertEqual(cs.score, 0.75)

    def test_fallback_on_llm_failure(self):
        """LLM 失败时 fallback 到规则版。"""
        class FailingMock(MockLLMClient):
            def generate(self, prompt: str = "") -> str:
                raise RuntimeError("LLM 调用失败")

        agent = LLMSentimentAgent(llm_client=FailingMock())
        result = agent.execute(self.dataset)
        # fallback 应仍然返回有效结果
        self.assertIsInstance(result, SentimentResult)
        self.assertGreater(len(result.comment_sentiments), 0)

    def test_empty_dataset_no_comments(self):
        """无评论的 dataset 不应崩溃。"""
        empty_dataset = NormalizedDataset(
            posts=[self.dataset.posts[0]],
            comments=[],
        )
        mock = MockLLMClient()
        agent = LLMSentimentAgent(llm_client=mock)
        result = agent.execute(empty_dataset)
        self.assertIsInstance(result, SentimentResult)
        self.assertEqual(len(result.comment_sentiments), 0)

    def test_build_sentiment_prompt_includes_comment_text(self):
        """prompt 包含评论内容。"""
        comment = self.dataset.comments[0]
        prompt = _build_sentiment_prompt(comment)
        self.assertIn(comment.content, prompt)
        self.assertIn("情感倾向", prompt)

    def test_parse_llm_response_empty(self):
        """空 dict 解析不崩溃。"""
        parsed = _parse_llm_response({})
        self.assertEqual(parsed.comment_id, "")
        self.assertEqual(parsed.sentiment, "neutral")
        self.assertEqual(parsed.confidence, 0.0)

    def test_parse_llm_response_full(self):
        """完整 dict 正确解析。"""
        raw = {
            "comment_id": "c1",
            "sentiment": "positive",
            "confidence": 0.92,
            "emotion_tags": ["满意", "推荐"],
            "evidence_text": "确实不错",
            "reason": "正面词汇较多",
        }
        parsed = _parse_llm_response(raw)
        self.assertEqual(parsed.comment_id, "c1")
        self.assertEqual(parsed.sentiment, "positive")
        self.assertEqual(parsed.confidence, 0.92)
        self.assertEqual(parsed.emotion_tags, ["满意", "推荐"])


if __name__ == "__main__":
    unittest.main()
