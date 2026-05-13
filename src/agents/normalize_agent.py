"""
NormalizeAgent - 标准化原始 UGC 数据。

输入:  RawDataset
输出: NormalizedDataset

执行的操作:
  1. 去除内容字段首尾空白。
  2. 移除去除空白后内容为空的记录。
  3. 按 ID 对帖子和评论去重（保留首次出现）。
  4. 将 publish_time 标准化为 ISO 8601 格式（YYYY-MM-DDTHH:MM:SS）。

边界约束:
  - NormalizeAgent 不进行洞察提取、情感分析、评分或市场结论。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Set

from src.schemas import CommentRecord, NormalizedDataset, PostRecord, RawDataset

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

_ISO_DATETIME_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
)



class NormalizeAgent:
    """负责清洗和标准化原始 UGC 数据的 Agent。

    不做持久化，由调用方（node）负责持久化。
    """

    def execute(self, dataset: RawDataset) -> NormalizedDataset:
        """清洗、去重并标准化原始数据集。

        不做持久化，由调用方（node）负责持久化。

        参数:
            dataset: 包含帖子和评论的 RawDataset。

        返回:
            包含已清洗记录的 NormalizedDataset。

        抛出:
            若清洗后负载为空则抛出 ValueError。
        """
        posts = self._clean_posts(dataset.posts)
        comments = self._clean_comments(dataset.comments)
        comments = self._link_comments_to_posts(comments, posts)

        normalized = NormalizedDataset(posts=posts, comments=comments)

        if not normalized.posts and not normalized.comments:
            raise ValueError(
                "NormalizeAgent: all records were empty after cleaning"
            )

        return normalized

    # ------------------------------------------------------------------
    # 清洗辅助方法
    # ------------------------------------------------------------------

    def _clean_posts(self, posts: list[PostRecord]) -> list[PostRecord]:
        """清洗并去重帖子。"""
        seen: Set[str] = set()
        cleaned: list[PostRecord] = []

        for post in posts:
            # 去除内容首尾空白
            stripped = post.content.strip() if post.content else ""
            if not stripped:
                logger.debug("Skipping post %s: empty content", post.post_id)
                continue

            # 去重
            if post.post_id in seen:
                logger.debug("Skipping duplicate post %s", post.post_id)
                continue
            seen.add(post.post_id)

            # 标准化时间
            normalized_time = self._normalize_time(post.publish_time)

            cleaned.append(
                PostRecord(
                    platform=post.platform,
                    post_id=post.post_id,
                    title=post.title.strip() if post.title else "",
                    content=stripped,
                    author=post.author.strip() if post.author else "",
                    publish_time=normalized_time,
                    likes=post.likes,
                    comments=post.comments,
                    favorites=post.favorites,
                    shares=post.shares,
                    url=post.url.strip() if post.url else "",
                    tags=post.tags,
                )
            )

        logger.info("Cleaned posts: %d kept, %d removed", len(cleaned), len(posts) - len(cleaned))
        return cleaned

    def _clean_comments(self, comments: list[CommentRecord]) -> list[CommentRecord]:
        """清洗并去重评论。"""
        seen: Set[str] = set()
        cleaned: list[CommentRecord] = []

        for comment in comments:
            # 去除内容首尾空白
            stripped = comment.content.strip() if comment.content else ""
            if not stripped:
                logger.debug("Skipping comment %s: empty content", comment.comment_id)
                continue

            # 去重
            if comment.comment_id in seen:
                logger.debug("Skipping duplicate comment %s", comment.comment_id)
                continue
            seen.add(comment.comment_id)

            # 标准化时间
            normalized_time = self._normalize_time(comment.publish_time)

            cleaned.append(
                CommentRecord(
                    platform=comment.platform,
                    comment_id=comment.comment_id,
                    post_id=comment.post_id,
                    content=stripped,
                    author=comment.author.strip() if comment.author else "",
                    publish_time=normalized_time,
                    likes=comment.likes,
                    parent_comment_id=comment.parent_comment_id,
                )
            )

        logger.info(
            "Cleaned comments: %d kept, %d removed",
            len(cleaned),
            len(comments) - len(cleaned),
        )
        return cleaned

    @staticmethod
    def _link_comments_to_posts(
        comments: list[CommentRecord],
        posts: list[PostRecord],
    ) -> list[CommentRecord]:
        """移除 post_id 不匹配任何剩余帖子的评论。"""
        valid_post_ids = {p.post_id for p in posts}
        linked = [c for c in comments if c.post_id in valid_post_ids]
        orphaned = len(comments) - len(linked)
        if orphaned:
            logger.warning("Removed %d orphaned comments (no matching post)", orphaned)
        return linked

    # ------------------------------------------------------------------
    # 时间标准化
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_time(raw: str) -> str:
        """尝试将原始时间转换为 ISO 8601 格式 YYYY-MM-DDTHH:MM:SS。

        支持的输入格式（可扩展）:
          - YYYY-MM-DDTHH:MM:SS           （已是合法格式）
          - YYYY-MM-DD HH:MM:SS           （空格分隔）
          - YYYY/MM/DD HH:MM:SS
          - YYYY年MM月DD日 HH:MM
          - Unix 时间戳（浮点数 / 整数）
          - MM-DD地区（如 "03-25广东"）     （XHS 评论常见格式，补当年年份）
          - "昨天 HH:MM地区"              （XHS 评论相对时间）
          - YYYY-MM-DD（仅日期）

        若没有匹配任何格式，则原样返回原始字符串。
        """
        if not raw or not raw.strip():
            return raw

        text = raw.strip()

        # 已是 ISO 8601 格式
        if _ISO_DATETIME_PATTERN.match(text):
            return text

        # 尝试常见格式
        patterns = [
            ("%Y-%m-%d %H:%M:%S", r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"),
            ("%Y/%m/%d %H:%M:%S", r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}"),
            ("%Y-%m-%d %H:%M", r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}"),
            ("%Y/%m/%d %H:%M", r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}"),
        ]

        for fmt, pattern in patterns:
            if re.match(pattern, text):
                try:
                    dt = datetime.strptime(text, fmt)
                    return dt.strftime("%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    continue

        # 尝试数值时间戳
        try:
            ts = float(text)
            dt = datetime.fromtimestamp(ts)
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except (ValueError, OSError):
            pass

        # XHS 评论格式: "MM-DD地区" (如 "03-25广东")
        # 去掉末尾中文地区后缀后按 MM-DD 解析，补当年年份
        m = re.match(r"^(\d{2})-(\d{2})", text)
        if m:
            try:
                now = datetime.now()
                dt = datetime(now.year, int(m.group(1)), int(m.group(2)))
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                pass

        # XHS 评论格式: "昨天 HH:MM地区"
        if "昨天" in text:
            try:
                now = datetime.now()
                # 提取时间部分
                time_match = re.search(r"(\d{2}):(\d{2})", text)
                if time_match:
                    from datetime import timedelta
                    yesterday = now - timedelta(days=1)
                    dt = yesterday.replace(hour=int(time_match.group(1)), minute=int(time_match.group(2)), second=0, microsecond=0)
                    return dt.strftime("%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                pass

        # YYYY-MM-DD 纯日期
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
        if m:
            try:
                dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                pass

        logger.warning("Unable to parse time '%s', returning as-is", raw)
        return raw

