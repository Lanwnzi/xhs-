"""飞书机器人模块测试。

所有测试使用 mock，不真实调用飞书 API。
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---- Mock lark-oapi 模块（必须在 import feishu_bot 之前） ----
_FAKE_LARK = MagicMock()
_FAKE_LARK.ws = MagicMock()
_FAKE_LARK.ws.Client = MagicMock()
_FAKE_LARK.api = MagicMock()
_FAKE_LARK.api.im = MagicMock()
_FAKE_LARK.api.im.v1 = MagicMock()
sys.modules["lark_oapi"] = _FAKE_LARK
sys.modules["lark_oapi.ws"] = _FAKE_LARK.ws
sys.modules["lark_oapi.api"] = _FAKE_LARK.api
sys.modules["lark_oapi.api.im"] = _FAKE_LARK.api.im
sys.modules["lark_oapi.api.im.v1"] = _FAKE_LARK.api.im.v1

# 现在安全地 import 飞书机器人模块
from src.integrations.feishu_bot import (
    FeishuBot,
    FeishuMessageSender,
    HELP_MESSAGE,
    _LARK_AVAILABLE,
    create_bot_from_env,
    parse_analysis_command,
)


def _make_text_event(text: str, chat_type: str = "p2p", open_id: str = "test_user") -> MagicMock:
    """创建文本消息事件 mock — 模块级共享 helper。

    lark-oapi 1.x 中 sender 位于 event.event.sender，
    而非 event.event.message.sender。
    """
    event = MagicMock()
    msg_event = MagicMock()
    event.event = msg_event
    msg_event.message = MagicMock()
    msg_event.message.content = json.dumps({"text": text})
    msg_event.message.chat_type = chat_type
    msg_event.message.chat_id = "test_chat"
    msg_event.sender = MagicMock()
    msg_event.sender.sender_id = MagicMock()
    msg_event.sender.sender_id.open_id = open_id
    return event


class TestParseAnalysisCommand(unittest.TestCase):
    """parse_analysis_command 单元测试。"""

    def test_parse_analysis_command_valid(self):
        """"分析 控油洗发水" -> "控油洗发水" """
        result = parse_analysis_command("分析 控油洗发水")
        self.assertEqual(result, "控油洗发水")

    def test_parse_analysis_command_with_spaces(self):
        """多空格关键词应被正确 trim。"""
        result = parse_analysis_command("分析   控油")
        self.assertEqual(result, "控油")

    def test_parse_analysis_command_no_match(self):
        """不匹配的输入返回 None。"""
        result = parse_analysis_command("你好")
        self.assertIsNone(result)

    def test_parse_analysis_command_empty(self):
        """空输入返回 None。"""
        self.assertIsNone(parse_analysis_command(""))
        self.assertIsNone(parse_analysis_command(None))

    def test_parse_analysis_command_only_keyword(self):
        """仅"分析"无关键词返回 None。"""
        result = parse_analysis_command("分析")
        self.assertIsNone(result)

    def test_parse_analysis_command_multi_word(self):
        """多词关键词应完整保留。"""
        result = parse_analysis_command("分析 敏感肌 洗面奶")
        self.assertEqual(result, "敏感肌 洗面奶")


class TestFeishuMessageSender(unittest.TestCase):
    """FeishuMessageSender 单元测试。"""

    @patch("httpx.Client")
    def test_send_text_success(self, mock_httpx_client_cls):
        """send_text 成功发送消息。"""
        mock_client = MagicMock()
        mock_httpx_client_cls.return_value = mock_client

        # 模拟 token 刷新响应
        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = {
            "code": 0,
            "tenant_access_token": "test_access_token",
            "expire": 7200,
        }
        # 模拟发送消息响应
        mock_send_resp = MagicMock()
        mock_send_resp.json.return_value = {
            "code": 0,
            "data": {"message_id": "test_msg_001"},
        }
        mock_client.post.side_effect = [mock_token_resp, mock_send_resp]

        sender = FeishuMessageSender("test_app_id", "test_app_secret")
        result = sender.send_text("test_open_id", "Hello 飞书")

        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["message_id"], "test_msg_001")

        # 验证两次 POST 调用
        self.assertEqual(mock_client.post.call_count, 2)
        # 第一次调用是获取 token
        token_call = mock_client.post.call_args_list[0]
        self.assertIn("auth/v3/tenant_access_token/internal", token_call[0][0])
        # 第二次调用是发送消息
        send_call = mock_client.post.call_args_list[1]
        self.assertIn("im/v1/messages", send_call[0][0])

    @patch("httpx.Client")
    def test_send_text_failure(self, mock_httpx_client_cls):
        """send_text 失败时抛出异常。"""
        mock_client = MagicMock()
        mock_httpx_client_cls.return_value = mock_client

        # 模拟 token 刷新成功
        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = {
            "code": 0,
            "tenant_access_token": "test_token",
            "expire": 7200,
        }
        # 模拟发送消息失败
        mock_send_resp = MagicMock()
        mock_send_resp.json.return_value = {
            "code": 99991663,
            "msg": "invalid auth",
        }
        mock_client.post.side_effect = [mock_token_resp, mock_send_resp]

        sender = FeishuMessageSender("test_app_id", "test_app_secret")
        with self.assertRaises(RuntimeError) as ctx:
            sender.send_text("test_open_id", "test")
        self.assertIn("发送飞书消息失败", str(ctx.exception))

    @patch("httpx.Client")
    def test_send_text_with_token_cache(self, mock_httpx_client_cls):
        """验证 token 缓存机制：两次发送只刷新一次 token。"""
        mock_client = MagicMock()
        mock_httpx_client_cls.return_value = mock_client

        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = {
            "code": 0,
            "tenant_access_token": "cached_token",
            "expire": 7200,
        }
        mock_send_resp = MagicMock()
        mock_send_resp.json.return_value = {"code": 0}

        # 第一次：token + send；第二次：仅 send
        mock_client.post.side_effect = [
            mock_token_resp,
            mock_send_resp,
            mock_send_resp,
        ]

        sender = FeishuMessageSender("test_app_id", "test_app_secret")
        sender.send_text("uid1", "msg1")
        sender.send_text("uid2", "msg2")

        # token 只刷新一次
        token_calls = [
            c
            for c in mock_client.post.call_args_list
            if "auth/v3/tenant_access_token/internal" in c[0][0]
        ]
        self.assertEqual(len(token_calls), 1)


class TestFeishuBot(unittest.TestCase):
    """FeishuBot 消息处理测试。"""

    def _make_bot(self):
        """创建 FeishuBot 实例并 mock 内部依赖。"""
        self.assertTrue(_LARK_AVAILABLE, "lark-oapi mock 未生效")
        bot = FeishuBot("test_app_id", "test_app_secret")
        bot._sender = MagicMock()
        bot._ws_client = MagicMock()
        return bot

    @patch("src.api.jobs.create_job")
    def test_feishu_bot_handle_message_valid(self, mock_create_job):
        """有效分析指令应创建 job 并回复初始提交消息。"""
        mock_job = MagicMock()
        mock_job.job_id = "test_job_001"
        mock_create_job.return_value = mock_job

        bot = self._make_bot()
        event = _make_text_event("分析 控油洗发水")

        bot._handle_message(event)

        # 验证 create_job 被调用，且 keyword 正确
        mock_create_job.assert_called_once()
        request = mock_create_job.call_args[0][0]
        self.assertEqual(request.keyword, "控油洗发水")
        self.assertEqual(request.max_posts, 2)

        # 初始消息：不应包含"查看报告"（P4.2 禁止误导）
        bot._sender.send_text.assert_called_once()
        send_args = bot._sender.send_text.call_args
        reply_text = send_args[0][1]  # text 参数
        self.assertIn("完成后我会再次通知你", reply_text)
        self.assertIn("控油洗发水", reply_text)
        self.assertIn("test_job_001", reply_text)
        self.assertIn("任务编号", reply_text)
        self.assertNotIn("查看报告", reply_text)
        self.assertEqual(send_args[1]["receive_id_type"], "open_id")

    @patch("src.api.jobs.create_job")
    def test_feishu_bot_handle_message_invalid(self, mock_create_job):
        """非分析指令不应创建 job。"""
        bot = self._make_bot()
        event = _make_text_event("你好")

        bot._handle_message(event)

        mock_create_job.assert_not_called()
        bot._sender.send_text.assert_not_called()

    @patch("src.api.jobs.create_job")
    def test_feishu_bot_handle_help(self, mock_create_job):
        """"帮助" 应回复帮助文本。"""
        bot = self._make_bot()
        event = _make_text_event("帮助")

        bot._handle_message(event)

        mock_create_job.assert_not_called()
        bot._sender.send_text.assert_called_once()
        reply_text = bot._sender.send_text.call_args[0][1]
        self.assertIn("分析 <关键词>", reply_text)
        self.assertIn("小红书评论洞察助手", reply_text)

    def test_feishu_bot_handle_non_text(self):
        """非文本消息不处理。"""
        bot = self._make_bot()
        event = MagicMock()
        msg_event = MagicMock()
        event.event = msg_event
        msg_event.message = MagicMock()
        msg_event.message.content = json.dumps({"image_key": "xxx"})
        msg_event.message.chat_type = "p2p"

        bot._handle_message(event)
        bot._sender.send_text.assert_not_called()

    def test_feishu_bot_handle_none_content(self):
        """content 为 None 时不处理。"""
        bot = self._make_bot()
        event = MagicMock()
        msg_event = MagicMock()
        event.event = msg_event
        msg_event.message = MagicMock()
        msg_event.message.content = None

        bot._handle_message(event)
        bot._sender.send_text.assert_not_called()

    @patch("src.api.jobs.create_job")
    def test_feishu_bot_handle_analysis_only_keyword(self, mock_create_job):
        """仅"分析"无关键词应回复帮助。"""
        bot = self._make_bot()
        event = _make_text_event("分析")

        bot._handle_message(event)

        mock_create_job.assert_not_called()
        bot._sender.send_text.assert_called_once()
        reply_text = bot._sender.send_text.call_args[0][1]
        self.assertIn("分析 <关键词>", reply_text)


class TestFeishuBotNotification(unittest.TestCase):
    """飞书机器人任务完成/失败通知测试。"""

    def _make_bot(self):
        self.assertTrue(_LARK_AVAILABLE, "lark-oapi mock 未生效")
        bot = FeishuBot("test_id", "test_secret")
        bot._sender = MagicMock()
        bot._ws_client = MagicMock()
        return bot

    def _make_job_record(self, status="completed", data_root=None, error=None):
        job = MagicMock()
        job.status = status
        job.data_root = data_root
        job.error = error
        return job

    # ------------------------------------------------------------------
    # 初始提交消息
    # ------------------------------------------------------------------
    def test_sends_initial_submitted_message(self):
        """初始提交消息不应误导报告可用。"""
        with patch("src.api.jobs.create_job") as mock_create_job:
            mock_job = MagicMock()
            mock_job.job_id = "job_submit_001"
            mock_create_job.return_value = mock_job
            bot = self._make_bot()
            with patch("threading.Thread") as mock_thread:
                mock_thread.return_value = MagicMock()
                event = _make_text_event("分析 测试关键词")
                bot._handle_analysis_command_internal(event, "测试关键词")
                bot._sender.send_text.assert_called_once()
                reply = bot._sender.send_text.call_args[0][1]
                self.assertIn("测试关键词", reply)
                self.assertIn("job_submit_001", reply)
                self.assertIn("完成后我会再次通知你", reply)
                self.assertNotIn("查看报告", reply)

    # ------------------------------------------------------------------
    # 后台线程分发逻辑
    # ------------------------------------------------------------------
    def test_report_available_called_when_report_exists(self):
        """报告存在时调用 _notify_report_available。"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs = os.path.join(tmpdir, "outputs")
            os.makedirs(outputs)
            open(os.path.join(outputs, "report.html"), "w").close()

            with patch("src.api.jobs.create_job") as mock_create_job, \
                 patch("src.api.services.run_xhs_langgraph_analysis") as mock_run, \
                 patch("src.api.jobs.get_job") as mock_get_job, \
                 patch("threading.Thread") as mock_thread:

                mock_job = MagicMock()
                mock_job.job_id = "notify_job_001"
                mock_create_job.return_value = mock_job
                mock_get_job.return_value = self._make_job_record(
                    status="completed", data_root=tmpdir)
                mock_thread.return_value = MagicMock()

                bot = self._make_bot()
                bot._notify_report_available = MagicMock()
                bot._notify_job_failed = MagicMock()

                bot._handle_analysis_command_internal(
                    _make_text_event("分析 测试"), "测试")

                target_fn = mock_thread.call_args[1]["target"]
                target_fn()

                bot._notify_report_available.assert_called_once()
                bot._notify_job_failed.assert_not_called()

    def test_failed_no_report_calls_notify_job_failed(self):
        """报告不存在且任务失败时调用 _notify_job_failed。"""
        import tempfile, shutil
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmpdir, ignore_errors=True))
        os.makedirs(os.path.join(tmpdir, "outputs"), exist_ok=True)

        with patch("src.api.jobs.create_job") as mock_create_job, \
             patch("src.api.services.run_xhs_langgraph_analysis") as mock_run, \
             patch("src.api.jobs.get_job") as mock_get_job, \
             patch("threading.Thread") as mock_thread:

            mock_job = MagicMock()
            mock_job.job_id = "notify_job_fail_001"
            mock_create_job.return_value = mock_job
            mock_get_job.return_value = self._make_job_record(
                status="failed", data_root=tmpdir, error="采集失败")
            mock_thread.return_value = MagicMock()

            bot = self._make_bot()
            bot._notify_report_available = MagicMock()
            bot._notify_job_failed = MagicMock()

            bot._handle_analysis_command_internal(
                _make_text_event("分析 测试"), "测试")

            target_fn = mock_thread.call_args[1]["target"]
            target_fn()

            bot._notify_job_failed.assert_called_once()
            bot._notify_report_available.assert_not_called()

    # ------------------------------------------------------------------
    # _notify_report_available — 质量通过
    # ------------------------------------------------------------------
    def test_report_available_quality_passed(self):
        """质量通过时消息包含 ✅ 和通过标记及评分。"""
        import tempfile
        bot = self._make_bot()
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs = os.path.join(tmpdir, "outputs")
            os.makedirs(outputs)
            with open(os.path.join(outputs, "scorecard.json"), "w", encoding="utf-8") as f:
                json.dump({"overall_score": 8.0}, f)
            with open(os.path.join(outputs, "report_quality_review.json"),
                      "w", encoding="utf-8") as f:
                json.dump({"passed": True}, f)

            bot._notify_report_available(
                "job_001", "测试课程",
                self._make_job_record(data_root=tmpdir),
                "uid", "open_id",
            )

            text = bot._sender.send_text.call_args[0][1]
            self.assertIn("✅", text)
            self.assertIn("分析完成", text)
            self.assertIn("报告质量：通过", text)
            self.assertIn("8.0", text)
            self.assertIn("/api/reports/job_001", text)

    # ------------------------------------------------------------------
    # _notify_report_available — 质量未通过（含原因和建议）
    # ------------------------------------------------------------------
    def test_report_available_quality_failed(self):
        """质量未通过时消息包含 ⚠️、评审原因和修订建议。"""
        import tempfile
        bot = self._make_bot()
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs = os.path.join(tmpdir, "outputs")
            os.makedirs(outputs)
            with open(os.path.join(outputs, "report_quality_review.json"),
                      "w", encoding="utf-8") as f:
                json.dump({
                    "passed": False,
                    "hard_fail_reasons": ["热点选题仍然偏模板化", "代表评论证据不足"],
                    "reasons": ["缺少真实评论引用"],
                    "revision_instructions": ["每条选题建议需包含依据"],
                }, f)

            bot._notify_report_available(
                "job_002", "测试课程",
                self._make_job_record(data_root=tmpdir),
                "uid", "open_id",
            )

            text = bot._sender.send_text.call_args[0][1]
            self.assertIn("⚠️", text)
            self.assertIn("分析完成", text)
            self.assertIn("报告质量：未通过", text)
            self.assertIn("热点选题仍然偏模板化", text)
            self.assertIn("代表评论证据不足", text)
            self.assertIn("每条选题建议需包含依据", text)
            self.assertIn("/api/reports/job_002", text)

    # ------------------------------------------------------------------
    # _notify_report_available — 无质量评审文件
    # ------------------------------------------------------------------
    def test_report_available_no_review_file(self):
        """无质量评审文件时提示未生成评审结果。"""
        import tempfile
        bot = self._make_bot()
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs = os.path.join(tmpdir, "outputs")
            os.makedirs(outputs)

            bot._notify_report_available(
                "job_003", "测试",
                self._make_job_record(data_root=tmpdir),
                "uid", "open_id",
            )

            text = bot._sender.send_text.call_args[0][1]
            self.assertIn("⚠️", text)
            self.assertIn("未生成质量评审结果", text)
            self.assertIn("/api/reports/job_003", text)

    # ------------------------------------------------------------------
    # _notify_report_available — 任务失败但报告存在
    # ------------------------------------------------------------------
    def test_report_available_job_failed_but_report_exists(self):
        """任务失败但报告存在时仍发送报告链接，并注明状态异常。"""
        import tempfile
        bot = self._make_bot()
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs = os.path.join(tmpdir, "outputs")
            os.makedirs(outputs)
            with open(os.path.join(outputs, "report.html"), "w", encoding="utf-8") as f:
                f.write("<html>test</html>")

            bot._notify_report_available(
                "job_004", "测试",
                self._make_job_record(status="failed", data_root=tmpdir, error="页面超时"),
                "uid", "open_id",
            )

            text = bot._sender.send_text.call_args[0][1]
            self.assertIn("⚠️", text)
            self.assertIn("任务状态：failed", text)
            self.assertIn("页面超时", text)
            self.assertIn("/api/reports/job_004", text)

    # ------------------------------------------------------------------
    # _notify_report_available — 截断：原因和建议最多 3 条
    # ------------------------------------------------------------------
    def test_report_available_truncates_reasons(self):
        """评审原因和建议最多展示 3 条，超出的不显示。"""
        import tempfile
        bot = self._make_bot()
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs = os.path.join(tmpdir, "outputs")
            os.makedirs(outputs)
            with open(os.path.join(outputs, "report_quality_review.json"),
                      "w", encoding="utf-8") as f:
                json.dump({
                    "passed": False,
                    "hard_fail_reasons": [f"原因{i}" for i in range(1, 6)],
                    "revision_instructions": [f"建议{i}" for i in range(1, 6)],
                }, f)

            bot._notify_report_available(
                "job_005", "测试",
                self._make_job_record(data_root=tmpdir),
                "uid", "open_id",
            )

            text = bot._sender.send_text.call_args[0][1]
            # 前 3 条存在
            for i in range(1, 4):
                self.assertIn(f"原因{i}", text)
                self.assertIn(f"建议{i}", text)
            # 第 4 条不存在
            self.assertNotIn("原因4", text)
            self.assertNotIn("建议4", text)

    # ------------------------------------------------------------------
    # 发送失败不阻塞
    # ------------------------------------------------------------------
    def test_notification_failure_does_not_fail_job(self):
        """飞书发送失败只记录 warning，不抛异常。"""
        bot = self._make_bot()
        bot._sender.send_text.side_effect = RuntimeError("飞书网络异常")

        bot._notify_report_available(
            "job_006", "测试",
            self._make_job_record(data_root=None),
            "uid", "open_id",
        )

        bot._sender.send_text.assert_called_once()

    # ------------------------------------------------------------------
    # _notify_job_failed — 无报告时的失败通知
    # ------------------------------------------------------------------
    def test_notify_job_failed_contains_error(self):
        """失败通知必须包含错误原因。"""
        bot = self._make_bot()
        bot._notify_job_failed(
            "job_err_001", "测试",
            self._make_job_record(status="failed", data_root=None, error="采集超时"),
            "uid", "open_id",
        )

        bot._sender.send_text.assert_called_once()
        text = bot._sender.send_text.call_args[0][1]
        self.assertIn("❌", text)
        self.assertIn("分析失败", text)
        self.assertIn("采集超时", text)


