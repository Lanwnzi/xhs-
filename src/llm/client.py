"""LLM 客户端抽象层。

BaseLLMClient — 抽象基类，只暴露 generate(prompt) -> str
LangChainLLMClient — 基于 langchain_openai.ChatOpenAI 的真实实现
MockLLMClient — 测试使用，返回固定 JSON 字符串

工具函数：
    extract_json_from_text — 从 LLM 输出文本中提取 JSON dict

配置环境变量：
    LLM_BASE_URL
    LLM_API_KEY
    LLM_MODEL
    LLM_TIMEOUT_SECONDS (默认 60)
    LLM_MAX_RETRIES (默认 2)
"""

from __future__ import annotations

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Optional

from dotenv import load_dotenv

# 自动从项目根目录加载 .env 文件
load_dotenv()

logger = logging.getLogger(__name__)


# ============================================================================
# 公共工具函数 — JSON 提取
# ============================================================================


def extract_json_from_text(text: str) -> dict[str, Any] | None:
    """从包含 markdown 代码块的文本中提取 JSON。

    处理 LLM 常见输出格式：

        ```json
        { ... }
        ```

        ```json
        {
          "key": "value"
        }
        ```

    返回解析后的 dict，解析失败返回 None。
    """
    # 尝试匹配 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        json_text = m.group(1).strip()
    else:
        # 尝试找到第一个 { 到最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            json_text = text[start:end + 1]
        else:
            return None

    try:
        result = json.loads(json_text)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass
    return None


# ============================================================================
# 抽象基类
# ============================================================================


class BaseLLMClient(ABC):
    """LLM 客户端抽象基类。

    所有实现只需提供一个方法：generate(prompt) -> str。
    JSON 提取、schema 校验等由业务方负责。
    """

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """调用 LLM 生成原始文本。

        返回 LLM 的原始文本输出（不解析、不校验）。

        抛出：
            RuntimeError: LLM 调用失败
        """
        ...

    def spawn(self) -> "BaseLLMClient":
        """创建新的独立实例（用于并发线程安全）。

        默认使用 __class__()，子类可覆盖以传递构造参数。
        """
        return self.__class__()


# ============================================================================
# LangChain LLM 实现
# ============================================================================


class LangChainLLMClient(BaseLLMClient):
    """基于 LangChain ChatOpenAI 的 LLM 客户端。

    从环境变量读取配置。缺少必需环境变量时抛出清晰 RuntimeError。
    """

    def __init__(self):
        from langchain_openai import ChatOpenAI

        self._base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
        self._api_key = os.getenv("LLM_API_KEY", "")
        self._model = os.getenv("LLM_MODEL", "")
        self._timeout = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
        self._max_retries = int(os.getenv("LLM_MAX_RETRIES", "2"))

        # 检查必需环境变量
        missing = []
        if not self._base_url:
            missing.append("LLM_BASE_URL")
        if not self._api_key:
            missing.append("LLM_API_KEY")
        if not self._model:
            missing.append("LLM_MODEL")
        if missing:
            raise RuntimeError(
                f"LangChainLLMClient: 缺少必需环境变量: {', '.join(missing)}。"
                f" 请设置环境变量或参考 .env.example。"
            )

        self._chat_openai = ChatOpenAI(
            model=self._model,
            base_url=self._base_url,
            api_key=self._api_key,
            temperature=0.1,
            timeout=self._timeout,
            max_retries=self._max_retries,
        )

    def generate(self, prompt: str) -> str:
        """调用 LangChain ChatOpenAI 生成原始文本。

        返回 LLM 的原始文本输出。
        retry/timeout 由 LangChain 内部处理。

        抛出：
            RuntimeError: LLM 调用失败
        """
        try:
            response = self._chat_openai.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            if not content:
                raise RuntimeError("LangChainLLMClient: API 返回空 content")
            return content
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"LangChainLLMClient: 调用失败: {e}") from e

    def spawn(self) -> "LangChainLLMClient":
        """创建新的独立 LangChainLLMClient 实例（含独立 ChatOpenAI）。"""
        return LangChainLLMClient()


# 向后兼容别名，后续版本移除
OpenAICompatLLMClient = LangChainLLMClient


# ============================================================================
# Mock LLM 实现
# ============================================================================


