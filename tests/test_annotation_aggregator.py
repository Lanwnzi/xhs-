"""AnnotationAggregator 单元测试。

聚合 CommentAnnotationRecord 为 SentimentResult 和 InsightRecord。
测试不访问真实 API，不涉及 LLM。
"""

from __future__ import annotations

import sys
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import unittest

from src.agents.annotation_aggregator import AnnotationAggregator
from src.schemas import (
    CommentRecord, CommentSentiment, InsightRecord,
    PostRecord, PostSentiment, SentimentResult,
)
from src.schemas.llm_records import CommentAnnotationRecord


class TestAnnotationAggregatorToSentimentResult(unittest.TestCase):
    """AnnotationAggregator.to_sentiment_result 测试。"""

    def setUp(self):
        self.posts = [
            PostRecord(
                platform="xhs", post_id="p1", title="", content="",
                author="u1", publish_time="2026-01-01T00:00:00",
            ),
            PostRecord(
                platform="xhs", post_id="p2", title="", content="",
                author="u2", publish_time="2026-01-01T00:00:00",
            ),
        ]
        self.comments = [
            CommentRecord(
                platform="xhs", comment_id="c1", post_id="p1",
                content="好用", author="u3",
                publish_time="2026-01-01T01:00:00",
            ),
            CommentRecord(
                platform="xhs", comment_id="c2", post_id="p1",
                content="太贵", author="u4",
                publish_time="2026-01-01T02:00:00",
            ),
        ]

    def test_empty_annotations_returns_neutral(self):
        """空 annotations 返回 overall_sentiment='neutral'。"""
        result = AnnotationAggregator.to_sentiment_result([], self.posts, self.comments)
        self.assertIsInstance(result, SentimentResult)
        self.assertEqual(result.overall_sentiment, "neutral")
        self.assertEqual(len(result.comment_sentiments), 0)
        self.assertEqual(len(result.post_sentiments), 0)

    def test_single_positive_annotation(self):
        """单条 positive annotation。"""
        annotations = [
            CommentAnnotationRecord(
                comment_id="c1", post_id="p1", sentiment="positive",
            ),
        ]
        result = AnnotationAggregator.to_sentiment_result(
            annotations, self.posts, self.comments
        )
        self.assertEqual(result.overall_sentiment, "positive")
        self.assertEqual(len(result.comment_sentiments), 1)
        self.assertEqual(result.comment_sentiments[0].label, "positive")
        self.assertEqual(result.comment_sentiments[0].score, 1.0)

    def test_single_negative_annotation(self):
        """单条 negative annotation。"""
        annotations = [
            CommentAnnotationRecord(
                comment_id="c1", post_id="p1", sentiment="negative",
            ),
        ]
        result = AnnotationAggregator.to_sentiment_result(
            annotations, self.posts, self.comments
        )
        self.assertEqual(result.overall_sentiment, "negative")
        self.assertEqual(result.comment_sentiments[0].label, "negative")

    def test_single_neutral_annotation(self):
        """单条 neutral annotation。"""
        annotations = [
            CommentAnnotationRecord(
                comment_id="c1", post_id="p1", sentiment="neutral",
            ),
        ]
        result = AnnotationAggregator.to_sentiment_result(
            annotations, self.posts, self.comments
        )
        self.assertEqual(result.overall_sentiment, "neutral")
        self.assertEqual(result.comment_sentiments[0].label, "neutral")
        self.assertEqual(result.comment_sentiments[0].score, 0.5)

    def test_mixed_annotations_in_same_post(self):
        """同一帖子下的不同评论产生帖子级多数情感。"""
        annotations = [
            CommentAnnotationRecord(comment_id="c1", post_id="p1", sentiment="positive"),
            CommentAnnotationRecord(comment_id="c2", post_id="p1", sentiment="negative"),
        ]
        result = AnnotationAggregator.to_sentiment_result(
            annotations, self.posts, self.comments
        )
        # 评论级
        self.assertEqual(len(result.comment_sentiments), 2)
        # 帖子级 - positive 和 negative 数量相等，取字典序或 Counter 顺序
        # Counter({'positive': 1, 'negative': 1}) 取第一个
        self.assertEqual(len(result.post_sentiments), 1)
        # 整体 - 正负相等且差距 <= 1 -> mixed
        self.assertEqual(result.overall_sentiment, "mixed")

    def test_sentiment_overall_mixed_when_close(self):
        """当 positive 和 negative 接近时 overall 为 mixed。"""
        annotations = [
            CommentAnnotationRecord(comment_id="c1", post_id="p1", sentiment="positive"),
            CommentAnnotationRecord(comment_id="c2", post_id="p1", sentiment="negative"),
            CommentAnnotationRecord(comment_id="c3", post_id="p2", sentiment="positive"),
            CommentAnnotationRecord(comment_id="c4", post_id="p2", sentiment="negative"),
        ]
        result = AnnotationAggregator.to_sentiment_result(
            annotations, self.posts, self.comments
        )
        self.assertEqual(result.overall_sentiment, "mixed")

    def test_sentiment_maps_mixed_to_neutral(self):
        """annotation 的 mixed sentiment 被映射为 neutral。"""
        annotations = [
            CommentAnnotationRecord(
                comment_id="c1", post_id="p1", sentiment="mixed",
            ),
        ]
        result = AnnotationAggregator.to_sentiment_result(
            annotations, self.posts, self.comments
        )
        self.assertEqual(result.comment_sentiments[0].label, "neutral")
        self.assertEqual(result.comment_sentiments[0].score, 0.5)

    def test_post_sentiment_maps_mixed_to_neutral(self):
        """帖子级情感中 mixed 被映射为 neutral。"""
        annotations = [
            CommentAnnotationRecord(comment_id="c1", post_id="p1", sentiment="mixed"),
            CommentAnnotationRecord(comment_id="c2", post_id="p1", sentiment="mixed"),
        ]
        result = AnnotationAggregator.to_sentiment_result(
            annotations, self.posts, self.comments
        )
        self.assertEqual(result.post_sentiments[0].label, "neutral")

    def test_outputs_existing_sentiment_result(self):
        """输出类型必须是 SentimentResult。"""
        annotations = [
            CommentAnnotationRecord(comment_id="c1", post_id="p1", sentiment="positive"),
        ]
        result = AnnotationAggregator.to_sentiment_result(
            annotations, self.posts, self.comments
        )
        self.assertIsInstance(result, SentimentResult)

    def test_post_sentiments_grouped_by_post_id(self):
        """按 post_id 分组聚合帖子情感。"""
        annotations = [
            CommentAnnotationRecord(comment_id="c1", post_id="p1", sentiment="positive"),
            CommentAnnotationRecord(comment_id="c2", post_id="p1", sentiment="positive"),
            CommentAnnotationRecord(comment_id="c3", post_id="p2", sentiment="negative"),
        ]
        result = AnnotationAggregator.to_sentiment_result(
            annotations, self.posts, self.comments
        )
        self.assertEqual(len(result.post_sentiments), 2)
        post_map = {ps.post_id: ps.label for ps in result.post_sentiments}
        self.assertEqual(post_map.get("p1"), "positive")
        self.assertEqual(post_map.get("p2"), "negative")


