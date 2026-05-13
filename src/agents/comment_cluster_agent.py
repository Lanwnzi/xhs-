"""
P6.0 CommentClusterAgent - 基于 embedding cosine similarity + union-find 的评论主题聚类。

职责：
  1. 读取标准化评论列表
  2. 调用 EmbeddingClient 获取向量
  3. 计算 pairwise cosine similarity
  4. union-find 聚类
  5. 噪声过滤
  6. hotness 排序
  7. 主题命名（从 annotation labels 或文本高频词）
  8. 持久化到 outputs/comment_clusters.json
  9. 返回 CommentClusterResult

设计决策：
  - 旁路产物：不修改 LangGraph DAG 或 UGCGraphState
  - 接入点在 services.py 中 graph.invoke() 之后
  - embedding 失败时跳过（不阻塞主流程）
  - 聚类算法：cosine similarity threshold + union-find connected components
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from collections import Counter
from typing import Optional

from src.llm.embedding_client import EmbeddingClient
from src.schemas import CommentRecord
from src.schemas.comment_cluster import (
    CommentClusterRecord,
    CommentClusterResult,
)
from src.schemas.llm_records import CommentAnnotationRecord
from src.utils import AppPaths

logger = logging.getLogger(__name__)


class CommentClusterAgent:
    """评论主题聚类 Agent。

    参数：
        embedding_client: EmbeddingClient 实例。为 None 时 execute() 返回空结果。
        similarity_threshold: cosine similarity 阈值，默认 0.72。
        min_cluster_size: 最小聚类大小（小于此值视为噪声），默认 2。
        top_k: 按 hotness 排序输出的前 K 个聚类，默认 5。
    """

    def __init__(
        self,
        embedding_client: Optional[EmbeddingClient] = None,
        similarity_threshold: float = 0.72,
        min_cluster_size: int = 2,
        top_k: int = 5,
    ):
        self.embedding_client = embedding_client
        self.similarity_threshold = similarity_threshold
        self.min_cluster_size = min_cluster_size
        self.top_k = top_k

    def execute(
        self,
        normalized_comments: list[CommentRecord],
        annotations: Optional[list[CommentAnnotationRecord]] = None,
    ) -> CommentClusterResult:
        """执行聚类主流程。

        参数：
            normalized_comments: 标准化后的评论列表。
            annotations: 可选的 LLM 评论语义标注列表，用于标签提取。

        返回：
            CommentClusterResult（embedding 不可用或数据不足时返回空结果）。
        """
        if self.embedding_client is None:
            logger.warning("CommentClusterAgent: embedding_client 为 None，跳过聚类")
            return CommentClusterResult(
                clusters=[],
                total_comments=len(normalized_comments),
                clustered_comments=0,
                noise_comments=len(normalized_comments),
                similarity_threshold=self.similarity_threshold,
                skipped_reason="embedding_client 为 None（未配置 EMBEDDING_API_KEY 等）",
            )

        # 1. 提取有效评论（需要有非空 content）
        valid_comments = [
            c for c in normalized_comments if c.content and c.content.strip()
        ]
        if len(valid_comments) < self.min_cluster_size:
            logger.warning(
                "CommentClusterAgent: 有效评论数 %d < min_cluster_size %d",
                len(valid_comments), self.min_cluster_size,
            )
            return CommentClusterResult(
                clusters=[],
                total_comments=len(normalized_comments),
                clustered_comments=0,
                noise_comments=len(normalized_comments),
                similarity_threshold=self.similarity_threshold,
                skipped_reason=f"有效评论数 {len(valid_comments)} < min_cluster_size {self.min_cluster_size}",
            )

        # 2. 调用 embedding
        logger.info(
            "CommentClusterAgent: 开始 embedding %d 条评论",
            len(valid_comments),
        )
        texts = [c.content.strip() for c in valid_comments]
        vectors = self.embedding_client.embed(texts)
        if vectors is None:
            logger.warning("CommentClusterAgent: embedding 返回 None，跳过聚类")
            return CommentClusterResult(
                clusters=[],
                total_comments=len(normalized_comments),
                clustered_comments=0,
                noise_comments=len(normalized_comments),
                similarity_threshold=self.similarity_threshold,
                skipped_reason="embedding API 返回 None（网络错误或超时）",
            )

        logger.info(
            "CommentClusterAgent: embedding 成功获取 %d 个向量",
            len(vectors),
        )

        if len(vectors) != len(valid_comments):
            logger.warning(
                "CommentClusterAgent: embedding 返回数量 %d 与输入 %d 不匹配",
                len(vectors), len(valid_comments),
            )
            return CommentClusterResult(
                clusters=[],
                total_comments=len(normalized_comments),
                clustered_comments=0,
                noise_comments=len(normalized_comments),
                similarity_threshold=self.similarity_threshold,
                skipped_reason=f"embedding 返回 {len(vectors)} 个向量，预期 {len(valid_comments)}",
            )

        # 3. L2 normalize vectors
        normalized_vectors = [_l2_normalize(v) for v in vectors]

        # 4. 计算 pairwise cosine similarity matrix
        n = len(normalized_vectors)
        similarity_matrix = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i == j:
                    similarity_matrix[i][j] = 1.0
                elif i < j:
                    sim = _cosine_similarity(normalized_vectors[i], normalized_vectors[j])
                    similarity_matrix[i][j] = sim
                    similarity_matrix[j][i] = sim

        # 5. Union-find 聚类
        clusters = _union_find_clusters(
            similarity_matrix, self.similarity_threshold, n
        )

        # 6. 过滤噪声
        non_noise_clusters = [
            c for c in clusters if len(c) >= self.min_cluster_size
        ]
        noise_indices = set()
        for c in clusters:
            if len(c) < self.min_cluster_size:
                for idx in c:
                    noise_indices.add(idx)

        clustered_indices = set()
        for c in non_noise_clusters:
            for idx in c:
                clustered_indices.add(idx)

        # 7. 构建 CommentClusterRecord 列表
        max_comment_count = max((len(c) for c in non_noise_clusters), default=0)
        max_comment_likes = 0
        cluster_likes_list = []
        for c in non_noise_clusters:
            total_likes = sum(valid_comments[idx].likes for idx in c)
            cluster_likes_list.append(total_likes)
            if total_likes > max_comment_likes:
                max_comment_likes = total_likes

        cluster_records = []
        for cluster_idx, cluster_indices in enumerate(non_noise_clusters):
            count = len(cluster_indices)
            total_likes = cluster_likes_list[cluster_idx]

            # 计算簇内平均 similarity
            intra_sims = []
            for i in cluster_indices:
                for j in cluster_indices:
                    if i < j:
                        intra_sims.append(similarity_matrix[i][j])
            avg_sim = sum(intra_sims) / len(intra_sims) if intra_sims else 0.0

            # 热点排序
            hotness = _compute_hotness(
                count, max_comment_count,
                total_likes, max_comment_likes,
                avg_sim,
            )

            # 主题命名
            cluster_comments = [valid_comments[idx] for idx in cluster_indices]
            topic, top_labels, keywords = _derive_topic(
                cluster_indices, valid_comments, annotations,
            )

            # 代表评论
            rep_texts, rep_ids = _pick_representative(
                cluster_indices, valid_comments, n=3,
            )

            record = CommentClusterRecord(
                cluster_id=f"cluster_{cluster_idx + 1:03d}",
                topic=topic,
                summary="",
                comment_count=count,
                total_comment_likes=total_likes,
                avg_similarity=avg_sim,
                hotness=hotness,
                keywords=keywords,
                top_labels=top_labels,
                evidence_comment_ids=rep_ids,
                representative_comments=rep_texts,
            )
            cluster_records.append(record)

        # 8. 按 hotness 降序排序，取 top_k
        cluster_records.sort(key=lambda r: r.hotness, reverse=True)
        cluster_records = cluster_records[:self.top_k]

        result = CommentClusterResult(
            clusters=cluster_records,
            total_comments=len(normalized_comments),
            clustered_comments=len(clustered_indices),
            noise_comments=len(noise_indices),
            algorithm="cosine_threshold_union_find",
            similarity_threshold=self.similarity_threshold,
        )

        logger.info(
            "CommentClusterAgent: 聚类完成 total=%d, clustered=%d, noise=%d, clusters=%d",
            result.total_comments, result.clustered_comments,
            result.noise_comments, len(result.clusters),
        )
        return result

    def execute_and_persist(
        self,
        paths: AppPaths,
        normalized_comments: list[CommentRecord],
        annotations: Optional[list[CommentAnnotationRecord]] = None,
    ) -> CommentClusterResult:
        """执行聚类并持久化到 outputs/comment_clusters.json。

        参数：
            paths: AppPaths 实例。
            normalized_comments: 标准化后的评论列表。
            annotations: 可选的 LLM 语义标注列表。

        返回：
            CommentClusterResult。
        """
        result = self.execute(normalized_comments, annotations)

        # 持久化
        output_path = paths.comment_clusters_file
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)

        logger.info("CommentClusterAgent: 已持久化到 %s", output_path)
        return result


# ===================================================================
# 内部数学函数
# ===================================================================


def _l2_normalize(v: list[float]) -> list[float]:
    """L2 归一化向量。"""
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0.0:
        return v
    return [x / norm for x in v]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个 L2 归一化向量的 cosine similarity。

    参数为已归一化向量，结果等价于 dot product。
    """
    if len(a) != len(b):
        return 0.0
    dot = sum(ai * bi for ai, bi in zip(a, b))
    # 由于已归一化，dot 应在 [-1, 1] 范围内
    return max(-1.0, min(1.0, dot))


