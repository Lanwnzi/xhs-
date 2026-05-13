"""UGCGraphState - LangGraph 的有状态数据模型。

LangGraph 中的 state 是节点之间传递的统一数据容器。
每个节点读取 state，执行自己的逻辑，然后返回一个部分更新。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from typing import Optional

from src.schemas import (
    AnalysisRequest,
    InsightRecord,
    NormalizedDataset,
    RawDataset,
    ScoreCard,
    SentimentResult,
)
from src.schemas.content_ideation import ContentIdeationResult
from src.schemas.llm_records import CommentAnnotationRecord
from src.utils import AppPaths


class UGCGraphState(BaseModel):
    """LangGraph 中节点之间传递的统一状态。

    request 和 paths 在初始时注入（不可变输入）。
    后续节点逐步填充 raw_dataset、normalized_dataset、sentiment_result、
    insights、scorecard、comment_annotations 和 report_path。

    report_generated 在 report_node 完成后设为 True。
    success 在 report_node 完成后设为 True。

    comment_annotations: llm_annotation 模式下由 annotate_comments_node 填充。
    rule 模式下为 None。
    """

    request: AnalysisRequest
    paths: AppPaths
    raw_dataset: RawDataset | None = None
    normalized_dataset: NormalizedDataset | None = None
    sentiment_result: SentimentResult | None = None
    insights: InsightRecord | None = None
    scorecard: ScoreCard | None = None
    comment_annotations: list[CommentAnnotationRecord] | None = None
    content_ideation_result: ContentIdeationResult | None = None
    report_path: str | None = None
    success: bool = False
    report_generated: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True)
