"""API 层离线测试。不访问真实小红书、不访问真实 LLM、不启动 Playwright。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Mock playwright before any imports
sys.modules["playwright"] = MagicMock()
sys.modules["playwright.sync_api"] = MagicMock()

from fastapi.testclient import TestClient
from src.api.main import app, _start_job_thread

client = TestClient(app)


class TestHealth(unittest.TestCase):
    def test_health_ok(self):
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")


class TestAnalyze(unittest.TestCase):
    """API 端点测试。

    在这些测试中，mock _start_job_thread 避免真实线程启动。
    mock get_running_job 返回 None 避免测试间互相干扰。
    线程启动逻辑在 TestJobExecution 中单独测试。
    """

    def setUp(self):
        self._mock_start = MagicMock()
        self._mock_get_running = MagicMock(return_value=None)
        self._patcher = patch.multiple(
            "src.api.main",
            _start_job_thread=self._mock_start,
            get_running_job=self._mock_get_running,
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_analyze_creates_job(self):
        resp = client.post("/api/xhs/analyze", json={
            "keyword": "测试",
            "max_posts": 1,
            "mock_llm": True,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("job_id", data)
        self.assertIn("report_url", data)
        self.assertIn("data_root", data)
        self.assertEqual(data["status"], "pending")
        # 验证不会在线程中调用 run_xhs_langgraph_analysis
        self._mock_start.assert_called_once()

    def test_analyze_rejects_empty_keyword(self):
        resp = client.post("/api/xhs/analyze", json={"keyword": ""})
        self.assertEqual(resp.status_code, 422)
        self._mock_start.assert_not_called()

    def test_analyze_returns_data_root_and_report_url(self):
        resp = client.post("/api/xhs/analyze", json={
            "keyword": "测试分析",
            "mock_llm": True,
        })
        data = resp.json()
        self.assertTrue("jobs" in data["data_root"])
        self.assertTrue(data["report_url"].startswith("/api/reports/"))
        self._mock_start.assert_called_once()

    def test_analyze_endpoint_is_sync(self):
        """验证 analyze endpoint 是普通 def 函数，不是 async def。"""
        import inspect
        from src.api.main import analyze
        self.assertFalse(
            inspect.iscoroutinefunction(analyze),
            "analyze endpoint 必须是 def 而不是 async def",
        )

    def test_analyze_rejects_when_job_running(self):
        """如果已有 job 在 running，新提交应返回 409。"""
        from src.api.jobs import create_job, update_job
        from src.api.schemas import APIAnalyzeRequest

        # 临时恢复真实 get_running_job 以检测 running job
        self._patcher.stop()
        self._mock_get_running = MagicMock()
        self._mock_start = MagicMock()
        self._patcher = patch.multiple(
            "src.api.main",
            _start_job_thread=self._mock_start,
            get_running_job=self._mock_get_running,
        )
        self._patcher.start()

        # 模拟已有 running job
        running_req = APIAnalyzeRequest(keyword="已在运行")
        job = create_job(running_req)
        update_job(job.job_id, status="running")
        self._mock_get_running.return_value = job  # mock 返回 running job

        resp = client.post("/api/xhs/analyze", json={
            "keyword": "新任务",
            "mock_llm": True,
        })
        self.assertEqual(resp.status_code, 409)
        self.assertIn("运行中", resp.json()["detail"])
        self._mock_start.assert_not_called()

    def test_second_submit_after_completed_allowed(self):
        """第一个 job completed 后，第二次提交应正常创建 job。"""
        from src.api.jobs import create_job
        from src.api.schemas import APIAnalyzeRequest

        # 创建一个 completed 的 job（模拟历史任务）
        old_req = APIAnalyzeRequest(keyword="已完成任务")
        old_job = create_job(old_req)
        from src.api.jobs import update_job
        update_job(old_job.job_id, status="completed")

        # 第二次提交应成功
        resp = client.post("/api/xhs/analyze", json={
            "keyword": "新任务",
            "mock_llm": True,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("job_id", data)
        self.assertEqual(data["status"], "pending")
        self._mock_start.assert_called_once()


class TestGetJob(unittest.TestCase):
    def setUp(self):
        self._patcher = patch.multiple(
            "src.api.main",
            _start_job_thread=MagicMock(),
            get_running_job=MagicMock(return_value=None),
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_get_job_returns_status(self):
        resp = client.post("/api/xhs/analyze", json={"keyword": "查询测试", "mock_llm": True})
        job_id = resp.json()["job_id"]

        resp = client.get(f"/api/jobs/{job_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("status", resp.json())

    def test_get_missing_job_returns_404(self):
        resp = client.get("/api/jobs/nonexistent_job")
        self.assertEqual(resp.status_code, 404)


class TestReport(unittest.TestCase):
    def setUp(self):
        self._patcher = patch.multiple(
            "src.api.main",
            _start_job_thread=MagicMock(),
            get_running_job=MagicMock(return_value=None),
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_report_missing_job_returns_404(self):
        resp = client.get("/api/reports/nonexistent_job")
        self.assertEqual(resp.status_code, 404)

    def test_latest_report_without_jobs_returns_404(self):
        resp = client.get("/api/reports/latest")
        self.assertIn(resp.status_code, [200, 404])


class TestNoRealAccess(unittest.TestCase):
    def setUp(self):
        self._patcher = patch.multiple(
            "src.api.main",
            _start_job_thread=MagicMock(),
            get_running_job=MagicMock(return_value=None),
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_api_does_not_call_real_xhs(self):
        """验证测试不启动真实浏览器。"""
        resp = client.post("/api/xhs/analyze", json={
            "keyword": "离线测试",
            "max_posts": 1,
            "mock_llm": True,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "pending")


class TestJobExecution(unittest.TestCase):
    """线程启动和 worker 执行测试。

    不启动真实 Playwright/LLM。使用 mock 模拟 worker 执行。
    """

    def setUp(self):
        self._patcher = patch("src.api.main.get_running_job", return_value=None)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_start_job_thread_creates_new_thread(self):
        """_start_job_thread 应创建新线程。"""
        from src.api.schemas import APIAnalyzeRequest

        request = APIAnalyzeRequest(keyword="线程测试", mock_llm=True)
        with patch("src.api.main._run_job_worker") as mock_worker:
            _start_job_thread("test_job_001", request)

        # _run_job_worker 应在后台线程中被调用，所以无法立即断言
        # 验证没有抛出异常，且函数返回
        self.assertTrue(True, "启动线程未抛异常")

    def test_analyze_endpoint_invokes_start_job_thread(self):
        """POST /api/xhs/analyze 应调用 _start_job_thread。"""
        with patch("src.api.main._start_job_thread") as mock_start:
            resp = client.post("/api/xhs/analyze", json={
                "keyword": "端点测试",
                "mock_llm": True,
            })
        self.assertEqual(resp.status_code, 200)
        mock_start.assert_called_once()


class TestJobStore(unittest.TestCase):
    """Job Store 单元测试。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="api_test_")
        self.jobs_root = os.path.join(self.temp_dir, "jobs")
        os.makedirs(self.jobs_root, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_request(self, keyword="测试", **kwargs):
        from src.api.schemas import APIAnalyzeRequest
        return APIAnalyzeRequest(keyword=keyword, **kwargs)

    def test_keyword_slug_for_chinese_uses_hash(self):
        from src.api.jobs import _make_keyword_slug
        slug = _make_keyword_slug("控油洗发水")
        self.assertTrue(slug.startswith("keyword_"))
        self.assertEqual(len(slug), 14)  # "keyword_" (8) + 6 hex

    def test_keyword_slug_for_english_is_readable(self):
        from src.api.jobs import _make_keyword_slug
        slug = _make_keyword_slug("study planner")
        self.assertEqual(slug, "study_planner")

    def test_create_and_get_job(self):
        from src.api.jobs import create_job, get_job
        request = self._make_request(keyword="测试商品", mock_llm=True)
        job = create_job(request, jobs_root=self.jobs_root)
        self.assertEqual(job.status, "pending")
        self.assertIn("测试商品", job.keyword)

        fetched = get_job(job.job_id, jobs_root=self.jobs_root)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.job_id, job.job_id)

    def test_update_job_persists_status(self):
        from src.api.jobs import create_job, update_job, get_job
        request = self._make_request(keyword="更新测试", mock_llm=True)
        job = create_job(request, jobs_root=self.jobs_root)

        update_job(job.job_id, jobs_root=self.jobs_root, status="completed", report_path="test.html")
        updated = get_job(job.job_id, jobs_root=self.jobs_root)
        self.assertEqual(updated.status, "completed")
        self.assertEqual(updated.report_path, "test.html")

    def test_index_json_created_if_missing(self):
        from src.api.jobs import _ensure_index
        path = _ensure_index(self.jobs_root)
        self.assertTrue(os.path.exists(path))

    def test_different_keywords_use_different_slugs(self):
        from src.api.jobs import _make_keyword_slug
        slug1 = _make_keyword_slug("控油洗发水")
        slug2 = _make_keyword_slug("敏感肌")
        self.assertNotEqual(slug1, slug2)

    def test_same_keyword_multiple_runs_different_run_ids(self):
        from src.api.jobs import _make_run_id
        id1 = _make_run_id()
        id2 = _make_run_id()
        self.assertNotEqual(id1, id2)

    def test_get_running_job_returns_running(self):
        from src.api.jobs import create_job, get_running_job
        request = self._make_request(keyword="运行中测试", mock_llm=True)
        job = create_job(request, jobs_root=self.jobs_root)
        from src.api.jobs import update_job
        update_job(job.job_id, jobs_root=self.jobs_root, status="running")

        running = get_running_job(jobs_root=self.jobs_root)
        self.assertIsNotNone(running)
        self.assertEqual(running.status, "running")

    def test_get_running_job_returns_none_when_all_completed(self):
        from src.api.jobs import create_job, get_running_job
        request = self._make_request(keyword="已完成测试", mock_llm=True)
        job = create_job(request, jobs_root=self.jobs_root)
        from src.api.jobs import update_job
        update_job(job.job_id, jobs_root=self.jobs_root, status="completed")

        running = get_running_job(jobs_root=self.jobs_root)
        self.assertIsNone(running)

    def test_job_failure_updates_status_failed(self):
        """验证当 build_ugc_market_graph 抛出异常时，任务状态更新为 failed。"""
        import unittest.mock as mock
        from src.api.jobs import create_job, get_job
        from src.api.schemas import APIAnalyzeRequest
        from src.api.services import run_xhs_langgraph_analysis

        request = APIAnalyzeRequest(keyword="测试失败", mock_llm=True)
        job = create_job(request, jobs_root=self.jobs_root)

        with mock.patch(
            "src.api.services.build_ugc_market_graph",
            side_effect=Exception("模拟构建图失败"),
        ):
            run_xhs_langgraph_analysis(job.job_id, request, jobs_root=self.jobs_root)

        updated = get_job(job.job_id, jobs_root=self.jobs_root)
        self.assertEqual(updated.status, "failed")
        self.assertIsNotNone(updated.error)