class TestAnnotationAggregatorToInsightRecord(unittest.TestCase):
    """AnnotationAggregator.to_insight_record 测试。"""

    def setUp(self):
        self.posts = [
            PostRecord(
                platform="xhs", post_id="p1", title="", content="",
                author="u1", publish_time="2026-01-01T00:00:00",
            ),
        ]
        self.comments = [
            CommentRecord(
                platform="xhs", comment_id="c1", post_id="p1",
                content="", author="u3",
                publish_time="2026-01-01T01:00:00",
            ),
            CommentRecord(
                platform="xhs", comment_id="c2", post_id="p1",
                content="", author="u4",
                publish_time="2026-01-01T02:00:00",
            ),
        ]

    def test_empty_annotations_returns_empty(self):
        """空 annotations 返回空的 InsightRecord。"""
        result = AnnotationAggregator.to_insight_record([], self.posts, self.comments)
        self.assertIsInstance(result, InsightRecord)
        self.assertEqual(result.pain_points, [])
        self.assertEqual(result.user_needs, [])
        self.assertEqual(result.complaints, [])
        self.assertEqual(result.solutions, [])
        self.assertEqual(result.market_signals, [])
        self.assertEqual(result.evidence_post_ids, [])
        self.assertEqual(result.evidence_comment_ids, [])
        self.assertEqual(result.sentiment, "neutral")

    def test_maps_pain_labels_to_pain_points(self):
        """pain_point_labels 映射到 pain_points。"""
        annotations = [
            CommentAnnotationRecord(
                comment_id="c1", post_id="p1",
                pain_point_labels=["头皮痒", "出油快"],
            ),
        ]
        result = AnnotationAggregator.to_insight_record(
            annotations, self.posts, self.comments
        )
        self.assertIn("头皮痒", result.pain_points)
        self.assertIn("出油快", result.pain_points)

    def test_maps_need_labels_to_user_needs(self):
        """need_labels 映射到 user_needs。"""
        annotations = [
            CommentAnnotationRecord(
                comment_id="c1", post_id="p1",
                need_labels=["控油持久", "清爽不油腻"],
            ),
        ]
        result = AnnotationAggregator.to_insight_record(
            annotations, self.posts, self.comments
        )
        self.assertIn("控油持久", result.user_needs)
        self.assertIn("清爽不油腻", result.user_needs)

    def test_maps_complaint_labels_to_complaints(self):
        """complaint_labels 映射到 complaints。"""
        annotations = [
            CommentAnnotationRecord(
                comment_id="c1", post_id="p1",
                complaint_labels=["价格太贵", "洗后干涩"],
            ),
        ]
        result = AnnotationAggregator.to_insight_record(
            annotations, self.posts, self.comments
        )
        self.assertIn("价格太贵", result.complaints)
        self.assertIn("洗后干涩", result.complaints)

    def test_maps_solution_labels_to_solutions(self):
        """solution_labels 映射到 solutions。"""
        annotations = [
            CommentAnnotationRecord(
                comment_id="c1", post_id="p1",
                solution_labels=["氨基酸洗发水", "无硅油配方"],
            ),
        ]
        result = AnnotationAggregator.to_insight_record(
            annotations, self.posts, self.comments
        )
        self.assertIn("氨基酸洗发水", result.solutions)
        self.assertIn("无硅油配方", result.solutions)

    def test_maps_intent_labels_to_market_signals(self):
        """intent_labels 映射到 market_signals。"""
        annotations = [
            CommentAnnotationRecord(
                comment_id="c1", post_id="p1",
                intent_labels=["求推荐", "哪里买"],
            ),
        ]
        result = AnnotationAggregator.to_insight_record(
            annotations, self.posts, self.comments
        )
        self.assertIn("求推荐", result.market_signals)
        self.assertIn("哪里买", result.market_signals)

    def test_maps_signal_labels_to_market_signals(self):
        """market_signal_labels 映射到 market_signals。"""
        annotations = [
            CommentAnnotationRecord(
                comment_id="c1", post_id="p1",
                market_signal_labels=["多少钱", "有用吗"],
            ),
        ]
        result = AnnotationAggregator.to_insight_record(
            annotations, self.posts, self.comments
        )
        self.assertIn("多少钱", result.market_signals)
        self.assertIn("有用吗", result.market_signals)

    def test_keeps_duplicate_labels(self):
        """重复标签不被去重，保持原始顺序。"""
        annotations = [
            CommentAnnotationRecord(
                comment_id="c1", post_id="p1",
                pain_point_labels=["头皮痒"],
            ),
            CommentAnnotationRecord(
                comment_id="c2", post_id="p1",
                pain_point_labels=["头皮痒"],
            ),
        ]
        result = AnnotationAggregator.to_insight_record(
            annotations, self.posts, self.comments
        )
        self.assertEqual(result.pain_points, ["头皮痒", "头皮痒"])

    def test_ignores_empty_labels_only(self):
        """只过滤空标签（空字符串或全空格），不清洗其他。"""
        annotations = [
            CommentAnnotationRecord(
                comment_id="c1", post_id="p1",
                pain_point_labels=["", "  ", "有效标签"],
                need_labels=["", ""],
                complaint_labels=["有效投诉"],
                solution_labels=[""],
                market_signal_labels=[],
                intent_labels=[],
            ),
        ]
        result = AnnotationAggregator.to_insight_record(
            annotations, self.posts, self.comments
        )
        self.assertEqual(result.pain_points, ["有效标签"])
        self.assertEqual(result.user_needs, [])
        self.assertEqual(result.complaints, ["有效投诉"])
        self.assertEqual(result.solutions, [])
        self.assertEqual(result.market_signals, [])

    def test_outputs_existing_insight_record(self):
        """输出必须是 InsightRecord 类型。"""
        annotations = [
            CommentAnnotationRecord(
                comment_id="c1", post_id="p1",
                pain_point_labels=["头皮痒"],
            ),
        ]
        result = AnnotationAggregator.to_insight_record(
            annotations, self.posts, self.comments
        )
        self.assertIsInstance(result, InsightRecord)

    def test_evidence_comment_ids_from_annotations(self):
        """evidence_comment_ids 来自所有 annotation 的 comment_id。"""
        annotations = [
            CommentAnnotationRecord(comment_id="c1", post_id="p1"),
            CommentAnnotationRecord(comment_id="c2", post_id="p1"),
        ]
        result = AnnotationAggregator.to_insight_record(
            annotations, self.posts, self.comments
        )
        self.assertIn("c1", result.evidence_comment_ids)
        self.assertIn("c2", result.evidence_comment_ids)

    def test_evidence_post_ids_deduplicated(self):
        """evidence_post_ids 不重复。"""
        annotations = [
            CommentAnnotationRecord(comment_id="c1", post_id="p1"),
            CommentAnnotationRecord(comment_id="c2", post_id="p1"),
        ]
        result = AnnotationAggregator.to_insight_record(
            annotations, self.posts, self.comments
        )
        self.assertEqual(result.evidence_post_ids, ["p1"])

    def test_sentiment_aggregation(self):
        """sentiment 按多数情绪聚合。"""
        annotations = [
            CommentAnnotationRecord(comment_id="c1", post_id="p1", sentiment="positive"),
            CommentAnnotationRecord(comment_id="c2", post_id="p1", sentiment="positive"),
            CommentAnnotationRecord(comment_id="c3", post_id="p2", sentiment="negative"),
        ]
        result = AnnotationAggregator.to_insight_record(
            annotations, self.posts, self.comments
        )
        self.assertEqual(result.sentiment, "positive")

    def test_strips_whitespace_from_labels(self):
        """标签首尾空格被去除。"""
        annotations = [
            CommentAnnotationRecord(
                comment_id="c1", post_id="p1",
                pain_point_labels=["  头皮屑多  "],
            ),
        ]
        result = AnnotationAggregator.to_insight_record(
            annotations, self.posts, self.comments
        )
        self.assertEqual(result.pain_points, ["头皮屑多"])


if __name__ == "__main__":
    unittest.main()
