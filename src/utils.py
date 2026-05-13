"""UGC Market Validator 的共享工具函数。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def resolve_max_comments(
    max_comments: int | None = None,
    max_comments_per_post: int | None = None,
    default: int = 20,
) -> int:
    """解析 max_comments 参数。

    优先级：
    1. max_comments_per_post（不为 None 时）
    2. max_comments（不为 None 时）
    3. default

    Args:
        max_comments: --max-comments 参数值。
        max_comments_per_post: --max-comments-per-post 参数值（优先级更高）。
        default: 两者均为空时的默认值。

    Returns:
        解析后的最大评论数。
    """
    if max_comments_per_post is not None:
        return max_comments_per_post
    if max_comments is not None:
        return max_comments
    return default


def find_project_root() -> str:
    """从当前文件所在目录向上遍历，直到找到项目根目录。

    项目根目录的判断依据是同时包含 src/ 和 data/ 目录。
    如果向上遍历 10 层仍未找到，则抛出 RuntimeError 异常。
    """
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(10):  # 安全上限
        if os.path.isdir(os.path.join(current, "src")) and os.path.isdir(
            os.path.join(current, "data")
        ):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    raise RuntimeError(
        "Could not determine project root: no parent directory contains both src/ and data/"
    )


@dataclass
class AppPaths:
    """统一路径配置，集中管理所有产物路径。

    模块首次调用 get_app_paths() 时计算一次并缓存，
    避免重复调用 find_project_root()。
    """

    project_root: str
    raw_dir: str
    normalized_dir: str
    outputs_dir: str
    raw_posts_file: str
    raw_comments_file: str
    normalized_posts_file: str
    normalized_comments_file: str
    insights_file: str
    scorecard_file: str
    report_file: str
    comment_clusters_file: str = ""

    @classmethod
    def create(cls) -> AppPaths:
        """扫描项目结构并构建完整路径集合。"""
        root = find_project_root()
        raw_dir = os.path.join(root, "data", "raw")
        normalized_dir = os.path.join(root, "data", "normalized")
        outputs_dir = os.path.join(root, "data", "outputs")
        return cls(
            project_root=root,
            raw_dir=raw_dir,
            normalized_dir=normalized_dir,
            outputs_dir=outputs_dir,
            raw_posts_file=os.path.join(raw_dir, "raw_posts.json"),
            raw_comments_file=os.path.join(raw_dir, "raw_comments.json"),
            normalized_posts_file=os.path.join(normalized_dir, "normalized_posts.json"),
            normalized_comments_file=os.path.join(normalized_dir, "normalized_comments.json"),
            insights_file=os.path.join(outputs_dir, "insights.json"),
            scorecard_file=os.path.join(outputs_dir, "scorecard.json"),
            report_file=os.path.join(outputs_dir, "report.html"),
            comment_clusters_file=os.path.join(outputs_dir, "comment_clusters.json"),
        )

    @classmethod
    def from_data_root(cls, data_root: str) -> AppPaths:
        """从自定义数据根目录构造 AppPaths。

        data_root 可以是 data/ 或 data/experiments/oil_control_shampoo 等。
        """
        data_root = data_root.rstrip("/\\")
        # 判断 data_root 是否在 project_root 内部，以 project_root 为基准
        # 如果包含 "experiments"，则 project_root 为上一级的上一级
        # 否则 project_root 为 data_root 自身
        normalized = data_root.replace("\\", "/")
        if "/experiments/" in normalized:
            project_root = os.path.dirname(os.path.dirname(data_root))
        else:
            project_root = data_root
        return cls(
            project_root=project_root,
            raw_dir=os.path.join(data_root, "raw"),
            normalized_dir=os.path.join(data_root, "normalized"),
            outputs_dir=os.path.join(data_root, "outputs"),
            raw_posts_file=os.path.join(data_root, "raw", "raw_posts.json"),
            raw_comments_file=os.path.join(data_root, "raw", "raw_comments.json"),
            normalized_posts_file=os.path.join(data_root, "normalized", "normalized_posts.json"),
            normalized_comments_file=os.path.join(data_root, "normalized", "normalized_comments.json"),
            insights_file=os.path.join(data_root, "outputs", "insights.json"),
            scorecard_file=os.path.join(data_root, "outputs", "scorecard.json"),
            report_file=os.path.join(data_root, "outputs", "report.html"),
            comment_clusters_file=os.path.join(data_root, "outputs", "comment_clusters.json"),
        )


_PATHS: Optional[AppPaths] = None


def get_app_paths() -> AppPaths:
    """返回全局共享的 AppPaths 单例。"""
    global _PATHS
    if _PATHS is None:
        _PATHS = AppPaths.create()
    return _PATHS