class TestCreateBotFromEnv(unittest.TestCase):
    """create_bot_from_env 工厂函数测试。"""

    def setUp(self):
        self._env_backup = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env_backup)

    def test_create_bot_from_env_enabled(self):
        """启用 + 完整配置 -> 返回 FeishuBot 实例。"""
        os.environ["FEISHU_BOT_ENABLED"] = "true"
        os.environ["FEISHU_APP_ID"] = "cli_test_id"
        os.environ["FEISHU_APP_SECRET"] = "test_secret"
        os.environ["PUBLIC_REPORT_BASE_URL"] = "http://test:8000"

        bot = create_bot_from_env()
        self.assertIsNotNone(bot)
        self.assertIsInstance(bot, FeishuBot)

    def test_create_bot_from_env_disabled(self):
        """FEISHU_BOT_ENABLED=false -> 返回 None。"""
        os.environ["FEISHU_BOT_ENABLED"] = "false"
        bot = create_bot_from_env()
        self.assertIsNone(bot)

    def test_create_bot_from_env_missing_id(self):
        """FEISHU_APP_ID 为空 -> 返回 None。"""
        os.environ["FEISHU_BOT_ENABLED"] = "true"
        os.environ["FEISHU_APP_ID"] = ""
        os.environ["FEISHU_APP_SECRET"] = "test_secret"
        bot = create_bot_from_env()
        self.assertIsNone(bot)

    def test_create_bot_from_env_missing_secret(self):
        """FEISHU_APP_SECRET 为空 -> 返回 None。"""
        os.environ["FEISHU_BOT_ENABLED"] = "true"
        os.environ["FEISHU_APP_ID"] = "cli_test_id"
        os.environ["FEISHU_APP_SECRET"] = ""
        bot = create_bot_from_env()
        self.assertIsNone(bot)

    def test_create_bot_from_env_default_url(self):
        """未设置 PUBLIC_REPORT_BASE_URL -> 使用默认值。"""
        os.environ["FEISHU_BOT_ENABLED"] = "true"
        os.environ["FEISHU_APP_ID"] = "cli_test_id"
        os.environ["FEISHU_APP_SECRET"] = "test_secret"
        if "PUBLIC_REPORT_BASE_URL" in os.environ:
            del os.environ["PUBLIC_REPORT_BASE_URL"]

        bot = create_bot_from_env()
        self.assertIsNotNone(bot)


