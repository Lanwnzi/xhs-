"""评分规则单元测试。"""

from __future__ import annotations

import math
import sys
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import unittest

from src.schemas import (
    InsightRecord, NormalizedDataset, PostRecord, CommentRecord, SentimentResult,
)
from src.scoring.rules import (
    calc_demand_intensity, calc_sentiment_friction, calc_solution_saturation,
    calc_purchase_intent, calc_freshness, calc_overall,
)


class TestSolutionSaturation(unittest.TestCase):

    def test_range(self):
        """solution_saturation 应在 0~1 之间。"""
        for count in [0, 1, 2, 3, 4, 5, 7, 8, 10, 100]:
            insight = InsightRecord(
                solutions=[f"s{i}" for i in range(count)],
                evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
            )
            score = calc_solution_saturation(insight)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

    def test_specific_values(self):
        """solution_saturation 预期值校验。"""
        cases = [
            (0, 0.0),
            (1, 0.2),
            (2, 0.2),
            (3, 0.5),
            (4, 0.5),
            (5, 0.7),
            (7, 0.7),
            (8, 0.9),
            (100, 0.9),
        ]
        for count, expected in cases:
            insight = InsightRecord(
                solutions=[f"s{i}" for i in range(count)],
                evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
            )
            self.assertEqual(calc_solution_saturation(insight), expected)

    def test_inverted_in_overall(self):
        """overall 应使用 1 - solution_saturation 而非直接加 saturation。"""
        insight_low = InsightRecord(
            solutions=["s1"],
            evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
        )
        insight_high = InsightRecord(
            solutions=["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8"],
            evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
        )
        dataset = NormalizedDataset()
        sentiment = SentimentResult(overall_sentiment="neutral")

        overall_low, _ = calc_overall(0.5, 0.5, calc_solution_saturation(insight_low), 0.5, 0.5, insight_low, sentiment)
        overall_high, _ = calc_overall(0.5, 0.5, calc_solution_saturation(insight_high), 0.5, 0.5, insight_high, sentiment)

        # high saturation 应该使 overall 更低（因为 opportunity gap 更小）
        self.assertGreaterEqual(overall_low, overall_high,
            "高饱和度应导致更低综合分，因为机会空间 = 1 - 饱和度")


class TestDemandIntensity(unittest.TestCase):

    def test_not_maxed_easily(self):
        """5 needs + 4 signals 不应直接等于 1.0。"""
        insight = InsightRecord(
            user_needs=[f"n{i}" for i in range(5)],
            market_signals=[f"s{i}" for i in range(4)],
            evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
        )
        score = calc_demand_intensity(insight)
        self.assertLess(score, 1.0,
            "5 needs + 4 signals 不应直接打满 1.0")

    def test_range(self):
        """demand_intensity 应在 0~1 之间。"""
        for n_needs in [0, 1, 3, 5, 10, 20]:
            for n_signals in [0, 1, 3, 5, 10]:
                insight = InsightRecord(
                    user_needs=[f"n{i}" for i in range(n_needs)],
                    market_signals=[f"s{i}" for i in range(n_signals)],
                    evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
                )
                score = calc_demand_intensity(insight)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 1.0)

    def test_empty_returns_low(self):
        """0 needs + 0 signals 应接近 0。"""
        insight = InsightRecord(
            evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
        )
        score = calc_demand_intensity(insight)
        # log1p(0) = 0, so score should be 0
        self.assertEqual(score, 0.0)

    def test_log1p_smoothing(self):
        """验证 log1p 的边际递减效果: 从 5->10 的增量应小于 0->5。"""
        insight_5 = InsightRecord(
            user_needs=[f"n{i}" for i in range(5)],
            market_signals=[],
            evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
        )
        insight_10 = InsightRecord(
            user_needs=[f"n{i}" for i in range(10)],
            market_signals=[],
            evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
        )

        score_5 = calc_demand_intensity(insight_5)
        score_10 = calc_demand_intensity(insight_10)

        # 5->10 的增量应小于 0->5
        self.assertGreater(score_10 - score_5, 0.0,
            "更多需求应产生更高分数")
        # 相对增量验证: (score_10 - score_5) < score_5
        # log1p(10)/log1p(20) - log1p(5)/log1p(20) < log1p(5)/log1p(20)
        # => log1p(10) - log1p(5) < log1p(5)
        # => log1p(10) < 2*log1p(5)
        # => log(11) < 2*log(6) => 2.398 < 3.584 ✓
        self.assertLess(score_10 - score_5, score_5,
            "log1p 平滑应使高段增幅小于低段")


