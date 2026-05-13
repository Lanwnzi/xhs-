"""SourceAgent - 从本地 JSON 文件或平台适配器读取原始数据。

输入：AnalysisRequest（topic 指定搜索主题）
输出：RawDataset（已校验的 Pydantic 模型）

使用方式：
    # 方式一：从 adapter 读取真实数据
    adapter = XhsImportAdapter("data/raw/xhs_export.json")
    agent = SourceAgent(adapter=adapter)
    raw = agent.execute(request)

    # 方式二：读取 mock JSON 文件（默认）
    agent = SourceAgent()
    raw = agent.execute(request)

边界约束：
    - SourceAgent 不做分析、总结或内容加工。
    - 它只负责采集和组装数据。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from src.adapters.base import BaseAdapter
from src.schemas import AnalysisRequest, CommentRecord, PostRecord, RawDataset
from src.utils import AppPaths, get_app_paths

logger = logging.getLogger(__name__)


class SourceAgent:
    """负责采集原始 UGC 数据的 Agent。

    接收可选的 adapter 参数。有 adapter 时从 adapter 获取数据，
    否则从本地 mock JSON 文件读取。

    参数:
        adapter: 平台适配器（可选）。
        paths: AppPaths 实例，用于定位 mock 文件。为 None 时使用全局默认路径。
    """

    def __init__(
        self,
        adapter: Optional[BaseAdapter] = None,
        paths: Optional[AppPaths] = None,
    ):
        self._adapter = adapter
        self._paths = paths

    def execute(self, request: AnalysisRequest) -> RawDataset:
        """采集数据并返回校验后的 RawDataset。

        不做持久化，由调用方（node）负责持久化。

        参数：
            request: AnalysisRequest（topic 用于 adapter 搜索关键词）。

        返回：
            包含已校验 PostRecord / CommentRecord 的 RawDataset。
        """
        if self._adapter is not None:
            return self._execute_with_adapter(request)
        return self._execute_with_mock_files()

    # ------------------------------------------------------------------
    # Adapter 模式
    # ------------------------------------------------------------------

    def _execute_with_adapter(self, request: AnalysisRequest) -> RawDataset:
        """使用 adapter 采集真实数据。"""
        adapter = self._adapter  # type: ignore[assignment]
        keyword = request.topic

        logger.info("SourceAgent: 使用 adapter %s 搜索: %s", type(adapter).__name__, keyword)

        raw_posts = adapter.fetch_posts(keyword=keyword)
        raw_comments: list[dict] = []

        # 为每条帖子拉取评论
        for post in raw_posts:
            post_id = post.get("post_id", "")
            if post_id:
                try:
                    cmts = adapter.fetch_comments(post_id=post_id)
                    raw_comments.extend(cmts)
                except Exception:
                    logger.warning("SourceAgent: 获取评论失败 post_id=%s", post_id, exc_info=True)

        return self._assemble(raw_posts, raw_comments)

    # ------------------------------------------------------------------
    # Mock 文件模式
    # ------------------------------------------------------------------

    def _execute_with_mock_files(self) -> RawDataset:
        """从 mock JSON 文件读取数据。"""
        raw_posts, raw_comments = self._load_files()
        return self._assemble(raw_posts, raw_comments)

    def _load_files(self) -> tuple[list[dict], list[dict]]:
        """从 data/raw/ 加载原始 JSON 文件。

        抛出：
            FileNotFoundError: 若任一文件缺失。
        """
        paths = self._paths or get_app_paths()
        files = [
            ("帖子", paths.raw_posts_file),
            ("评论", paths.raw_comments_file),
        ]
        for name, path in files:
            if not os.path.exists(path):
                raise FileNotFoundError(f"SourceAgent: {name}文件不存在: {path}")

        with open(paths.raw_posts_file, encoding="utf-8") as f:
            raw_posts: list[dict] = json.load(f)
        with open(paths.raw_comments_file, encoding="utf-8") as f:
            raw_comments: list[dict] = json.load(f)

        logger.info(
            "SourceAgent: 从 %s 加载 %d 条帖子, %d 条评论",
            paths.raw_dir, len(raw_posts), len(raw_comments),
        )
        return raw_posts, raw_comments

    # ------------------------------------------------------------------
    # 数据组装
    # ------------------------------------------------------------------

    @staticmethod
    def _assemble(raw_posts: list[dict], raw_comments: list[dict]) -> RawDataset:
        """将字典校验为 Pydantic 模型，构建 RawDataset。"""
        posts = [PostRecord(**p) for p in raw_posts]
        comments = [CommentRecord(**c) for c in raw_comments]
        return RawDataset(posts=posts, comments=comments)

