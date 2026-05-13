"""AnnotationAggregator - 从 CommentAnnotationRecord 聚合现有 SentimentResult 和 InsightRecord。

不做 label 去重、同义词映射、聚类、低频过滤。
只做 strip()、空 label 跳过、None 跳过。
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Optional

from src.schemas import (
    CommentRecord, CommentSentiment, InsightRecord,
    NormalizedDataset, PostRecord, PostSentiment, SentimentResult,
)
from src.schemas.llm_records import CommentAnnotationRecord

logger = logging.getLogger(__name__)


class AnnotationAggregator:
    """从 CommentAnnotationRecord 聚合现有 SentimentResult 和 InsightRecord。"""

    @staticmethod
    def to_sentiment_result(
        annotations: list[CommentAnnotationRecord],
        posts: list[PostRecord],
        comments: list[CommentRecord],
    ) -> SentimentResult:
        """从 annotation 列表聚合 SentimentResult。

        - comment_sentiments 从 annotations 生成
        - post_sentiments 按 post_id 聚合多数情绪
        - overall_sentiment 按全部评论多数情绪
        """
        if not annotations:
            return SentimentResult(overall_sentiment="neutral")

        # comment_sentiments
        comment_sentiments = []
        for ann in annotations:
            label = "positive" if ann.sentiment == "positive" else \
                    "negative" if ann.sentiment == "negative" else \
                    "neutral"
            comment_sentiments.append(CommentSentiment(
                comment_id=ann.comment_id,
                label=label,
                score=1.0 if ann.sentiment in ("positive", "negative") else 0.5,
            ))

        # post_sentiments
        post_comments: dict[str, list[CommentAnnotationRecord]] = {}
        for ann in annotations:
            post_comments.setdefault(ann.post_id, []).append(ann)

        post_sentiments = []
        for post_id, anns in post_comments.items():
            sentiments = [a.sentiment for a in anns]
            counter = Counter(sentiments)
            majority = counter.most_common(1)[0][0]
            majority_label = "positive" if majority == "positive" else \
                             "negative" if majority == "negative" else \
                             "neutral"
            post_sentiments.append(PostSentiment(
                post_id=post_id,
                label=majority_label,
                score=1.0,
            ))

        # overall_sentiment
        all_sentiments = [a.sentiment for a in annotations]
        counter = Counter(all_sentiments)
        most_common = counter.most_common()

        if not most_common:
            overall = "neutral"
        else:
            top_label, top_count = most_common[0]
            # 如果 positive 和 negative 最高且差距 <= 1，则 mixed
            if len(most_common) > 1:
                second_label, second_count = most_common[1]
                if {"positive", "negative"} <= {top_label, second_label} and abs(top_count - second_count) <= 1:
                    overall = "mixed"
                else:
                    overall = top_label
            else:
                overall = top_label

        return SentimentResult(
            overall_sentiment=overall,
            post_sentiments=post_sentiments,
            comment_sentiments=comment_sentiments,
        )

    @staticmethod
    def to_insight_record(
        annotations: list[CommentAnnotationRecord],
        posts: list[PostRecord],
        comments: list[CommentRecord],
    ) -> InsightRecord:
        """从 annotation 列表聚合 InsightRecord。

        - LLM 不生成 evidence ids，由代码按 annotation.comment_id 绑定
        - LLM 不生成 InsightRecord，由代码聚合
        - 不做 label 去重
        """
        pain_points: list[str] = []
        user_needs: list[str] = []
        complaints: list[str] = []
        solutions: list[str] = []
        market_signals: list[str] = []
        evidence_comment_ids: list[str] = []
        evidence_post_ids: list[str] = []

        for ann in annotations:
            # labels
            for label in ann.pain_point_labels:
                label = label.strip()
                if label:
                    pain_points.append(label)

            for label in ann.need_labels:
                label = label.strip()
                if label:
                    user_needs.append(label)

            for label in ann.complaint_labels:
                label = label.strip()
                if label:
                    complaints.append(label)

            for label in ann.solution_labels:
                label = label.strip()
                if label:
                    solutions.append(label)

            for label in ann.market_signal_labels:
                label = label.strip()
                if label:
                    market_signals.append(label)

            for label in ann.intent_labels:
                label = label.strip()
                if label:
                    market_signals.append(label)

            # evidence
            if ann.comment_id not in evidence_comment_ids:
                evidence_comment_ids.append(ann.comment_id)
            if ann.post_id and ann.post_id not in evidence_post_ids:
                evidence_post_ids.append(ann.post_id)

        # sentiment
        sentiment_counts = Counter(a.sentiment for a in annotations if a.sentiment)
        overall = sentiment_counts.most_common(1)[0][0] if sentiment_counts else "neutral"

        return InsightRecord(
            pain_points=pain_points,
            user_needs=user_needs,
            complaints=complaints,
            solutions=solutions,
            market_signals=market_signals,
            sentiment=overall,
            evidence_post_ids=evidence_post_ids,
            evidence_comment_ids=evidence_comment_ids,
        )
