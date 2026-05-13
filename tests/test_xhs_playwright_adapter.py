"""
XhsPlaywrightAdapter 离线测试。

测试内容（不访问真实小红书）：
1. 字段映射：raw post → PostRecord
2. 字段映射：raw comment → CommentRecord
3. comment.post_id 能对应 post.post_id
4. adapter 不输出 insights/scorecard/report
5. parse_count_text 能解析各种计数格式
6. filter_note 能过滤低互动笔记
7. 代码不含硬编码 cookie/token
8. 代码不含 requests 逆向逻辑
"""

from __future__ import annotations

import sys
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import ast
import unittest

from src.schemas import PostRecord, CommentRecord
from src.adapters.xhs_playwright_adapter import (
    XhsPlaywrightAdapter, _map_post, _map_comment,
    _map_click_detail_post, _map_click_detail_comments,
    _filter_post,
)
from src.adapters.xhs_utils import parse_count_text
from src.adapters.xhs_collect_config import XhsCollectConfig


# Mock 小红书原始字段数据
_MOCK_RAW_POST = {
    "note_id": "xhs_test_001",
    "title": "控油洗发水亲测推荐",
    "desc": "用了这款控油洗发水两周，出油明显减少，推荐给油头姐妹",
    "nickname": "护肤小达人",
    "create_time": 1710748800,  # 2024-03-18
    "liked_count": 234,
    "comment_count": 45,
    "collected_count": 89,
    "share_count": 12,
    "note_url": "https://www.xiaohongshu.com/explore/xhs_test_001",
    "tag_list": ["控油", "洗发水", "好物分享"],
}

_MOCK_RAW_COMMENT = {
    "id": "xhs_cmt_001",
    "note_id": "xhs_test_001",
    "content": "真的很好用，回购第二次了",
    "nickname": "用户A",
    "create_time": 1710777600,  # 2024-03-18
    "like_count": 23,
    "parent_comment_id": None,
}

_MOCK_RAW_REPLY_COMMENT = {
    "id": "xhs_cmt_002",
    "note_id": "xhs_test_001",
    "content": "是的，我也觉得不错",
    "nickname": "用户B",
    "create_time": 1710781200,
    "like_count": 5,
    "parent_comment_id": "xhs_cmt_001",
}


class TestFieldMapping(unittest.TestCase):
    """字段映射测试：验证小红书原始字段→标准字段的映射正确性。"""

    def test_post_mapping_has_all_fields(self):
        """映射后的 post dict 应包含 PostRecord 所有字段。"""
        mapped = _map_post(_MOCK_RAW_POST)
        required = {"platform", "post_id", "title", "content", "author",
                    "publish_time", "likes", "comments", "favorites",
                    "shares", "url", "tags"}
        self.assertEqual(required, set(mapped.keys()))

    def test_post_mapping_values(self):
        """验证映射后的字段值正确。"""
        mapped = _map_post(_MOCK_RAW_POST)
        self.assertEqual(mapped["platform"], "xhs")
        self.assertEqual(mapped["post_id"], "xhs_test_001")
        self.assertEqual(mapped["title"], "控油洗发水亲测推荐")
        self.assertIn("出油明显减少", mapped["content"])
        self.assertEqual(mapped["author"], "护肤小达人")
        self.assertEqual(mapped["likes"], 234)
        self.assertEqual(mapped["comments"], 45)
        self.assertEqual(mapped["favorites"], 89)
        self.assertEqual(mapped["shares"], 12)
        self.assertEqual(mapped["tags"], ["控油", "洗发水", "好物分享"])
        # publish_time 应被正确转换
        self.assertIn("T", mapped["publish_time"])

    def test_post_mapped_can_construct_postrecord(self):
        """映射后的 post dict 应能被 PostRecord 校验。"""
        mapped = _map_post(_MOCK_RAW_POST)
        record = PostRecord(**mapped)
        self.assertEqual(record.post_id, "xhs_test_001")
        self.assertEqual(record.likes, 234)
        self.assertIsInstance(record.tags, list)

    def test_comment_mapping_has_all_fields(self):
        """映射后的 comment dict 应包含 CommentRecord 所有字段。"""
        mapped = _map_comment(_MOCK_RAW_COMMENT)
        required = {"platform", "comment_id", "post_id", "content", "author",
                    "publish_time", "likes", "parent_comment_id"}
        self.assertEqual(required, set(mapped.keys()))

    def test_comment_mapping_values(self):
        """验证映射后的评论字段值正确。"""
        mapped = _map_comment(_MOCK_RAW_COMMENT)
        self.assertEqual(mapped["platform"], "xhs")
        self.assertEqual(mapped["comment_id"], "xhs_cmt_001")
        self.assertEqual(mapped["post_id"], "xhs_test_001")
        self.assertEqual(mapped["content"], "真的很好用，回购第二次了")
        self.assertEqual(mapped["author"], "用户A")
        self.assertEqual(mapped["likes"], 23)
        self.assertIsNone(mapped["parent_comment_id"])
        self.assertIn("T", mapped["publish_time"])

    def test_comment_mapped_can_construct_commentrecord(self):
        """映射后的 comment dict 应能被 CommentRecord 校验。"""
        mapped = _map_comment(_MOCK_RAW_COMMENT)
        record = CommentRecord(**mapped)
        self.assertEqual(record.comment_id, "xhs_cmt_001")
        self.assertEqual(record.likes, 23)

    def test_reply_comment_parent_id(self):
        """二级评论的 parent_comment_id 应正确映射。"""
        mapped = _map_comment(_MOCK_RAW_REPLY_COMMENT)
        self.assertEqual(mapped["parent_comment_id"], "xhs_cmt_001")

    def test_comment_post_id_matches_post(self):
        """评论的 post_id 应能对应该帖子的 post_id。"""
        post_mapped = _map_post(_MOCK_RAW_POST)
        comment_mapped = _map_comment(_MOCK_RAW_COMMENT)
        self.assertEqual(comment_mapped["post_id"], post_mapped["post_id"])