class TestFeishuBotEventHandlers(unittest.TestCase):
    """FeishuBot 事件处理内部逻辑测试。"""

    def test_get_message_text_valid(self):
        """_get_message_text 正确提取文本。"""
        bot = FeishuBot("test_id", "test_secret")
        bot._sender = MagicMock()
        bot._ws_client = MagicMock()
        event = _make_text_event("分析 控油洗发水")
        text = bot._get_message_text(event)
        self.assertEqual(text, "分析 控油洗发水")

    def test_get_message_text_no_text_field(self):
        """_get_message_text 处理无 text 字段的 content。"""
        bot = FeishuBot("test_id", "test_secret")
        bot._sender = MagicMock()
        bot._ws_client = MagicMock()
        event = MagicMock()
        msg_event = MagicMock()
        event.event = msg_event
        msg_event.message = MagicMock()
        msg_event.message.content = json.dumps({"image_key": "xxx"})
        text = bot._get_message_text(event)
        self.assertIsNone(text)

    def test_get_receive_id_p2p(self):
        """p2p 消息返回 (open_id, open_id)。"""
        bot = FeishuBot("test_id", "test_secret")
        bot._sender = MagicMock()
        bot._ws_client = MagicMock()
        event = _make_text_event("test", chat_type="p2p", open_id="user_open_id_001")
        receive_id, id_type = bot._get_receive_id(event)
        self.assertEqual(receive_id, "user_open_id_001")
        self.assertEqual(id_type, "open_id")

    def test_get_receive_id_group(self):
        """group 消息返回 (chat_id, chat_id)。"""
        bot = FeishuBot("test_id", "test_secret")
        bot._sender = MagicMock()
        bot._ws_client = MagicMock()
        event = _make_text_event("test", chat_type="group", open_id="user_001")
        receive_id, id_type = bot._get_receive_id(event)
        self.assertEqual(receive_id, "test_chat")
        self.assertEqual(id_type, "chat_id")

    @patch("src.api.jobs.create_job")
    def test_handle_analysis_command_starts_thread(self, mock_create_job):
        """_handle_analysis_command_internal 启动 daemon thread。"""
        mock_job = MagicMock()
        mock_job.job_id = "job_thread_test"
        mock_create_job.return_value = mock_job

        bot = FeishuBot("test_id", "test_secret")
        bot._sender = MagicMock()
        bot._ws_client = MagicMock()
        event = _make_text_event("分析 测试")

        with patch("threading.Thread") as mock_thread:
            mock_thread_instance = MagicMock()
            mock_thread.return_value = mock_thread_instance

            bot._handle_analysis_command_internal(event, "测试")

            mock_thread.assert_called_once()
            self.assertTrue(mock_thread.call_args[1].get("daemon", False))
            mock_thread_instance.start.assert_called_once()

            bot._sender.send_text.assert_called_once()


