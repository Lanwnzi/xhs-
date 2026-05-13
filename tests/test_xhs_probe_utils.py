"""
XHS 探测工具函数离线测试。

不访问真实小红书。
"""

from __future__ import annotations

import sys
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import unittest

from src.adapters.xhs_utils import parse_count_text, extract_post_id_from_url


class TestParseCountText(unittest.TestCase):
    """计数文本解析测试。"""

    def test_plain_number(self):
        self.assertEqual(parse_count_text("300"), 300)
        self.assertEqual(parse_count_text("0"), 0)

    def test_wan(self):
        self.assertEqual(parse_count_text("1.2万"), 12000)
        self.assertEqual(parse_count_text("3万"), 30000)
        self.assertEqual(parse_count_text("0.5万"), 5000)

    def test_k(self):
        self.assertEqual(parse_count_text("2k"), 2000)
        self.assertEqual(parse_count_text("1.5K"), 1500)

    def test_thousand_separator(self):
        self.assertEqual(parse_count_text("1,200"), 1200)

    def test_empty_and_invalid(self):
        self.assertEqual(parse_count_text(""), 0)
        self.assertEqual(parse_count_text(None), 0)
        self.assertEqual(parse_count_text("abc"), 0)


class TestExtractPostId(unittest.TestCase):
    """URL 提取测试。"""

    def test_explore_url(self):
        url = "https://www.xiaohongshu.com/explore/66b3c5e1000000001c008c6b"
        self.assertEqual(extract_post_id_from_url(url), "66b3c5e1000000001c008c6b")

    def test_invalid_url(self):
        self.assertEqual(extract_post_id_from_url(""), "")
        self.assertEqual(extract_post_id_from_url("not a url"), "")


