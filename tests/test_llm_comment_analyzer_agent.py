"""LLM 评论语义标注 Agent 单元测试。

使用 MockLLMClient，不访问真实 API。
"""

from __future__ import annotations

import sys
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
import unittest
from typing import Any

from src.agents.llm_comment_analyzer_agent import (
    LLMCommentAnalyzerAgent,
    _build_batch_prompt,
    _build_post_context_map,
    _parse_annotations,
)
from src.llm.client import MockLLMClient
from src.schemas import CommentRecord, PostRecord
from src.schemas.llm_records import CommentAnnotationRecord


def _make_comment(comment_id: str, post_id: str, content: str) -> CommentRecord:
    """创建测试用的 CommentRecord。"""
    return CommentRecord(
        platform="xhs",
        comment_id=comment_id,
        post_id=post_id,
        content=content,
        author="test_user",
        publish_time="2026-01-01T00:00:00",
    )


def _make_post(post_id: str, title: str, content: str) -> PostRecord:
    """创建测试用的 PostRecord。"""
    return PostRecord(
        platform="xhs",
        post_id=post_id,
        title=title,
        content=content,
        author="test_author",
        publish_time="2026-01-01T00:00:00",
    )


def _make_valid_annotation(
    index: int,
    sentiment: str = "positive",
    pain_labels: list[str] | None = None,
    need_labels: list[str] | None = None,
    complaint_labels: list[str] | None = None,
    solution_labels: list[str] | None = None,
    signal_labels: list[str] | None = None,
    intent_labels: list[str] | None = None,
    reason: str = "test reason",
) -> dict[str, Any]:
    """创建有效的 annotation 字典。"""
    return {
        "index": index,
        "sentiment": sentiment,
        "pain_point_labels": pain_labels or [],
        "need_labels": need_labels or [],
        "complaint_labels": complaint_labels or [],
        "solution_labels": solution_labels or [],
        "market_signal_labels": signal_labels or [],
        "intent_labels": intent_labels or [],
        "reason": reason,
    }


class TestBuildBatchPrompt(unittest.TestCase):
    """_build_batch_prompt 单元测试。"""

    def test_prompt_includes_content(self):
        """prompt 包含所有评论内容。"""
        comments = [
            _make_comment("c1", "p1", "这个产品很好用"),
            _make_comment("c2", "p1", "太贵了"),
        ]
        prompt = _build_batch_prompt(comments, 0)
        self.assertIn("这个产品很好用", prompt)
        self.assertIn("太贵了", prompt)
        self.assertIn('"index": 0', prompt)
        self.assertIn('"index": 1', prompt)

    def test_prompt_start_idx_offset(self):
        """start_idx 偏移影响注释中的 index。"""
        comments = [_make_comment("c1", "p1", "测试")]
        prompt = _build_batch_prompt(comments, 5)
        self.assertIn('"index": 5', prompt)

    def test_empty_content(self):
        """空内容在 prompt 中为空字符串。"""
        comments = [_make_comment("c1", "p1", "")]
        prompt = _build_batch_prompt(comments, 0)
        self.assertIn('"content": ""', prompt)