class MockLLMClient(BaseLLMClient):
    """Mock LLM 客户端，用于测试。

    generate() 返回 JSON 字符串（模拟 LLM 原始输出）。
    业务方需要自行调用 extract_json_from_text() 解析。

    参数：
        mock_response: 可选的预设响应 dict，提供时 generate() 始终返回其 JSON 字符串
    """

    def __init__(self, mock_response: Optional[dict[str, Any]] = None):
        self.mock_response = mock_response

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def generate(self, prompt: str = "") -> str:
        """返回 mock JSON 字符串。"""
        logger.info("MockLLMClient.generate(): 返回 mock 数据")
        if self.mock_response is not None:
            return json.dumps(self.mock_response, ensure_ascii=False)
        data = self._build_mock_response(prompt)
        return json.dumps(data, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Mock 响应构建
    # ------------------------------------------------------------------

    def _build_mock_response(self, prompt: str) -> dict[str, Any]:
        """根据 prompt 内容推断上下文并构建 mock 数据。"""
        # 检测 comment_annotation 模式
        if re.search(r'"index":\s*\d+\s*,\s*"content"', prompt):
            return self._build_comment_annotations(prompt)

        # 检测 content_ideation_perspective 模式
        if "content_ideation_perspective" in prompt or "suggestions" in prompt and "direction" in prompt:
            return self._build_perspective_suggestions(prompt)

        # 检测 content_ideation 模式
        if "topic_suggestions" in prompt and "custom_title_suggestions" in prompt:
            return self._build_content_ideation(prompt)

        # 默认固定响应（旧 schema 兼容）
        return {
            "sentiment": "positive",
            "confidence": 0.85,
            "reason": "测试用固定响应",
        }

    def _build_content_ideation(self, prompt: str) -> dict[str, Any]:
        """为 content_ideation schema 生成 mock 选题建议。"""
        return {
            "topic_suggestions": [
                {
                    "direction": "高频关注方向",
                    "title": f"小红书用户最关注的3个趋势（基于{prompt[:20]}...评论分析）",
                    "evidence": "多条评论提到用户关注点，如控油效果、温和配方等",
                    "content_angle": "从用户核心关注点出发，制作深度解析内容",
                },
                {
                    "direction": "用户疑问",
                    "title": "关于控油洗发水，这些高频疑问值得回应",
                    "evidence": "评论中出现了求推荐、如何选择等疑问",
                    "content_angle": "以FAQ形式整理常见问题，逐一解答",
                },
                {
                    "direction": "典型痛点",
                    "title": "避开这些误区：评论区用户踩坑经验总结",
                    "evidence": "用户反馈了价格、效果等方面的困扰",
                    "content_angle": "基于真实踩坑经验制作避坑指南",
                },
            ],
            "custom_title_suggestions": [
                {
                    "direction": "避坑指南",
                    "title": "控油洗发水选购避坑：评论区300条反馈总结出这几点",
                    "evidence": "用户反馈中多次出现价格、效果相关顾虑",
                    "content_angle": "收集用户真实反馈，制作选购避坑内容",
                },
                {
                    "direction": "答疑解惑",
                    "title": "控油洗发水怎么选？评论区高频问题一次讲清",
                    "evidence": "评论中有大量求推荐、怎么选等疑问",
                    "content_angle": "以决策指南形式呈现，帮助用户做出选择",
                },
                {
                    "direction": "实战经验",
                    "title": "真实用户分享：控油洗发水使用体验与推荐",
                    "evidence": "部分用户在评论中提到了具体产品和效果",
                    "content_angle": "整理真实体验，做对比评测型内容",
                },
            ],
        }

    def _build_perspective_suggestions(self, prompt: str) -> dict[str, Any]:
        """为 content_ideation_perspective schema 生成 mock 选题建议。"""
        return {
            "suggestions": [
                {
                    "direction": "Mock 视角",
                    "title": f"Mock 选题建议（基于{prompt[:30]}...）",
                    "evidence": "Mock 生成的依据",
                    "content_angle": "Mock 生成的文案角度",
                },
            ]
        }

    def _build_comment_annotations(self, prompt: str) -> dict[str, Any]:
        """从 prompt 解析 comments 并生成合法 annotations。

        只匹配 comments 数据中的 index（通过「content」字段区分），
        避免匹配模板示例中的 index。
        """
        annotations = []
        # 只匹配紧跟着 ,"content" 的 index，避免误匹配示例格式
        indices = re.findall(r'"index":\s*(\d+)\s*,\s*"content"', prompt)
        seen = set()
        for idx_str in indices:
            idx = int(idx_str)
            if idx not in seen:
                seen.add(idx)
                annotations.append({
                    "index": idx,
                    "sentiment": "neutral",
                    "pain_point_labels": [],
                    "need_labels": [],
                    "complaint_labels": [],
                    "solution_labels": [],
                    "market_signal_labels": [],
                    "intent_labels": [],
                    "reason": "mock annotation",
                })
        if not annotations:
            # fallback: 如果 prompt 中没有 index，返回一条默认 annotation
            annotations.append({
                "index": 0,
                "sentiment": "neutral",
                "pain_point_labels": [],
                "need_labels": [],
                "complaint_labels": [],
                "solution_labels": [],
                "market_signal_labels": [],
                "intent_labels": [],
                "reason": "mock annotation (fallback)",
            })
        return {"annotations": annotations}
