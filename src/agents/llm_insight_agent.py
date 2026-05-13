"""LLM 增强的洞察抽取 Agent。

使用 LLM 抽取结构化的用户需求、痛点、投诉、替代方案和市场信号。
最终输出现有 InsightRecord。
LLM 失败时 fallback 到规则版 InsightAgent。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from src.agents.insight_agent import InsightAgent
from src.llm.client import BaseLLMClient, MockLLMClient, extract_json_from_text
from src.llm.evidence_verifier import EvidenceVerifier
from src.llm.score_filter import filter_forbidden_scores
from src.schemas import (
    InsightRecord, NormalizedDataset, SentimentResult,
    CommentRecord, PostRecord,
)
from src.schemas.llm_records import LLMInsightItem, LLMInsightResult

logger = logging.getLogger(__name__)

_DEFAULT_INSIGHT_PROMPT = """
分析以下小红书帖子和评论，提取用户需求、痛点、投诉、替代方案和市场信号。

帖子：
{posts_text}

评论：
{comments_text}

请输出 JSON：
{{
  "pain_points": [{{"text": "...", "evidence_comment_ids": [], "evidence_post_ids": [], "evidence_text": "..."}}],
  "user_needs": [{{"text": "...", "evidence_comment_ids": [], "evidence_post_ids": [], "evidence_text": "..."}}],
  "complaints": [{{"text": "...", "evidence_comment_ids": [], "evidence_post_ids": [], "evidence_text": "..."}}],
  "solutions": [{{"text": "...", "evidence_comment_ids": [], "evidence_post_ids": [], "evidence_text": "..."}}],
  "market_signals": [{{"text": "...", "evidence_comment_ids": [], "evidence_post_ids": [], "evidence_text": "..."}}],
  "sentiment": "positive/negative/neutral"
}}
"""


def _build_insight_prompt(dataset: NormalizedDataset) -> str:
    posts_text = "\n".join(
        f"[{p.post_id}] {p.title}: {p.content[:200]}" for p in dataset.posts
    ) or "(无帖子)"
    comments_text = "\n".join(
        f"[{c.comment_id}]({c.post_id}) {c.content[:200]}" for c in dataset.comments
    ) or "(无评论)"
    return _DEFAULT_INSIGHT_PROMPT.format(posts_text=posts_text, comments_text=comments_text)


class LLMInsightAgent:
    """LLM 增强的洞察抽取 Agent。

    使用 LLM 抽取结构化洞察。
    经过 evidence verification 后输出现有 InsightRecord。
    失败时 fallback 到规则版 InsightAgent。
    """

    def __init__(
        self,
        llm_client: Optional[BaseLLMClient] = None,
        fallback_agent: Optional[InsightAgent] = None,
    ):
        self._llm = llm_client or MockLLMClient()
        self._fallback = fallback_agent or InsightAgent()

    def execute(
        self,
        dataset: NormalizedDataset,
        sentiment: SentimentResult,
    ) -> InsightRecord:
        try:
            return self._execute_llm(dataset, sentiment)
        except Exception as e:
            logger.warning("LLMInsightAgent 失败，fallback 到规则版: %s", e, exc_info=True)
            return self._fallback.execute(dataset, sentiment)

    def _execute_llm(
        self,
        dataset: NormalizedDataset,
        sentiment: SentimentResult,
    ) -> InsightRecord:
        prompt = _build_insight_prompt(dataset)
        text = self._llm.generate(prompt)
        raw = extract_json_from_text(text)
        if raw is None:
            raise RuntimeError(f"LLMInsightAgent: LLM 返回非法 JSON，原始内容: {text[:500]}")
        raw = filter_forbidden_scores(raw)
        llm_result = self._parse_insight_result(raw)

        # Evidence verification
        verifier = EvidenceVerifier(
            posts=list(dataset.posts),
            comments=list(dataset.comments),
        )

        filtered = {}
        for category in ["pain_points", "user_needs", "complaints", "solutions", "market_signals"]:
            items = getattr(llm_result, category, [])
            valid = verifier.filter_items(items)
            filtered[category] = [item.text for item in valid]

        # 收集所有有效 evidence IDs
        all_post_ids: list[str] = []
        all_comment_ids: list[str] = []
        for category in ["pain_points", "user_needs", "complaints", "solutions", "market_signals"]:
            items = getattr(llm_result, category, [])
            for item in items:
                for pid in item.evidence_post_ids:
                    if pid and pid not in all_post_ids:
                        all_post_ids.append(pid)
                for cid in item.evidence_comment_ids:
                    if cid and cid not in all_comment_ids:
                        all_comment_ids.append(cid)

        # 如果没有有效 evidence，不允许输出市场机会强结论
        if not all_post_ids and not all_comment_ids:
            logger.warning("LLMInsightAgent: 无有效 evidence，清空洞察列表")

        return InsightRecord(
            pain_points=filtered["pain_points"],
            user_needs=filtered["user_needs"],
            complaints=filtered["complaints"],
            solutions=filtered["solutions"],
            market_signals=filtered["market_signals"],
            sentiment=sentiment.overall_sentiment or "",
            evidence_post_ids=all_post_ids,
            evidence_comment_ids=all_comment_ids,
        )

    @staticmethod
    def _parse_insight_result(raw: dict[str, Any]) -> LLMInsightResult:
        """解析 LLM JSON 响应为 LLMInsightResult。"""
        result = LLMInsightResult(sentiment=raw.get("sentiment", ""))
        for category in ["pain_points", "user_needs", "complaints", "solutions", "market_signals"]:
            items = raw.get(category, [])
            parsed = []
            for item in items:
                parsed.append(LLMInsightItem(
                    text=item.get("text", ""),
                    evidence_post_ids=item.get("evidence_post_ids", []),
                    evidence_comment_ids=item.get("evidence_comment_ids", []),
                    evidence_text=item.get("evidence_text", ""),
                ))
            setattr(result, category, parsed)
        return result
