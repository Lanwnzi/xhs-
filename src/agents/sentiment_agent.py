"""
SentimentAgent - 基于关键词的 UGC 数据情感分析。

输入:  NormalizedDataset
输出: SentimentResult

操作:
  1. 使用关键词规则将每条评论分类为 positive / negative / neutral。
  2. 基于评论聚合每条帖子的情感。
  3. 聚合整体主题情感。

边界约束:
  - SentimentAgent 不进行评分、报告生成或市场结论。
  - 仅使用关键词匹配（不调用 LLM）。
"""

from __future__ import annotations

import logging
from collections import Counter

from src.keywords import NEGATIVE_KEYWORDS, POSITIVE_KEYWORDS
from src.schemas import (
    CommentRecord,
    CommentSentiment,
    NormalizedDataset,
    PostRecord,
    PostSentiment,
    SentimentResult,
)

logger = logging.getLogger(__name__)


class SentimentAgent:
    """负责基于关键词的情感分类的 Agent。"""

    def execute(self, dataset: NormalizedDataset) -> SentimentResult:
        """对所有评论进行情感分类，聚合到帖子级和整体级。

        参数:
            dataset: 包含帖子和评论的 NormalizedDataset。

        返回:
            SentimentResult，包含每条评论、每条帖子和整体的情感。

        抛出:
            若帖子和评论均为空则抛出 ValueError。
        """
        if not dataset.posts and not dataset.comments:
            raise ValueError("SentimentAgent: dataset is empty (no posts or comments)")

        # 构建 post_id -> 评论列表的查找表
        comments_by_post: dict[str, list[CommentRecord]] = {}
        for c in dataset.comments:
            comments_by_post.setdefault(c.post_id, []).append(c)

        # 分类每条评论
        comment_sentiments = [
            self._classify_comment(c) for c in dataset.comments
        ]

        # 构建查找表，供 _aggregate_post_sentiments 使用，避免重复分类
        comment_sentiments_lookup: dict[str, CommentSentiment] = {
            cs.comment_id: cs for cs in comment_sentiments
        }

        # 基于评论聚合每条帖子的情感
        post_sentiments = self._aggregate_post_sentiments(
            dataset.posts, comments_by_post, comment_sentiments_lookup
        )

        # 聚合整体主题情感
        overall = self._aggregate_overall(comment_sentiments)

        result = SentimentResult(
            overall_sentiment=overall["label"],
            post_sentiments=post_sentiments,
            comment_sentiments=comment_sentiments,
        )

        logger.info(
            "Sentiment analysis complete: overall=%s, posts=%d, comments=%d",
            overall["label"],
            len(post_sentiments),
            len(comment_sentiments),
        )
        return result

    # ------------------------------------------------------------------
    # 评论级分类
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_comment(comment: CommentRecord) -> CommentSentiment:
        """使用关键词匹配对单条评论进行情感分类。

        返回:
            包含标签和分数的 CommentSentiment。
        """
        content = comment.content or ""

        pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in content)
        neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in content)

        if pos_count == 0 and neg_count == 0:
            label = "neutral"
            score = 0.5
        elif pos_count > neg_count:
            label = "positive"
            score = round(pos_count / (pos_count + neg_count), 4)
        elif neg_count > pos_count:
            label = "negative"
            score = round(neg_count / (pos_count + neg_count), 4)
        else:
            # 正负数量相等
            label = "neutral"
            score = 0.5

        return CommentSentiment(
            comment_id=comment.comment_id, label=label, score=score
        )

    # ------------------------------------------------------------------
    # 帖子级聚合
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate_post_sentiments(
        posts: list[PostRecord],
        comments_by_post: dict[str, list[CommentRecord]],
        comment_sentiments_lookup: dict[str, CommentSentiment],
    ) -> list[PostSentiment]:
        """基于帖子的评论聚合每条帖子的情感。

        使用预先分类的 CommentSentiment 查找表，避免重复分类。

        对于没有评论的帖子，默认为 neutral（分数 0.5）。
        """
        post_sentiments: list[PostSentiment] = []

        for post in posts:
            post_comments = comments_by_post.get(post.post_id, [])
            if not post_comments:
                post_sentiments.append(
                    PostSentiment(post_id=post.post_id, label="neutral", score=0.5)
                )
                continue

            # 查找每条评论的预先分类情感
            labels: Counter = Counter()
            scores: list[float] = []
            for comment in post_comments:
                cs = comment_sentiments_lookup[comment.comment_id]
                labels[cs.label] += 1
                scores.append(cs.score)

            # 多数标签
            majority_label = labels.most_common(1)[0][0]
            # 平均分数
            avg_score = round(sum(scores) / len(scores), 4)

            post_sentiments.append(
                PostSentiment(
                    post_id=post.post_id, label=majority_label, score=avg_score
                )
            )

        return post_sentiments

    # ------------------------------------------------------------------
    # 整体聚合
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate_overall(
        comment_sentiments: list[CommentSentiment],
    ) -> dict[str, object]:
        """从所有评论情感中聚合整体情感。

        返回包含 "label" 和 "score" 键的字典。
        """
        if not comment_sentiments:
            return {"label": "neutral", "score": 0.5}

        labels: Counter = Counter()
        total_score = 0.0

        for cs in comment_sentiments:
            labels[cs.label] += 1
            total_score += cs.score

        avg_score = round(total_score / len(comment_sentiments), 4)
        majority_label = labels.most_common(1)[0][0]

        return {"label": majority_label, "score": avg_score}
