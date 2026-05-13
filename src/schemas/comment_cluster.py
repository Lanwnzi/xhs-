"""
P6.0 CommentClusterAgent 的 Pydantic schema。

定义评论主题聚类结果的数据结构。
每个聚类代表一组语义相似的评论组成的热点主题。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CommentClusterRecord(BaseModel):
    """一个评论主题聚类。

    代表一组语义相似的评论，通常围绕同一个话题或问题。
    """

    cluster_id: str
    topic: str
    summary: str = ""
    comment_count: int
    total_comment_likes: int
    avg_similarity: float
    hotness: float
    keywords: list[str] = Field(default_factory=list)
    top_labels: list[str] = Field(default_factory=list)
    evidence_comment_ids: list[str] = Field(default_factory=list)
    representative_comments: list[str] = Field(default_factory=list)


class CommentClusterResult(BaseModel):
    """完整聚类结果。"""

    clusters: list[CommentClusterRecord] = Field(default_factory=list)
    total_comments: int = 0
    clustered_comments: int = 0
    noise_comments: int = 0
    algorithm: str = "cosine_threshold_union_find"
    similarity_threshold: float = 0.72
    skipped_reason: str = ""
