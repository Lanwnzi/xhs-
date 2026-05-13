"""飞书机器人长连接接入模块。

使用 lark-oapi SDK 的 ws.Client（WebSocket 长连接）接收 im.message.receive_v1 事件。
使用 httpx 直接调用飞书 REST API 发送文本消息。

架构：
- parse_analysis_command() -- 纯函数解析 "分析 <关键词>"
- FeishuMessageSender -- 管理 tenant_access_token + 发送消息
- FeishuBot -- 主机器人类 (lark_oapi.ws.Client + EventDispatcherHandler)
- create_bot_from_env() -- 工厂函数
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# 懒加载 lark-oapi，不 import 具体子模块（版本兼容性）
_LARK_AVAILABLE = False
try:
    import lark_oapi as lark

    _LARK_AVAILABLE = True
except ImportError:
    lark = None  # type: ignore

# ---- 默认参数 ----
DEFAULT_MAX_POSTS = 2
DEFAULT_MAX_COMMENTS = 15
DEFAULT_ANALYSIS_MODE = "llm_annotation"
DEFAULT_MOCK_LLM = False
DEFAULT_HEADLESS = True

HELP_MESSAGE = (
    "你好！我是小红书评论洞察助手。\n\n"
    "你可以发送以下指令：\n"
    "  \xb7 分析 <关键词>  -- 启动小红书评论分析任务\n"
    "  \xb7 帮助           -- 查看此帮助信息\n\n"
    "示例：\n"
    "  \xb7 分析 控油洗发水\n"
    "  \xb7 分析 敏感肌 洗面奶\n"
    "  \xb7 分析 2025 防晒霜\n\n"
    "我会在分析完成后通知你。"
)


def parse_analysis_command(text: Optional[str]) -> Optional[str]:
    """从用户输入中解析 "分析 <关键词>" 指令。

    支持关键词中包含空格（如 "分析 敏感肌 洗面奶"），
    关键词部分保留原始空格作为完整关键词的一部分。

    返回：
        如果匹配则返回关键词，否则返回 None。
    """
    if not text or not text.strip():
        return None
    stripped = text.strip()
    prefix = "分析"
    if stripped == prefix:
        return None
    if stripped.startswith(prefix) and stripped[len(prefix) : len(prefix) + 1] in (
        " ",
        "\t",
    ):
        keyword = stripped[len(prefix) :].strip()
        return keyword if keyword else None
    return None


class FeishuMessageSender:
    """飞书消息发送器。

    使用 httpx 直接调用飞书 REST API 发送消息。
    自动管理 tenant_access_token 的获取和刷新（提前 60 秒刷新）。
    """

    _TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    _SEND_MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"

    def __init__(self, app_id: str, app_secret: str):
        self._app_id = app_id
        self._app_secret = app_secret
        self._token: Optional[str] = None
        self._token_expire_at: float = 0
        self._lock = threading.Lock()
        self._http_client = None

    def _get_http_client(self):
        """延迟创建 httpx 客户端。"""
        if self._http_client is None:
            import httpx

            self._http_client = httpx.Client(timeout=30)
        return self._http_client

    def _refresh_token(self) -> str:
        """获取新的 tenant_access_token。"""
        client = self._get_http_client()
        payload = {
            "app_id": self._app_id,
            "app_secret": self._app_secret,
        }
        logger.info("刷新飞书 tenant_access_token ...")
        resp = client.post(self._TOKEN_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
        code = data.get("code", -1)
        if code != 0:
            msg = data.get("msg", "unknown error")
            raise RuntimeError(f"获取飞书 token 失败: code={code}, msg={msg}")
        token = data["tenant_access_token"]
        expire = data.get("expire", 7200)
        self._token = token
        # 提前 60 秒刷新，避免边界情况
        self._token_expire_at = time.time() + expire - 60
        logger.info("飞书 tenant_access_token 刷新成功")
        return token

    def _get_valid_token(self) -> str:
        """获取有效 token，必要时自动刷新。"""
        with self._lock:
            if self._token is None or time.time() >= self._token_expire_at:
                return self._refresh_token()
            return self._token

    def send_text(
        self, receive_id: str, text: str, receive_id_type: str = "open_id"
    ) -> dict:
        """发送纯文本消息。

        POST https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=xxx

        Args:
            receive_id: 接收者 ID（open_id / chat_id / user_id）。
            text: 消息文本内容。
            receive_id_type: ID 类型，默认 open_id。

        Returns:
            飞书 API 响应 JSON。
        """
        token = self._get_valid_token()
        client = self._get_http_client()

        content = json.dumps({"text": text}, ensure_ascii=False)
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": content,
        }
        params = {"receive_id_type": receive_id_type}
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        logger.info(
            "发送飞书消息: receive_id_type=%s, receive_id=%s ...",
            receive_id_type,
            receive_id[:8] if receive_id else "",
        )
        resp = client.post(
            self._SEND_MESSAGE_URL,
            params=params,
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        code = data.get("code", -1)
        if code != 0:
            msg = data.get("msg", "unknown error")
            raise RuntimeError(f"发送飞书消息失败: code={code}, msg={msg}")
        logger.info("飞书消息发送成功")
        return data

    def close(self) -> None:
        """关闭 HTTP 客户端，释放连接。"""
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None


def _create_event_handler(callback) -> object:
    """创建 EventDispatcherHandler 并注册消息接收事件。

    lark-oapi 1.x 使用 builder 模式注册事件处理器。
    """
    if not _LARK_AVAILABLE:
        raise RuntimeError(
            "lark-oapi 未安装或版本不兼容。请执行: pip install -U lark-oapi"
        )
    builder = lark.EventDispatcherHandler.builder("", "")
    builder.register_p2_im_message_receive_v1(callback)
    return builder.build()


class FeishuBot:
    """飞书机器人主类。

    使用 lark_oapi.ws.Client 建立 WebSocket 长连接，
    接收 im.message.receive_v1 事件并处理分析指令。
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        public_report_base_url: str = "http://127.0.0.1:8000",
    ):
        if not _LARK_AVAILABLE:
            raise RuntimeError(
                "lark-oapi 未安装或版本不兼容。请执行: pip install -U lark-oapi"
            )
        self._app_id = app_id
        self._app_secret = app_secret
        self._public_report_base_url = public_report_base_url.rstrip("/")
        self._sender = FeishuMessageSender(app_id, app_secret)

        # 创建事件处理器（builder 模式）
        self._event_handler = _create_event_handler(self._handle_message)

        # 创建 WS 长连接客户端
        self._ws_client = lark.ws.Client(
            app_id=app_id,
            app_secret=app_secret,
            event_handler=self._event_handler,
            log_level=lark.LogLevel.INFO,
            domain=lark.FEISHU_DOMAIN,
            auto_reconnect=True,
        )
        self._running = False

    @staticmethod
    def _get_message_text(event) -> Optional[str]:
        """从事件中提取文本消息内容。

        event.event.message.content 是 JSON 字符串，如:
            {"text": "用户发送的消息"}

        在 lark-oapi 1.x 中，event.event 是 P2ImMessageReceiveV1Data 对象，
        其 .message 是 EventMessage 对象，.content 是 JSON 字符串。
        """
        try:
            message = event.event.message
            content_str = message.content
            if not content_str:
                return None
            content = json.loads(content_str)
            return content.get("text") if isinstance(content, dict) else None
        except (AttributeError, json.JSONDecodeError, KeyError, TypeError):
            return None

    @staticmethod
    def _get_receive_id(event) -> Tuple[str, str]:
        """从事件中提取接收者 ID 和 ID 类型。

        在 lark-oapi 1.x 中：
        - event.event.sender 是 EventSender 对象，包含 sender_id
          （sender 位于 event 层级，不在 message 层级）
        - event.event.message.chat_type 区分 p2p / group
        - event.event.message.chat_id 是群聊 ID

        Returns:
            (receive_id, id_type)
        """
        try:
            message = event.event.message
            chat_type = message.chat_type
            if chat_type == "p2p":
                sender = event.event.sender
                open_id = sender.sender_id.open_id
                return open_id, "open_id"
            else:
                chat_id = message.chat_id
                return chat_id, "chat_id"
        except AttributeError:
            return "", "open_id"

    def _send_message(self, event, text: str) -> None:
        """向事件发送者回复消息。"""
        receive_id, id_type = self._get_receive_id(event)
        if receive_id:
            self._sender.send_text(receive_id, text, receive_id_type=id_type)

    def _send_help(self, event) -> None:
        """发送帮助消息。"""
        self._send_message(event, HELP_MESSAGE)

    def _notify_report_available(
        self,
        job_id: str,
        keyword: str,
        job_record,
        receive_id: str,
        id_type: str,
    ) -> None:
        """发送报告可用通知（含质量评审详情）。

        只要 outputs/report.html 存在就调用此方法。
        根据 report_quality_review.json 内容决定消息格式：

        - passed=true  → ✅ 正常完成
        - passed=false → ⚠️ 含评审原因和修订建议
        - 文件不存在   → ⚠️ 提示未生成评审结果
        - job failed   → ⚠️ 提示任务异常但报告可用

        消息中的原因和建议最多各展示 3 条，避免过长。
        """
        import json
        import os

        report_url = f"{self._public_report_base_url}/api/reports/{job_id}"

        # 可选：读取评分
        score = None
        scorecard_path = os.path.join(
            job_record.data_root or "", "outputs", "scorecard.json"
        )
        if os.path.exists(scorecard_path):
            try:
                with open(scorecard_path, encoding="utf-8") as _f:
                    sc = json.load(_f)
                score = sc.get("overall_score")
            except Exception:
                pass

        # 读取质量评审（如果存在）
        quality_path = os.path.join(
            job_record.data_root or "", "outputs", "report_quality_review.json"
        )
        quality_data = None
        quality_passed: Optional[bool] = None
        if os.path.exists(quality_path):
            try:
                with open(quality_path, encoding="utf-8") as _f:
                    quality_data = json.load(_f)
                quality_passed = quality_data.get("passed")
            except Exception:
                pass

        lines: list[str] = []

        if quality_passed is True:
            # ---- ✅ 质量通过 ----
            lines.append("✅ 分析完成！")
            lines.append("")
            lines.append(f"关键词：{keyword}")
            lines.append(f"任务编号：{job_id}")
            if score is not None:
                lines.append(f"内容选题价值评分：{score:.1f}")
            lines.append("报告质量：通过")

        elif quality_passed is False:
            # ---- ⚠️ 质量未通过（展示原因和建议） ----
            lines.append(
                "⚠️ 分析完成，但报告质量评审未通过，建议人工核查。"
            )
            lines.append("")
            lines.append(f"关键词：{keyword}")
            lines.append(f"任务编号：{job_id}")
            if score is not None:
                lines.append(f"内容选题价值评分：{score:.1f}")
            lines.append("报告质量：未通过")

            if quality_data:
                hard_fail = quality_data.get("hard_fail_reasons", [])
                if hard_fail:
                    lines.append("")
                    lines.append("主要原因：")
                    for i, r in enumerate(hard_fail[:3], 1):
                        lines.append(f"{i}. {r}")

                reasons = quality_data.get("reasons", [])
                if reasons:
                    lines.append("")
                    lines.append("评审意见：")
                    for i, r in enumerate(reasons[:3], 1):
                        lines.append(f"{i}. {r}")

                instructions = quality_data.get("revision_instructions", [])
                if instructions:
                    lines.append("")
                    lines.append("修订建议：")
                    for i, ins in enumerate(instructions[:3], 1):
                        lines.append(f"{i}. {ins}")

        else:
            # ---- ⚠️ 未生成质量评审 ----
            lines.append(
                "⚠️ 分析完成，但未生成质量评审结果，建议人工核查。"
            )
            lines.append("")
            lines.append(f"关键词：{keyword}")
            lines.append(f"任务编号：{job_id}")
            if score is not None:
                lines.append(f"内容选题价值评分：{score:.1f}")
            lines.append("报告质量：未生成评审结果")

        # 如果任务状态不是 completed（如 failed 但报告存在），追加说明
        if job_record.status != "completed":
            lines.append("")
            lines.append(f"任务状态：{job_record.status}")
            err = (job_record.error or "")[:200]
            if err:
                lines.append(f"错误摘要：{err}")

        lines.append("")
        lines.append(f"查看完整报告：\n{report_url}")

        msg = "\n".join(lines)
        try:
            self._sender.send_text(receive_id, msg, receive_id_type=id_type)
            logger.info("飞书机器人: 已发送报告通知 job_id=%s", job_id)
        except Exception as e:
            logger.warning(
                "飞书机器人: 发送通知失败（不阻塞任务）: %s", e
            )

    def _notify_job_failed(
        self,
        job_id: str,
        keyword: str,
        job_record,
        receive_id: str,
        id_type: str,
    ) -> None:
        """发送分析失败通知（无报告可用）。"""
        error_msg = (job_record.error or "未知错误")[:200]
        msg = (
            f"❌ 分析失败\n"
            f"关键词：{keyword}\n"
            f"任务编号：{job_id}\n"
            f"原因：{error_msg}"
        )
        try:
            self._sender.send_text(receive_id, msg, receive_id_type=id_type)
            logger.info("飞书机器人: 已发送失败通知 job_id=%s", job_id)
        except Exception as e:
            logger.warning(
                "飞书机器人: 发送失败通知出错（不阻塞任务）: %s", e
            )

    def _handle_analysis_command_internal(self, event, keyword: str) -> None:
        """处理分析指令：创建 job -> 启动线程 -> 回复用户。

        P4.2 增强：
        - 第一条消息只提示任务已提交，不误导用户以为报告可用。
        - 后台分析线程执行完毕后，读取 job 状态并主动推送完成/失败通知。
        """
        from src.api.jobs import create_job
        from src.api.schemas import APIAnalyzeRequest
        from src.api.services import run_xhs_langgraph_analysis

        request = APIAnalyzeRequest(
            keyword=keyword,
            max_posts=DEFAULT_MAX_POSTS,
            max_comments=DEFAULT_MAX_COMMENTS,
            analysis_mode=DEFAULT_ANALYSIS_MODE,
            mock_llm=DEFAULT_MOCK_LLM,
            headless=DEFAULT_HEADLESS,
        )
        job = create_job(request)
        job_id = job.job_id
        logger.info(
            "飞书机器人: 创建分析任务 job_id=%s, keyword=%s", job_id, keyword
        )

        # 缓存通知上下文（receive_id 在 daemon thread 完成后仍需要）
        receive_id, id_type = self._get_receive_id(event)

        # ---- 封装后台线程：执行分析 + 完成后通知 ----
        def _run_and_notify():
            try:
                run_xhs_langgraph_analysis(job_id, request)
            finally:
                try:
                    from src.api.jobs import get_job

                    job_record = get_job(job_id)
                    if job_record is None or not job_record.data_root:
                        logger.warning(
                            "飞书机器人: 分析后 job 未找到 job_id=%s",
                            job_id,
                        )
                        return

                    import os as _os

                    report_path = _os.path.join(
                        job_record.data_root, "outputs", "report.html"
                    )
                    report_exists = _os.path.exists(report_path)

                    if report_exists:
                        # 报告存在 → 无论 job 状态如何都发送报告链接
                        self._notify_report_available(
                            job_id, keyword, job_record,
                            receive_id, id_type,
                        )
                    elif job_record.status == "failed":
                        # 无报告 + 任务失败 → 发送失败通知
                        self._notify_job_failed(
                            job_id, keyword, job_record,
                            receive_id, id_type,
                        )
                    else:
                        logger.warning(
                            "飞书机器人: 报告文件不存在但状态为 %s "
                            "job_id=%s",
                            job_record.status, job_id,
                        )

                except Exception as notify_err:
                    logger.warning(
                        "飞书机器人: 通知发送失败（不阻塞任务）: %s",
                        notify_err,
                    )

        thread = threading.Thread(
            target=_run_and_notify,
            name=f"feishu_job_{job_id[:8]}",
            daemon=True,
        )
        thread.start()

        # ---- 立即回复用户：任务已提交（不误导报告可用） ----
        reply = (
            f"已收到！正在分析「{keyword}」的相关内容。\n"
            f"任务编号：{job_id}\n\n"
            f"请稍候，分析可能需要 1-3 分钟，"
            f"完成后我会再次通知你。"
        )
        self._send_message(event, reply)

    def _handle_message(self, event) -> None:
        """处理收到的消息事件。

        1. 提取文本内容
        2. 解析 "分析 <关键词>" 指令
        3. 匹配则启动分析任务，其他情况按需回复帮助
        """
        text = self._get_message_text(event)
        if text is None:
            # 非文本消息不处理
            return

        keyword = parse_analysis_command(text)
        if keyword is not None:
            self._handle_analysis_command_internal(event, keyword)
        else:
            stripped = text.strip()
            # 对 "分析"（无关键词）和 "帮助" 等回复帮助信息
            if stripped in ("分析", "帮助", "help", "?", "？"):
                self._send_help(event)
            # 其他消息不回复，避免骚扰

    def start(self) -> None:
        """启动飞书机器人长连接（blocking）。

        注册 im.message.receive_v1 事件处理器后，
        调用 ws.Client.start() 建立 WebSocket 长连接。
        此方法会阻塞当前线程。
        """
        if not _LARK_AVAILABLE:
            raise RuntimeError(
                "lark-oapi 未安装或版本不兼容。请执行: pip install -U lark-oapi"
            )
        self._running = True
        logger.info(
            "飞书机器人: 启动 WebSocket 长连接 (app_id=%s)",
            self._app_id[:6] + "...",
        )
        self._ws_client.start()

    def stop(self) -> None:
        """停止飞书机器人，关闭 HTTP 客户端。"""
        self._running = False
        logger.info("飞书机器人: 关闭连接 ...")
        self._sender.close()
        logger.info("飞书机器人: 已停止")


