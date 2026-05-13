"""LLM 客户端单元测试。"""

from __future__ import annotations

import json
import sys
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import unittest

from src.llm.client import (
    BaseLLMClient,
    MockLLMClient,
    LangChainLLMClient,
    OpenAICompatLLMClient,
    extract_json_from_text,
)


class TestBaseLLMClient(unittest.TestCase):
    """BaseLLMClient 是抽象类，无法直接实例化。"""

    def test_cannot_instantiate(self):
        """直接实例化 BaseLLMClient 应抛出 TypeError。"""
        with self.assertRaises(TypeError):
            BaseLLMClient()  # type: ignore

    def test_spawn_creates_instance(self):
        """spawn() 应在子类上创建新实例。"""
        client = MockLLMClient()
        spawned = client.spawn()
        self.assertIsInstance(spawned, MockLLMClient)
        self.assertIsNot(spawned, client)


class TestMockLLMClient(unittest.TestCase):
    """MockLLMClient 测试。"""

    def test_generate_returns_string(self):
        """generate() 返回 JSON 字符串。"""
        client = MockLLMClient()
        result = client.generate("test prompt")
        self.assertIsInstance(result, str)
        # 应该是有效的 JSON
        data = json.loads(result)
        self.assertIsInstance(data, dict)

    def test_default_response(self):
        """默认 prompt 返回的 JSON 包含 sentiment 字段。"""
        client = MockLLMClient()
        text = client.generate("test prompt")
        result = extract_json_from_text(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["sentiment"], "positive")
        self.assertEqual(result["confidence"], 0.85)
        self.assertEqual(result["reason"], "测试用固定响应")

    def test_custom_mock_response(self):
        """自定义 mock_response 的 JSON 字符串。"""
        custom = {"sentiment": "negative", "confidence": 0.9, "reason": "自定义测试"}
        client = MockLLMClient(mock_response=custom)
        text = client.generate("test prompt")
        result = json.loads(text)
        self.assertEqual(result, custom)

    def test_empty_prompt(self):
        """空 prompt 不应影响 MockLLMClient。"""
        client = MockLLMClient()
        text = client.generate("")
        data = json.loads(text)
        self.assertIn("sentiment", data)

    def test_is_instance_of_base(self):
        """MockLLMClient 应是 BaseLLMClient 的子类。"""
        self.assertTrue(issubclass(MockLLMClient, BaseLLMClient))


class TestOpenAICompatLLMClientAlias(unittest.TestCase):
    """OpenAICompatLLMClient 向后兼容别名测试。"""

    def setUp(self):
        os.environ["LLM_BASE_URL"] = "https://api.openai.com/v1"
        os.environ["LLM_API_KEY"] = "sk-test"
        os.environ["LLM_MODEL"] = "gpt-4o-mini"

    def tearDown(self):
        for k in ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"]:
            os.environ.pop(k, None)

    def test_aliased_to_langchain_client(self):
        """OpenAICompatLLMClient 等同于 LangChainLLMClient。"""
        self.assertIs(OpenAICompatLLMClient, LangChainLLMClient)

    def test_is_instance_of_base(self):
        """OpenAICompatLLMClient 应是 BaseLLMClient 的子类。"""
        self.assertTrue(issubclass(OpenAICompatLLMClient, BaseLLMClient))

    def test_instantiation_succeeds(self):
        """设置环境变量后实例化成功。"""
        client = OpenAICompatLLMClient()
        self.assertIsInstance(client, LangChainLLMClient)
        self.assertEqual(client._model, "gpt-4o-mini")
        self.assertEqual(client._base_url, "https://api.openai.com/v1")

    def test_raises_when_env_vars_missing(self):
        """缺少环境变量时抛出 RuntimeError。"""
        for k in ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"]:
            os.environ.pop(k, None)
        with self.assertRaises(RuntimeError) as ctx:
            OpenAICompatLLMClient()
        self.assertIn("LLM_BASE_URL", str(ctx.exception))
        self.assertIn("LLM_API_KEY", str(ctx.exception))
        self.assertIn("LLM_MODEL", str(ctx.exception))