class TestFeishuBotGroupMessage(unittest.TestCase):
    """飞书机器人群聊消息处理测试。"""

    def _make_group_event(self, text, chat_id="group_chat_001"):
        event = MagicMock()
        msg_event = MagicMock()
        event.event = msg_event
        msg_event.message = MagicMock()
        msg_event.message.content = json.dumps({"text": text})
        msg_event.message.chat_type = "group"
        msg_event.message.chat_id = chat_id
        msg_event.sender = MagicMock()
        msg_event.sender.sender_id = MagicMock()
        msg_event.sender.sender_id.open_id = "user_in_group"
        return event

    @patch("src.api.jobs.create_job")
    def test_group_message_analysis(self, mock_create_job):
        """群聊中分析指令应回复群聊。"""
        mock_job = MagicMock()
        mock_job.job_id = "group_job_001"
        mock_create_job.return_value = mock_job

        bot = FeishuBot("test_id", "test_secret")
        bot._sender = MagicMock()
        bot._ws_client = MagicMock()
        event = self._make_group_event("分析 防晒霜", chat_id="group_abc")

        with patch("threading.Thread") as mock_thread:
            mock_thread_instance = MagicMock()
            mock_thread.return_value = mock_thread_instance

            bot._handle_message(event)

            mock_create_job.assert_called_once()
            request = mock_create_job.call_args[0][0]
            self.assertEqual(request.keyword, "防晒霜")

            bot._sender.send_text.assert_called_once()
            call_args = bot._sender.send_text.call_args
            self.assertEqual(call_args[0][0], "group_abc")
            self.assertEqual(call_args[1]["receive_id_type"], "chat_id")


class TestImportSafety(unittest.TestCase):
    """验证模块导入安全性。"""

    def test_feishu_bot_importable(self):
        """关键对象可正常导入。"""
        self.assertIsNotNone(FeishuBot)
        self.assertIsNotNone(FeishuMessageSender)
        self.assertIsNotNone(parse_analysis_command)
        self.assertIsNotNone(create_bot_from_env)

    def test_lark_available_true(self):
        """_LARK_AVAILABLE 应为 True。"""
        self.assertTrue(_LARK_AVAILABLE)


if __name__ == "__main__":
    unittest.main()