# ===================================================================
# Union-Find 聚类
# ===================================================================


class _UnionFind:
    """Union-Find (Disjoint Set Union) 实现。"""

    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[ry] = rx


def _union_find_clusters(
    similarity_matrix: list[list[float]],
    threshold: float,
    n: int,
) -> list[list[int]]:
    """基于 similarity threshold 的 union-find 聚类。

    参数：
        similarity_matrix: n x n 的 cosine similarity 矩阵。
        threshold: 相似度阈值，高于此值的 pair 视为连通。
        n: 元素数量。

    返回：
        簇列表，每个簇为元素索引列表。
    """
    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if similarity_matrix[i][j] >= threshold:
                uf.union(i, j)

    # 收集每个 root 的成员
    root_to_members: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        if root not in root_to_members:
            root_to_members[root] = []
        root_to_members[root].append(i)

    return list(root_to_members.values())


# ===================================================================
# Hotness 计算
# ===================================================================


def _compute_hotness(
    count: int,
    max_count: int,
    likes: int,
    max_likes: int,
    avg_similarity: float,
) -> float:
    """计算聚类热度（归一化到 0~1 范围）。

    公式：
        norm_log_count = log1p(count) / log1p(max_count)
        norm_log_likes = log1p(likes) / log1p(max_likes)
        hotness = 0.5 * norm_log_count + 0.3 * norm_log_likes + 0.2 * avg_similarity

    边界处理：max_count<=0 时 norm=0，max_likes<=0 时 norm=0。
    """
    norm_log_count = 0.0
    if max_count > 0:
        norm_log_count = math.log1p(count) / math.log1p(max_count)

    norm_log_likes = 0.0
    if max_likes > 0:
        norm_log_likes = math.log1p(likes) / math.log1p(max_likes)

    hotness = (
        0.5 * norm_log_count
        + 0.3 * norm_log_likes
        + 0.2 * avg_similarity
    )
    return max(0.0, min(1.0, hotness))


