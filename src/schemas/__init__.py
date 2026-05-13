"""
UGC Market Validator 的统一模式导出。

用法：
    from src.schemas import PostRecord, CommentRecord
"""

from src.schemas.comment_cluster import CommentClusterRecord, CommentClusterResult
from src.schemas.records import (
    AnalysisRequest,
    CommentRecord,
    CommentSentiment,
    InsightRecord,
    NormalizedDataset,
    PostRecord,
    PostSentiment,
    RawDataset,
    ReportResult,
    ScoreCard,
    SentimentResult,
)
from src.schemas.content_ideation import (
    ContentIdeationResult,
    TitleSuggestion,
    TopicSuggestion,
)
from src.schemas.report_review import ReportQualityReview

__all__ = [
    "PostRecord",
    "CommentRecord",
    "InsightRecord",
    "ScoreCard",
    "AnalysisRequest",
    "RawDataset",
    "NormalizedDataset",
    "SentimentResult",
    "PostSentiment",
    "CommentSentiment",
    "ReportResult",
    "ReportQualityReview",
    "CommentClusterRecord",
    "CommentClusterResult",
    "ContentIdeationResult",
    "TopicSuggestion",
    "TitleSuggestion",
]
