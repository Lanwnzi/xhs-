"""LangGraph 图构建。

使用 StateGraph 定义 UGC Market Validator 的流水线。

支持两种分析模式：
- rule（默认）：原 8 节点 DAG（collect -> normalize -> sentiment -> insight -> score -> ideate_content -> report）
- llm_annotation：LLM 评论级语义标注 + 聚合（collect -> normalize -> annotate_comments ->
  sentiment_from_annotations -> insight_from_annotations -> score -> ideate_content -> report）
"""

from __future__ import annotations

from typing import Any, Optional

from langgraph.graph import END, START, StateGraph

from src.adapters.base import BaseAdapter
from src.graph.nodes import (
    create_annotate_comments_node,
    create_collect_node,
    create_ideate_content_node,
    create_insight_node,
    create_normalize_node,
    create_report_node,
    create_score_node,
    create_sentiment_node,
    insight_from_annotations_node,
    sentiment_from_annotations_node,
)
from src.graph.state import UGCGraphState
from src.utils import AppPaths


def build_ugc_market_graph(
    adapter: Optional[BaseAdapter] = None,
    analysis_mode: str = "rule",
    llm_client: Any = None,
    paths: Optional[AppPaths] = None,
) -> StateGraph:
    """构建 LangGraph 图。

    支持的分析模式：
    - rule（默认）：原 8 节点 DAG，使用规则版 SentimentAgent 和 InsightAgent。
    - llm_annotation：LLM 评论级语义标注 + 聚合模式。使用 LLMCommentAnalyzerAgent
      对评论进行语义标注，然后通过 AnnotationAggregator 聚合为 SentimentResult
      和 InsightRecord。

    参数：
        adapter: 可选适配器，传入 SourceAgent。为 None 时使用 mock 文件。
        analysis_mode: 分析模式，可选 "rule" 或 "llm_annotation"。
        llm_client: LLM 客户端实例（llm_annotation 模式必需）。
            不提供时抛出 ValueError。
        paths: 可选的 AppPaths 实例，传入节点闭包。

    返回：
        compile 后的 StateGraph。

    抛出：
        ValueError: analysis_mode 不支持，或 llm_annotation 模式未提供 llm_client。
    """
    builder = StateGraph(UGCGraphState)

    if analysis_mode == "rule":
        # 注册规则节点
        builder.add_node("collect", create_collect_node(adapter, paths=paths))
        builder.add_node("normalize", create_normalize_node(paths=paths))
        builder.add_node("sentiment", create_sentiment_node())
        builder.add_node("insight", create_insight_node(paths=paths))
        builder.add_node("score", create_score_node(paths=paths))
        builder.add_node("ideate_content", create_ideate_content_node(llm_client, paths=paths))
        builder.add_node("report", create_report_node(paths=paths))

        # rule 边
        builder.add_edge(START, "collect")
        builder.add_edge("collect", "normalize")
        builder.add_edge("normalize", "sentiment")
        builder.add_edge("sentiment", "insight")
        builder.add_edge("insight", "score")
        builder.add_edge("score", "ideate_content")
        builder.add_edge("ideate_content", "report")
        builder.add_edge("report", END)

    elif analysis_mode == "llm_annotation":
        if llm_client is None:
            raise ValueError(
                "analysis_mode='llm_annotation' requires llm_client. "
                "Please provide an LLM client instance."
            )

        builder.add_node("collect", create_collect_node(adapter, paths=paths))
        builder.add_node("normalize", create_normalize_node(paths=paths))
        builder.add_node("annotate_comments", create_annotate_comments_node(llm_client))
        builder.add_node("sentiment_from_annotations", sentiment_from_annotations_node)
        builder.add_node("insight_from_annotations", insight_from_annotations_node)
        builder.add_node("score", create_score_node(paths=paths))
        builder.add_node("ideate_content", create_ideate_content_node(llm_client, paths=paths))
        builder.add_node("report", create_report_node(paths=paths))

        builder.add_edge(START, "collect")
        builder.add_edge("collect", "normalize")
        builder.add_edge("normalize", "annotate_comments")
        builder.add_edge("annotate_comments", "sentiment_from_annotations")
        builder.add_edge("sentiment_from_annotations", "insight_from_annotations")
        builder.add_edge("insight_from_annotations", "score")
        builder.add_edge("score", "ideate_content")
        builder.add_edge("ideate_content", "report")
        builder.add_edge("report", END)

    else:
        raise ValueError(f"unsupported analysis_mode: {analysis_mode}")

    return builder.compile()