# ===================================================================
# 主题命名
# ===================================================================


def _derive_topic(
    cluster_indices: list[int],
    comments: list[CommentRecord],
    annotations: Optional[list[CommentAnnotationRecord]] = None,
) -> tuple[str, list[str], list[str]]:
    """为聚类推导主题名称、top_labels 和 keywords。

    优先级：
    1. 从 annotation 统计高频标签
    2. 从评论文本抽高频词/bigram
    3. 回退到 "评论主题 cluster_XXX"

    参数：
        cluster_indices: 簇内的评论索引列表。
        comments: 完整的评论列表（与索引对应）。
        annotations: 可选的语义标注列表。

    返回：
        (topic: str, top_labels: list[str], keywords: list[str])
    """
    # 收集该簇的 comment_ids
    cluster_comment_ids = set()
    for idx in cluster_indices:
        if 0 <= idx < len(comments):
            cluster_comment_ids.add(comments[idx].comment_id)

    # 尝试从 annotations 提取标签
    top_labels: list[str] = []
    if annotations:
        label_counter: Counter[str] = Counter()
        for ann in annotations:
            if ann.comment_id in cluster_comment_ids:
                for label in ann.pain_point_labels:
                    label_counter[label] += 1
                for label in ann.need_labels:
                    label_counter[label] += 1
                for label in ann.complaint_labels:
                    label_counter[label] += 1
                for label in ann.solution_labels:
                    label_counter[label] += 1
                for label in ann.market_signal_labels:
                    label_counter[label] += 1
                for label in ann.intent_labels:
                    label_counter[label] += 1
        top_labels = [label for label, _ in label_counter.most_common(5)]

    # 从评论文本提取关键词
    keywords = _extract_keywords(cluster_indices, comments)

    # 构建 topic
    if top_labels:
        topic = " / ".join(top_labels[:3])
    elif keywords:
        topic = " ".join(keywords[:3])
    else:
        # 取第一条评论的前 30 字符作为主题
        first_idx = cluster_indices[0]
        if 0 <= first_idx < len(comments):
            first_text = comments[first_idx].content or ""
            topic = first_text[:30] + ("..." if len(first_text) > 30 else "")
        else:
            topic = "评论主题"

    return topic, top_labels, keywords


