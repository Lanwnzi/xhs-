"""小红书本地导入适配器。

从本地 JSON/CSV 文件读取人工整理或手动导出的公开小红书样本数据，
映射为 PostRecord / CommentRecord 兼容的字典格式，供 SourceAgent 消费。

本适配器不处理 cookie、不做逆向签名、不调用真实平台接口。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from src.adapters.base import BaseAdapter
from src.utils import get_app_paths

logger = logging.getLogger(__name__)

# XHS JSON 导出文件中使用的字段名 → PostRecord 字段名的映射
_POST_FIELD_MAP: dict[str, str] = {
    "note_id": "post_id",
    "id": "post_id",
    "title": "title",
    "desc": "content",
    "description": "content",
    "content": "content",
    "time": "publish_time",
    "create_time": "publish_time",
    "liked_count": "likes",
    "likes": "likes",
    "comment_count": "comments",
    "comments_count": "comments",
    "collected_count": "favorites",
    "collected": "favorites",
    "share_count": "shares",
    "share": "shares",
    "url": "url",
    "note_url": "url",
    "tag_list": "tags",
    "tags": "tags",
    "user": "author",
    "nickname": "author",
    "author": "author",
}

_COMMENT_FIELD_MAP: dict[str, str] = {
    "id": "comment_id",
    "comment_id": "comment_id",
    "note_id": "post_id",
    "post_id": "post_id",
    "content": "content",
    "text": "content",
    "time": "publish_time",
    "create_time": "publish_time",
    "like_count": "likes",
    "likes": "likes",
    "user": "author",
    "nickname": "author",
    "author": "author",
    "parent_comment_id": "parent_comment_id",
    "target_comment_id": "parent_comment_id",
}


def _map_fields(raw: dict[str, Any], field_map: dict[str, str]) -> dict[str, Any]:
    """将原始字典的字段名映射为统一字段名。

    只保留 field_map 中存在的字段，忽略未知字段。
    """
    result: dict[str, Any] = {}
    for raw_key, mapped_key in field_map.items():
        if raw_key in raw:
            result[mapped_key] = raw[raw_key]
    # 补上 platform 字段
    result.setdefault("platform", "xhs")
    return result


def _normalize_xhs_time(value: Any) -> str:
    """将 XHS 多种时间格式统一为 ISO 8601。"""
    if isinstance(value, (int, float)):
        # Unix 时间戳
        dt = datetime.fromtimestamp(value)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, str):
        value = value.strip()
        # 已经是 ISO 格式
        if "T" in value or len(value) >= 16:
            return value
        # 纯数字字符串（时间戳）
        if value.isdigit() or (value.startswith("1") and "." in value):
            try:
                dt = datetime.fromtimestamp(float(value))
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
            except (ValueError, OSError):
                pass
    return str(value) if value else ""


class XhsImportAdapter(BaseAdapter):
    """从本地导入文件读取小红书数据的适配器。

    使用方式：
        adapter = XhsImportAdapter(source_path="data/raw/xhs_export.json")
        posts = adapter.fetch_posts(keyword="控油洗发水")
        comments = adapter.fetch_comments(post_id="xhs_sample_001")

    导入 JSON 文件格式支持以下两种结构：
    1. 包含 "posts" 和 "comments" 两个顶级键的对象
    2. 纯数组（帖子列表），评论由单独的 JSON 文件提供
    """

    def __init__(self, source_path: str = ""):
        self._source_path = source_path or os.path.join(
            get_app_paths().raw_dir, "xhs_export.json"
        )
        self._cache: dict[str, Any] = {}  # 避免重复读取

    def fetch_posts(self, keyword: str = "", max_count: int = 20) -> list[dict]:
        """按关键词搜索帖子，返回已映射字段的字典列表。

        从本地 JSON 读取全部帖子，按关键词做简单标题/内容过滤。
        keyword 为空时返回全部帖子。
        """
        all_posts = self._get_cached("posts")
        if not keyword:
            return all_posts[:max_count]
        keyword_lower = keyword.lower()
        matched = []
        for p in all_posts:
            title = (p.get("title") or "").lower()
            content = (p.get("content") or "").lower()
            if keyword_lower in title or keyword_lower in content:
                matched.append(p)
                if len(matched) >= max_count:
                    break
        logger.info("XHS import: 关键词 '%s' 匹配 %d/%d 条帖子", keyword, len(matched), len(all_posts))
        return matched

    def fetch_comments(self, post_id: str = "", max_count: int = 50) -> list[dict]:
        """按帖子 ID 获取评论，返回已映射字段的字典列表。"""
        all_comments = self._get_cached("comments")
        if not post_id:
            return all_comments[:max_count]
        matched = [c for c in all_comments if c.get("post_id") == post_id][:max_count]
        return matched

    def read_posts(self) -> list[dict]:
        """（保留）读取全部帖子，返回已映射字段的字典列表。"""
        return self._get_cached("posts")

    def read_comments(self) -> list[dict]:
        """（保留）读取全部评论，返回已映射字段的字典列表。"""
        return self._get_cached("comments")

    def _get_cached(self, key: str) -> list[dict]:
        """带缓存的 JSON 解析 + 字段映射。"""
        if key not in self._cache:
            data = self._load_json()
            if key == "posts":
                self._cache["posts"] = self._parse_posts(data)
            else:
                self._cache["comments"] = self._parse_comments(data)
        return self._cache[key]

    # ------------------------------------------------------------------
    # 内部解析
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_posts(data: Any) -> list[dict]:
        """从 JSON 数据中解析帖子列表。"""
        raw_posts: list[dict] = []
        if isinstance(data, dict):
            raw_posts = data.get("posts", data.get("items", []))
        elif isinstance(data, list):
            raw_posts = data
        else:
            return []

        result = []
        for i, raw in enumerate(raw_posts):
            mapped = _map_fields(raw, _POST_FIELD_MAP)
            if "publish_time" in mapped:
                mapped["publish_time"] = _normalize_xhs_time(mapped["publish_time"])
            if isinstance(mapped.get("tags"), str):
                mapped["tags"] = [t.strip() for t in mapped["tags"].split(",") if t.strip()]
            mapped.setdefault("post_id", f"xhs_import_{i}")
            result.append(mapped)

        logger.info("XHS import: 解析 %d 条帖子", len(result))
        return result

    @staticmethod
    def _parse_comments(data: Any) -> list[dict]:
        """从 JSON 数据中解析评论列表。"""
        raw_comments: list[dict] = []
        if isinstance(data, dict):
            raw_comments = data.get("comments", [])
        elif isinstance(data, list):
            return []
        else:
            return []

        result = []
        for i, raw in enumerate(raw_comments):
            mapped = _map_fields(raw, _COMMENT_FIELD_MAP)
            if "publish_time" in mapped:
                mapped["publish_time"] = _normalize_xhs_time(mapped["publish_time"])
            mapped.setdefault("comment_id", f"xhs_cmt_import_{i}")
            result.append(mapped)

        logger.info("XHS import: 解析 %d 条评论", len(result))
        return result

    def _load_json(self) -> Any:
        """从 source_path 加载 JSON 文件。"""
        path = self._source_path
        if not os.path.exists(path):
            logger.warning("XHS import: 文件不存在 %s，返回空数据", path)
            return {}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        logger.info("XHS import: 从 %s 加载完成", path)
        return data