class TestParseCountText(unittest.TestCase):
    """计数文本解析测试。"""

    def test_wan(self):
        self.assertEqual(parse_count_text("1.2万"), 12000)
        self.assertEqual(parse_count_text("3万"), 30000)
        self.assertEqual(parse_count_text("0.5万"), 5000)

    def test_k(self):
        self.assertEqual(parse_count_text("2k"), 2000)
        self.assertEqual(parse_count_text("1.5K"), 1500)

    def test_plain_number(self):
        self.assertEqual(parse_count_text("300"), 300)
        self.assertEqual(parse_count_text("0"), 0)

    def test_empty(self):
        self.assertEqual(parse_count_text(""), 0)
        self.assertEqual(parse_count_text(None), 0)


class TestFilterPost(unittest.TestCase):
    """帖子过滤测试。"""

    def test_keep_valid_post(self):
        post = {"post_id": "test_001", "likes": 100, "comments": 10, "favorites": 50}
        config = XhsCollectConfig(min_likes=50, min_comments=5)
        self.assertTrue(_filter_post(post, config))

    def test_skip_low_likes(self):
        post = {"post_id": "test_001", "likes": 10, "comments": 10, "favorites": 50}
        config = XhsCollectConfig(min_likes=50, min_comments=5)
        self.assertFalse(_filter_post(post, config))

    def test_skip_no_id(self):
        post = {"title": "no id"}
        config = XhsCollectConfig()
        self.assertFalse(_filter_post(post, config))


