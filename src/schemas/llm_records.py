"""LLM 内部使用的 Pydantic schema。

这些是 LLM Agent 内部 schema，不直接写入最终产物。
最终输出仍然使用 records.py 中的 SentimentResult 和 InsightRecord。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LLMCommentSentiment(BaseModel):
    """LLM 情感分析输出的单条评论情感。"""
    comment_id: str = ""
    post_id: str = ""
    sentiment: str = "neutral"  # positive / negative / neutral / mixed
    emotion_tags: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    evidence_text: str = ""
    reason: str = ""


class LLMInsightItem(BaseModel):
    """LLM 洞察抽取输出的单条洞察。"""
    text: str = ""
    evidence_post_ids: list[str] = Field(default_factory=list)
    evidence_comment_ids: list[str] = Field(default_factory=list)
    evidence_text: str = ""


class LLMInsightResult(BaseModel):
    """LLM 洞察抽取的完整输出。"""
    pain_points: list[LLMInsightItem] = Field(default_factory=list)
    user_needs: list[LLMInsightItem] = Field(default_factory=list)
    complaints: list[LLMInsightItem] = Field(default_factory=list)
    solutions: list[LLMInsightItem] = Field(default_factory=list)
    market_signals: list[LLMInsightItem] = Field(default_factory=list)
    sentiment: str = ""


class CommentAnnotationRecord(BaseModel):
    """LLM 评论级语义标注的输出记录。

    comment_id 和 post_id 由代码从原始 CommentRecord 绑定。
    LLM 只输出 label 列表和情绪。
    reason 仅用于 debug，不进入最终 InsightRecord。
    """

    comment_id: str = ""
    post_id: str = ""
    sentiment: str = "neutral"
    pain_point_labels: list[str] = []
    need_labels: list[str] = []
    complaint_labels: list[str] = []
    solution_labels: list[str] = []
    market_signal_labels: list[str] = []
    intent_labels: list[str] = []
    reason: str = ""