def create_bot_from_env() -> Optional[FeishuBot]:
    """从环境变量创建飞书机器人。

    环境变量：
        FEISHU_BOT_ENABLED   -- 启用开关（设为 true/1/yes 启用）
        FEISHU_APP_ID        -- 飞书应用 ID
        FEISHU_APP_SECRET    -- 飞书应用 Secret（禁止写入日志）
        PUBLIC_REPORT_BASE_URL -- 报告公开访问地址（默认 http://127.0.0.1:8000）

    返回：
        FeishuBot 实例，如果配置不完整或未启用则返回 None。
    """
    enabled = os.getenv("FEISHU_BOT_ENABLED", "").lower() in ("true", "1", "yes")
    if not enabled:
        logger.info("飞书机器人未启用 (FEISHU_BOT_ENABLED 不为 true)")
        return None

    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    public_base = (
        os.getenv("PUBLIC_REPORT_BASE_URL", "http://127.0.0.1:8000").strip()
    )

    if not app_id:
        logger.error("飞书机器人配置不完整: FEISHU_APP_ID 为空")
        return None
    if not app_secret:
        logger.error("飞书机器人配置不完整: FEISHU_APP_SECRET 为空")
        return None
    if not _LARK_AVAILABLE:
        logger.error(
            "lark-oapi 未安装或版本不兼容。请执行: pip install -U lark-oapi"
        )
        return None

    logger.info("飞书机器人配置加载成功: app_id=%s", app_id[:6] + "...")
    return FeishuBot(
        app_id=app_id,
        app_secret=app_secret,
        public_report_base_url=public_base,
    )
