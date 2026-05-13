#!/usr/bin/env python
"""
LangGraph 版本 UGC Market Validator 流水线。

用法：
    python scripts/run_langgraph_pipeline.py
    python scripts/run_langgraph_pipeline.py --analysis-mode llm_annotation --mock-llm
    python scripts/run_langgraph_pipeline.py --analysis-mode rule

支持两种分析模式：
- rule（默认）：规则版 SentimentAgent + InsightAgent
- llm_annotation：LLM 评论级语义标注 + AnnotationAggregator 聚合

保持与 python src/pipeline/pipeline.py 相同的 5 个核心产物输出。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.graph.graph import build_ugc_market_graph
from src.graph.state import UGCGraphState
from src.llm.client import MockLLMClient
from src.schemas import AnalysisRequest
from src.utils import get_app_paths

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="UGC Market Validator LangGraph pipeline"
    )
    parser.add_argument(
        "--analysis-mode",
        default="rule",
        choices=["rule", "llm_annotation"],
        help="分析模式：rule（规则）或 llm_annotation（LLM 标注 + 聚合）",
    )
    parser.add_argument(
        "--mock-llm",
        action="store_true",
        help="使用 MockLLMClient（不访问真实 API），仅用于测试",
    )
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("LangGraph Pipeline started")
    logger.info("  analysis_mode=%s", args.analysis_mode)
    logger.info("=" * 50)

    paths = get_app_paths()
    request = AnalysisRequest(
        topic="控油洗发水",
        product_direction="针对油性头皮的氨基酸洗发水",
        industry_question="用户对控油洗发水的主要痛点和需求是什么",
    )

    # 构造 llm_client（两种模式都需要：llm_annotation 用于评论标注，rule 用于内容选题生成）
    if args.mock_llm:
        llm_client = MockLLMClient()
        logger.info("  llm_client=MockLLMClient (mock mode)")
    elif args.analysis_mode == "llm_annotation":
        from src.llm.client import OpenAICompatLLMClient
        llm_client = OpenAICompatLLMClient()
        logger.info("  llm_client=OpenAICompatLLMClient (real API)")
    else:
        # rule 模式也创建 LLM client 用于 ContentIdeationAgent 选题生成
        from src.llm.client import OpenAICompatLLMClient
        try:
            llm_client = OpenAICompatLLMClient()
            logger.info("  llm_client=OpenAICompatLLMClient (for content ideation)")
        except RuntimeError:
            logger.warning("  llm_client=不可用，ContentIdeationAgent 将跳过（报告选题使用回退模板）")
            llm_client = None

    graph = build_ugc_market_graph(
        analysis_mode=args.analysis_mode,
        llm_client=llm_client,
    )
    state = UGCGraphState(request=request, paths=paths)

    try:
        result = graph.invoke(state)
        logger.info("=" * 50)
        logger.info("LangGraph Pipeline completed!")
        logger.info("  report_path=%s", result.get("report_path", "N/A"))
        logger.info("  success=%s", result.get("success", False))
        logger.info("=" * 50)
    except Exception as e:
        logger.error("LangGraph Pipeline failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
