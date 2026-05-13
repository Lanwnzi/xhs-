"""Evidence 校验器。

校验 LLM 输出的洞察是否具有有效的证据来源。
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Optional

from src.schemas import CommentRecord, PostRecord
from src.schemas.llm_records import LLMInsightItem

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    """归一化文本用于匹配。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\n", "").replace(" ", "").replace("\r", "").replace("\t", "").strip()
    return text


class EvidenceVerifier:
    """Evidence 校验器。

    校验每条洞察的 evidence 是否真实存在于输入数据中。
    """

    def __init__(
        self,
        posts: Optional[list[PostRecord]] = None,
        comments: Optional[list[CommentRecord]] = None,
    ):
        self._post_ids = {p.post_id for p in (posts or [])}
        self._comment_ids = {c.comment_id for c in (comments or [])}
        self._comment_map = {c.comment_id: c.content for c in (comments or [])}
        self._post_content_map = {p.post_id: p.title + " " + p.content for p in (posts or [])}

    def verify_comment_id(self, comment_id: str) -> bool:
        """验证 comment_id 是否存在于输入评论中。"""
        return comment_id in self._comment_ids

    def verify_post_id(self, post_id: str) -> bool:
        """验证 post_id 是否存在于输入帖子中。"""
        return post_id in self._post_ids

    def verify_evidence_text(self, text: str, comment_id: str = "", post_id: str = "") -> bool:
        """验证 evidence_text 是否能在对应的 comment.content 或 post.content 中找到。

        匹配采用归一化子串匹配。
        """
        if not text:
            return False
        norm_text = _normalize(text)
        if not norm_text:
            return False

        if comment_id and comment_id in self._comment_map:
            source = _normalize(self._comment_map[comment_id])
            if norm_text in source:
                return True

        if post_id and post_id in self._post_content_map:
            source = _normalize(self._post_content_map[post_id])
            if norm_text in source:
                return True

        return False

    def verify_item(self, item: LLMInsightItem) -> bool:
        """验证单条洞察是否有有效 evidence。

        规则：
        1. 至少有一个 evidence_comment_id 或 evidence_post_id
        2. 每个 ID 必须存在于输入数据
        3. evidence_text 必须在对应源中找到
        """
        has_valid_id = False

        for cid in item.evidence_comment_ids:
            if self.verify_comment_id(cid):
                has_valid_id = True
                if item.evidence_text and not self.verify_evidence_text(item.evidence_text, comment_id=cid):
                    logger.debug("evidence_text 不在评论中: comment_id=%s", cid)
                    return False

        for pid in item.evidence_post_ids:
            if self.verify_post_id(pid):
                has_valid_id = True
                if item.evidence_text and not self.verify_evidence_text(item.evidence_text, post_id=pid):
                    logger.debug("evidence_text 不在帖子中: post_id=%s", pid)
                    return False

        return has_valid_id

    def filter_items(self, items: list[LLMInsightItem]) -> list[LLMInsightItem]:
        """过滤掉无有效 evidence 的洞察。"""
        filtered = [item for item in items if self.verify_item(item)]
        removed = len(items) - len(filtered)
        if removed:
            logger.warning("EvidenceVerifier: 移除了 %d 条无证据洞察", removed)
        return filtered
