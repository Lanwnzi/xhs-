"""
XhsPlaywrightPipeline 入口脚本的离线测试。

不访问真实小红书，不启动 Playwright。
使用 mock 拦截 Pipeline 构造，验证 adapter 注入。
"""

from __future__ import annotations

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Mock playwright BEFORE any imports that might trigger its import.
# This ensures the test is truly offline and does not require playwright.
# ---------------------------------------------------------------------------
sys.modules["playwright"] = MagicMock()
sys.modules["playwright.sync_api"] = MagicMock()

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.run_xhs_playwright_pipeline import parse_args, main
from src.adapters.xhs_playwright_adapter import XhsPlaywrightAdapter
from src.schemas import AnalysisRequest
from src.utils import resolve_max_comments


class TestResolveMaxComments(unittest.TestCase):
    """max_comments 参数解析测试。"""

    def test_default(self):
        """max_comments 和 max_comments_per_post 均为 None 时返回默认值 20。"""
        self.assertEqual(resolve_max_comments(None, None), 20)

    def test_max_comments(self):
        """max_comments 为 15 时返回 15。"""
        self.assertEqual(resolve_max_comments(15, None), 15)

    def test_max_comments_per_post(self):
        """max_comments_per_post 为 25 时返回 25（覆盖 max_comments）。"""
        self.assertEqual(resolve_max_comments(10, 25), 25)

    def test_both_zero_returns_zero(self):
        """两者均为 0 时返回 0（0 是合法值，不再被视为"未指定"）。"""
        self.assertEqual(resolve_max_comments(0, 0), 0)

    def test_none_with_default(self):
        """两个参数都是 None 时使用指定的 default 值。"""
        self.assertEqual(resolve_max_comments(None, None, default=30), 30)

    def test_max_comments_per_post_overrides(self):
        """max_comments_per_post 优先级高于 max_comments。"""
        self.assertEqual(resolve_max_comments(5, 10), 10)


class TestCliArgs(unittest.TestCase):
    """CLI 参数解析测试。"""

    def test_keyword_required(self):
        """--keyword 是必填参数，缺失时抛出 SystemExit。"""
        with self.assertRaises(SystemExit):
            parse_args([])

    def test_parse_keyword(self):
        """--keyword 被正确解析。"""
        args = parse_args(["--keyword", "控油洗发水"])
        self.assertEqual(args.keyword, "控油洗发水")

    def test_parse_max_comments(self):
        """--max-comments 参数可正常解析。"""
        args = parse_args(["--keyword", "test", "--max-comments", "15"])
        self.assertEqual(args.max_comments, 15)

    def test_parse_max_comments_per_post(self):
        """--max-comments-per-post 参数可正常解析。"""
        args = parse_args(["--keyword", "test", "--max-comments-per-post", "25"])
        self.assertEqual(args.max_comments_per_post, 25)

    def test_default_max_posts(self):
        """--max-posts 默认值为 3。"""
        args = parse_args(["--keyword", "test"])
        self.assertEqual(args.max_posts, 3)

    def test_request_interval_default(self):
        """--request-interval-seconds 默认值为 3.0。"""
        args = parse_args(["--keyword", "test"])
        self.assertEqual(args.request_interval_seconds, 3.0)


