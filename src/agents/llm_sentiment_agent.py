"""LLM 增强的情感分析 Agent。

使用 LLM 对评论进行情绪分类。
最终输出转换为现有 SentimentResult。
LLM 失败时 fallback 到规则 SentimentAgent。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from src.agents.sentiment_agent import SentimentAgent
from src.llm.client import BaseLLMClient, MockLLMClient, extract_json_from_text
from src.llm.score_filter import filter_forbidden_scores
from src.schemas import (
    CommentRecord, NormalizedDataset, PostSentiment, CommentSentiment, SentimentResult,
)
from src.schemas.llm_records import LLMCommentSentiment

logger = logging.getLogger(__name__)

_DEFAULT_SENTIMENT_PROMPT = """
分析以下小红书评论的情感倾向。

评论内容：
{comment_text}

请输出 JSON 格式：
{{
  "comment_id": "...",
  "sentiment": "positive" | "negative" | "neutral" | "mixed",
  "confidence": 0.0-1.0,
  "emotion_tags": ["标签1", "标签2"],
  "evidence_text": "评论中体现情感的关键句子",
  "reason": "情感判断理由"
}}
"""


def _build_sentiment_prompt(comment: CommentRecord) -> str:
    return _DEFAULT_SENTIMENT_PROMPT.format(comment_text=comment.content)


def _parse_llm_response(response: dict[str, Any]) -> LLMCommentSentiment:
    """解析 LLM JSON 响应为 LLMCommentSentiment。"""
    return LLMCommentSentiment(
        comment_id=response.get("comment_id", ""),
        sentiment=response.get("sentiment", "neutral"),
        confidence=float(response.get("confidence", 0.0)),
        emotion_tags=response.get("emotion_tags", []),
        evidence_text=response.get("evidence_text", ""),
        reason=response.get("reason", ""),
    )


class LLMSentimentAgent:
    """LLM 增强的情感分析 Agent。

    使用 LLM 逐条评论分析情感。
    失败时 fallback 到规则版 SentimentAgent。
    """

    def __init__(
        self,
        llm_client: Optional[BaseLLMClient] = None,
        fallback_agent: Optional[SentimentAgent] = None,
    ):
        self._llm = llm_client or MockLLMClient()
        self._fallback = fallback_agent or SentimentAgent()

    def execute(self, dataset: NormalizedDataset) -> SentimentResult:
        """对 normalized_dataset 做 LLM 情感分析，返回 SentimentResult。"""
        try:
            return self._execute_llm(dataset)
        except Exception as e:
            logger.warning("LLMSentimentAgent 失败，fallback 到规则版: %s", e, exc_info=True)
            return self._fallback.execute(dataset)

    def _execute_llm(self, dataset: NormalizedDataset) -> SentimentResult:
        """使用 LLM 分析情感。"""
        llm_sentiments: list[LLMCommentSentiment] = []

        for comment in dataset.comments:
            prompt = _build_sentiment_prompt(comment)
            text = self._llm.generate(prompt)
            raw = extract_json_from_text(text)
            if raw is None:
                raise RuntimeError(f"LLMSentimentAgent: LLM 返回非法 JSON，原始内容: {text[:500]}")
            raw = filter_forbidden_scores(raw)
            parsed = _parse_llm_response(raw)
            parsed.comment_id = comment.comment_id
            parsed.post_id = comment.post_id
            if not parsed.evidence_text:
                parsed.evidence_text = comment.content[:100]
            llm_sentiments.append(parsed)

        # 转换为现有 SentimentResult
        comment_sentiments = []
        label_map = {"positive": "positive", "negative": "negative", "neutral": "neutral", "mixed": "neutral"}
        for ls in llm_sentiments:
            comment_sentiments.append(CommentSentiment(
                comment_id=ls.comment_id,
                label=label_map.get(ls.sentiment, "neutral"),
                score=ls.confidence,
            ))

        # 聚合帖子级情感
        post_map: dict[str, list[CommentSentiment]] = {}
        for cs in comment_sentiments:
            for c in dataset.comments:
                if c.comment_id == cs.comment_id:
                    post_map.setdefault(c.post_id, []).append(cs)
                    break

        post_sentiments = []
        for post_id, sentiments in post_map.items():
            avg_score = sum(s.score for s in sentiments) / max(len(sentiments), 1)
            labels = [s.label for s in sentiments]
            majority = max(set(labels), key=labels.count) if labels else "neutral"
            post_sentiments.append(PostSentiment(post_id=post_id, label=majority, score=round(avg_score, 4)))

        # 整体情感
        all_labels = [cs.label for cs in comment_sentiments]
        overall = "neutral"
        if all_labels:
            overall = max(set(all_labels), key=all_labels.count)

        return SentimentResult(
            overall_sentiment=overall,
            post_sentiments=post_sentiments,
            comment_sentiments=comment_sentiments,
        )
