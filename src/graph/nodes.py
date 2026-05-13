"""LangGraph 节点函数。

每个节点是纯 state 管理函数：
  1. 从 state 提取输入并校验
  2. 调用业务函数（纯逻辑，不依赖 state）
  3. 调用 persistence 模块持久化
  4. 返回 state update dict

Node 函数不直接做业务计算、不直接做文件 I/O。
所有节点支持通过闭包注入 agent 实例，便于单元测试。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from src.adapters.base import BaseAdapter
from src.agents import (
    InsightAgent,
    NormalizeAgent,
    ScoringAgent,
    SentimentAgent,
    SourceAgent,
)
from src.agents.annotation_aggregator import AnnotationAggregator
from src.agents.content_ideation_agent import ContentIdeationAgent
from src.agents.llm_comment_analyzer_agent import LLMCommentAnalyzerAgent
from src.graph.persistence import (
    save_content_ideation,
    save_insights,
    save_normalized_dataset,
    save_raw_dataset,
    save_scorecard,
)
from src.graph.state import UGCGraphState
from src.reports.report_agent import ReportAgent
from src.utils import AppPaths

logger = logging.getLogger(__name__)


# ============================================================================
# 工厂函数：创建 node（闭包注入 agent / adapter / paths）
# ============================================================================


def create_collect_node(
    adapter: Optional[BaseAdapter] = None,
    agent: Optional[SourceAgent] = None,
    paths: Optional[AppPaths] = None,
):
    """创建 collect node。

    adapter / agent / paths 通过闭包注入，不放入 state。
    """

    def collect_node(state: UGCGraphState) -> dict[str, Any]:
        logger.info("[Graph] collect_node: 开始采集")
        if not state.request:
            raise ValueError("collect_node: state.request 为空")

        effective_paths = paths or state.paths
        instance = agent or SourceAgent(adapter=adapter, paths=effective_paths)

        # 调用业务函数（纯逻辑）
        raw = instance.execute(state.request)

        # 持久化
        save_raw_dataset(raw, effective_paths)

        logger.info(
            "[Graph] collect_node: %d 条帖子, %d 条评论",
            len(raw.posts), len(raw.comments),
        )
        return {"raw_dataset": raw}

    return collect_node


def create_normalize_node(agent: Optional[NormalizeAgent] = None, paths: Optional[AppPaths] = None):
    """创建 normalize node。"""

    def normalize_node(state: UGCGraphState) -> dict[str, Any]:
        logger.info("[Graph] normalize_node: 开始标准化")
        if not state.raw_dataset:
            raise ValueError("normalize_node: state.raw_dataset 为空")

        effective_paths = paths or state.paths
        instance = agent or NormalizeAgent()

        # 调用业务函数（纯逻辑）
        normalized = instance.execute(state.raw_dataset)

        # 持久化
        save_normalized_dataset(normalized, effective_paths)

        logger.info(
            "[Graph] normalize_node: %d 条帖子, %d 条评论",
            len(normalized.posts), len(normalized.comments),
        )
        return {"normalized_dataset": normalized}

    return normalize_node


def create_sentiment_node(agent: Optional[SentimentAgent] = None):
    """创建 sentiment node。"""

    def sentiment_node(state: UGCGraphState) -> dict[str, Any]:
        logger.info("[Graph] sentiment_node: 开始情感分析")
        if not state.normalized_dataset:
            raise ValueError("sentiment_node: state.normalized_dataset 为空")

        instance = agent or SentimentAgent()

        # 调用业务函数（纯逻辑，SentimentAgent 不持久化）
        sentiment = instance.execute(state.normalized_dataset)

        logger.info(
            "[Graph] sentiment_node: overall=%s",
            sentiment.overall_sentiment,
        )
        return {"sentiment_result": sentiment}

    return sentiment_node


def create_insight_node(agent: Optional[InsightAgent] = None, paths: Optional[AppPaths] = None):
    """创建 insight node。"""

    def insight_node(state: UGCGraphState) -> dict[str, Any]:
        logger.info("[Graph] insight_node: 开始洞察提取")
        if not state.normalized_dataset or not state.sentiment_result:
            raise ValueError(
                "insight_node: state.normalized_dataset 或 sentiment_result 为空"
            )

        instance = agent or InsightAgent()

        # 调用业务函数（纯逻辑）
        insight = instance.execute(state.normalized_dataset, state.sentiment_result)

        # 持久化
        effective_paths = paths or state.paths
        save_insights(insight, effective_paths)

        logger.info(
            "[Graph] insight_node: 痛点=%d, 需求=%d, 投诉=%d",
            len(insight.pain_points),
            len(insight.user_needs),
            len(insight.complaints),
        )
        return {"insights": insight}

    return insight_node


def create_score_node(agent: Optional[ScoringAgent] = None, paths: Optional[AppPaths] = None):
    """创建 score node。"""

    def score_node(state: UGCGraphState) -> dict[str, Any]:
        logger.info("[Graph] score_node: 开始评分")
        if not state.insights or not state.normalized_dataset or not state.sentiment_result:
            raise ValueError("score_node: 必要输入为空")

        instance = agent or ScoringAgent()

        # 调用业务函数（纯逻辑）
        scorecard = instance.execute(
            state.insights, state.normalized_dataset, state.sentiment_result
        )

        # 持久化
        effective_paths = paths or state.paths
        save_scorecard(scorecard, effective_paths)

        logger.info("[Graph] score_node: overall=%.2f", scorecard.overall_score)
        return {"scorecard": scorecard}

    return score_node


def create_report_node(agent: Optional[ReportAgent] = None, paths: Optional[AppPaths] = None):
    """创建 report node。ReportAgent 负责 HTML 生成（其核心输出即文件）。"""

    def report_node(state: UGCGraphState) -> dict[str, Any]:
        logger.info("[Graph] report_node: 开始生成报告")
        if not state.insights or not state.scorecard or not state.normalized_dataset:
            raise ValueError("report_node: 必要输入为空")

        effective_paths = paths or state.paths
        instance = agent or ReportAgent(paths=effective_paths)

        # ReportAgent.execute() 写入 HTML 文件并返回 ReportResult
        result = instance.execute(
            state.insights,
            state.scorecard,
            state.normalized_dataset,
            topic=state.request.topic,
            product_direction=state.request.product_direction,
            content_ideation_result=state.content_ideation_result,
        )

        logger.info("[Graph] report_node: 报告已生成 %s", result.report_path)
        return {"report_path": result.report_path, "report_generated": True, "success": True}

    return report_node


def create_annotate_comments_node(llm_client, use_concurrent: bool = True):
    """创建 annotate_comments node。

    llm_client 通过闭包注入，不保存在 state 中。
    """

    def annotate_comments_node(state: UGCGraphState) -> dict[str, Any]:
        logger.info(
            "[Graph] annotate_comments_node: 开始 LLM 评论标注 (concurrent=%s)",
            use_concurrent,
        )
        if not state.normalized_dataset:
            raise ValueError("annotate_comments_node: state.normalized_dataset 为空")

        agent = LLMCommentAnalyzerAgent(llm_client=llm_client)

        # 调用业务函数（纯逻辑）
        if use_concurrent:
            annotations = agent.execute_concurrent(
                state.normalized_dataset.comments,
                posts=state.normalized_dataset.posts,
            )
        else:
            annotations = agent.execute(
                state.normalized_dataset.comments,
                posts=state.normalized_dataset.posts,
            )

        logger.info("[Graph] annotate_comments_node: %d 条标注", len(annotations))
        return {"comment_annotations": annotations}

    return annotate_comments_node


def create_ideate_content_node(llm_client, paths: Optional[AppPaths] = None):
    """创建 ideate_content node。

    在 score 之后、report 之前调用 ContentIdeationAgent。
    llm_client 通过闭包注入。
    """

    def ideate_content_node(state: UGCGraphState) -> dict[str, Any]:
        logger.info("[Graph] ideate_content_node: 开始 LLM 内容选题生成")
        if not state.insights or not state.scorecard or not state.normalized_dataset:
            raise ValueError("ideate_content_node: 必要输入为空")

        agent = ContentIdeationAgent(
            llm_client=llm_client,
            keyword=state.request.topic,
        )

        # 调用业务函数（纯逻辑）
        result = agent.execute(
            insight=state.insights,
            scorecard=state.scorecard,
            dataset=state.normalized_dataset,
            keyword=state.request.topic,
        )

        # 持久化
        effective_paths = paths or state.paths
        save_content_ideation(result, effective_paths)

        logger.info(
            "[Graph] ideate_content_node: topics=%d, titles=%d, mode=%s",
            len(result.topic_suggestions),
            len(result.custom_title_suggestions),
            result.generation_mode,
        )
        return {"content_ideation_result": result}

    return ideate_content_node


# ============================================================================
# llm_annotation 模式专用节点（聚合 annotations → sentiment / insight）
# ============================================================================


def sentiment_from_annotations_node(state: UGCGraphState) -> dict[str, Any]:
    """从 comment_annotations 聚合 SentimentResult。

    使用 AnnotationAggregator（纯业务逻辑）转换。
    """
    logger.info("[Graph] sentiment_from_annotations_node: 开始聚合情感")
    if state.comment_annotations is None:
        raise ValueError(
            "sentiment_from_annotations_node: state.comment_annotations 为 None"
        )

    aggregator = AnnotationAggregator()
    posts = list(state.normalized_dataset.posts) if state.normalized_dataset else []
    comments = list(state.normalized_dataset.comments) if state.normalized_dataset else []

    # 调用业务函数（纯逻辑）
    sentiment = aggregator.to_sentiment_result(state.comment_annotations, posts, comments)

    #TODO 添加持久化操作

    logger.info(
        "[Graph] sentiment_from_annotations_node: overall=%s",
        sentiment.overall_sentiment,
    )
    return {"sentiment_result": sentiment}


def insight_from_annotations_node(state: UGCGraphState) -> dict[str, Any]:
    """从 comment_annotations 聚合 InsightRecord 并持久化。

    使用 AnnotationAggregator（纯业务逻辑）转换，然后持久化。
    """
    logger.info("[Graph] insight_from_annotations_node: 开始聚合洞察")
    if state.comment_annotations is None:
        raise ValueError(
            "insight_from_annotations_node: state.comment_annotations 为 None"
        )

    aggregator = AnnotationAggregator()
    posts = list(state.normalized_dataset.posts) if state.normalized_dataset else []
    comments = list(state.normalized_dataset.comments) if state.normalized_dataset else []

    # 调用业务函数（纯逻辑）
    insight = aggregator.to_insight_record(state.comment_annotations, posts, comments)

    # 持久化
    save_insights(insight, state.paths)

    logger.info(
        "[Graph] insight_from_annotations_node: 痛点=%d, 需求=%d",
        len(insight.pain_points),
        len(insight.user_needs),
    )
    return {"insights": insight}