class TestAdapterInjection(unittest.TestCase):
    """验证脚本正确构造并注入 adapter 到 Pipeline。"""

    def setUp(self):
        """每个测试前重置 mock 状态。"""
        self.patchers = []

    def tearDown(self):
        """每个测试后清理 patcher。"""
        for p in self.patchers:
            p.stop()
        self.patchers = []

    def _setup_mocks(self):
        """创建并启动 Pipeline 和 XhsPlaywrightAdapter 的 mock。"""
        pipe_patcher = patch(
            "scripts.run_xhs_playwright_pipeline.Pipeline"
        )
        adapter_patcher = patch(
            "scripts.run_xhs_playwright_pipeline.XhsPlaywrightAdapter"
        )
        self.patchers = [pipe_patcher, adapter_patcher]

        mock_pipeline_cls = pipe_patcher.start()
        mock_adapter_cls = adapter_patcher.start()

        mock_adapter_instance = MagicMock(spec=XhsPlaywrightAdapter)
        mock_adapter_cls.return_value = mock_adapter_instance

        mock_pipeline_instance = MagicMock()
        mock_pipeline_instance.run.return_value.success = True
        mock_pipeline_cls.return_value = mock_pipeline_instance

        return mock_pipeline_cls, mock_adapter_cls, mock_adapter_instance, mock_pipeline_instance

    def test_pipeline_receives_adapter(self):
        """Pipeline 被调用，且 adapter 参数为 XhsPlaywrightAdapter 实例。"""
        mock_pipeline_cls, _, mock_adapter_instance, _ = self._setup_mocks()

        test_args = ["--keyword", "测试", "--max-posts", "1"]
        with patch("sys.argv", ["run_xhs_playwright_pipeline.py"] + test_args):
            with self.assertRaises(SystemExit):
                main()

        # 断言 Pipeline.__init__ 被调用，且 adapter= 参数传入
        call_kwargs = mock_pipeline_cls.call_args.kwargs
        self.assertIn(
            "adapter",
            call_kwargs,
            "Pipeline 必须通过 adapter= 参数注入 XhsPlaywrightAdapter",
        )
        self.assertIs(
            call_kwargs["adapter"],
            mock_adapter_instance,
            "传入 Pipeline 的 adapter 必须是 XhsPlaywrightAdapter 实例",
        )

    def test_pipeline_is_constructed(self):
        """Pipeline 必须被构造一次（非默认空构造）。"""
        mock_pipeline_cls, _, _, _ = self._setup_mocks()

        test_args = ["--keyword", "测试", "--max-posts", "1"]
        with patch("sys.argv", ["run_xhs_playwright_pipeline.py"] + test_args):
            with self.assertRaises(SystemExit):
                main()

        # Pipeline 必须被调用一次
        mock_pipeline_cls.assert_called_once()

    def test_analysis_request_topic_matches_keyword(self):
        """AnalysisRequest.topic 应等于 --keyword 参数值。"""
        mock_pipeline_cls, _, _, mock_pipeline_instance = self._setup_mocks()

        test_args = ["--keyword", "控油洗发水", "--max-posts", "1"]
        with patch("sys.argv", ["run_xhs_playwright_pipeline.py"] + test_args):
            with self.assertRaises(SystemExit):
                main()

        # 获取传给 Pipeline.run 的 request
        call_args, _ = mock_pipeline_instance.run.call_args
        request = call_args[0]
        self.assertIsInstance(request, AnalysisRequest)
        self.assertEqual(
            request.topic,
            "控油洗发水",
            "AnalysisRequest.topic 必须等于 --keyword",
        )

    def test_pipeline_run_return_value_checked(self):
        """main() 在 pipeline.run 返回 success=False 时以非零码退出。"""
        mock_pipeline_cls, _, _, mock_pipeline_instance = self._setup_mocks()
        mock_pipeline_instance.run.return_value.success = False
        mock_pipeline_instance.run.return_value.error_message = "test error"

        test_args = ["--keyword", "测试", "--max-posts", "1"]
        with patch("sys.argv", ["run_xhs_playwright_pipeline.py"] + test_args):
            with self.assertRaises(SystemExit):
                main()

    def test_pipeline_run_return_value_success_exit_zero(self):
        """main() 在 pipeline.run 返回 success=True 时以 0 码退出。"""
        mock_pipeline_cls, _, _, mock_pipeline_instance = self._setup_mocks()
        mock_pipeline_instance.run.return_value.success = True

        test_args = ["--keyword", "测试", "--max-posts", "1"]
        with patch("sys.argv", ["run_xhs_playwright_pipeline.py"] + test_args):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
