"""
UGC Market Validator 的评分规则。

所有评分函数均为纯基于规则（不调用 LLM）。
各维度函数 (calc_demand_intensity / calc_sentiment_friction / ...) 返回 [0.0, 1.0] 范围内的浮点数。
calc_overall 返回 (float, str)，即 overall_score 与对应的评分理由。
"""

from __future__ import annotations

import logging
import math
from datetime import datetime

from src.schemas import InsightRecord, NormalizedDataset, SentimentResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 购买意向关键词子集
# ---------------------------------------------------------------------------

_PURCHASE_KEYWORDS: set[str] = {
    "多少钱",
    "哪里买",
    "想买",
    "怎么买",
    "下单",
    "链接",
    "求链接",
    "同求",
    "要买",
    "入手",
    "购买",
    "求购",
    "在哪儿",
    "买",
}

# ---------------------------------------------------------------------------
# 综合评分的维度权重
# ---------------------------------------------------------------------------

_DEMAND_WEIGHT = 0.30
_FRICTION_WEIGHT = 0.25
_SATURATION_WEIGHT = 0.15
_PURCHASE_WEIGHT = 0.20
_FRESHNESS_WEIGHT = 0.10


# ===================================================================
# 规则函数
# ===================================================================


def calc_demand_intensity(insight: InsightRecord) -> float:
    """根据用户需求和市场信号计算需求强度。

    使用 log1p 平滑让前几个需求贡献大、后面边际递减，避免少数需求直接打满。

    - need_score = log1p(needs) / log1p(20)，权重 0.6
    - signal_score = log1p(signals) / log1p(20)，权重 0.4
    - 总分上限为 1.0
    """
    needs = len(insight.user_needs)
    signals = len(insight.market_signals)

    need_score = math.log1p(needs) / math.log1p(20)
    signal_score = math.log1p(signals) / math.log1p(20)

    raw = need_score * 0.6 + signal_score * 0.4
    return min(round(raw, 4), 1.0)


def calc_sentiment_friction(
    insight: InsightRecord,
    sentiment: SentimentResult,
) -> float:
    """根据整体情感和投诉数量计算负面摩擦。

    - 负面情感加 0.4，中性加 0.2，正面加 0.0
    - 每个投诉或痛点加 0.05（投诉/痛点部分最高 0.6）
    - 总分上限为 1.0
    """
    # 情感基础分
    overall = (sentiment.overall_sentiment or insight.sentiment or "").lower()
    if overall == "negative":
        sentiment_base = 0.4
    elif overall == "neutral":
        sentiment_base = 0.2
    else:
        sentiment_base = 0.0

    # 投诉 / 痛点贡献
    complaint_count = len(insight.complaints) + len(insight.pain_points)
    complaint_score = min(complaint_count * 0.05, 0.6)

    raw = sentiment_base + complaint_score
    return min(round(raw, 2), 1.0)


def calc_solution_saturation(insight: InsightRecord) -> float:
    """根据提及的解决方案数量计算方案饱和度。

    - 0 个解决方案 -> 0.0
    - 1-2 个解决方案 -> 0.2
    - 3-4 个解决方案 -> 0.5
    - 5-7 个解决方案 -> 0.7
    - 8 个以上解决方案 -> 0.9
    """
    count = len(insight.solutions)
    if count == 0:
        return 0.0
    if count <= 2:
        return 0.2
    if count <= 4:
        return 0.5
    if count <= 7:
        return 0.7
    return 0.9


def calc_purchase_intent(insight: InsightRecord) -> float:
    """根据市场信号计算购买意向。

    每个与购买相关关键词匹配的市场信号贡献 +0.2（总分上限为 1.0）。
    """
    if not insight.market_signals:
        return 0.0

    count = sum(
        1 for signal in insight.market_signals if signal in _PURCHASE_KEYWORDS
    )
    raw = count * 0.2
    return min(round(raw, 2), 1.0)