def _extract_keywords(
    cluster_indices: list[int],
    comments: list[CommentRecord],
    max_keywords: int = 5,
) -> list[str]:
    """从聚类评论中提取高频关键词。

    使用简单的分词（按标点和空格分割），统计频率。
    """
    word_counter: Counter[str] = Counter()

    for idx in cluster_indices:
        if 0 <= idx < len(comments):
            text = comments[idx].content or ""
            # 按标点、空格分割
            words = re.split(r'[\s,.!?;:()\-、，。！？；：　]', text)
            for w in words:
                w = w.strip()
                # 过滤过短或过长的词
                if 2 <= len(w) <= 20:
                    word_counter[w] += 1

    # 取 top 关键词
    keywords = [w for w, _ in word_counter.most_common(max_keywords)]
    return keywords


# ===================================================================
# 代表评论选取
# ===================================================================


def _pick_representative(
    cluster_indices: list[int],
    comments: list[CommentRecord],
    n: int = 3,
) -> tuple[list[str], list[str]]:
    """从聚类中选取代表性评论。

    按点赞数降序选取最多 n 条。

    参数：
        cluster_indices: 簇内评论索引。
        comments: 完整评论列表。
        n: 最多选取条数。

    返回：
        (texts: list[str], ids: list[str])
    """
    cluster_comments: list[tuple[int, CommentRecord]] = [
        (idx, comments[idx]) for idx in cluster_indices
        if 0 <= idx < len(comments)
    ]

    # 按点赞数降序
    cluster_comments.sort(key=lambda x: x[1].likes, reverse=True)

    texts: list[str] = []
    ids: list[str] = []
    for _, comment in cluster_comments[:n]:
        texts.append(comment.content or "")
        ids.append(comment.comment_id)

    return texts, ids
