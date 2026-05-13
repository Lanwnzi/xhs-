"""
Rule vs LLM 分析对比实验。

读取同一批 raw 数据，分别运行 rule 和 llm 分析，导出对比报告。

用法：
    # 使用 MockLLMClient（离线可用）
    python scripts/run_rule_vs_llm_analysis.py --mock-llm

    # 使用真实 LLM（需要配置环境变量）
    python scripts/run_rule_vs_llm_analysis.py

本脚本不覆盖正式 insights.json / scorecard.json / report.html。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import shutil
from datetime import datetime

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rule vs LLM 分析对比实验")
    parser.add_argument("--mock-llm", action="store_true", help="使用 MockLLMClient（不访问真实 LLM）")
    parser.add_argument("--max-comments", type=int, default=50, help="最大评论数")
    parser.add_argument("--output", default="docs/rule_vs_llm_review.md", help="对比报告输出路径")
    parser.add_argument(
        "--analysis-mode",
        default="llm",
        choices=["llm", "llm_annotation"],
        help="LLM 分析模式：llm（直接生成洞察，默认），llm_annotation（先评论级标注再聚合）",
    )
    return parser.parse_args()


def _make_temp_paths() -> tuple[object, str]:
    """创建临时 AppPaths，避免覆盖正式产物。"""
    from src.utils import AppPaths
    tmpdir = tempfile.mkdtemp(prefix="rule_vs_llm_")
    paths = AppPaths(
        project_root=tmpdir,
        raw_dir=os.path.join(tmpdir, "raw"),
        normalized_dir=os.path.join(tmpdir, "normalized"),
        outputs_dir=os.path.join(tmpdir, "outputs"),
        raw_posts_file=os.path.join(tmpdir, "raw", "raw_posts.json"),
        raw_comments_file=os.path.join(tmpdir, "raw", "raw_comments.json"),
        normalized_posts_file=os.path.join(tmpdir, "normalized", "normalized_posts.json"),
        normalized_comments_file=os.path.join(tmpdir, "normalized", "normalized_comments.json"),
        insights_file=os.path.join(tmpdir, "outputs", "insights.json"),
        scorecard_file=os.path.join(tmpdir, "outputs", "scorecard.json"),
        report_file=os.path.join(tmpdir, "outputs", "report.html"),
    )
    os.makedirs(paths.raw_dir, exist_ok=True)
    os.makedirs(paths.normalized_dir, exist_ok=True)
    os.makedirs(paths.outputs_dir, exist_ok=True)
    return paths, tmpdir


def _load_raw_data() -> tuple[list[dict], list[dict]]:
    """加载 data/raw/ 下的帖子、评论（从最原始的平台字段开始）。"""
    raw_posts_path = os.path.join(_PROJECT_ROOT, "data", "raw", "raw_posts.json")
    raw_comments_path = os.path.join(_PROJECT_ROOT, "data", "raw", "raw_comments.json")

    if not os.path.exists(raw_posts_path) or not os.path.exists(raw_comments_path):
        logger.error("raw 数据不存在，请先运行采集脚本")
        sys.exit(1)

    with open(raw_posts_path, encoding="utf-8") as f:
        posts = json.load(f)
    with open(raw_comments_path, encoding="utf-8") as f:
        comments = json.load(f)

    logger.info("加载 raw 数据: %d 条帖子, %d 条评论", len(posts), len(comments))
    return posts, comments


def _resolve_llm_client(use_mock: bool):
    """根据 --mock-llm 标志返回 LLM 客户端实例。

    返回：
        MockLLMClient（use_mock=True）或 OpenAICompatLLMClient
    抛出：
        RuntimeError: 环境变量缺失时
    """
    if use_mock:
        from src.llm.client import MockLLMClient
        return MockLLMClient()
    from src.llm.client import OpenAICompatLLMClient
    return OpenAICompatLLMClient()


def _run_rule_analysis(posts: list[dict], comments: list[dict]) -> dict:
    """运行 rule 模式分析（仅 analyze 阶段）。"""
    from src.schemas import NormalizedDataset, PostRecord, CommentRecord
    from src.agents import SentimentAgent, InsightAgent

    dataset = NormalizedDataset(
        posts=[PostRecord(**p) for p in posts],
        comments=[CommentRecord(**c) for c in comments],
    )

    paths, tmpdir = _make_temp_paths()
    try:
        sa = SentimentAgent()
        sentiment = sa.execute(dataset)
        ia = InsightAgent()
        insight = ia.execute(dataset, sentiment)

        return {
            "sentiment": sentiment.model_dump(),
            "insight": insight.model_dump(),
            "llm_mode": "rule",
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _run_llm_analysis(posts: list[dict], comments: list[dict], use_mock: bool = False) -> dict:
    """运行 LLM 模式分析（仅 analyze 阶段）。"""
    from src.schemas import NormalizedDataset, PostRecord, CommentRecord

    dataset = NormalizedDataset(
        posts=[PostRecord(**p) for p in posts],
        comments=[CommentRecord(**c) for c in comments],
    )

    if use_mock:
        from src.llm.client import MockLLMClient
        llm_client = MockLLMClient()
    else:
        try:
            from src.llm.client import OpenAICompatLLMClient
            llm_client = OpenAICompatLLMClient()
        except RuntimeError as e:
            logger.warning("LLM 环境变量未配置: %s", e)
            logger.info("使用 --mock-llm 可运行离线对比")
            raise

    from src.agents.llm_sentiment_agent import LLMSentimentAgent
    from src.agents.llm_insight_agent import LLMInsightAgent

    sa = LLMSentimentAgent(llm_client=llm_client)
    sentiment = sa.execute(dataset)
    ia = LLMInsightAgent(llm_client=llm_client)
    insight = ia.execute(dataset, sentiment)

    return {
        "sentiment": sentiment.model_dump(),
        "insight": insight.model_dump(),
        "llm_mode": "llm",
    }


def _run_llm_annotation_analysis(
    posts: list[dict],
    comments: list[dict],
    llm_client,
) -> dict:
    """运行 llm_annotation 模式分析——先评论级标注再聚合。"""
    from src.schemas import NormalizedDataset, PostRecord, CommentRecord, SentimentResult, InsightRecord
    from src.agents.llm_comment_analyzer_agent import LLMCommentAnalyzerAgent
    from src.agents.annotation_aggregator import AnnotationAggregator

    dataset = NormalizedDataset(
        posts=[PostRecord(**p) for p in posts],
        comments=[CommentRecord(**c) for c in comments],
    )

    annotator = LLMCommentAnalyzerAgent(llm_client=llm_client)
    try:
        annotations = annotator.execute(dataset.comments)
    except Exception as e:
        logger.warning("LLMCommentAnalyzerAgent 执行失败，返回空结果: %s", e)
        return {
            "sentiment": SentimentResult(overall_sentiment="neutral").model_dump(),
            "insight": InsightRecord().model_dump(),
            "llm_mode": "llm_annotation",
        }

    aggregator = AnnotationAggregator()
    sentiment = aggregator.to_sentiment_result(annotations, dataset.posts, dataset.comments)
    insight = aggregator.to_insight_record(annotations, dataset.posts, dataset.comments)

    return {
        "sentiment": sentiment.model_dump(),
        "insight": insight.model_dump(),
        "llm_mode": "llm_annotation",
    }


def _generate_report(
    rule_result: dict,
    llm_result: dict,
    output_path: str,
    use_mock: bool,
    posts_count: int,
    comments_count: int,
) -> None:
    """生成对比报告 Markdown。"""
    llm_mode = llm_result.get("llm_mode", "llm")
    llm_label = "LLM (annotation)" if llm_mode == "llm_annotation" else "LLM"

    lines = []
    lines.append(f"# Rule vs {llm_label} 分析对比报告\n")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    lines.append("## 实验数据概览\n")
    lines.append(f"- 帖子数：{posts_count}")
    lines.append(f"- 评论数：{comments_count}")
    lines.append(f"- 使用 Mock LLM：{use_mock}")
    lines.append(f"- 使用真实 LLM：{not use_mock}")
    lines.append(f"- LLM 分析模式：{llm_mode}\n")

    rule_insight = rule_result.get("insight", {})
    llm_insight = llm_result.get("insight", {})

    for label, key in [
        ("情绪判断 (sentiment)", "sentiment"),
        ("痛点 (pain_points)", "pain_points"),
        ("用户需求 (user_needs)", "user_needs"),
        ("投诉 (complaints)", "complaints"),
        ("替代方案 (solutions)", "solutions"),
        ("市场信号 (market_signals)", "market_signals"),
    ]:
        lines.append(f"## {label}\n")
        rule_val = rule_insight.get(key, rule_result.get(key, ""))
        llm_val = llm_insight.get(key, llm_result.get(key, ""))

        if isinstance(rule_val, list):
            lines.append("### Rule 版\n")
            for item in rule_val:
                lines.append(f"- {item}")
            lines.append("")
            lines.append("### LLM 版\n")
            for item in llm_val:
                lines.append(f"- {item}")
        else:
            lines.append(f"- Rule: {rule_val}")
            lines.append(f"- LLM: {llm_val}")
        lines.append("")

    # Evidence 检查
    lines.append("## Evidence 检查\n")
    rule_post_ids = rule_insight.get("evidence_post_ids", [])
    rule_comment_ids = rule_insight.get("evidence_comment_ids", [])
    llm_post_ids = llm_insight.get("evidence_post_ids", [])
    llm_comment_ids = llm_insight.get("evidence_comment_ids", [])
    lines.append(f"- Rule evidence_post_ids: {rule_post_ids}")
    lines.append(f"- Rule evidence_comment_ids: {rule_comment_ids}")
    lines.append(f"- LLM evidence_post_ids: {llm_post_ids}")
    lines.append(f"- LLM evidence_comment_ids: {llm_comment_ids}")
    lines.append("")

    # 人工评价栏
    lines.append("## 人工评价\n")
    for question in [
        "情绪判断是否更准确",
        "痛点是否更贴近评论",
        "需求概括是否更好",
        "是否有编造",
    ]:
        lines.append(f"- [ ] {question}：")
    lines.append("- 备注：\n")

    lines.append("---\n")
    lines.append("*由 run_rule_vs_llm_analysis.py 自动生成*\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info("对比报告已生成: %s", output_path)


def main():
    args = parse_args()

    posts, comments = _load_raw_data()

    # Rule 分析
    logger.info("运行 rule 分析...")
    rule_result = _run_rule_analysis(posts, comments)

    # LLM 分析（根据 --analysis-mode 选择）
    use_mock = args.mock_llm
    logger.info("运行 %s 分析（模式: %s）...", "LLM" if args.analysis_mode == "llm" else "LLM annotation", args.analysis_mode)

    try:
        if args.analysis_mode == "llm":
            llm_result = _run_llm_analysis(posts, comments, use_mock=use_mock)
        elif args.analysis_mode == "llm_annotation":
            llm_client = _resolve_llm_client(use_mock)
            llm_result = _run_llm_annotation_analysis(posts, comments, llm_client)
        else:
            raise ValueError(f"未知 analysis_mode: {args.analysis_mode}")
    except RuntimeError as e:
        print(f"\nLLM 分析不可用: {e}")
        print("请使用 --mock-llm 运行离线对比。")
        sys.exit(1)

    # 生成对比报告
    _generate_report(
        rule_result, llm_result, args.output, use_mock,
        len(posts), len(comments),
    )

    print(f"\n对比报告已生成: {args.output}")
    print(f"Rule 分析: {len(rule_result.get('insight', {}).get('pain_points', []))} 条痛点")
    print(f"LLM 分析: {len(llm_result.get('insight', {}).get('pain_points', []))} 条痛点")
    if use_mock:
        print("注意: 当前使用 MockLLMClient，结果不代表真实 LLM 质量。")
        print("请配置 LLM 环境变量后重新运行以获取真实对比。")
    sys.exit(0)


if __name__ == "__main__":
    main()