class TestSentimentFriction(unittest.TestCase):

    def test_range(self):
        """sentiment_friction 应在 0~1 之间。"""
        for n_pains in [0, 2, 5, 10, 20]:
            for n_complaints in [0, 2, 5, 10]:
                insight = InsightRecord(
                    pain_points=[f"p{i}" for i in range(n_pains)],
                    complaints=[f"c{i}" for i in range(n_complaints)],
                    evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
                )
                sentiment = SentimentResult(overall_sentiment="neutral")
                score = calc_sentiment_friction(insight, sentiment)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 1.0)

    def test_sentiment_base_effect(self):
        """情感倾向对 friction 的影响顺序: negative > neutral > positive。"""
        base_insight = InsightRecord(
            evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
        )

        neg = calc_sentiment_friction(base_insight, SentimentResult(overall_sentiment="negative"))
        neu = calc_sentiment_friction(base_insight, SentimentResult(overall_sentiment="neutral"))
        pos = calc_sentiment_friction(base_insight, SentimentResult(overall_sentiment="positive"))

        self.assertGreater(neg, neu)
        self.assertGreater(neu, pos)


class TestPurchaseIntent(unittest.TestCase):

    def test_range(self):
        """purchase_intent 应在 0~1 之间。"""
        insight = InsightRecord(
            market_signals=["想买", "多少钱", "怎么买", "链接", "随便说说"],
            evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
        )
        score = calc_purchase_intent(insight)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_no_signals(self):
        """无 market_signals 时返回 0.0。"""
        insight = InsightRecord(
            evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
        )
        self.assertEqual(calc_purchase_intent(insight), 0.0)

    def test_keyword_matching(self):
        """仅匹配关键词列表中的信号。"""
        insight = InsightRecord(
            market_signals=["想买", "哪里买", "随便", "无关"],
            evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
        )
        # 2 个匹配 * 0.2 = 0.4
        self.assertEqual(calc_purchase_intent(insight), 0.4)


class TestFreshness(unittest.TestCase):

    def test_no_posts(self):
        """无帖子时返回 0.1。"""
        dataset = NormalizedDataset()
        self.assertEqual(calc_freshness(dataset), 0.1)

    def test_recent_returns_high(self):
        """最近帖子返回 1.0。"""
        from datetime import datetime, timedelta
        recent_time = (datetime.now() - timedelta(days=1)).isoformat()
        dataset = NormalizedDataset(posts=[
            PostRecord(platform="xhs", post_id="p1", title="t", content="c",
                       author="a", publish_time=recent_time),
        ])
        self.assertEqual(calc_freshness(dataset), 1.0)

    def test_old_returns_low(self):
        """超过 1 年的帖子返回 0.1。"""
        from datetime import datetime, timedelta
        old_time = (datetime.now() - timedelta(days=400)).isoformat()
        dataset = NormalizedDataset(posts=[
            PostRecord(platform="xhs", post_id="p1", title="t", content="c",
                       author="a", publish_time=old_time),
        ])
        self.assertEqual(calc_freshness(dataset), 0.1)


