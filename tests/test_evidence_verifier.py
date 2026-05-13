"""Evidence 校验器单元测试。"""

from __future__ import annotations

import sys
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import unittest

from src.llm.evidence_verifier import EvidenceVerifier, _normalize
from src.schemas import CommentRecord, PostRecord
from src.schemas.llm_records import LLMInsightItem


class TestNormalize(unittest.TestCase):
    """_normalize 工具函数测试。"""

    def test_empty_string(self):
        """空字符串返回空字符串。"""
        self.assertEqual(_normalize(""), "")

    def test_whitespace_removed(self):
        """空白被移除。"""
        result = _normalize("  hello  world  ")
        self.assertEqual(result, "helloworld")

    def test_newlines_removed(self):
        """换行被移除。"""
        result = _normalize("line1\nline2\nline3")
        self.assertEqual(result, "line1line2line3")

    def test_nfkc_normalization(self):
        """NFKC 归一化生效。"""
        result = _normalize("　test")  # ideographic space
        self.assertNotIn("　", result)


class TestEvidenceVerifier(unittest.TestCase):
    """EvidenceVerifier 主测试。"""

    def setUp(self):
        self.posts = [
            PostRecord(
                platform="xhs", post_id="p1", title="测试帖子", content="这个产品真的很好用",
                author="u1", publish_time="2026-01-01T00:00:00",
            ),
            PostRecord(
                platform="xhs", post_id="p2", title="另一个帖子", content="太差了完全没用",
                author="u2", publish_time="2026-01-02T00:00:00",
            ),
        ]
        self.comments = [
            CommentRecord(
                platform="xhs", comment_id="c1", post_id="p1",
                content="确实不错，回购了", author="u3",
                publish_time="2026-01-01T01:00:00",
            ),
            CommentRecord(
                platform="xhs", comment_id="c2", post_id="p1",
                content="不好用，太油了", author="u4",
                publish_time="2026-01-01T02:00:00",
            ),
            CommentRecord(
                platform="xhs", comment_id="c3", post_id="p2",
                content="求链接", author="u5",
                publish_time="2026-01-02T01:00:00",
            ),
        ]
        self.verifier = EvidenceVerifier(posts=self.posts, comments=self.comments)

    def test_verify_existing_comment_id(self):
        """存在的 comment_id 返回 True。"""
        self.assertTrue(self.verifier.verify_comment_id("c1"))
        self.assertTrue(self.verifier.verify_comment_id("c2"))
        self.assertTrue(self.verifier.verify_comment_id("c3"))

    def test_verify_nonexistent_comment_id(self):
        """不存在的 comment_id 返回 False。"""
        self.assertFalse(self.verifier.verify_comment_id("nonexistent"))
        self.assertFalse(self.verifier.verify_comment_id(""))

    def test_verify_existing_post_id(self):
        """存在的 post_id 返回 True。"""
        self.assertTrue(self.verifier.verify_post_id("p1"))
        self.assertTrue(self.verifier.verify_post_id("p2"))

    def test_verify_nonexistent_post_id(self):
        """不存在的 post_id 返回 False。"""
        self.assertFalse(self.verifier.verify_post_id("nonexistent"))
        self.assertFalse(self.verifier.verify_post_id(""))

    def test_verify_evidence_text_in_comment(self):
        """evidence_text 能在评论中找到。"""
        self.assertTrue(
            self.verifier.verify_evidence_text("确实不错", comment_id="c1")
        )
        self.assertTrue(
            self.verifier.verify_evidence_text("太油了", comment_id="c2")
        )

    def test_verify_evidence_text_not_in_comment(self):
        """evidence_text 不在评论中返回 False。"""
        self.assertFalse(
            self.verifier.verify_evidence_text("不存在的内容", comment_id="c1")
        )

    def test_verify_evidence_text_in_post(self):
        """evidence_text 能在帖子中找到。"""
        self.assertTrue(
            self.verifier.verify_evidence_text("真的很好用", post_id="p1")
        )
        self.assertTrue(
            self.verifier.verify_evidence_text("完全没用", post_id="p2")
        )

    def test_verify_evidence_text_empty(self):
        """空 evidence_text 返回 False。"""
        self.assertFalse(
            self.verifier.verify_evidence_text("", comment_id="c1")
        )

    def test_verify_item_valid_comment_evidence(self):
        """有效的 comment evidence 使 verify_item 返回 True。"""
        item = LLMInsightItem(
            text="用户觉得产品不错",
            evidence_comment_ids=["c1"],
            evidence_text="确实不错",
        )
        self.assertTrue(self.verifier.verify_item(item))

    def test_verify_item_valid_post_evidence(self):
        """有效的 post evidence 使 verify_item 返回 True。"""
        item = LLMInsightItem(
            text="用户说产品好用",
            evidence_post_ids=["p1"],
            evidence_text="真的很好用",
        )
        self.assertTrue(self.verifier.verify_item(item))

    def test_verify_item_nonexistent_comment_id(self):
        """不存在的 comment_id 应使 verify_item 返回 False。"""
        item = LLMInsightItem(
            text="用户觉得产品不错",
            evidence_comment_ids=["nonexistent"],
            evidence_text="确实不错",
        )
        self.assertFalse(self.verifier.verify_item(item))

    def test_verify_item_evidence_text_mismatch(self):
        """evidence_text 在源中不存在应使 verify_item 返回 False。"""
        item = LLMInsightItem(
            text="用户觉得产品不错",
            evidence_comment_ids=["c1"],
            evidence_text="这个文本不在评论中",
        )
        self.assertFalse(self.verifier.verify_item(item))

    def test_verify_item_no_evidence_ids(self):
        """没有 evidence IDs 应返回 False。"""
        item = LLMInsightItem(
            text="用户觉得产品不错",
            evidence_text="确实不错",
        )
        self.assertFalse(self.verifier.verify_item(item))

    def test_filter_items_removes_invalid(self):
        """filter_items 移除无效 evidence 的条目。"""
        items = [
            LLMInsightItem(
                text="有效洞察",
                evidence_comment_ids=["c1"],
                evidence_text="确实不错",
            ),
            LLMInsightItem(
                text="无效洞察",
                evidence_comment_ids=["nonexistent"],
            ),
            LLMInsightItem(
                text="无证据洞察",
            ),
        ]
        filtered = self.verifier.filter_items(items)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].text, "有效洞察")

    def test_filter_items_all_valid(self):
        """全部有效时不移除任何条目。"""
        items = [
            LLMInsightItem(
                text="洞察1",
                evidence_comment_ids=["c1"],
                evidence_text="确实不错",
            ),
            LLMInsightItem(
                text="洞察2",
                evidence_comment_ids=["c3"],
                evidence_text="求链接",
            ),
        ]
        filtered = self.verifier.filter_items(items)
        self.assertEqual(len(filtered), 2)


class TestEvidenceVerifierEmpty(unittest.TestCase):
    """空数据时的 EvidenceVerifier 行为。"""

    def test_empty_posts_and_comments(self):
        """无帖子无评论时，所有校验返回 False。"""
        verifier = EvidenceVerifier(posts=[], comments=[])
        self.assertFalse(verifier.verify_comment_id("c1"))
        self.assertFalse(verifier.verify_post_id("p1"))
        self.assertFalse(verifier.verify_evidence_text("test", comment_id="c1"))

    def test_filter_empty_list(self):
        """空列表 filter_items 返回空列表。"""
        verifier = EvidenceVerifier()
        self.assertEqual(verifier.filter_items([]), [])


if __name__ == "__main__":
    unittest.main()
