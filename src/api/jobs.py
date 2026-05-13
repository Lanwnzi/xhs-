"""Job 管理：JSON index + 目录隔离。"""

from __future__ import annotations

import json
import os
import re
import hashlib
import threading
import uuid
from datetime import datetime
from typing import Optional

from src.api.schemas import APIAnalyzeRequest, JobRecord

_JOBS_FILE = "data/jobs/index.json"
_JOBS_ROOT = "data/jobs"
_jobs_lock = threading.Lock()


def _get_project_root() -> str:
    """获取项目根目录。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ensure_jobs_dir(jobs_root: str = "") -> str:
    """确保 jobs 目录存在。"""
    root = jobs_root or os.path.join(_get_project_root(), _JOBS_ROOT)
    os.makedirs(root, exist_ok=True)
    return root


def _ensure_index(jobs_root: str = "") -> str:
    """确保 index.json 存在。"""
    root = jobs_root or os.path.join(_get_project_root(), _JOBS_ROOT)
    index_path = os.path.join(root, "index.json")
    if not os.path.exists(index_path):
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump({"jobs": []}, f, ensure_ascii=False, indent=2)
    return index_path


def _load_jobs(jobs_root: str = "") -> list[dict]:
    """加载 jobs 列表。"""
    index_path = _ensure_index(jobs_root)
    with open(index_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("jobs", [])


def _save_jobs(jobs: list[dict], jobs_root: str = "") -> None:
    """保存 jobs 列表。"""
    index_path = _ensure_index(jobs_root)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump({"jobs": jobs}, f, ensure_ascii=False, indent=2)


def _make_keyword_slug(keyword: str) -> str:
    """把 keyword 转为安全目录名。

    英文/数字保留并小写，空格/特殊字符转下划线。
    中文 keyword 使用 keyword_ + short_hash。
    """
    if all(ord(c) < 128 for c in keyword):
        slug = re.sub(r'[^a-zA-Z0-9]+', '_', keyword).strip('_').lower()
        if slug:
            return slug
    h = hashlib.md5(keyword.encode("utf-8")).hexdigest()[:6]
    return f"keyword_{h}"


def _make_run_id() -> str:
    """生成 run_id：timestamp + short uuid。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_uid = uuid.uuid4().hex[:6]
    return f"{ts}_{short_uid}"


def _make_job_id(keyword_slug: str, run_id: str) -> str:
    return f"{keyword_slug}_{run_id}"


def create_job(request: APIAnalyzeRequest, jobs_root: str = "") -> JobRecord:
    """创建 job，写入 index.json。"""
    keyword_slug = _make_keyword_slug(request.keyword)
    run_id = _make_run_id()
    job_id = _make_job_id(keyword_slug, run_id)
    now = datetime.now().isoformat()

    root = jobs_root or os.path.join(_get_project_root(), _JOBS_ROOT)
    data_root = os.path.join(root, keyword_slug, run_id)
    os.makedirs(os.path.join(data_root, "raw"), exist_ok=True)
    os.makedirs(os.path.join(data_root, "normalized"), exist_ok=True)
    os.makedirs(os.path.join(data_root, "outputs"), exist_ok=True)

    record = JobRecord(
        job_id=job_id,
        keyword=request.keyword,
        keyword_slug=keyword_slug,
        run_id=run_id,
        status="pending",
        analysis_mode=request.analysis_mode,
        mock_llm=request.mock_llm,
        max_posts=request.max_posts,
        max_comments=request.max_comments,
        headless=request.headless,
        data_root=data_root,
        created_at=now,
        updated_at=now,
    )

    with _jobs_lock:
        jobs = _load_jobs(jobs_root)
        jobs.append(record.model_dump())
        _save_jobs(jobs, jobs_root)
    return record


def update_job(job_id: str, jobs_root: str = "", **updates) -> Optional[JobRecord]:
    """更新 job 状态。"""
    with _jobs_lock:
        jobs = _load_jobs(jobs_root)
        for i, j in enumerate(jobs):
            if j.get("job_id") == job_id:
                j.update(updates)
                j["updated_at"] = datetime.now().isoformat()
                jobs[i] = j
                _save_jobs(jobs, jobs_root)
                return JobRecord(**j)
    return None


def get_job(job_id: str, jobs_root: str = "") -> Optional[JobRecord]:
    """查询 job。"""
    with _jobs_lock:
        jobs = _load_jobs(jobs_root)
        for j in jobs:
            if j.get("job_id") == job_id:
                return JobRecord(**j)
    return None


def get_latest_completed_job(jobs_root: str = "") -> Optional[JobRecord]:
    """获取最近完成的 job。"""
    with _jobs_lock:
        jobs = _load_jobs(jobs_root)
        completed = [JobRecord(**j) for j in jobs if j.get("status") == "completed"]
        if not completed:
            return None
        return max(completed, key=lambda j: j.updated_at)


def get_running_job(jobs_root: str = "") -> Optional[JobRecord]:
    """获取当前正在运行的 job。"""
    with _jobs_lock:
        jobs = _load_jobs(jobs_root)
        for j in jobs:
            if j.get("status") == "running":
                return JobRecord(**j)
    return None


def recover_stale_jobs(max_age_seconds: int = 1800, jobs_root: str = "") -> list[JobRecord]:
    """恢复 stale job：将超时的 running/pending job 标记为 failed。

    - pending/running 超时标记为 failed。
    - 使用 updated_at 比较（比 created_at 更准确反映最后活动时间）。
    - 如果时间解析失败，保守地将该 pending/running job 标记为 failed。
    - 不删除 job 目录，不删除已有产物。
    - 返回所有被恢复的 job 列表。
    """
    now = datetime.now()
    recovered: list[JobRecord] = []
    with _jobs_lock:
        jobs = _load_jobs(jobs_root)
        for j in jobs:
            status = j.get("status", "")

            if status not in ("pending", "running"):
                continue
            updated_str = j.get("updated_at", "") or j.get("created_at", "")
            if not updated_str:
                # 没有时间戳的 pending/running job → 保守标记为 failed
                j["status"] = "failed"
                j["error"] = "stale job recovered (no timestamp)"
                j["updated_at"] = now.isoformat()
                recovered.append(JobRecord(**j))
                continue
            try:
                updated = datetime.fromisoformat(updated_str)
                if updated.tzinfo is not None:
                    updated = updated.replace(tzinfo=None)
                is_stale = (now - updated).total_seconds() > max_age_seconds
            except (ValueError, TypeError):
                # 时间解析失败 → 保守标记为 failed
                is_stale = True

            if is_stale:
                j["status"] = "failed"
                j["error"] = "stale job recovered"
                j["updated_at"] = now.isoformat()
                recovered.append(JobRecord(**j))
        if recovered:
            _save_jobs(jobs, jobs_root)
    return recovered


def cancel_job(job_id: str, jobs_root: str = "") -> Optional[JobRecord]:
    """取消 job（仅标记为 failed，不杀线程）。"""
    return update_job(job_id, jobs_root, status="failed", error="cancelled by user")
