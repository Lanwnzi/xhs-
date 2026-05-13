"""过滤 LLM 输出中的评分字段。

LLM 可以输出 sentiment、insight 等分析结果，
但禁止输出 demand_intensity / sentiment_friction / solution_saturation /
purchase_intent / freshness / overall_score 等评分字段。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_FORBIDDEN_SCORE_FIELDS = {
    "demand_intensity", "sentiment_friction", "solution_saturation",
    "purchase_intent", "freshness", "overall_score",
    "demand_score", "friction_score", "saturation_score",
    "purchase_score", "freshness_score", "score",
}


def filter_forbidden_scores(data: dict[str, Any]) -> dict[str, Any]:
    """递归过滤 dict 中的评分字段。"""
    if not isinstance(data, dict):
        return data
    filtered = {}
    for key, value in data.items():
        # 检查键名
        if key in _FORBIDDEN_SCORE_FIELDS:
            logger.warning("score_filter: 移除禁止字段 %s", key)
            continue
        # 递归处理嵌套 dict
        if isinstance(value, dict):
            filtered[key] = filter_forbidden_scores(value)
        elif isinstance(value, list):
            filtered[key] = [
                filter_forbidden_scores(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            filtered[key] = value
    return filtered