class TestParseAnnotations(unittest.TestCase):
    """_parse_annotations 验证逻辑测试。"""

    def setUp(self):
        self.batch = [
            _make_comment("c1", "p1", "有效评论1"),
            _make_comment("c2", "p1", "有效评论2"),
        ]

    def test_parses_valid_annotations(self):
        """有效的 annotations 正确解析。"""
        raw = {
            "annotations": [
                _make_valid_annotation(0, "positive", pain_labels=["好用"], need_labels=["效果好"]),
                _make_valid_annotation(1, "negative", complaint_labels=["太贵"]),
            ]
        }
        result = _parse_annotations(raw, self.batch, 0)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].comment_id, "c1")
        self.assertEqual(result[0].post_id, "p1")
        self.assertEqual(result[0].sentiment, "positive")
        self.assertEqual(result[0].pain_point_labels, ["好用"])
        self.assertEqual(result[0].need_labels, ["效果好"])
        self.assertEqual(result[1].comment_id, "c2")
        self.assertEqual(result[1].sentiment, "negative")
        self.assertEqual(result[1].complaint_labels, ["太贵"])

    def test_missing_annotations_field(self):
        """缺少 annotations 字段抛出 ValueError。"""
        raw = {"other": "data"}
        with self.assertRaises(ValueError) as ctx:
            _parse_annotations(raw, self.batch, 0)
        self.assertIn("缺少 annotations", str(ctx.exception))

    def test_annotations_not_a_list(self):
        """annotations 不是 list 抛出 ValueError。"""
        raw = {"annotations": "not_a_list"}
        with self.assertRaises(ValueError) as ctx:
            _parse_annotations(raw, self.batch, 0)
        self.assertIn("必须是 list", str(ctx.exception))

    def test_output_count_mismatch(self):
        """annotations 数量与 batch 不一致抛出 ValueError。"""
        raw = {"annotations": [_make_valid_annotation(0)]}
        with self.assertRaises(ValueError) as ctx:
            _parse_annotations(raw, self.batch, 0)
        self.assertIn("不一致", str(ctx.exception))

    def test_missing_index(self):
        """缺少 index 抛出 ValueError。"""
        raw = {
            "annotations": [
                {"index": 0, "sentiment": "positive", "pain_point_labels": []},
                {"sentiment": "negative", "pain_point_labels": []},
            ]
        }
        with self.assertRaises(ValueError) as ctx:
            _parse_annotations(raw, self.batch, 0)
        self.assertIn("缺少 index", str(ctx.exception))

    def test_invalid_sentiment(self):
        """无效 sentiment 抛出 ValueError。"""
        raw = {
            "annotations": [
                _make_valid_annotation(0, sentiment="invalid_sentiment"),
                _make_valid_annotation(1, sentiment="positive"),
            ]
        }
        with self.assertRaises(ValueError) as ctx:
            _parse_annotations(raw, self.batch, 0)
        self.assertIn("无效 sentiment", str(ctx.exception))

    def test_duplicate_index(self):
        """重复 index 抛出 ValueError。"""
        raw = {
            "annotations": [
                _make_valid_annotation(0),
                _make_valid_annotation(0),
            ]
        }
        with self.assertRaises(ValueError) as ctx:
            _parse_annotations(raw, self.batch, 0)
        self.assertIn("重复 index", str(ctx.exception))

    def test_out_of_range_index(self):
        """超出范围的 index 抛出 ValueError。"""
        raw = {
            "annotations": [
                _make_valid_annotation(0),
                _make_valid_annotation(5),  # 超出范围
            ]
        }
        with self.assertRaises(ValueError) as ctx:
            _parse_annotations(raw, self.batch, 0)
        self.assertIn("越界", str(ctx.exception))

    def test_out_of_range_index_negative(self):
        """负 index 抛出 ValueError。"""
        raw = {
            "annotations": [
                _make_valid_annotation(-1),
                _make_valid_annotation(1),
            ]
        }
        with self.assertRaises(ValueError) as ctx:
            _parse_annotations(raw, self.batch, 0)
        self.assertIn("越界", str(ctx.exception))

    def test_forbidden_score_fields_filtered(self):
        """禁止的评分字段被过滤，不阻断解析。"""
        raw = {
            "annotations": [
                _make_valid_annotation(0, sentiment="neutral"),
                _make_valid_annotation(1, sentiment="negative"),
            ],
            "overall_score": 0.85,  # 禁止字段
            "demand_intensity": 0.9,  # 禁止字段
        }
        # 不应抛出异常
        result = _parse_annotations(raw, self.batch, 0)
        self.assertEqual(len(result), 2)

    def test_start_idx_offset_parsing(self):
        """start_idx 偏移不影响 index 到 comment 的映射。"""
        batch = [
            _make_comment("c10", "p5", "评论A"),
            _make_comment("c11", "p5", "评论B"),
        ]
        raw = {
            "annotations": [
                _make_valid_annotation(10, sentiment="positive"),
                _make_valid_annotation(11, sentiment="negative"),
            ]
        }
        result = _parse_annotations(raw, batch, 10)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].comment_id, "c10")
        self.assertEqual(result[0].sentiment, "positive")
        self.assertEqual(result[1].comment_id, "c11")
        self.assertEqual(result[1].sentiment, "negative")

    def test_empty_labels_are_filtered(self):
        """空标签和 None 标签被过滤。"""
        raw = {
            "annotations": [
                {
                    "index": 0,
                    "sentiment": "neutral",
                    "pain_point_labels": ["", None, "有效标签"],
                    "need_labels": [],
                    "complaint_labels": [],
                    "solution_labels": [],
                    "market_signal_labels": [],
                    "intent_labels": [],
                    "reason": "",
                },
                _make_valid_annotation(1, sentiment="neutral"),
            ]
        }
        result = _parse_annotations(raw, self.batch, 0)
        self.assertEqual(result[0].pain_point_labels, ["有效标签"])


