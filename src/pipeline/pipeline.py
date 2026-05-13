"""
Pipeline - 编排 UGC Market Validator 的完整工作流。

执行顺序（CLAUDE.md 默认）：
    collect -> normalize -> analyze -> score -> render_report

其中 "analyze" 包含：
    1. SentimentAgent（基于关键词的情感分类）或 LLMSentimentAgent（LLM 增强）
    2. InsightAgent（结构化洞察提取）或 LLMInsightAgent（LLM 增强）

每个阶段均记录摘要统计信息。
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from typing import Any, Optional

# 确保项目根目录在 sys.path 中（当直接作为脚本运行时）。
# 此操作必须在任何 'from src.' 导入之前完成。
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))  # src/../..
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from pydantic import BaseModel

from src.adapters.base import BaseAdapter
from src.agents import (
    InsightAgent,
    LLMInsightAgent,
    LLMSentimentAgent,
    NormalizeAgent,
    ScoringAgent,
    SentimentAgent,
    SourceAgent,
)
from src.graph.persistence import save_insights, save_scorecard
from src.llm.client import BaseLLMClient
from src.reports.report_agent import ReportAgent
from src.schemas import AnalysisRequest, InsightRecord, NormalizedDataset, ScoreCard
from src.utils import AppPaths, get_app_paths

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 流水线结果模型
# ---------------------------------------------------------------------------


class PipelineResult(BaseModel):
    """完整流水线运行的结果，跟踪所有产物路径。"""

    raw_posts_path: str = ""
    raw_comments_path: str = ""
    normalized_posts_path: str = ""
    normalized_comments_path: str = ""
    insights_path: str = ""
    scorecard_path: str = ""
    report_path: str = ""
    success: bool = False
    error_message: str = ""


# ---------------------------------------------------------------------------
# 流水线
# ---------------------------------------------------------------------------


class Pipeline:
    """UGC Market Validator 工作流的编排器。

    用法：
        # 使用 mock 数据
        result = Pipeline().run(AnalysisRequest(...))

        # 使用平台适配器（如 XhsImportAdapter）
        adapter = XhsImportAdapter("data/raw/xhs_export.json")
        result = Pipeline(adapter=adapter).run(AnalysisRequest(...))
    """

    def __init__(
        self,
        adapter: Optional[BaseAdapter] = None,
        paths: Optional[AppPaths] = None,
        analysis_mode: str = "rule",
        llm_client: Optional[BaseLLMClient] = None,
        source_agent: Optional[SourceAgent] = None,
        normalize_agent: Optional[NormalizeAgent] = None,
        sentiment_agent: Optional[SentimentAgent] = None,
        insight_agent: Optional[InsightAgent] = None,
        scoring_agent: Optional[ScoringAgent] = None,
        report_agent: Optional[ReportAgent] = None,
    ):
        self._adapter = adapter
        self._paths = paths
        self._analysis_mode = analysis_mode
        self._llm_client = llm_client
        self._source_agent = source_agent
        self._normalize_agent = normalize_agent
        self._sentiment_agent = sentiment_agent
        self._insight_agent = insight_agent
        self._scoring_agent = scoring_agent
        self._report_agent = report_agent

    def run(
        self,
        request: AnalysisRequest,
        revision_instructions: Optional[list[str]] = None,
    ) -> PipelineResult:
        """执行完整流水线：collect -> normalize -> analyze -> score -> render_report。

        参数：
            request: 包含 topic、product_direction、industry_question 的 AnalysisRequest。
            revision_instructions: 可选的质量评审修订指令。

        返回：
            包含所有生成产物路径和成功标志的 PipelineResult。
        """
        result = PipelineResult()
        paths = self._paths or get_app_paths()

        logger.info("=" * 50)
        logger.info("Pipeline started: topic=%s", request.topic)
        logger.info("=" * 50)

        try:
            # ------------------------------------------------------------------
            # 步骤 1：采集
            # ------------------------------------------------------------------
            logger.info("[1/5] Collecting data...")
            source_agent = self._source_agent or SourceAgent(
                adapter=self._adapter, paths=self._paths
            )
            raw = source_agent.execute(request)
            logger.info(
                "       -> %d posts, %d comments", len(raw.posts), len(raw.comments)
            )

            result.raw_posts_path = paths.raw_posts_file
            result.raw_comments_path = paths.raw_comments_file

            # ------------------------------------------------------------------
            # 步骤 2：标准化
            # ------------------------------------------------------------------
            logger.info("[2/5] Normalizing data...")
            normalize_agent = self._normalize_agent or NormalizeAgent()
            normalized = normalize_agent.execute(raw)
            logger.info(
                "       -> %d posts, %d comments",
                len(normalized.posts),
                len(normalized.comments),
            )

            result.normalized_posts_path = paths.normalized_posts_file
            result.normalized_comments_path = paths.normalized_comments_file

            # ------------------------------------------------------------------
            # 步骤 3：分析（情感 -> 洞察）
            # ------------------------------------------------------------------
            logger.info("[3/5] Analyzing sentiment and extracting insights...")

            if self._analysis_mode == "llm_annotation":
                from src.agents.llm_comment_analyzer_agent import LLMCommentAnalyzerAgent
                from src.agents.annotation_aggregator import AnnotationAggregator

                # 检查注入 agent 冲突
                if self._sentiment_agent is not None or self._insight_agent is not None:
                    logger.warning(
                        "analysis_mode='llm_annotation' ignores injected sentiment_agent/"
                        "insight_agent because sentiment and insight are generated "
                        "from comment annotations."
                    )

                logger.info("[3/5] Annotating comments with LLM...")
                annotator = LLMCommentAnalyzerAgent(
                    llm_client=self._llm_client,
                )
                annotations = annotator.execute(normalized.comments)
                logger.info("       -> %d annotations", len(annotations))

                aggregator = AnnotationAggregator()
                sentiment = aggregator.to_sentiment_result(annotations, normalized.posts, normalized.comments)
                insight = aggregator.to_insight_record(annotations, normalized.posts, normalized.comments)
                logger.info(
                    "       -> sentiment=%s, pain=%d, needs=%d, complaints=%d, solutions=%d, signals=%d",
                    sentiment.overall_sentiment,
                    len(insight.pain_points), len(insight.user_needs),
                    len(insight.complaints), len(insight.solutions), len(insight.market_signals),
                )

                # persist insight to disk
                import json
                os.makedirs(paths.outputs_dir, exist_ok=True)
                with open(paths.insights_file, "w", encoding="utf-8") as _f:
                    json.dump(insight.model_dump(), _f, ensure_ascii=False, indent=2)
                logger.info(
                    "       -> persisted insights to %s", paths.insights_file
                )
            else:
                # rule / llm 模式使用原来的 sentiment + insight agent 链路
                if self._analysis_mode == "llm" and self._sentiment_agent is None:
                    sentiment_agent = LLMSentimentAgent(llm_client=self._llm_client)
                else:
                    sentiment_agent = self._sentiment_agent or SentimentAgent()
                sentiment = sentiment_agent.execute(normalized)
                logger.info(
                    "       -> overall_sentiment=%s", sentiment.overall_sentiment
                )

                if self._analysis_mode == "llm" and self._insight_agent is None:
                    insight_agent = LLMInsightAgent(llm_client=self._llm_client)
                else:
                    insight_agent = self._insight_agent or InsightAgent()
                insight = insight_agent.execute(normalized, sentiment)
                save_insights(insight, paths)
                logger.info(
                    "       -> pain_points=%d, user_needs=%d, complaints=%d, "
                    "solutions=%d, signals=%d",
                    len(insight.pain_points),
                    len(insight.user_needs),
                    len(insight.complaints),
                    len(insight.solutions),
                    len(insight.market_signals),
                )

            result.insights_path = paths.insights_file

            # ------------------------------------------------------------------
            # 步骤 4：评分
            # ------------------------------------------------------------------
            logger.info("[4/5] Scoring...")
            scoring_agent = self._scoring_agent or ScoringAgent()
            scorecard = scoring_agent.execute(insight, normalized, sentiment)
            save_scorecard(scorecard, paths)
            logger.info(
                "       -> overall_score=%.2f", scorecard.overall_score
            )

            result.scorecard_path = paths.scorecard_file

            # ------------------------------------------------------------------
            # 步骤 5：生成报告
            # ------------------------------------------------------------------
            logger.info("[5/5] Generating report...")
            report_agent = self._report_agent or ReportAgent(paths=self._paths)
            report = report_agent.execute(
                insight, scorecard, normalized,
                topic=request.topic,
                product_direction=request.product_direction,
                revision_instructions=revision_instructions,
            )
            logger.info("       -> report_path=%s", report.report_path)

            result.report_path = report.report_path

            # ------------------------------------------------------------------
            # 成功
            # ------------------------------------------------------------------
            result.success = True
            logger.info("=" * 50)
            logger.info("Pipeline completed successfully!")
            logger.info("=" * 50)

        except Exception:
            error_msg = traceback.format_exc()
            logger.error("Pipeline failed:\n%s", error_msg)
            result.error_message = error_msg
            result.success = False

        return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="UGC Market Validator Pipeline")
    parser.add_argument(
        "--analysis-mode",
        choices=["rule", "llm", "llm_annotation"],
        default="rule",
        help="分析模式: rule (关键词规则), llm (LLM 增强), 或 llm_annotation (LLM 评论语义标注)",
    )
    parser.add_argument("--topic", default="控油洗发水", help="分析主题")
    parser.add_argument(
        "--product-direction",
        default="针对油性头皮的氨基酸洗发水",
        help="产品方向",
    )
    parser.add_argument(
        "--industry-question",
        default="用户对控油洗发水的主要痛点和需求是什么",
        help="行业问题",
    )
    args = parser.parse_args()

    req = AnalysisRequest(
        topic=args.topic,
        product_direction=args.product_direction,
        industry_question=args.industry_question,
    )
    result = Pipeline(
        analysis_mode=args.analysis_mode,
    ).run(req)
    print(f"\nPipeline finished: success={result.success}")
    print(f"  Report: {result.report_path}")