class TestOverall(unittest.TestCase):

    def test_scoring_reason_not_empty(self):
        """calc_overall 的 scoring_reason 不应为空。"""
        insight = InsightRecord(
            user_needs=["n1"], market_signals=["s1"],
            pain_points=["p1"], complaints=["c1"], solutions=["s1"],
            evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
        )
        dataset = NormalizedDataset(
            posts=[PostRecord(platform="xhs", post_id="p1", title="t", content="c",
                              author="a", publish_time="2026-01-01T00:00:00")],
            comments=[CommentRecord(platform="xhs", comment_id="c1", post_id="p1",
                                    content="c", author="a",
                                    publish_time="2026-01-01T00:00:00")],
        )
        sentiment = SentimentResult(overall_sentiment="positive")

        _, reason = calc_overall(0.5, 0.5, 0.5, 0.5, 0.5, insight, sentiment)
        self.assertTrue(len(reason) > 0)
        self.assertIn("机会空间", reason, "scoring_reason 应包含机会空间说明")

    def test_overall_saturation_inverted(self):
        """显式验证 opportunity_gap 在 overall 中使用。"""
        insight = InsightRecord(
            solutions=["s1", "s2", "s3"],
            evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
        )
        dataset = NormalizedDataset()
        sentiment = SentimentResult(overall_sentiment="neutral")

        # 全部维度一样，只有 saturation 不同
        overall_low_sat, reason_low = calc_overall(
            0.5, 0.5, 0.2, 0.5, 0.5, insight, sentiment,
        )
        overall_high_sat, reason_high = calc_overall(
            0.5, 0.5, 0.9, 0.5, 0.5, insight, sentiment,
        )

        # 高饱和 -> 低机会空间 -> 更低 overall
        self.assertGreater(overall_low_sat, overall_high_sat,
            "高饱和应导致更低的综合分")
        self.assertIn("机会空间", reason_low)
        self.assertIn("机会空间", reason_high)

    def test_range(self):
        """overall_score 应在 0~1 之间。"""
        insight = InsightRecord(
            user_needs=["n1"], market_signals=["s1"],
            pain_points=["p1"], complaints=["c1"], solutions=["s1"],
            evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
        )
        dataset = NormalizedDataset()
        sentiment = SentimentResult(overall_sentiment="neutral")

        overall, _ = calc_overall(0.5, 0.5, 0.5, 0.5, 0.5, insight, sentiment)
        self.assertGreaterEqual(overall, 0.0)
        self.assertLessEqual(overall, 1.0)

    def test_friction_reason_positive_with_many_complaints(self):
        """当情感为 positive 但投诉/痛点 > 5 时，friction 行应特别说明。"""
        insight = InsightRecord(
            complaints=["c1", "c2", "c3", "c4", "c5", "c6"],
            pain_points=["p1", "p2"],
            user_needs=["n1"],
            evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
        )
        dataset = NormalizedDataset()
        sentiment = SentimentResult(overall_sentiment="positive")

        _, reason = calc_overall(0.5, 0.3, 0.3, 0.3, 0.5, insight, sentiment)
        # 应包含"但样本中仍检测到"的说明
        self.assertIn("但样本中仍检测到", reason,
            "positive 情感但投诉/痛点较多时应特别说明")

    def test_friction_reason_normal(self):
        """常规 case — friction 行正常输出。"""
        insight = InsightRecord(
            complaints=["c1"],
            user_needs=["n1"],
            evidence_post_ids=["p1"], evidence_comment_ids=["c1"],
        )
        dataset = NormalizedDataset()
        sentiment = SentimentResult(overall_sentiment="positive")

        _, reason = calc_overall(0.5, 0.1, 0.3, 0.3, 0.5, insight, sentiment)
        self.assertNotIn("但样本中仍检测到", reason,
            "投诉/痛点较少时不应使用特殊说明")
        self.assertIn("共 1 个投诉/痛点", reason)


if __name__ == "__main__":
    unittest.main()
