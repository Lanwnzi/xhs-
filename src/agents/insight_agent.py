"""
InsightAgent - 从标准化 UGC 数据中提取结构化洞察。

输入:  NormalizedDataset, SentimentResult
输出: InsightRecord（持久化到 data/outputs/insights.json）

操作:
  1. 扫描帖子和评论，匹配每个洞察类别的关键词。
  2. 为每个匹配的洞察收集 evidence post_ids 和 comment_ids。
  3. 从 SentimentResult 中分配情感。
  4. 持久化到 data/outputs/insights.json。

边界约束:
  - InsightAgent 不进行评分、报告生成或市场结论。
  - 每条洞察条目至少有一个证据 ID 作为支撑。
"""

from __future__ import annotations

import logging

from src.keywords import (
    COMPLAINT_KEYWORDS,
    MARKET_SIGNAL_KEYWORDS,
    PAIN_POINT_KEYWORDS,
    SOLUTION_KEYWORDS,
    USER_NEED_KEYWORDS,
)

from src.schemas import (
    InsightRecord,
    NormalizedDataset,
    SentimentResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 洞察关键词字典
#
# 每个类别映射到 src.keywords 中定义的中文关键词列表。
# 当在帖子或评论中发现关键词时，记录一条洞察条目，
# 以匹配到的关键词作为洞察文本，来源 ID 作为证据。
# ---------------------------------------------------------------------------

# 类别名到关键词列表的映射，用于迭代
_INSIGHT_KEYWORDS: dict[str, list[str]] = {
    "pain_points": PAIN_POINT_KEYWORDS,
    "user_needs": USER_NEED_KEYWORDS,
    "complaints": COMPLAINT_KEYWORDS,
    "solutions": SOLUTION_KEYWORDS,
    "market_signals": MARKET_SIGNAL_KEYWORDS,
}

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------



class InsightAgent:
    """负责从 UGC 数据中提取结构化洞察的 Agent。

    不做持久化，由调用方（node）负责持久化。
    """

    def execute(
        self,
        dataset: NormalizedDataset,
        sentiment: SentimentResult,
    ) -> InsightRecord:
        """从帖子和评论中提取结构化洞察。

        参数:
            dataset: 包含已清洗帖子和评论的 NormalizedDataset。
            sentiment: 来自 SentimentAgent 的 SentimentResult。

        返回:
            InsightRecord，包含 pain_points、user_needs、complaints、
            solutions、market_signals、sentiment 和证据 ID。

        抛出:
            若无法从数据中提取任何洞察则抛出 ValueError。
        """
        # 收集洞察并跟踪证据
        raw_insights = self._collect_insights(dataset)

        # 从原始洞察构建 InsightRecord
        insight = self._build_insight(raw_insights, sentiment)

        if not insight.pain_points and not insight.user_needs and not insight.complaints:
            logger.warning(
                "InsightAgent: no insights extracted from the dataset"
            )

        return insight

    # ------------------------------------------------------------------
    # 洞察收集
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_insights(
        dataset: NormalizedDataset,
    ) -> dict[str, dict[str, dict]]:
        """扫描所有帖子和评论，匹配关键词。

        返回嵌套字典:
          {
            "pain_points": {
              "太贵": {"post_ids": {"p1"}, "comment_ids": {"c3"}},
              ...
            },
            "user_needs": { ... },
            ...
          }

        每个匹配的关键词映射到一组证据 ID。
        """
        # 初始化结构
        results: dict[str, dict[str, dict]] = {}
        for category in _INSIGHT_KEYWORDS:
            results[category] = {}

        # 扫描帖子（标题 + 内容）
        for post in dataset.posts:
            text = (post.title + " " + post.content).lower()
            for category, keywords in _INSIGHT_KEYWORDS.items():
                for kw in keywords:
                    if kw in text:
                        if kw not in results[category]:
                            results[category][kw] = {
                                "post_ids": set(),
                                "comment_ids": set(),
                            }
                        results[category][kw]["post_ids"].add(post.post_id)

        # 扫描评论
        for comment in dataset.comments:
            text = (comment.content or "").lower()
            for category, keywords in _INSIGHT_KEYWORDS.items():
                for kw in keywords:
                    if kw in text:
                        if kw not in results[category]:
                            results[category][kw] = {
                                "post_ids": set(),
                                "comment_ids": set(),
                            }
                        results[category][kw]["comment_ids"].add(
                            comment.comment_id
                        )

        return results

    # ------------------------------------------------------------------
    # InsightRecord 构建器
    # ------------------------------------------------------------------

    @staticmethod
    def _build_insight(
        raw_insights: dict[str, dict[str, dict]],
        sentiment: SentimentResult,
    ) -> InsightRecord:
        """将原始收集的洞察转换为已校验的 InsightRecord。

        每个匹配的关键词成为对应列表中的一条条目。
        所有条目的证据 ID 被合并。
        """
        pain_points: list[str] = list(raw_insights["pain_points"].keys())
        user_needs: list[str] = list(raw_insights["user_needs"].keys())
        complaints: list[str] = list(raw_insights["complaints"].keys())
        solutions: list[str] = list(raw_insights["solutions"].keys())
        market_signals: list[str] = list(raw_insights["market_signals"].keys())

        # 收集所有证据 ID
        evidence_post_ids: set[str] = set()
        evidence_comment_ids: set[str] = set()

        for category_data in raw_insights.values():
            for entry in category_data.values():
                evidence_post_ids.update(entry.get("post_ids", set()))
                evidence_comment_ids.update(entry.get("comment_ids", set()))

        # 排序以确保确定性输出
        pain_points.sort()
        user_needs.sort()
        complaints.sort()
        solutions.sort()
        market_signals.sort()

        return InsightRecord(
            pain_points=pain_points,
            user_needs=user_needs,
            complaints=complaints,
            solutions=solutions,
            market_signals=market_signals,
            sentiment=sentiment.overall_sentiment,
            evidence_post_ids=sorted(evidence_post_ids),
            evidence_comment_ids=sorted(evidence_comment_ids),
        )