class TestAdapterContract(unittest.TestCase):
    """Adapter 接口契约测试。"""

    def test_implements_base_adapter(self):
        """验证 XhsPlaywrightAdapter 实现了 BaseAdapter。"""
        from src.adapters.base import BaseAdapter
        self.assertTrue(issubclass(XhsPlaywrightAdapter, BaseAdapter))

    def test_fetch_posts_returns_list(self):
        """fetch_posts 返回 list。"""
        adapter = XhsPlaywrightAdapter()
        result = adapter.fetch_posts()
        self.assertIsInstance(result, list)

    def test_fetch_comments_returns_list(self):
        """fetch_comments 返回 list。"""
        adapter = XhsPlaywrightAdapter()
        result = adapter.fetch_comments()
        self.assertIsInstance(result, list)

    def test_no_insights_generated(self):
        """adapter 不应生成 insights.json。"""
        adapter_file = os.path.join(_PROJECT_ROOT, "src", "adapters", "xhs_playwright_adapter.py")
        with open(adapter_file, encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("insight", content, "adapter 不应引用 insight")
        self.assertNotIn("scorecard", content, "adapter 不应引用 scorecard")
        self.assertNotIn("report", content, "adapter 不应引用 report")


class TestNoForbiddenCode(unittest.TestCase):
    """不应包含的代码模式测试。"""

    def test_no_hardcoded_cookie(self):
        """adapter 不应包含硬编码 cookie。"""
        adapter_file = os.path.join(_PROJECT_ROOT, "src", "adapters", "xhs_playwright_adapter.py")
        with open(adapter_file, encoding="utf-8") as f:
            content = f.read()
        # 检查是否包含硬编码 cookie 赋值模式（排除 docstring 中的说明文本）
        import re
        # 匹配类似 cookie = "xxx" 或 cookies={"key":"val"} 的赋值模式
        cookie_assignments = re.findall(r'cookie\s*[=:]\s*["\']', content, re.IGNORECASE)
        self.assertEqual(len(cookie_assignments), 0, f"发现硬编码 cookie 赋值: {cookie_assignments}")

    def test_no_requests_reverse_logic(self):
        """adapter 不应包含 requests 逆向逻辑。"""
        adapter_file = os.path.join(_PROJECT_ROOT, "src", "adapters", "xhs_playwright_adapter.py")
        with open(adapter_file, encoding="utf-8") as f:
            content = f.read()
        # 允许 import requests 用于其他用途，但不应有逆向相关模式
        forbidden = ["x-s", "x-t", "sign", "anti_spider", "encrypt"]
        for pattern in forbidden:
            self.assertNotIn(pattern, content.lower(), f"不应包含 {pattern}")


class TestConfig(unittest.TestCase):
    """配置测试。"""

    def test_default_values(self):
        """默认配置应有效。"""
        config = XhsCollectConfig(keyword="test")
        self.assertEqual(config.keyword, "test")
        self.assertEqual(config.max_posts, 20)
        self.assertEqual(config.max_comments_per_post, 30)
        self.assertFalse(config.headless)
        self.assertGreater(config.request_interval_seconds, 0)

    def test_state_path_default(self):
        """默认 state_path 应包含 data/private。"""
        config = XhsCollectConfig(keyword="test")
        normalized_path = config.state_path.replace("\\", "/")
        self.assertIn("data/private", normalized_path)


class TestClickDetailMapping(unittest.TestCase):
    """click-detail 映射函数测试。"""

    def setUp(self):
        self.probe_result = {
            "post_id": "66b3c5e1000000001c008c6b",
            "title_candidates": ["控油洗发水推荐"],
            "content_candidates": ["这款控油效果真的很好，回购第二次了 #控油 #洗发水"],
            "author_candidates": ["护肤小达人"],
            "publish_time_candidates": ["2025-07-08"],
            "likes_candidates": ["1.2万"],
            "favorites_candidates": ["3000"],
            "comments_count_candidates": ["500"],
            "shares_candidates": ["200"],
            "tags_candidates": ["控油", "热推"],
            "url_candidates": ["https://www.xiaohongshu.com/explore/66b3c5e1000000001c008c6b"],
            "visible_comment_candidates": [
                {"comment_id": "cmt_001", "content": "真的很好用", "author": "用户A", "publish_time": "2025-07-08", "likes": "123", "parent_comment_id": ""},
                {"comment_id": "cmt_002", "content": "", "author": "用户B", "publish_time": "", "likes": "", "parent_comment_id": ""},  # 空内容，应跳过
            ],
        }

    def test_map_post_to_postrecord(self):
        """_map_click_detail_post 输出可被 PostRecord 校验。"""
        mapped = _map_click_detail_post(self.probe_result)
        record = PostRecord(**mapped)
        self.assertEqual(record.post_id, "66b3c5e1000000001c008c6b")
        self.assertEqual(record.likes, 12000)
        self.assertEqual(record.author, "护肤小达人")
        self.assertIsInstance(record.tags, list)
        self.assertIn("控油", record.tags)

    def test_map_comments_to_commentrecord(self):
        """_map_click_detail_comments 输出可被 CommentRecord 校验。"""
        mapped = _map_click_detail_comments(self.probe_result)
        self.assertEqual(len(mapped), 1)  # 空 content 被过滤
        record = CommentRecord(**mapped[0])
        self.assertEqual(record.comment_id, "cmt_001")
        self.assertEqual(record.likes, 123)
        self.assertIsNone(record.parent_comment_id)

    def test_content_first_only(self):
        """content_candidates 混入评论时，post.content 只取第一个。"""
        result = dict(self.probe_result)
        result["content_candidates"] = ["真实正文内容", "不应该出现的评论内容"]
        mapped = _map_click_detail_post(result)
        self.assertEqual(mapped["content"], "真实正文内容")
        self.assertNotEqual(mapped["content"], "不应该出现的评论内容")

    def test_int_field_types(self):
        """likes/favorites/comments/shares 都是 int。"""
        mapped = _map_click_detail_post(self.probe_result)
        for field in ["likes", "comments", "favorites", "shares"]:
            self.assertIsInstance(mapped[field], int, f"{field} 应为 int")

    def test_empty_comment_skipped(self):
        """空 content 评论不输出。"""
        mapped = _map_click_detail_comments(self.probe_result)
        for c in mapped:
            self.assertTrue(c["content"].strip())

    def test_parent_id_empty_to_none(self):
        """parent_comment_id 空字符串转 None。"""
        mapped = _map_click_detail_comments(self.probe_result)
        for c in mapped:
            self.assertIsNone(c["parent_comment_id"])

    def test_author_clean_newline(self):
        """author 中的 \\n作者 被清理。"""
        result = dict(self.probe_result)
        result["author_candidates"] = ["\n作者小A"]
        mapped = _map_click_detail_post(result)
        self.assertEqual(mapped["author"], "小A")


class TestOpsModule(unittest.TestCase):
    """xhs_playwright_ops 模块验证。"""

    def test_ops_not_import_scripts(self):
        """xhs_playwright_ops 不应依赖 scripts/。"""
        ops_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "src", "adapters", "xhs_playwright_ops.py")
        with open(ops_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn("scripts", (node.module or ""),
                                f"不应 import scripts/: {node.module}")


if __name__ == "__main__":
    unittest.main()
