"""LangChainLLMClient 离线测试。不访问真实外部 API。"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.llm.client import (
    LangChainLLMClient,
    OpenAICompatLLMClient,
    MockLLMClient,
    extract_json_from_text,
)


class TestLangChainLLMClientInit(unittest.TestCase):
    """初始化测试。"""

    def tearDown(self):
        for k in ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"]:
            os.environ.pop(k, None)

    def test_raises_on_missing_env_vars(self):
        """缺少环境变量时抛出 RuntimeError。"""
        for k in ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"]:
            os.environ.pop(k, None)
        with self.assertRaises(RuntimeError) as ctx:
            LangChainLLMClient()
        self.assertIn("LLM_BASE_URL", str(ctx.exception))
        self.assertIn("LLM_API_KEY", str(ctx.exception))
        self.assertIn("LLM_MODEL", str(ctx.exception))

    def test_init_succeeds_with_env_vars(self):
        """设置环境变量后初始化成功。"""
        os.environ["LLM_BASE_URL"] = "https://api.openai.com/v1"
        os.environ["LLM_API_KEY"] = "sk-test"
        os.environ["LLM_MODEL"] = "gpt-4o-mini"
        client = LangChainLLMClient()
        self.assertEqual(client._base_url, "https://api.openai.com/v1")
        self.assertEqual(client._model, "gpt-4o-mini")

    def test_strips_trailing_slash_from_base_url(self):
        """base_url 尾部斜杠被去除。"""
        os.environ["LLM_BASE_URL"] = "https://api.openai.com/v1/"
        os.environ["LLM_API_KEY"] = "sk-test"
        os.environ["LLM_MODEL"] = "gpt-4o-mini"
        client = LangChainLLMClient()
        self.assertEqual(client._base_url, "https://api.openai.com/v1")

    def test_raises_on_single_missing_var(self):
        """仅缺少一个环境变量时也应报错。"""
        os.environ["LLM_BASE_URL"] = "https://api.openai.com/v1"
        os.environ["LLM_API_KEY"] = "sk-test"
        os.environ.pop("LLM_MODEL", None)
        with self.assertRaises(RuntimeError) as ctx:
            LangChainLLMClient()
        self.assertIn("LLM_MODEL", str(ctx.exception))
        self.assertNotIn("LLM_BASE_URL", str(ctx.exception))

    def test_reads_timeout_and_retries(self):
        """超时和重试次数从环境变量读取。"""
        os.environ["LLM_BASE_URL"] = "https://api.openai.com/v1"
        os.environ["LLM_API_KEY"] = "sk-test"
        os.environ["LLM_MODEL"] = "gpt-4o-mini"
        os.environ["LLM_TIMEOUT_SECONDS"] = "30"
        os.environ["LLM_MAX_RETRIES"] = "3"
        client = LangChainLLMClient()
        self.assertEqual(client._timeout, 30)
        self.assertEqual(client._max_retries, 3)

    def test_spawn_creates_independent_instance(self):
        """spawn() 应创建新的独立 LangChainLLMClient。"""
        os.environ["LLM_BASE_URL"] = "https://api.openai.com/v1"
        os.environ["LLM_API_KEY"] = "sk-test"
        os.environ["LLM_MODEL"] = "gpt-4o-mini"
        client = LangChainLLMClient()
        spawned = client.spawn()
        self.assertIsInstance(spawned, LangChainLLMClient)
        self.assertIsNot(spawned, client)
        self.assertIsNot(spawned._chat_openai, client._chat_openai)


class TestLangChainLLMClientGenerate(unittest.TestCase):
    """generate() 测试（mock ChatOpenAI）。"""

    def setUp(self):
        os.environ["LLM_BASE_URL"] = "https://api.openai.com/v1"
        os.environ["LLM_API_KEY"] = "sk-test"
        os.environ["LLM_MODEL"] = "gpt-4o-mini"

    def tearDown(self):
        for k in ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"]:
            os.environ.pop(k, None)

    @patch("langchain_openai.ChatOpenAI.invoke")
    def test_generate_returns_string(self, mock_invoke):
        """generate() 返回 LLM 原始文本。"""
        mock_message = MagicMock()
        mock_message.content = '{"sentiment": "positive"}'
        mock_invoke.return_value = mock_message

        client = LangChainLLMClient()
        result = client.generate("test prompt")
        self.assertIsInstance(result, str)
        self.assertEqual(result, '{"sentiment": "positive"}')

    @patch("langchain_openai.ChatOpenAI.invoke")
    def test_extract_json_after_generate(self, mock_invoke):
        """generate() 后通过 extract_json_from_text 提取 JSON。"""
        mock_message = MagicMock()
        mock_message.content = '{"sentiment": "positive", "confidence": 0.9}'
        mock_invoke.return_value = mock_message

        client = LangChainLLMClient()
        text = client.generate("test prompt")
        result = extract_json_from_text(text)
        self.assertIsNotNone(result)
        self.assertEqual(result, {"sentiment": "positive", "confidence": 0.9})

    @patch("langchain_openai.ChatOpenAI.invoke")
    def test_empty_content_raises(self, mock_invoke):
        """API 返回空 content 时抛出 RuntimeError。"""
        mock_message = MagicMock()
        mock_message.content = ""
        mock_invoke.return_value = mock_message

        client = LangChainLLMClient()
        with self.assertRaises(RuntimeError) as ctx:
            client.generate("test prompt")
        self.assertIn("空 content", str(ctx.exception))

    @patch("langchain_openai.ChatOpenAI.invoke")
    def test_invoke_error_raises_runtime_error(self, mock_invoke):
        """LangChain 调用异常应包装为 RuntimeError。"""
        mock_invoke.side_effect = Exception("Connection timeout")

        client = LangChainLLMClient()
        with self.assertRaises(RuntimeError) as ctx:
            client.generate("test prompt")
        self.assertIn("LangChainLLMClient", str(ctx.exception))
        self.assertIn("Connection timeout", str(ctx.exception))


class TestScoreFilter(unittest.TestCase):
    """评分字段过滤测试。"""

    def test_forbidden_fields_removed(self):
        from src.llm.score_filter import filter_forbidden_scores
        data = {
            "sentiment": "positive",
            "overall_score": 0.9,
            "demand_intensity": 0.8,
            "pain_points": [{"text": "test", "score": 0.5}],
        }
        filtered = filter_forbidden_scores(data)
        self.assertIn("sentiment", filtered)
        self.assertNotIn("overall_score", filtered)
        self.assertNotIn("demand_intensity", filtered)
        for pp in filtered.get("pain_points", []):
            self.assertNotIn("score", pp)

    def test_all_forbidden_fields_list(self):
        """所有禁止字段都应被过滤。"""
        from src.llm.score_filter import _FORBIDDEN_SCORE_FIELDS
        data = {f: i for i, f in enumerate(_FORBIDDEN_SCORE_FIELDS)}
        data["legitimate_field"] = "keep"
        from src.llm.score_filter import filter_forbidden_scores
        filtered = filter_forbidden_scores(data)
        self.assertIn("legitimate_field", filtered)
        for field in _FORBIDDEN_SCORE_FIELDS:
            self.assertNotIn(field, filtered)

    def test_nested_dict_filtering(self):
        """嵌套 dict 中的评分字段也应被过滤。"""
        from src.llm.score_filter import filter_forbidden_scores
        data = {
            "category": "test",
            "nested": {
                "overall_score": 0.95,
                "inner_data": {"value": 1},
            }
        }
        filtered = filter_forbidden_scores(data)
        self.assertIn("category", filtered)
        self.assertIn("nested", filtered)
        self.assertNotIn("overall_score", filtered["nested"])
        self.assertIn("inner_data", filtered["nested"])

    def test_preserves_non_forbidden_float_fields(self):
        """非禁止的浮点数/数字字段应被保留。"""
        from src.llm.score_filter import filter_forbidden_scores
        data = {
            "confidence": 0.85,
            "relevance": 0.7,
            "temperature": 0.5,
        }
        filtered = filter_forbidden_scores(data)
        self.assertIn("confidence", filtered)
        self.assertIn("relevance", filtered)

    def test_non_dict_input_passthrough(self):
        """非 dict 输入直接返回原值。"""
        from src.llm.score_filter import filter_forbidden_scores
        self.assertEqual(filter_forbidden_scores("string"), "string")
        self.assertEqual(filter_forbidden_scores(42), 42)
        self.assertEqual(filter_forbidden_scores(None), None)
        self.assertEqual(filter_forbidden_scores([1, 2, 3]), [1, 2, 3])


class TestDotEnvSupport(unittest.TestCase):
    """测试 .env 自动读取。"""

    def setUp(self):
        self._saved = {}
        for k in ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"]:
            self._saved[k] = os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_load_dotenv_makes_env_vars_available(self):
        """验证 dotenv 可以让环境变量生效。"""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False, encoding="utf-8") as f:
            f.write("LLM_BASE_URL=https://test.api.com/v1\n")
            f.write("LLM_API_KEY=sk-from-dotenv\n")
            f.write("LLM_MODEL=gpt-4o-mini\n")
            dotenv_path = f.name

        try:
            from dotenv import load_dotenv

            load_dotenv(dotenv_path=dotenv_path, override=True)
            # 直接创建新实例验证环境变量已生效（不 reload 模块，避免污染其他测试）
            client = LangChainLLMClient()
            self.assertEqual(client._base_url, "https://test.api.com/v1")
            self.assertEqual(client._api_key, "sk-from-dotenv")
            self.assertEqual(client._model, "gpt-4o-mini")
        finally:
            os.unlink(dotenv_path)
            for k in ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"]:
                os.environ.pop(k, None)


if __name__ == "__main__":
    unittest.main()
