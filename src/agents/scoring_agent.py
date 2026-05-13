"""
ScoringAgent - UGC Market Validator 的基于规则的市场评分。

输入:  InsightRecord, NormalizedDataset, SentimentResult
输出: ScoreCard（持久化到 data/outputs/scorecard.json）

操作:
  1. 调用 src.scoring.rules 中的每条规则函数计算各维度分数。
  2. 组装已校验的 ScoreCard。
  3. 持久化到 data/outputs/scorecard.json。

边界约束:
  - ScoringAgent 不进行分析、重新提取洞察或生成报告。
  - 所有分数通过规则函数计算（不调用 LLM 进行评分）。
"""

from __future__ import annotations

import logging

from src.scoring.rules import (
    calc_demand_intensity,
    calc_freshness,
    calc_overall,
    calc_purchase_intent,
    calc_sentiment_friction,
    calc_solution_saturation,
)

from src.schemas import InsightRecord, NormalizedDataset, ScoreCard, SentimentResult

logger = logging.getLogger(__name__)


class ScoringAgent:
    """负责基于规则的内容选题评分的 Agent。

    不做持久化，由调用方（node）负责持久化。
    """

    def execute(
        self,
        insight: InsightRecord,
        dataset: NormalizedDataset,
        sentiment: SentimentResult,
    ) -> ScoreCard:
        """通过规则计算各维度分数并组装 ScoreCard。

        参数:
            insight: 来自 InsightAgent 的 InsightRecord。
            dataset: 包含已清洗帖子和评论的 NormalizedDataset。
            sentiment: 来自 SentimentAgent 的 SentimentResult。

        返回:
            包含全部六个维度和 scoring_reason 的 ScoreCard。

        抛出:
            若 insight 为空（无数据可评分）则抛出 ValueError。
        """
        # ---- 通过纯规则计算每个维度 ----
        demand_intensity = calc_demand_intensity(insight)
        sentiment_friction = calc_sentiment_friction(insight, sentiment)
        solution_saturation = calc_solution_saturation(insight)
        purchase_intent = calc_purchase_intent(insight)
        freshness = calc_freshness(dataset)

        overall, scoring_reason = calc_overall(
            demand_intensity=demand_intensity,
            sentiment_friction=sentiment_friction,
            solution_saturation=solution_saturation,
            purchase_intent=purchase_intent,
            freshness=freshness,
            insight=insight,
            sentiment=sentiment,
        )

        scorecard = ScoreCard(
            demand_intensity=demand_intensity,
            sentiment_friction=sentiment_friction,
            solution_saturation=solution_saturation,
            purchase_intent=purchase_intent,
            freshness=freshness,
            overall_score=overall,
            scoring_reason=scoring_reason,
        )

        logger.info(
            "Scoring complete: overall=%.4f, demand=%.2f, friction=%.2f, "
            "saturation=%.2f, purchase=%.2f, freshness=%.2f",
            scorecard.overall_score,
            scorecard.demand_intensity,
            scorecard.sentiment_friction,
            scorecard.solution_saturation,
            scorecard.purchase_intent,
            scorecard.freshness,
        )
        return scorecard



