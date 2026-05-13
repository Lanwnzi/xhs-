"""平台适配器基类接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseAdapter(ABC):
    """平台采集适配器的抽象基类。

    所有平台适配器（小红书、Reddit 等）必须实现此接口。
    """

    @abstractmethod
    def fetch_posts(self, keyword: str, max_count: int = 20) -> list[dict]:
        """按关键词搜索帖子，返回原始字典列表。

        返回的字典应包含 PostRecord 所需字段的子集，
        由 SourceAgent 统一校验和组装。
        """

    @abstractmethod
    def fetch_comments(self, post_id: str, max_count: int = 50) -> list[dict]:
        """按帖子 ID 获取评论，返回原始字典列表。

        返回的字典应包含 CommentRecord 所需字段的子集。
        """
