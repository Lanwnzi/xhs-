"""
UGC Market Validator - Pydantic 模式定义

所有 Agent 输入输出的统一数据契约。
所有模型继承 BaseModel，支持 JSON 序列化。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# 核心业务模型
# ---------------------------------------------------------------------------


class PostRecord(BaseModel):
    """来自任意平台的单条 UGC 帖子。"""

    platform: str
    post_id: str
    title: str
    content: str
    author: str
    publish_time: str  # ISO 8601 格式
    likes: int = 0
    comments: int = 0
    favorites: int = 0
    shares: int = 0
    url: str = ""
    tags: list[str] = []

    # 允许宽松输入，以便 mock / 原始平台数据通过校验
    model_config = ConfigDict(strict=False)


class CommentRecord(BaseModel):
    """附属于帖子的一条评论。"""

    platform: str
    comment_id: str
    post_id: str
    content: str
    author: str
    publish_time: str  # ISO 8601 格式
    likes: int = 0
    parent_comment_id: str | None = None

    model_config = ConfigDict(strict=False)


class InsightRecord(BaseModel):
    """从标准化数据中提取的结构化洞察。

    每个列表条目必须至少有一个证据 ID 作为支撑。
    """

    pain_points: list[str] = []
    user_needs: list[str] = []
    complaints: list[str] = []
    solutions: list[str] = []
    market_signals: list[str] = []
    sentiment: str = ""
    evidence_post_ids: list[str] = []
    evidence_comment_ids: list[str] = []


class ScoreCard(BaseModel):
    """基于规则驱动的市场评分结果。

    所有维度分数为 [0, 1] 范围内的浮点数。
    scoring_reason 必须解释每个维度是如何得出的。
    """

    demand_intensity: float
    sentiment_friction: float
    solution_saturation: float
    purchase_intent: float
    freshness: float
    overall_score: float
    scoring_reason: str


# ---------------------------------------------------------------------------
# 辅助输入输出模型
# ---------------------------------------------------------------------------


class AnalysisRequest(BaseModel):
    """一次完整市场验证运行的输入参数。"""

    topic: str
    product_direction: str
    industry_question: str


class RawDataset(BaseModel):
    """标准化前的原始数据容器。"""

    posts: list[PostRecord] = []
    comments: list[CommentRecord] = []


class NormalizedDataset(BaseModel):
    """清洗/映射后的标准化数据容器。"""

    posts: list[PostRecord] = []
    comments: list[CommentRecord] = []


class PostSentiment(BaseModel):
    """单条帖子的情感分析结果。"""

    post_id: str
    label: str  # 可选值: positive / negative / neutral
    score: float  # 取值范围 0.0 到 1.0


class CommentSentiment(BaseModel):
    """单条评论的情感分析结果。"""

    comment_id: str
    label: str  # 可选值: positive / negative / neutral
    score: float  # 取值范围 0.0 到 1.0


class SentimentResult(BaseModel):
    """聚合后的情感分析输出。"""

    overall_sentiment: str = ""
    post_sentiments: list[PostSentiment] = []
    comment_sentiments: list[CommentSentiment] = []


# ---------------------------------------------------------------------------
# 报告输出模型
# ---------------------------------------------------------------------------


class ReportResult(BaseModel):
    """报告生成的输出结果。"""

    success: bool = False
    report_path: str = ""