class TestLLMCommentAnalyzerAgentExecute(unittest.TestCase):
    """LLMCommentAnalyzerAgent.execute 完整流程测试。"""

    def test_empty_comments_returns_empty(self):
        """空评论列表返回空列表。"""
        agent = LLMCommentAnalyzerAgent()
        result = agent.execute([])
        self.assertEqual(result, [])

    def test_with_valid_comments(self):
        """有效的评论列表返回正确数量的 annotation。"""
        comments = [
            _make_comment("c1", "p1", "这个很好用"),
            _make_comment("c2", "p1", "太贵了不划算"),
        ]
        mock = MockLLMClient(mock_response={
            "annotations": [
                _make_valid_annotation(0, "positive", pain_labels=["好用"]),
                _make_valid_annotation(1, "negative", complaint_labels=["太贵", "不划算"]),
            ]
        })
        agent = LLMCommentAnalyzerAgent(llm_client=mock)
        result = agent.execute(comments)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].comment_id, "c1")
        self.assertEqual(result[0].sentiment, "positive")
        self.assertEqual(result[0].pain_point_labels, ["好用"])
        self.assertEqual(result[1].comment_id, "c2")
        self.assertEqual(result[1].sentiment, "negative")
        self.assertEqual(result[1].complaint_labels, ["太贵", "不划算"])

    def test_binds_original_comment_ids(self):
        """输出的 annotation 使用原始评论的 comment_id。"""
        comments = [
            _make_comment("unique_c1", "post_x", "内容A"),
            _make_comment("unique_c2", "post_x", "内容B"),
        ]
        mock = MockLLMClient(mock_response={
            "annotations": [
                _make_valid_annotation(0, "positive"),
                _make_valid_annotation(1, "negative"),
            ]
        })
        agent = LLMCommentAnalyzerAgent(llm_client=mock)
        result = agent.execute(comments)
        self.assertEqual(result[0].comment_id, "unique_c1")
        self.assertEqual(result[1].comment_id, "unique_c2")

    def test_preserves_empty_comment(self):
        """空评论不崩溃，产生默认标注。"""
        comments = [
            _make_comment("c_empty", "p1", ""),
        ]
        mock = MockLLMClient(mock_response={
            "annotations": [
                _make_valid_annotation(0, "neutral"),
            ]
        })
        agent = LLMCommentAnalyzerAgent(llm_client=mock)
        result = agent.execute(comments)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].sentiment, "neutral")
        self.assertEqual(result[0].pain_point_labels, [])

    def test_preserves_duplicate_comment_content(self):
        """相同内容的评论各自保留自己的 comment_id。"""
        comments = [
            _make_comment("dup_c1", "p1", "相同内容"),
            _make_comment("dup_c2", "p1", "相同内容"),
        ]
        mock = MockLLMClient(mock_response={
            "annotations": [
                _make_valid_annotation(0, "positive"),
                _make_valid_annotation(1, "neutral"),
            ]
        })
        agent = LLMCommentAnalyzerAgent(llm_client=mock)
        result = agent.execute(comments)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].comment_id, "dup_c1")
        self.assertEqual(result[1].comment_id, "dup_c2")

    def test_rejects_output_count_mismatch(self):
        """LLM 返回数量与输入不一致时抛出异常。"""
        comments = [
            _make_comment("c1", "p1", "评论1"),
            _make_comment("c2", "p1", "评论2"),
        ]
        mock = MockLLMClient(mock_response={
            "annotations": [
                _make_valid_annotation(0, "positive"),
                # 缺少 index 1
            ]
        })
        agent = LLMCommentAnalyzerAgent(llm_client=mock)
        with self.assertRaises(ValueError) as ctx:
            agent.execute(comments)
        self.assertIn("不一致", str(ctx.exception))

    def test_rejects_invalid_sentiment(self):
        """LLM 返回无效 sentiment 时抛出异常。"""
        comments = [
            _make_comment("c1", "p1", "评论1"),
            _make_comment("c2", "p1", "评论2"),
        ]
        mock = MockLLMClient(mock_response={
            "annotations": [
                _make_valid_annotation(0, sentiment="unknown"),
                _make_valid_annotation(1, sentiment="positive"),
            ]
        })
        agent = LLMCommentAnalyzerAgent(llm_client=mock)
        with self.assertRaises(ValueError) as ctx:
            agent.execute(comments)
        self.assertIn("无效 sentiment", str(ctx.exception))

    def test_rejects_forbidden_score_fields(self):
        """禁止的评分字段出现时被过滤，不阻断流程。"""
        comments = [
            _make_comment("c1", "p1", "好用"),
            _make_comment("c2", "p1", "不好"),
        ]
        mock = MockLLMClient(mock_response={
            "annotations": [
                _make_valid_annotation(0, "positive"),
                _make_valid_annotation(1, "negative"),
            ],
            "overall_score": 0.9,  # 禁止字段
        })
        agent = LLMCommentAnalyzerAgent(llm_client=mock)
        # 不应抛出异常
        result = agent.execute(comments)
        self.assertEqual(len(result), 2)

    def test_rejects_duplicate_index(self):
        """LLM 返回重复 index 时抛出异常。"""
        comments = [
            _make_comment("c1", "p1", "评论1"),
            _make_comment("c2", "p1", "评论2"),
        ]
        mock = MockLLMClient(mock_response={
            "annotations": [
                _make_valid_annotation(0, "positive"),
                _make_valid_annotation(0, "negative"),  # 重复 index
            ]
        })
        agent = LLMCommentAnalyzerAgent(llm_client=mock)
        with self.assertRaises(ValueError) as ctx:
            agent.execute(comments)
        self.assertIn("重复 index", str(ctx.exception))

    def test_rejects_out_of_range_index(self):
        """LLM 返回超出范围的 index 时抛出异常。"""
        comments = [
            _make_comment("c1", "p1", "评论1"),
            _make_comment("c2", "p1", "评论2"),
        ]
        mock = MockLLMClient(mock_response={
            "annotations": [
                _make_valid_annotation(0, "positive"),
                _make_valid_annotation(5, "negative"),  # 超出范围
            ]
        })
        agent = LLMCommentAnalyzerAgent(llm_client=mock)
        with self.assertRaises(ValueError) as ctx:
            agent.execute(comments)
        self.assertIn("越界", str(ctx.exception))

    def test_batches_comments(self):
        """超过 batch_size 的评论分批次处理。"""
        comments = [_make_comment(f"c{i}", "p1", f"评论{i}") for i in range(15)]

        call_count = [0]

        class BatchTrackingMock(MockLLMClient):
            def generate(self, prompt: str = "") -> str:
                call_count[0] += 1
                # 根据调用次数返回不同的 annotations
                batch_num = call_count[0]
                if batch_num == 1:
                    # 第一批: index 0-9
                    annotations = [_make_valid_annotation(i, "positive") for i in range(10)]
                else:
                    # 第二批: index 10-14
                    annotations = [_make_valid_annotation(i, "neutral") for i in range(10, 15)]
                return json.dumps({"annotations": annotations}, ensure_ascii=False)

        agent = LLMCommentAnalyzerAgent(
            llm_client=BatchTrackingMock(),
            batch_size=10,
        )
        result = agent.execute(comments)
        # 验证所有 15 条都被标注
        self.assertEqual(len(result), 15)
        # 验证调用了 2 次
        self.assertEqual(call_count[0], 2)
        # 验证索引映射正确
        self.assertEqual(result[0].comment_id, "c0")
        self.assertEqual(result[14].comment_id, "c14")

    def test_max_comments_limit(self):
        """max_comments 限制处理的评论数量。"""
        comments = [_make_comment(f"c{i}", "p1", f"评论{i}") for i in range(100)]

        call_count = [0]

        class LimitedMock(MockLLMClient):
            def generate(self, prompt: str = "") -> str:
                call_count[0] += 1
                # 猜测 batch 索引
                offset = (call_count[0] - 1) * 10
                batch_size = min(10, 50 - offset)
                annotations = [_make_valid_annotation(offset + i, "neutral") for i in range(batch_size)]
                return json.dumps({"annotations": annotations}, ensure_ascii=False)

        agent = LLMCommentAnalyzerAgent(
            llm_client=LimitedMock(),
            batch_size=10,
            max_comments=50,
        )
        result = agent.execute(comments)
        self.assertEqual(len(result), 50)

    def test_content_empty_string(self):
        """空字符串内容 in prompt 被保留为空字符串。"""
        comments = [
            _make_comment("c1", "p1", ""),
        ]
        prompt = _build_batch_prompt(comments, 0)
        self.assertIn('"content": ""', prompt)


