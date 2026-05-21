"""服务层：LangGraph 分析任务。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import traceback

from src.adapters.xhs_collect_config import XhsCollectConfig
from src.adapters.xhs_playwright_adapter import XhsPlaywrightAdapter
from src.api.jobs import get_job, update_job
from src.api.schemas import APIAnalyzeRequest
from src.graph.graph import build_ugc_market_graph
from src.graph.state import UGCGraphState
from src.llm.client import MockLLMClient, OpenAICompatLLMClient
from src.schemas import AnalysisRequest, InsightRecord, NormalizedDataset, ScoreCard
from src.utils import AppPaths

logger = logging.getLogger(__name__)


def _run_comment_clustering(paths, result: dict) -> None:
    """执行 P6.0 评论聚类（旁路，不阻塞主流程）。

    无论结果如何（成功、跳过、失败），都确保 outputs/comment_clusters.json 存在。
    """
    try:
        from src.agents.comment_cluster_agent import CommentClusterAgent
        from src.llm.embedding_client import (
            create_embedding_client_from_env,
        )

        logger.info("P6.0: 开始评论聚类")
        logger.info("P6.0: normalized_comments path = %s", paths.normalized_comments_file)

        embedding_client = create_embedding_client_from_env()
        logger.info("P6.0: embedding config valid = %s", embedding_client is not None)

        cluster_agent = CommentClusterAgent(embedding_client=embedding_client)
        logger.info("P6.0: similarity threshold = %s", cluster_agent.similarity_threshold)

        # 从 result 中提取评论
        normalized_dataset = result.get("normalized_dataset")
        if normalized_dataset and hasattr(normalized_dataset, "comments"):
            comments = normalized_dataset.comments
            logger.info(
                "P6.0: loaded comments = %d",
                len(comments) if comments else 0,
            )
            annotations = result.get("comment_annotations")
            cluster_result = cluster_agent.execute_and_persist(
                paths, comments, annotations,
            )
            logger.info(
                "P6.0: 聚类完成 — 总评论=%d, 聚类=%d, 噪声=%d, 输出=%s",
                cluster_result.total_comments,
                len(cluster_result.clusters),
                cluster_result.noise_comments,
                paths.comment_clusters_file,
            )
        else:
            # result 中无评论数据 → 写空结果
            _write_empty_cluster_result(
                paths, reason="graph result 中无 normalized_dataset.comments",
            )
    except Exception as _cluster_err:
        logger.warning(
            "P6.0: 聚类异常（已写入空结果）: %s", _cluster_err,
        )
        _write_empty_cluster_result(
            paths, reason=f"聚类异常: {_cluster_err}",
        )


def _write_empty_cluster_result(paths, reason: str = "") -> None:
    """写入空的 comment_clusters.json，确保文件总是存在。"""
    import json as _json
    import os as _os

    output_path = paths.comment_clusters_file
    _os.makedirs(_os.path.dirname(output_path), exist_ok=True)
    empty = {
        "clusters": [],
        "total_comments": 0,
        "clustered_comments": 0,
        "noise_comments": 0,
        "algorithm": "cosine_threshold_union_find",
        "similarity_threshold": 0.72,
        "skipped_reason": reason or "未知",
    }
    with open(output_path, "w", encoding="utf-8") as _f:
        _json.dump(empty, _f, ensure_ascii=False, indent=2)
    logger.info("P6.0: 已写入空聚类结果到 %s (reason: %s)", output_path, reason)


def _rerender_report_with_clusters(paths: AppPaths, result: dict, topic: str = "") -> None:
    """重新渲染 report.html，包含聚类结果。"""
    from src.reports.report_agent import ReportAgent
    from src.schemas import InsightRecord, NormalizedDataset, ScoreCard

    clusters_path = paths.comment_clusters_file
    if not os.path.exists(clusters_path):
        logger.info("P6.0: comment_clusters.json 不存在，跳过重新渲染报告")
        return

    with open(clusters_path, encoding="utf-8") as f:
        clusters_data = json.load(f)

    if not clusters_data.get("clusters"):
        logger.info("P6.0: 聚类结果为空，不重新渲染报告")
        return

    logger.info("P6.0: 重新渲染 report.html 包含 %d 个聚类主题", len(clusters_data["clusters"]))

    # 读取数据
    with open(paths.insights_file, encoding="utf-8") as f:
        insight_data = json.load(f)
    with open(paths.scorecard_file, encoding="utf-8") as f:
        scorecard_data = json.load(f)

    insight = InsightRecord(**insight_data)
    scorecard = ScoreCard(**scorecard_data)

    normalized_dataset = result.get("normalized_dataset")
    if isinstance(normalized_dataset, dict):
        normalized = NormalizedDataset(**normalized_dataset)
    elif hasattr(normalized_dataset, "model_dump"):
        normalized = NormalizedDataset(**normalized_dataset.model_dump())
    else:
        normalized = NormalizedDataset()

    report_agent = ReportAgent(paths=paths)
    report_agent.execute(
        insight=insight,
        scorecard=scorecard,
        dataset=normalized,
        topic=topic,
        comment_clusters_data=clusters_data,
    )
    logger.info("P6.0: 已重新渲染 report.html 包含聚类结果: %s", paths.report_file)


def _assert_worker_thread() -> None:
    """运行时保护：检测当前线程是否存在 running asyncio loop。

    XhsPlaywrightAdapter 使用 Playwright Sync API，
    必须在独立线程中运行，不能在 asyncio event loop 中。
    """
    try:
        loop = asyncio.get_running_loop()
        raise RuntimeError(
            "run_xhs_langgraph_analysis must run in worker thread "
            "because XhsPlaywrightAdapter uses Playwright Sync API. "
            f"Current thread has running asyncio loop: {loop}"
        )
    except RuntimeError as e:
        if "must run in worker thread" in str(e):
            raise
        # 没有 running loop，安全


def run_xhs_langgraph_analysis(job_id: str, request: APIAnalyzeRequest, jobs_root: str = "") -> None:
    """在独立线程中执行 LangGraph 分析任务。

    此函数在 ThreadPoolExecutor 的独立线程中运行，不是 async 函数。
    Playwright Sync API（sync_playwright()）可以在此线程中正常工作。
    """
    import threading as _threading
    logger.info("服务层: 开始任务 job_id=%s, keyword=%s, thread=%s",
                job_id, request.keyword, _threading.current_thread().name)

    # 运行时保护：检测 asyncio loop
    _assert_worker_thread()

    # 获取 job（刚写入的）
    job = get_job(job_id, jobs_root)
    if not job:
        logger.error("服务层: job 不存在: %s", job_id)
        return

    try:
        # 更新为 running
        update_job(job_id, jobs_root, status="running")

        # 构造独立的 AppPaths
        paths = AppPaths.from_data_root(job.data_root)

        # 构造 LLM Client（两种模式都需要：llm_annotation 用于评论标注，rule 用于内容选题生成）
        llm_client = None
        if request.mock_llm:
            llm_client = MockLLMClient()
        elif request.analysis_mode == "llm_annotation":
            llm_client = OpenAICompatLLMClient()
        else:
            # rule 模式也尝试创建 LLM client 用于 ContentIdeationAgent
            try:
                llm_client = OpenAICompatLLMClient()
            except RuntimeError:
                logger.warning("LLM client 不可用，ContentIdeationAgent 将跳过")
                llm_client = None

        # 构造 Adapter
        config = XhsCollectConfig(
            keyword=request.keyword,
            max_posts=request.max_posts,
            max_comments_per_post=request.max_comments,
            headless=request.headless,
        )
        logger.info(
            "XHS collect config: keyword=%s, max_posts=%s, max_comments_per_post=%s, headless=%s",
            request.keyword, request.max_posts, request.max_comments, request.headless,
        )
        adapter = XhsPlaywrightAdapter(config=config)

        # 构造 LangGraph
        graph = build_ugc_market_graph(
            adapter=adapter,
            analysis_mode=request.analysis_mode,
            llm_client=llm_client,
            paths=paths,
        )

        # 构造请求
        analysis_request = AnalysisRequest(
            topic=request.keyword,
            product_direction=request.keyword,
            industry_question=f"分析 {request.keyword} 的用户需求、痛点、反馈和市场机会",
        )

        # 运行
        state = UGCGraphState(
            request=analysis_request,
            paths=paths,
        )

        # breakpoint()  # 🔴 BP3: graph.invoke 之前，所有零件已组装完毕
        # 检查: pp analysis_request, print(paths.data_root), print(analysis_mode)
        #       print(config), print(llm_client), pp state
        result = graph.invoke(state)

        # # breakpoint()  # 🔴 BP4: graph.invoke 之后，检查执行结果
        # 检查: pp dict(result.keys()), print(result.get("success"))
        #       print(result.get("raw_dataset")), print(result.get("report_path"))
        #       哪个字段是 None → 哪个节点就出了问题

        report_path = result.get("report_path", "")

        # P6.0 评论聚类 + 报告重渲染
        _run_comment_clustering(paths, result)
        _rerender_report_with_clusters(paths, result, topic=request.keyword)

        update_job(
            job_id, jobs_root, status="completed", report_path=report_path
        )
        logger.info("服务层: 任务完成 job_id=%s", job_id)

    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error("服务层: 任务异常 job_id=%s: %s", job_id, error_msg)
        update_job(job_id, jobs_root, status="failed", error=str(e)[:500])
