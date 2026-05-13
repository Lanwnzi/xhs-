"""
小红书 Playwright 真实数据完整 Pipeline 入口。

采集 + 分析 + 评分 + 报告一次性完成，避免 raw 与 outputs 数据来源不一致。

使用方式：
    # 最小运行（1 条帖子，20 条评论）
    python scripts/run_xhs_playwright_pipeline.py --keyword 控油洗发水 --max-posts 1 --max-comments 20

    # 完整运行
    python scripts/run_xhs_playwright_pipeline.py --keyword 控油洗发水 \
        --product-direction "控油洗发水产品" \
        --industry-question "用户对控油洗发水的偏好和痛点" \
        --max-posts 3 --max-comments 30 --headless

环境要求：
    1. 首次使用需安装 Playwright：
       pip install playwright
       python -m playwright install chromium
    2. 登录态保存在 data/private/xhs_state.json。
       首次运行时会打开浏览器供用户手动登录。
    3. data/private/ 不会提交到 git。

产物：
    - data/raw/raw_posts.json
    - data/raw/raw_comments.json
    - data/normalized/normalized_posts.json
    - data/normalized/normalized_comments.json
    - data/outputs/insights.json
    - data/outputs/scorecard.json
    - data/outputs/report.html

注意：
    本脚本使用 XhsPlaywrightAdapter 进行真实采集，不是 mock 模式。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.adapters.xhs_collect_config import XhsCollectConfig
from src.adapters.xhs_playwright_adapter import XhsPlaywrightAdapter
from src.pipeline.pipeline import Pipeline
from src.schemas import AnalysisRequest
from src.utils import resolve_max_comments

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 可选参数列表，为 None 时使用 sys.argv[1:]。

    Returns:
        解析后的命名空间对象。
    """
    parser = argparse.ArgumentParser(
        description="小红书 Playwright 真实数据完整 Pipeline 入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例：
  python scripts/run_xhs_playwright_pipeline.py --keyword 控油洗发水 --max-posts 1 --max-comments 20

注意：
  本脚本使用 XhsPlaywrightAdapter 进行真实采集，不是 mock 模式。
  登录态保存在 data/private/xhs_state.json，首次运行会打开浏览器供手动登录。
        """,
    )
    parser.add_argument("--keyword", required=True, help="搜索关键词（必填）")
    parser.add_argument("--product-direction", default="", help="产品方向（可选，默认使用 keyword）")
    parser.add_argument("--industry-question", default="", help="行业问题（可选，默认根据 keyword 生成）")
    parser.add_argument("--max-posts", type=int, default=3, help="最大采集帖子数（默认 3）")
    parser.add_argument("--max-comments", type=int, default=None, help="每帖最大评论数（默认 20）")
    parser.add_argument("--max-comments-per-post", type=int, default=None, help="max-comments 的别名，同时出现时以此为准（默认 20）")
    parser.add_argument("--headless", action="store_true", help="无头模式（默认 False）")
    parser.add_argument("--output-sample", default="", help="输出样本名称（仅适配器侧使用，不影响 pipeline 产物路径）")
    parser.add_argument("--request-interval-seconds", type=float, default=3.0, help="采集间隔秒数（默认 3.0）")
    return parser.parse_args(argv)



def main():
    """主入口：解析参数，构造适配器，运行 Pipeline。"""
    args = parse_args()

    keyword = args.keyword
    product_direction = args.product_direction or keyword
    industry_question = args.industry_question or f"分析 {keyword} 的用户需求、痛点、反馈和市场机会"
    max_comments = resolve_max_comments(args.max_comments, args.max_comments_per_post, default=20)

    logger.info("=" * 60)
    logger.info("XhsPlaywrightAdapter 真实数据 Pipeline 开始")
    logger.info("  关键词: %s", keyword)
    logger.info("  产品方向: %s", product_direction)
    logger.info("  最大帖子: %d", args.max_posts)
    logger.info("  每帖最大评论: %d", max_comments)
    logger.info("  headless: %s", args.headless)
    logger.info("  注意: 使用真实 XhsPlaywrightAdapter 采集，不是 mock 模式")
    logger.info("=" * 60)

    # 构造适配器和配置
    config = XhsCollectConfig(
        keyword=keyword,
        max_posts=args.max_posts,
        max_comments_per_post=max_comments,
        headless=args.headless,
        request_interval_seconds=args.request_interval_seconds,
        output_sample_name=args.output_sample,
    )

    adapter = XhsPlaywrightAdapter(config=config)

    # 构造请求
    request = AnalysisRequest(
        topic=keyword,
        product_direction=product_direction,
        industry_question=industry_question,
    )

    # 运行 Pipeline（注入 adapter，非默认 mock）
    pipeline = Pipeline(adapter=adapter)
    result = pipeline.run(request)

    if result.success:
        logger.info("=" * 60)
        logger.info("完整闭环完成！")
        logger.info("  raw_posts: %s", result.raw_posts_path)
        logger.info("  raw_comments: %s", result.raw_comments_path)
        logger.info("  normalized_posts: %s", result.normalized_posts_path)
        logger.info("  normalized_comments: %s", result.normalized_comments_path)
        logger.info("  insights: %s", result.insights_path)
        logger.info("  scorecard: %s", result.scorecard_path)
        logger.info("  report: %s", result.report_path)
        logger.info("=" * 60)
        print(f"\n完整闭环完成！产物已生成到 data/ 目录。")
        print(f"运行以下命令验证产物完整性：")
        print(f"  python scripts/acceptance_check.py")
        sys.exit(0)
    else:
        logger.error("完整闭环失败: %s", result.error_message)
        sys.exit(1)


if __name__ == "__main__":
    main()