class TestBuildPostContextMap(unittest.TestCase):
    """_build_post_context_map 单元测试。"""

    def test_builds_map_from_posts(self):
        """从 PostRecord 列表正确构建 post context map。"""
        posts = [
            _make_post("p1", "帖子标题1", "帖子内容1"),
            _make_post("p2", "帖子标题2", "帖子内容2"),
        ]
        comments = [
            _make_comment("c1", "p1", "评论内容"),
        ]
        result = _build_post_context_map(comments, posts)
        self.assertIn("p1", result)
        self.assertIn("p2", result)
        self.assertEqual(result["p1"]["title"], "帖子标题1")
        self.assertEqual(result["p1"]["content_excerpt"], "帖子内容1")
        self.assertEqual(result["p2"]["title"], "帖子标题2")

    def test_empty_posts_returns_empty_map(self):
        """posts 为空时返回空字典。"""
        result = _build_post_context_map([], [])
        self.assertEqual(result, {})

    def test_none_posts_returns_empty_map(self):
        """posts 为 None 时返回空字典。"""
        result = _build_post_context_map([], None)  # type: ignore
        self.assertEqual(result, {})

    def test_truncates_long_content(self):
        """超过 500 字符的 content_excerpt 被截断。"""
        posts = [
            _make_post("p1", "标题", "A" * 600),
        ]
        comments = []
        result = _build_post_context_map(comments, posts)
        self.assertEqual(len(result["p1"]["content_excerpt"]), 503)  # 500 + "..."
        self.assertTrue(result["p1"]["content_excerpt"].endswith("..."))

    def test_short_content_not_truncated(self):
        """不超过 500 字符的 content_excerpt 不被截断。"""
        content = "B" * 100
        posts = [
            _make_post("p1", "标题", content),
        ]
        result = _build_post_context_map([], posts)
        self.assertEqual(result["p1"]["content_excerpt"], content)
        self.assertFalse(result["p1"]["content_excerpt"].endswith("..."))

    def test_strips_whitespace(self):
        """content_excerpt 开头和结尾的空格被去除。"""
        posts = [
            _make_post("p1", "  标题  ", "  内容  "),
        ]
        result = _build_post_context_map([], posts)
        self.assertEqual(result["p1"]["title"], "标题")
        self.assertEqual(result["p1"]["content_excerpt"], "内容")


