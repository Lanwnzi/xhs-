"""
LangGraph 版本：真实小红书采集 + LLM annotation 一体化入口。

一条命令完成：
  真实小红书 Playwright 采集
  -> LangGraph collect
  -> normalize
  -> (LLM comment annotation | rule sentiment + insight)
  -> score
  -> report

用法：
    # rule 模式（默认，不需要 LLM）
    python scripts/run_langgraph_xhs_playwright_pipeline.py --keyword 控油洗发水 --max-posts 1

    # LLM annotation 模式（需要 .env 或环境变量）
    python scripts/run_langgraph_xhs_playwright_pipeline.py --keyword 控油洗发水 \
        --analysis-mode llm_annotation --max-posts 1 --max-comments 20

    # LLM annotation + mock LLM（离线测试）
    python scripts/run_langgraph_xhs_playwright_pipeline.py --keyword 控油洗发水 \
        --analysis-mode llm_annotation --mock-llm

环境要求：
    - 首次使用 Playwright 需执行：pip install playwright && python -m playwright install chromium
    - LLM 模式需配置 .env：参考 .env.example
    - 登录态保存在 data/private/xhs_state.json

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
from src.graph.graph import build_ugc_market_graph
from src.graph.state import UGCGraphState
from src.llm.client import MockLLMClient, OpenAICompatLLMClient
from src.schemas import AnalysisRequest
from src.utils import get_app_paths, resolve_max_comments

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
        description="LangGraph 版本：真实小红书采集 + LLM annotation 一体化入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例：
  python scripts/run_langgraph_xhs_playwright_pipeline.py --keyword 控油洗发水 --max-posts 1
  python scripts/run_langgraph_xhs_playwright_pipeline.py --keyword 控油洗发水 \\
      --analysis-mode llm_annotation --mock-llm --max-posts 1

注意：
  本脚本使用 XhsPlaywrightAdapter 进行真实采集，不是 mock 模式。
  登录态保存在 data/private/xhs_state.json，首次运行会打开浏览器供手动登录。
        """,
    )
    parser.add_argument("--keyword", required=True, help="搜索关键词（必填）")
    parser.add_argument("--max-posts", type=int, default=3, help="最大采集帖子数（默认 3）")
    parser.add_argument("--max-comments", type=int, default=None, help="每帖最大评论数（默认 20）")
    parser.add_argument("--max-comments-per-post", type=int, default=None, help="max-comments 的别名，优先级更高（默认 20）")
    parser.add_argument(
        "--analysis-mode",
        default="rule",
        choices=["rule", "llm_annotation"],
        help="分析模式：rule（规则，不需要 LLM）或 llm_annotation（LLM 语义标注，需要 LLM 环境变量）",
    )
    parser.add_argument("--mock-llm", action="store_true", help="使用 MockLLMClient（离线测试用，不访问真实 API）")
    parser.add_argument("--headless", action="store_true", help="无头模式（默认 False）")
    parser.add_argument("--request-interval-seconds", type=float, default=3.0, help="采集间隔秒数（默认 3.0）")
    parser.add_argument("--output-sample", default="", help="输出样本名称（仅适配器侧使用，不影响 pipeline 产物路径）")
    return parser.parse_args(argv)


def _validate_env_for_llm() -> None:
    """在启动 Playwright 前验证 LLM 环境变量。

    如果缺少必需变量，提前报错退出，提示用户配置 .env。
    """
    missing = []
    if not os.getenv("LLM_BASE_URL"):
        missing.append("LLM_BASE_URL")
    if not os.getenv("LLM_API_KEY"):
        missing.append("LLM_API_KEY")
    if not os.getenv("LLM_MODEL"):
        missing.append("LLM_MODEL")
    if missing:
        print("=" * 60)
        print("错误：缺少 LLM 环境变量")
        print(f"  缺少: {', '.join(missing)}")
        print()
        print("请配置 .env 文件（参考 .env.example）：")
        print("  LLM_BASE_URL=https://api.openai.com/v1")
        print("  LLM_API_KEY=your_api_key_here")
        print("  LLM_MODEL=gpt-4o-mini")
        print()
        print("或使用 --mock-llm 运行离线测试模式。")
        print("=" * 60)
        sys.exit(1)


def main():
    """主入口：解析参数，构造适配器，运行 LangGraph pipeline。"""
    args = parse_args()
    keyword = args.keyword
    max_comments = resolve_max_comments(args.max_comments, args.max_comments_per_post, default=20)
    paths = get_app_paths()

    logger.info("=" * 60)
    logger.info("LangGraph XhsPlaywrightAdapter 开始")
    logger.info("  关键词: %s", keyword)
    logger.info("  分析模式: %s", args.analysis_mode)
    logger.info("  最大帖子: %d", args.max_posts)
    logger.info("  每帖最大评论: %d", max_comments)
    logger.info("  headless: %s", args.headless)
    if args.mock_llm:
        logger.info("  使用 MockLLMClient（离线模式）")
    logger.info("=" * 60)

    # 构造 LLM Client（两种模式都需要：llm_annotation 用于评论标注，rule 用于内容选题生成）
    llm_client = None
    if args.mock_llm:
        llm_client = MockLLMClient()
    elif args.analysis_mode == "llm_annotation":
        _validate_env_for_llm()
        llm_client = OpenAICompatLLMClient()
    else:
        # rule 模式也尝试创建 LLM client 用于 ContentIdeationAgent 选题生成
        try:
            llm_client = OpenAICompatLLMClient()
        except RuntimeError:
            logger.warning("LLM client 不可用，ContentIdeationAgent 将跳过（报告选题使用回退模板）")
            llm_client = None

    # 构造 Adapter
    config = XhsCollectConfig(
        keyword=keyword,
        max_posts=args.max_posts,
        max_comments_per_post=max_comments,
        headless=args.headless,
        request_interval_seconds=args.request_interval_seconds,
        output_sample_name=args.output_sample,
    )
    adapter = XhsPlaywrightAdapter(config=config)

    # 构造 LangGraph
    graph = build_ugc_market_graph(
        adapter=adapter,
        analysis_mode=args.analysis_mode,
        llm_client=llm_client,
    )

    # 构造请求
    request = AnalysisRequest(
        topic=keyword,
        product_direction=keyword,
        industry_question=f"分析 {keyword} 的用户需求、痛点、反馈和市场机会",
    )

    # 运行
    state = UGCGraphState(request=request, paths=paths)
    try:
        result = graph.invoke(state)
        success = result.get("success", False)
        report_path = result.get("report_path", "")

        if success:
            logger.info("=" * 60)
            logger.info("LangGraph XhsPlaywrightAdapter 完成！")
            logger.info("  report_path=%s", report_path)
            logger.info("  analysis_mode=%s", args.analysis_mode)
            logger.info("=" * 60)
            print(f"\n完成！产物路径：")
            print(f"  报告: {report_path}")
            print(f"  insights: {paths.insights_file}")
            print(f"  scorecard: {paths.scorecard_file}")
            sys.exit(0)
        else:
            logger.error("LangGraph 执行失败")
            sys.exit(1)

    except Exception as e:
        logger.error("LangGraph 执行异常: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
