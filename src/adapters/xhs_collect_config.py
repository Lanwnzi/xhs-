"""
小红书 Playwright 采集的配置模型。

所有配置项都有默认值，用户可按需覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class XhsCollectConfig:
    """小红书 Playwright 采集配置。"""

    # 搜索关键词（必填）
    keyword: str = ""

    # 扩展主题词（可选）
    topic_words: list[str] = field(default_factory=list)

    # 采集上限
    max_posts: int = 20
    max_comments_per_post: int = 30

    # 互动量过滤（低于阈值的笔记跳过）
    min_likes: int = 0
    min_comments: int = 0
    min_favorites: int = 0

    # 时间过滤（仅采集指定天数内的笔记，0 表示不限）
    within_days: int = 0

    # 浏览器设置
    headless: bool = False

    # 访问间隔（秒）
    request_interval_seconds: float = 3.0

    # 搜索结果滚动轮数
    scroll_rounds: int = 5

    # 登录态保存路径
    state_path: str = ""

    # 输出样本名称（用于将采集结果组织到对应样本目录）
    output_sample_name: str = ""

    def __post_init__(self):
        if self.state_path == "":
            # 默认保存到 data/private/xhs_state.json
            import os
            self.state_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data", "private", "xhs_state.json"
            )