class TestPostContextInPrompt(unittest.TestCase):
    """带帖子上下文的 prompt 渲染测试。"""

    def test_prompt_includes_post_context(self):
        """当提供 post_context_map 和 post_id 时，prompt 包含帖子上下文。"""
        comments = [
            _make_comment("c1", "p1", "有叠加国补吗"),
        ]
        post_context_map = {
            "p1": {
                "title": "iPhone 17 Pro 值得买吗？真实体验分享",
                "content_excerpt": "刚入手一周，谈谈真实感受...价格方面确实不便宜...",
            },
        }
        prompt = _build_batch_prompt(
            comments, 0,
            post_context_map=post_context_map,
            post_id="p1",
        )
        self.assertIn("iPhone 17 Pro 值得买吗？真实体验分享", prompt)
        self.assertIn("刚入手一周，谈谈真实感受...价格方面确实不便宜...", prompt)
        self.assertIn("有叠加国补吗", prompt)

    def test_missing_post_context_fallback(self):
        """未提供 post_context_map 和 post_id 时，prompt 使用空上下文。"""
        comments = [
            _make_comment("c1", "p1", "这个很好用"),
        ]
        prompt = _build_batch_prompt(comments, 0)
        self.assertIn("这个很好用", prompt)
        # 检查空上下文占位
        self.assertIn("title:", prompt)

    def test_prompt_includes_likes(self):
        """prompt 中包含评论的 likes 字段。"""
        comment = _make_comment("c1", "p1", "热评内容")
        comment.likes = 42
        prompt = _build_batch_prompt([comment], 0)
        self.assertIn('"likes": 42', prompt)

    def test_prompt_flat_array_format(self):
        """comments 使用扁平 JSON 数组格式（非嵌套对象）。"""
        comments = [
            _make_comment("c1", "p1", "评论1"),
            _make_comment("c2", "p1", "评论2"),
        ]
        prompt = _build_batch_prompt(comments, 0)
        # 应该是扁平数组，不是 {"comments": [...]}
        self.assertFalse(prompt.startswith('{"comments":'))
        # 验证是 JSON 数组
        self.assertIn('[', prompt)
        self.assertIn(']', prompt)

    def test_uses_post_context_map_per_post_id(self):
        """不同 post_id 使用对应的 post context。"""
        comments = [
            _make_comment("c1", "p1", "评论A"),
            _make_comment("c2", "p2", "评论B"),
        ]
        post_context_map = {
            "p1": {"title": "帖子A标题", "content_excerpt": "帖子A内容"},
            "p2": {"title": "帖子B标题", "content_excerpt": "帖子B内容"},
        }
        prompt_p1 = _build_batch_prompt(
            [comments[0]], 0,
            post_context_map=post_context_map,
            post_id="p1",
        )
        self.assertIn("帖子A标题", prompt_p1)
        self.assertNotIn("帖子B标题", prompt_p1)

        prompt_p2 = _build_batch_prompt(
            [comments[1]], 0,
            post_context_map=post_context_map,
            post_id="p2",
        )
        self.assertIn("帖子B标题", prompt_p2)
        self.assertNotIn("帖子A标题", prompt_p2)