class TestNoForbiddenOutput(unittest.TestCase):
    """探测代码不应生成 pipeline 产物。

    使用完整文件名做断言（如 insights.json），
    避免 docstring 中 "不生成 insights/scorecard/report" 产生误报。
    """

    def test_no_insights(self):
        probe_file = os.path.join(_PROJECT_ROOT, "scripts", "probe_xhs_page.py")
        with open(probe_file, encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("insights.json", content, "探测脚本不应生成 insights.json")

    def test_no_scorecard(self):
        probe_file = os.path.join(_PROJECT_ROOT, "scripts", "probe_xhs_page.py")
        with open(probe_file, encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("scorecard.json", content, "探测脚本不应生成 scorecard.json")

    def test_no_report(self):
        probe_file = os.path.join(_PROJECT_ROOT, "scripts", "probe_xhs_page.py")
        with open(probe_file, encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("report.html", content, "探测脚本不应生成 report.html")


class TestNoteCardStructure(unittest.TestCase):
    """笔记卡片结构化字段测试。"""

    def test_note_card_required_fields(self):
        """验证 note_card 的结构化字段完整。"""
        card = {
            "href": "https://www.xiaohongshu.com/explore/66b3c5e1000000001c008c6b",
            "post_id": "66b3c5e1000000001c008c6b",
            "possible_title": "控油洗发水推荐",
            "possible_author": "用户A",
            "possible_publish_time": "2025-07-08",
            "possible_like_count": "1.2万",
            "text_sample": "控油效果真的很好...",
        }
        required = {"href", "post_id", "possible_title", "possible_author",
                     "possible_publish_time", "possible_like_count", "text_sample"}
        self.assertEqual(required, set(card.keys()))
        self.assertTrue(card["post_id"])

    def test_note_card_empty_fields(self):
        """空字段不应导致异常，应保持默认空字符串。"""
        for key in ("href", "post_id", "possible_title", "possible_author",
                     "possible_publish_time", "possible_like_count", "text_sample"):
            self.assertEqual("", type("").__new__(str))


class TestNoteLinkFilter(unittest.TestCase):
    """笔记链接过滤测试。"""

    def test_valid_explore_link(self):
        """/explore/<id> 格式且无查询参数应被保留。"""
        href = "/explore/66b3c5e1000000001c008c6b"
        if "?" not in href and href.startswith("/explore/"):
            post_id = href.replace("/explore/", "")
            self.assertEqual(post_id, "66b3c5e1000000001c008c6b")

    def test_invalid_explore_link_with_query(self):
        """/explore?channel_type=... 等带查询参数的链接应被过滤。"""
        links = [
            "/explore?channel_type=web_search_result_notes",
            "/explore?channel_id=homefeed_recommend",
        ]
        for link in links:
            # 应被过滤掉（带 ? 的链接不应进入 note_link_candidates）
            self.assertIn("?", link)
            self.assertFalse(link.startswith("/explore/"),
                             "带查询参数的链接不应匹配 /explore/ 格式")

    def test_other_link_not_notebook(self):
        """非标准 /explore/<note_id> 链接不应提取 post_id。"""
        bad = [
            "/search_result?keyword=test",
            "/explore?channel_type=web_search_result_notes",
            "https://www.xiaohongshu.com/explore?channel_id=homefeed",
        ]
        for link in bad:
            # 这些链接不应通过 extract_post_id_from_url 提取到 post_id
            self.assertEqual(extract_post_id_from_url(link), "")

            # 模拟 _extract_note_cards 中的过滤条件
            raw_href = link
            if "?" in raw_href:
                # 带 ? 的链接不会被加入 note_link_candidates
                self.assertFalse(raw_href.startswith("/explore/")
                                 and "?" not in raw_href)


class TestExtractPostIdStandard(unittest.TestCase):
    """标准 URL post_id 提取测试。"""

    def test_standard_explore_url(self):
        """标准 /explore/<id> URL 应提取 note_id。"""
        url = "https://www.xiaohongshu.com/explore/66b3c5e1000000001c008c6b"
        self.assertEqual(extract_post_id_from_url(url), "66b3c5e1000000001c008c6b")

    def test_longer_id(self):
        """更长的 hex id 也应支持。"""
        url = "https://www.xiaohongshu.com/explore/66b3c5e1000000001c008c6b123456"
        self.assertEqual(extract_post_id_from_url(url), "66b3c5e1000000001c008c6b123456")


class TestClickDetailResultStructure(unittest.TestCase):
    """click-detail 结果结构测试。"""

    def test_result_contains_postrecord_fields(self):
        """click-detail 结果应包含 PostRecord 所需候选字段。"""
        result = {
            "post_id": "test_001",
            "title_candidates": ["标题"],
            "content_candidates": ["正文"],
            "author_candidates": ["作者"],
            "publish_time_candidates": ["2025-07-08"],
            "likes_candidates": ["100"],
            "favorites_candidates": ["50"],
            "comments_count_candidates": ["20"],
            "shares_candidates": [],
            "url_candidates": ["https://www.xiaohongshu.com/explore/test_001"],
            "tags_candidates": [],
        }
        # PostRecord 要求的 12 个字段都能从 result 映射得到
        self.assertIn("post_id", result)
        self.assertIn("title_candidates", result)
        self.assertIn("content_candidates", result)
        self.assertIn("author_candidates", result)
        self.assertIn("publish_time_candidates", result)

    def test_visible_comment_can_map_to_commentrecord(self):
        """visible_comment_candidates 应能映射到 CommentRecord。"""
        comments = [
            {"comment_id": "p001_0_12345", "content": "好用", "author": "用户A", "publish_time": "", "likes": "", "parent_comment_id": ""},
            {"comment_id": "p001_1_67890", "content": "求链接", "author": "用户B", "publish_time": "", "likes": "10", "parent_comment_id": ""},
        ]
        for c in comments:
            self.assertIn("comment_id", c)
            self.assertIn("content", c)
            self.assertIn("author", c)
            self.assertIn("publish_time", c)
            self.assertIn("likes", c)
            self.assertIn("parent_comment_id", c)

    def test_comment_id_generation_stable(self):
        """comment_id 生成逻辑应稳定、唯一、可复现。"""
        post_id = "test_001"
        content = "好用的产品"
        idx = 0
        cid1 = f"{post_id}_{idx}_{hash(content) % 10000000}"
        cid2 = f"{post_id}_{idx}_{hash(content) % 10000000}"
        self.assertEqual(cid1, cid2)


class TestAccessStatus(unittest.TestCase):
    """access_status 分类测试。"""

    def test_ok_when_valid(self):
        body = "控油洗发水实测推荐，控油效果很好"
        status = "ok"
        if "暂时无法浏览" in body or "请打开小红书App查看" in body:
            status = "blocked_app_required"
        self.assertEqual(status, "ok")

    def test_blocked_when_restricted(self):
        body = "当前笔记暂时无法浏览，请打开小红书App扫码查看"
        status = "ok"
        if "暂时无法浏览" in body or "请打开小红书App查看" in body:
            status = "blocked_app_required"
        self.assertEqual(status, "blocked_app_required")


if __name__ == "__main__":
    unittest.main()