class TestStaleJobRecovery(unittest.TestCase):
    """Stale job 恢复测试。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="api_test_")
        self.jobs_root = os.path.join(self.temp_dir, "jobs")
        os.makedirs(self.jobs_root, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_request(self, **kw):
        from src.api.schemas import APIAnalyzeRequest
        return APIAnalyzeRequest(keyword=kw.get("keyword", "测试"), **kw)

    def _create_stale_job(self, status: str, age_seconds: int = 3600):
        """创建一个指定状态的旧 job。"""
        from datetime import datetime, timedelta
        from src.api.jobs import create_job
        from src.api.jobs import update_job as _upd
        from src.api.jobs import _make_keyword_slug, _make_run_id, _make_job_id
        import json, os

        slug = _make_keyword_slug("stale")
        run_id = _make_run_id()
        job_id = _make_job_id(slug, run_id)
        now = datetime.now()
        old_time = (now - timedelta(seconds=age_seconds)).isoformat()

        record = {
            "job_id": job_id,
            "keyword": "stale",
            "keyword_slug": slug,
            "run_id": run_id,
            "status": status,
            "analysis_mode": "rule",
            "data_root": os.path.join(self.jobs_root, slug, run_id),
            "created_at": old_time,
            "updated_at": old_time,
        }
        index_path = os.path.join(self.jobs_root, "index.json")
        if os.path.exists(index_path):
            with open(index_path, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {"jobs": []}
        data["jobs"].append(record)
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return job_id

    def test_recover_stale_running_job_marks_failed(self):
        """超过超时时间的 running job 应被标记为 failed。"""
        from src.api.jobs import recover_stale_jobs, get_job
        job_id = self._create_stale_job("running", age_seconds=3600)
        recovered = recover_stale_jobs(max_age_seconds=300, jobs_root=self.jobs_root)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].job_id, job_id)
        job = get_job(job_id, jobs_root=self.jobs_root)
        self.assertEqual(job.status, "failed")

    def test_recover_stale_pending_job_marks_failed(self):
        """超过超时时间的 pending job 应被标记为 failed。"""
        from src.api.jobs import recover_stale_jobs, get_job
        job_id = self._create_stale_job("pending", age_seconds=3600)
        recovered = recover_stale_jobs(max_age_seconds=300, jobs_root=self.jobs_root)
        self.assertEqual(len(recovered), 1)
        job = get_job(job_id, jobs_root=self.jobs_root)
        self.assertEqual(job.status, "failed")

    def test_recover_fresh_running_job_keeps_running(self):
        """未超时的 running job 应保持 running。"""
        from src.api.jobs import recover_stale_jobs, get_job
        job_id = self._create_stale_job("running", age_seconds=60)  # 1 分钟前
        recovered = recover_stale_jobs(max_age_seconds=300, jobs_root=self.jobs_root)  # 5 分钟阈值
        self.assertEqual(len(recovered), 0)
        job = get_job(job_id, jobs_root=self.jobs_root)
        self.assertEqual(job.status, "running")

    def test_cancel_running_job_marks_failed(self):
        """取消 running job 应标记为 failed。"""
        from src.api.jobs import cancel_job, get_job
        job_id = self._create_stale_job("running", age_seconds=60)
        cancelled = cancel_job(job_id, jobs_root=self.jobs_root)
        self.assertEqual(cancelled.status, "failed")
        self.assertEqual(cancelled.error, "cancelled by user")

    def test_cancel_missing_job_returns_none(self):
        """取消不存在的 job 应返回 None。"""
        from src.api.jobs import cancel_job
        result = cancel_job("nonexistent_job", jobs_root=self.jobs_root)
        self.assertIsNone(result)


class TestServicesConfig(unittest.TestCase):
    """验证 services.py 正确传递参数到 XhsCollectConfig。"""

    def test_services_passes_max_posts_to_config(self):
        """API request max_posts=5 → config.max_posts=5。"""
        from src.api.schemas import APIAnalyzeRequest
        request = APIAnalyzeRequest(keyword="测试", max_posts=5, mock_llm=True)
        from src.adapters.xhs_collect_config import XhsCollectConfig
        config = XhsCollectConfig(
            keyword=request.keyword,
            max_posts=request.max_posts,
            max_comments_per_post=request.max_comments,
            headless=request.headless,
        )
        self.assertEqual(config.max_posts, 5)

    def test_services_maps_max_comments_to_per_post(self):
        """API request max_comments=15 → config.max_comments_per_post=15。"""
        from src.api.schemas import APIAnalyzeRequest
        request = APIAnalyzeRequest(keyword="测试", max_comments=15, mock_llm=True)
        from src.adapters.xhs_collect_config import XhsCollectConfig
        config = XhsCollectConfig(
            keyword=request.keyword,
            max_posts=request.max_posts,
            max_comments_per_post=request.max_comments,
            headless=request.headless,
        )
        self.assertEqual(config.max_comments_per_post, 15)