class TestExecuteWithPostContext(unittest.TestCase):
    """LLMCommentAnalyzerAgent.execute 传入 posts 的测试。"""

    def test_output_still_binds_comment_id(self):
        """传入 posts 参数后，输出的 annotation 仍然绑定原始 comment_id 和 post_id。"""
        comments = [
            _make_comment("c1", "p1", "价格太贵了"),
            _make_comment("c2", "p1", "有没有平替推荐"),
        ]
        posts = [
            _make_post("p1", "某某产品值不值得买", "最近很多人在问某某产品"),
        ]
        mock = MockLLMClient(mock_response={
            "annotations": [
                _make_valid_annotation(0, "negative", complaint_labels=["价格贵"]),
                _make_valid_annotation(1, "neutral", intent_labels=["求推荐"]),
            ]
        })
        agent = LLMCommentAnalyzerAgent(llm_client=mock)
        result = agent.execute(comments, posts=posts)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].comment_id, "c1")
        self.assertEqual(result[0].post_id, "p1")
        self.assertEqual(result[0].sentiment, "negative")
        self.assertEqual(result[1].comment_id, "c2")
        self.assertEqual(result[1].post_id, "p1")
        self.assertEqual(result[1].sentiment, "neutral")

    def test_posts_parameter_optional(self):
        """posts 参数不传时仍然正常工作。"""
        comments = [
            _make_comment("c1", "p1", "产品不错"),
        ]
        mock = MockLLMClient(mock_response={
            "annotations": [
                _make_valid_annotation(0, "positive"),
            ]
        })
        agent = LLMCommentAnalyzerAgent(llm_client=mock)
        result = agent.execute(comments)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].comment_id, "c1")

    def test_mixed_post_ids_grouped_correctly(self):
        """来自不同帖子的评论按 post_id 分组，各自使用对应上下文。"""
        comments = [
            _make_comment("c1", "p1", "支持国补吗"),
            _make_comment("c2", "p2", "内容太长了"),
        ]
        posts = [
            _make_post("p1", "iPhone 17 Pro 体验", "谈谈新款手机的感受"),
            _make_post("p2", "零基础学开发", "很多同学问我怎么开始"),
        ]

        prompts_seen = []

        class PromptCaptureMock(MockLLMClient):
            def generate(self, prompt: str = "") -> str:
                prompts_seen.append(prompt)
                annotations = []
                if "iPhone 17 Pro" in prompt:
                    annotations = [_make_valid_annotation(0, "neutral", intent_labels=["询价"])]
                else:
                    annotations = [_make_valid_annotation(0, "negative", complaint_labels=["内容太长"])]
                return json.dumps({"annotations": annotations}, ensure_ascii=False)

        agent = LLMCommentAnalyzerAgent(
            llm_client=PromptCaptureMock(),
            batch_size=10,
        )
        result = agent.execute(comments, posts=posts)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].comment_id, "c1")
        self.assertEqual(result[1].comment_id, "c2")

        # 验证 prompt 中包含各自的帖子上下文
        p1_prompt = [p for p in prompts_seen if "iPhone 17 Pro" in p]
        p2_prompt = [p for p in prompts_seen if "零基础学开发" in p]
        self.assertEqual(len(p1_prompt), 1)
        self.assertEqual(len(p2_prompt), 1)


if __name__ == "__main__":
    unittest.main()