class TestMockLLMClientCommentAnnotation(unittest.TestCase):
    """MockLLMClient 对 comment_annotation 的 mock 支持。"""

    def setUp(self):
        self.client = MockLLMClient()

    def _generate_and_extract(self, prompt: str) -> dict:
        text = self.client.generate(prompt)
        result = extract_json_from_text(text)
        self.assertIsNotNone(result, f"extract_json_from_text returned None for: {text[:200]}")
        return result

    def test_returns_annotations_field(self):
        """返回结构必须包含 annotations 字段。"""
        prompt = '{"comments": [{"index": 0, "content": "test"}]}'
        result = self._generate_and_extract(prompt)
        self.assertIn("annotations", result)
        self.assertIsInstance(result["annotations"], list)

    def test_annotation_count_matches_prompt(self):
        """annotations 数量必须与 prompt 中的 comments 数量一致。"""
        prompt = '{"comments": [{"index": 0, "content": "a"}, {"index": 1, "content": "b"}, {"index": 2, "content": "c"}]}'
        result = self._generate_and_extract(prompt)
        self.assertEqual(len(result["annotations"]), 3)

    def test_each_annotation_has_required_fields(self):
        """每条 annotation 必须包含 index/sentiment/labels/reason。"""
        prompt = '{"comments": [{"index": 0, "content": "test"}]}'
        result = self._generate_and_extract(prompt)
        ann = result["annotations"][0]
        self.assertIn("index", ann)
        self.assertIn("sentiment", ann)
        self.assertIn("pain_point_labels", ann)
        self.assertIn("need_labels", ann)
        self.assertIn("complaint_labels", ann)
        self.assertIn("solution_labels", ann)
        self.assertIn("market_signal_labels", ann)
        self.assertIn("intent_labels", ann)
        self.assertIn("reason", ann)

    def test_old_format_prompt_returns_default(self):
        """旧格式 prompt 返回默认格式（包含 sentiment/confidence）。"""
        result = self._generate_and_extract("test prompt")
        self.assertIn("sentiment", result)
        self.assertIn("confidence", result)

    def test_mock_response_overrides(self):
        """用户传入 mock_response 时优先使用。"""
        custom = {"custom_key": "custom_value"}
        client = MockLLMClient(mock_response=custom)
        text = client.generate("any")
        result = json.loads(text)
        self.assertEqual(result, custom)

    def test_empty_prompt_fallback(self):
        """通过 mock_response 控制返回内容（测试用 control-data 模式）。"""
        mock_data = {"annotations": [{"index": 0, "sentiment": "neutral",
            "pain_point_labels": [], "need_labels": [], "complaint_labels": [],
            "solution_labels": [], "market_signal_labels": [], "intent_labels": [],
            "reason": "fallback"}]}
        client = MockLLMClient(mock_response=mock_data)
        text = client.generate("any prompt")
        result = extract_json_from_text(text)
        self.assertIsNotNone(result)
        self.assertIn("annotations", result)
        self.assertEqual(len(result["annotations"]), 1)
        self.assertEqual(result["annotations"][0]["index"], 0)


class TestExtractJsonFromText(unittest.TestCase):
    """extract_json_from_text 工具函数测试。"""

    def test_extracts_plain_json(self):
        """提取纯 JSON 文本。"""
        result = extract_json_from_text('{"key": "value"}')
        self.assertEqual(result, {"key": "value"})

    def test_extracts_markdown_json_block(self):
        """从 markdown 代码块中提取 JSON。"""
        text = '```json\n{"sentiment": "positive"}\n```'
        result = extract_json_from_text(text)
        self.assertEqual(result, {"sentiment": "positive"})

    def test_extracts_markdown_without_lang(self):
        """从无语言标记的 markdown 代码块提取。"""
        text = '```\n{"key": 123}\n```'
        result = extract_json_from_text(text)
        self.assertEqual(result, {"key": 123})

    def test_extracts_nested_braces(self):
        """提取嵌套大括号的 JSON。"""
        text = 'before text {"outer": {"inner": "value"}} after text'
        result = extract_json_from_text(text)
        self.assertEqual(result, {"outer": {"inner": "value"}})

    def test_returns_none_for_non_dict(self):
        """返回值不是 dict 时返回 None。"""
        result = extract_json_from_text('["list", "not", "dict"]')
        self.assertIsNone(result)

    def test_returns_none_for_no_json(self):
        """无 JSON 时返回 None。"""
        result = extract_json_from_text("no json here at all")
        self.assertIsNone(result)

    def test_markdown_block_with_whitespace(self):
        """markdown 代码块前后有空白。"""
        text = """some text before
```json
{
  "key": "value"
}
```
some text after"""
        result = extract_json_from_text(text)
        self.assertEqual(result, {"key": "value"})


if __name__ == "__main__":
    unittest.main()