def calc_freshness(dataset: NormalizedDataset) -> float:
    """根据最新帖子的发布时间计算数据时效性。

    - 1 个月以内 -> 1.0
    - 3 个月以内 -> 0.8
    - 6 个月以内 -> 0.5
    - 12 个月以内 -> 0.2
    - 更早 -> 0.1

    若无帖子，返回 0.1。
    """
    if not dataset.posts:
        return 0.1

    # 找到最晚的 publish_time
    times = [p.publish_time for p in dataset.posts if p.publish_time]
    if not times:
        return 0.1

    try:
        latest = max(datetime.fromisoformat(t) for t in times)
    except (ValueError, TypeError):
        logger.warning("calc_freshness: could not parse any publish_time")
        return 0.1

    now = datetime.now()
    days_diff = (now - latest).days
    months_diff = days_diff / 30.44

    if months_diff <= 1:
        return 1.0
    if months_diff <= 3:
        return 0.8
    if months_diff <= 6:
        return 0.5
    if months_diff <= 12:
        return 0.2
    return 0.1


def calc_overall(
    demand_intensity: float,
    sentiment_friction: float,
    solution_saturation: float,
    purchase_intent: float,
    freshness: float,
    insight: InsightRecord,
    sentiment: SentimentResult,
) -> tuple[float, str]:
    """将综合评分计算为加权平均值并生成理由。

    权重:
      demand_intensity    0.30
      sentiment_friction  0.25
      solution_saturation 0.15 (使用 1 - saturation 作为机会空间)
      purchase_intent     0.20
      freshness           0.10

    solution_saturation 在 overall 中反向处理: 高饱和 = 竞争激烈 = 机会空间小。
    使用 opportunity_gap = 1.0 - solution_saturation 作为正向分参与加权。

    注意: freshness 已由调用方独立计算，calc_overall 不再接收 dataset。

    返回:
        (overall_score, scoring_reason)，其中 overall_score 在 [0, 1] 范围内。
    """
    opportunity_gap = 1.0 - solution_saturation
    overall = round(
        demand_intensity * _DEMAND_WEIGHT
        + sentiment_friction * _FRICTION_WEIGHT
        + opportunity_gap * _SATURATION_WEIGHT  # 使用机会空间代替直接加 saturation
        + purchase_intent * _PURCHASE_WEIGHT
        + freshness * _FRESHNESS_WEIGHT,
        4,
    )

    # 构建评分理由
    overall_label = sentiment.overall_sentiment or insight.sentiment or "未知"
    complaint_total = len(insight.complaints) + len(insight.pain_points)

    # friction 解释: 当情感偏正面但投诉/痛点较多时表述要清楚
    if overall_label.lower() == "positive" and complaint_total > 5:
        friction_line = (
            f"【负面摩擦 {sentiment_friction:.2f}】整体情感为 {overall_label}，"
            f"但样本中仍检测到 {complaint_total} 个痛点/投诉，问题摩擦为中等"
        )
    else:
        friction_line = (
            f"【负面摩擦 {sentiment_friction:.2f}】情感倾向为 {overall_label}，"
            f"共 {complaint_total} 个投诉/痛点"
        )

    purchase_count = sum(
        1 for s in insight.market_signals if s in _PURCHASE_KEYWORDS
    )

    lines: list[str] = [
        f"【用户关注强度 {demand_intensity:.2f}】基于 {len(insight.user_needs)} 个用户需求和 {len(insight.market_signals)} 个内容机会信号计算",
        friction_line,
        f"【方案饱和 {solution_saturation:.2f}】共 {len(insight.solutions)} 个解决方案提及",
        f"【机会空间 {opportunity_gap:.2f}】方案饱和度为 {solution_saturation:.2f}，机会空间 = 1 - 饱和度 = {opportunity_gap:.2f}",
        f"【购买意向 {purchase_intent:.2f}】检测到 {purchase_count} 个购买信号",
        f"【内容选题价值 {overall:.2f}】加权计算：关注度 {_DEMAND_WEIGHT} + 负反馈 {_FRICTION_WEIGHT} + 机会空间 {_SATURATION_WEIGHT} + 行动信号 {_PURCHASE_WEIGHT} + 时效 {_FRESHNESS_WEIGHT}",
    ]

    scoring_reason = "\n".join(lines)
    return overall, scoring_reason
