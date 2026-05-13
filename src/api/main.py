"""FastAPI 应用入口。"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import traceback
from typing import Optional

# 在任何业务 import 之前配置 logging，确保所有模块的 logger.info() 有输出
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.api.jobs import (
    cancel_job,
    create_job,
    get_job,
    get_latest_completed_job,
    get_running_job,
    recover_stale_jobs,
    update_job,
)
from dotenv import load_dotenv

from src.api.schemas import APIAnalyzeRequest, APIJobResponse
from src.api.services import run_xhs_langgraph_analysis

logger = logging.getLogger(__name__)

# stale job 超时时间：10 分钟
# 一个正常的 Playwright 采集任务通常在 60-120 秒内完成。
# 超过 10 分钟仍为 pending/running 的 job 大概率是残留。
_STALE_JOB_TIMEOUT_SECONDS = 600


app = FastAPI(
    title="XHS Comment Insight Agent API",
    version="0.1.0",
    description="小红书评论洞察与文案选题助手 API",
)

# CORS（开发环境开放）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    """加载环境变量 + 恢复所有残留的 pending/running job。

    服务重启时，之前的 worker 线程已随进程销毁，所有标记为 running 或 pending 的 job
    都不可能再被继续执行。因此启动时无条件恢复所有 pending/running job，
    无论它们创建了多久。同时清理早于超时时间的 failed/completed job 避免 index 膨胀。
    """
    load_dotenv()

    # 无条件恢复所有 pending/running job（服务重启后这些 job 不可能再执行）
    recovered = recover_stale_jobs(max_age_seconds=0)
    if recovered:
        logger.info("启动时恢复了 %d 个残留 job", len(recovered))
        for r in recovered:
            logger.info("  recovered: %s (was %s)", r.job_id, r.status)


def _run_job_worker(job_id: str, request: APIAnalyzeRequest) -> None:
    """Worker thread：在一次性独立线程中执行分析任务。

    使用一次性线程而非线程池，避免复用执行过 Playwright Sync API
    的线程（可能残留 running asyncio loop）。
    """
    t = threading.current_thread()
    logger.info("worker 线程启动: job_id=%s, thread=%s, ident=%s",
                job_id, t.name, t.ident)
    try:
        run_xhs_langgraph_analysis(job_id, request)
        logger.info("worker 线程完成: job_id=%s", job_id)
    except Exception as exc:
        error_msg = traceback.format_exc()
        logger.error("worker 线程异常: job_id=%s: %s", job_id, error_msg)
        try:
            update_job(job_id, status="failed", error=str(exc)[:500])
        except Exception as update_err:
            logger.error("更新 job 失败状态时出错: %s", update_err)


def _start_job_thread(job_id: str, request: APIAnalyzeRequest) -> None:
    """启动一次性 worker 线程。"""
    thread = threading.Thread(
        target=_run_job_worker,
        args=(job_id, request),
        name=f"xhs_job_{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    logger.info("一次性线程已启动: job_id=%s, thread_name=%s, ident=%s",
                job_id, thread.name, thread.ident)


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# 分析任务
# ---------------------------------------------------------------------------


@app.post("/api/xhs/analyze", response_model=APIJobResponse)
def analyze(request: APIAnalyzeRequest):
    """提交小红书分析任务。

    每次调用创建一次性独立线程执行分析。
    如果已有任务运行中，返回 409 拒绝。
    但在检查前先恢复超时的 stale job，避免旧 job 永久阻塞。
    """
    if not request.keyword.strip():
        raise HTTPException(status_code=422, detail="keyword 不能为空")

    # 先恢复超时的 stale job
    recover_stale_jobs(max_age_seconds=_STALE_JOB_TIMEOUT_SECONDS)

    # 检查是否有任务正在运行
    running_job = get_running_job()
    if running_job:
        raise HTTPException(
            status_code=409,
            detail=f"当前已有任务运行中: {running_job.job_id}，请稍后再试",
        )

    job = create_job(request)
    report_url = f"/api/reports/{job.job_id}"

    _start_job_thread(job.job_id, request)

    return APIJobResponse(
        job_id=job.job_id,
        status=job.status,
        message="任务已提交",
        report_url=report_url,
        data_root=job.data_root,
    )


@app.post("/api/jobs/{job_id}/cancel")
def cancel_analysis_job(job_id: str):
    """取消正在运行或等待中的任务（仅标记状态，不杀线程）。

    仅开发/调试使用。生产环境如需强杀 Playwright 需另行设计。
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job 不存在")
    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=409, detail=f"任务状态为 {job.status}，不可取消")
    cancelled = cancel_job(job_id)
    logger.info("任务已取消: job_id=%s", job_id)
    return cancelled


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    """查询任务状态。"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job 不存在")
    return job


# ---------------------------------------------------------------------------
# 报告获取
# ---------------------------------------------------------------------------


@app.get("/api/reports/{job_id}")
def get_report(job_id: str):
    """获取任务报告。

    只要 report.html 存在就允许访问，不限制 job.status。
    包括 completed / failed 等状态。
    报告是审核和人工核查的基础，不是审核的门禁。
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job 不存在")

    # 优先使用 job.report_path，其次尝试 data_root/outputs/report.html
    report_path = job.report_path or ""
    if not report_path and job.data_root:
        report_path = os.path.join(job.data_root, "outputs", "report.html")

    if not report_path or not os.path.exists(report_path):
        raise HTTPException(status_code=404, detail="报告文件不存在")

    return FileResponse(report_path, media_type="text/html")


@app.get("/api/reports/latest")
def get_latest_report():
    """获取最近完成的报告。"""
    job = get_latest_completed_job()
    if not job:
        raise HTTPException(status_code=404, detail="没有已完成的任务")
    if not job.report_path or not os.path.exists(job.report_path):
        raise HTTPException(status_code=404, detail="报告文件不存在")
    return FileResponse(job.report_path, media_type="text/html")


@app.get("/api/jobs/{job_id}/quality-review")
def get_quality_review(job_id: str):
    """获取报告质量评审结果。"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job 不存在")
    review_path = os.path.join(job.data_root, "outputs", "report_quality_review.json")
    if not os.path.exists(review_path):
        return {"passed": None, "reasons": [], "summary": "未生成质量评审结果"}
    try:
        with open(review_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"passed": None, "reasons": [], "summary": "质量评审文件读取失败"}
