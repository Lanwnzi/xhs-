"""
小红书 Playwright 实时采集入口（仅采集，用于调试）。

用法：
    python scripts/run_xhs_playwright_collect.py --keyword "控油洗发水" [选项]

注意：
    - 本脚本仅执行采集步骤，不进行分析、评分和报告生成。
    - 正式完整分析请使用 run_xhs_playwright_pipeline.py：
        python scripts/run_xhs_playwright_pipeline.py --keyword "控油洗发水" --max-posts 3 --max-comments 30
    - 首次使用需要执行 playwright install chromium
    - data/private/xhs_state.json 保存登录态，首次需手动登录
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.adapters.xhs_collect_config import XhsCollectConfig
from src.adapters.xhs_playwright_adapter import XhsPlaywrightAdapter
from src.schemas import AnalysisRequest
from src.utils import get_app_paths

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="小红书 Playwright 实时采集")
    parser.add_argument("--keyword", required=True, help="搜索关键词")
    parser.add_argument("--max-posts", type=int, default=20, help="最大采集帖子数")
    parser.add_argument("--max-comments", type=int, default=30, help="每帖最大评论数")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    parser.add_argument("--output-sample", default="", help="输出样本名称")
    return parser.parse_args()


def main():
    args = parse_args()
    logger.info("=" * 50)
    logger.info("XhsPlaywrightAdapter 采集开始")
    logger.info("  关键词: %s", args.keyword)
    logger.info("  最大帖子: %d", args.max_posts)
    logger.info("  每帖最大评论: %d", args.max_comments)
    logger.info("  headless: %s", args.headless)
    logger.info("=" * 50)

    config = XhsCollectConfig(
        keyword=args.keyword,
        max_posts=args.max_posts,
        max_comments_per_post=args.max_comments,
        headless=args.headless,
        output_sample_name=args.output_sample,
    )

    adapter = XhsPlaywrightAdapter(config=config)

    # 采集帖子
    posts = adapter.fetch_posts(keyword=args.keyword, max_count=args.max_posts)
    logger.info("采集到 %d 条帖子", len(posts))

    # 采集评论
    all_comments: list[dict] = []
    for post in posts:
        post_id = post.get("post_id", "")
        if post_id:
            comments = adapter.fetch_comments(post_id=post_id, max_count=args.max_comments)
            all_comments.extend(comments)
            logger.info("  帖子 %s: %d 条评论", post_id, len(comments))

    logger.info("共采集 %d 条帖子, %d 条评论", len(posts), len(all_comments))

    # 保存到 data/raw/
    import json
    paths = get_app_paths()
    os.makedirs(paths.raw_dir, exist_ok=True)
    with open(paths.raw_posts_file, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    with open(paths.raw_comments_file, "w", encoding="utf-8") as f:
        json.dump(all_comments, f, ensure_ascii=False, indent=2)

    logger.info("原始数据已保存到 %s", paths.raw_dir)
    logger.info("采集完成")


if __name__ == "__main__":
    main()
