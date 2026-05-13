"""ContentIdeationAgent — 基于 LLM 的内容选题生成 Agent。

在报告生成前，基于洞察数据、评分结果和原始评论，
通过 LLM 生成高质量的内容选题建议。

支持两种模式：
- 模式 A：单 LLM 综合生成（评论 < 50 条）
- 模式 B：多角度并行生成（评论 >= 50 条），3-5 个 LLM 从不同角度思考
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
from typing import Any, Optional

from src.llm.client import BaseLLMClient, MockLLMClient, extract_json_from_text
from src.schemas import (
    InsightRecord,
    NormalizedDataset,
    ScoreCard,
)
from src.schemas.content_ideation import (
    ContentIdeationResult,
    TitleSuggestion,
    TopicSuggestion,
)

logger = logging.getLogger(__name__)

# ===================================================================
# Prompt 模板
# ===================================================================

_SINGLE_LLM_PROMPT = """你是一个资深内容运营专家。请基于以下小红书评论洞察数据，生成内容选题建议。

关键词: {keyword}

洞察数据:
- 用户需求: {user_needs}
- 用户痛点: {pain_points}
- 负面反馈: {complaints}
- 方案提及: {solutions}
- 内容机会信号: {market_signals}

评分数据:
- 用户关注强度: {demand_intensity}
- 负面反馈强度: {sentiment_friction}
- 方案提及度: {solution_saturation}
- 购买/行动信号: {purchase_intent}
- 评论时效性: {freshness}
- 综合评分: {overall_score}

代表评论:
{representative_comments}

请生成两类建议：

1. **关键词相关内容选题建议** (3-5条)：基于评论数据，指出哪些内容方向值得优先制作。每条包含：
   - direction: 选题方向
   - title: 建议标题（必须结合具体洞察词，不要模板化套话）
   - evidence: 数据依据（引用真实评论内容）
   - content_angle: 具体的文案角度和执行建议

2. **热点选题与文案定制建议** (3-5条)：基于评论数据，生成可立即执行的文案选题。每条包含：
   - direction: 选题方向
   - title: 建议标题（必须结合具体洞察词和内容策略）
   - evidence: 数据依据
   - content_angle: 具体文案角度和执行建议

要求：
- 标题不能使用模板化套话（如"关于XX，你不得不知道的几件事"）
- 必须结合具体的洞察词和真实评论内容
- 每个建议必须有数据依据
- 不输出市场规模、商业可行性判断

输出严格 JSON：
{{
  "topic_suggestions": [
    {{"direction": "...", "title": "...", "evidence": "...", "content_angle": "..."}}
  ],
  "custom_title_suggestions": [
    {{"direction": "...", "title": "...", "evidence": "...", "content_angle": "..."}}
  ]
}}"""

# ===================================================================
# 多角度 Prompt 模板
# ===================================================================

_PERSPECTIVE_PROMPTS: dict[str, str] = {
    "用户痛点角度": """你是一个用户研究专家。请基于以下数据，从**用户痛点和负面反馈**的角度，生成内容选题建议。

关键词: {keyword}

用户痛点: {pain_points}
负面反馈: {complaints}
代表评论:
{representative_comments}

聚焦于：避坑指南、对比评测、解决方案、用户真实痛点分析等内容选题。

请生成 2-3 条选题建议，每条包含 direction/title/evidence/content_angle。
标题必须结合具体洞察词，不要模板化套话。

输出严格 JSON：
{{"suggestions": [{{"direction": "...", "title": "...", "evidence": "...", "content_angle": "..."}}]}}""",

    "内容创作者角度": """你是一个资深内容创作者。请基于以下数据，从**内容创作和用户需求**的角度，生成内容选题建议。

关键词: {keyword}

用户需求: {user_needs}
内容机会信号: {market_signals}
评分: 用户关注强度={demand_intensity}, 综合={overall_score}
代表评论:
{representative_comments}

聚焦于：教程指南、入门路线、深度解析、答疑解惑等内容选题。

请生成 2-3 条选题建议，每条包含 direction/title/evidence/content_angle。
标题必须结合具体洞察词，不要模板化套话。

输出严格 JSON：
{{"suggestions": [{{"direction": "...", "title": "...", "evidence": "...", "content_angle": "..."}}]}}""",

    "搜索与流量角度": """你是一个SEO和内容流量专家。请基于以下数据，从**搜索意图和流量获取**的角度，生成内容选题建议。

关键词: {keyword}

用户需求: {user_needs}
内容机会信号: {market_signals}
代表评论:
{representative_comments}

聚焦于：高频搜索问题解答、SEO友好的问答内容、流量入口型选题。

请生成 2-3 条选题建议，每条包含 direction/title/evidence/content_angle。
标题必须结合具体洞察词，不要模板化套话。

输出严格 JSON：
{{"suggestions": [{{"direction": "...", "title": "...", "evidence": "...", "content_angle": "..."}}]}}""",

    "热点与趋势角度": """你是一个热点内容追踪专家。请基于以下数据，从**热点趋势和时效性**的角度，生成内容选题建议。

关键词: {keyword}

内容机会信号: {market_signals}
方案提及: {solutions}
评分: 评论时效性={freshness}, 综合={overall_score}
代表评论:
{representative_comments}

聚焦于：当前热点跟进、趋势分析、新鲜话题挖掘等时效性内容选题。

请生成 2-3 条选题建议，每条包含 direction/title/evidence/content_angle。
标题必须结合具体洞察词，不要模板化套话。

输出严格 JSON：
{{"suggestions": [{{"direction": "...", "title": "...", "evidence": "...", "content_angle": "..."}}]}}""",

    "产品与购买角度": """你是一个消费决策研究专家。请基于以下数据，从**购买决策和产品评估**的角度，生成内容选题建议。

关键词: {keyword}

方案提及: {solutions}
内容机会信号: {market_signals}
评分: 购买/行动信号={purchase_intent}, 综合={overall_score}
代表评论:
{representative_comments}

聚焦于：产品测评、购买指南、方案对比推荐、清单整理等消费决策型内容选题。

请生成 2-3 条选题建议，每条包含 direction/title/evidence/content_angle。
标题必须结合具体洞察词，不要模板化套话。

输出严格 JSON：
{{"suggestions": [{{"direction": "...", "title": "...", "evidence": "...", "content_angle": "..."}}]}}""",
}


def _build_perspective_prompt(
    perspective: str,
    keyword: str,
    insight: InsightRecord,
    scorecard: ScoreCard,
    representative_comments: str,
) -> str:
    """构建特定角度的 prompt。"""
    template = _PERSPECTIVE_PROMPTS[perspective]
    return template.format(
        keyword=keyword,
        pain_points="、".join(insight.pain_points[:5]) if insight.pain_points else "无",
        complaints="、".join(insight.complaints[:5]) if insight.complaints else "无",
        user_needs="、".join(insight.user_needs[:5]) if insight.user_needs else "无",
        market_signals="、".join(insight.market_signals[:5]) if insight.market_signals else "无",
        solutions="、".join(insight.solutions[:5]) if insight.solutions else "无",
        demand_intensity=scorecard.demand_intensity,
        sentiment_friction=scorecard.sentiment_friction,
        solution_saturation=scorecard.solution_saturation,
        purchase_intent=scorecard.purchase_intent,
        freshness=scorecard.freshness,
        overall_score=scorecard.overall_score,
        representative_comments=representative_comments,
    )


def _build_single_llm_prompt(
    keyword: str,
    insight: InsightRecord,
    scorecard: ScoreCard,
    representative_comments: str,
) -> str:
    """构建单 LLM 综合 prompt。"""
    return _SINGLE_LLM_PROMPT.format(
        keyword=keyword,
        user_needs="、".join(insight.user_needs[:10]) if insight.user_needs else "无",
        pain_points="、".join(insight.pain_points[:10]) if insight.pain_points else "无",
        complaints="、".join(insight.complaints[:10]) if insight.complaints else "无",
        solutions="、".join(insight.solutions[:10]) if insight.solutions else "无",
        market_signals="、".join(insight.market_signals[:10]) if insight.market_signals else "无",
        demand_intensity=scorecard.demand_intensity,
        sentiment_friction=scorecard.sentiment_friction,
        solution_saturation=scorecard.solution_saturation,
        purchase_intent=scorecard.purchase_intent,
        freshness=scorecard.freshness,
        overall_score=scorecard.overall_score,
        representative_comments=representative_comments,
    )


def _extract_representative_comments(
    dataset: NormalizedDataset,
    max_comments: int = 15,
) -> str:
    """从数据集中提取代表性评论（按点赞数排序）。"""
    if not dataset.comments:
        return "无评论数据"

    sorted_comments = sorted(dataset.comments, key=lambda c: c.likes, reverse=True)
    lines: list[str] = []
    for c in sorted_comments[:max_comments]:
        content = (c.content or "").strip()
        if not content:
            continue
        likes_str = f"（{c.likes}赞）" if c.likes > 0 else ""
        lines.append(f"- {content}{likes_str}")

    return "\n".join(lines) if lines else "无有效评论"


def _merge_suggestions_by_similarity(
    all_suggestions: list[dict],
    max_items: int = 5,
) -> list[dict]:
    """按 title 相似度去重合并，保留 evidence 最丰富的版本。

    简单策略：对 title 进行分词，计算重叠度；
    重叠度 > 0.6 视为重复。
    """
    if len(all_suggestions) <= max_items:
        return all_suggestions

    # 按 evidence 长度降序排序（evidence 越长通常越丰富）
    sorted_sugs = sorted(all_suggestions, key=lambda s: len(s.get("evidence", "")), reverse=True)

    def _title_words(title: str) -> set[str]:
        return set(title.replace("、", "").replace("，", "").replace("。", ""))

    selected: list[dict] = []
    for sug in sorted_sugs:
        title = sug.get("title", "")
        words = _title_words(title)
        if not words:
            if len(selected) < max_items:
                selected.append(sug)
            continue

        is_dup = False
        for existing in selected:
            existing_words = _title_words(existing.get("title", ""))
            if not existing_words:
                continue
            intersection = words & existing_words
            union = words | existing_words
            if len(union) == 0:
                continue
            overlap = len(intersection) / len(union)
            if overlap > 0.6:
                is_dup = True
                break

        if not is_dup:
            selected.append(sug)
            if len(selected) >= max_items:
                break

    return selected


class ContentIdeationAgent:
    """基于 LLM 的内容选题生成 Agent。

    参数：
        llm_client: LLM 客户端实例（用于创建独立 worker）
        keyword: 分析关键词
    """

    def __init__(
        self,
        llm_client: Optional[BaseLLMClient] = None,
        keyword: str = "",
    ):
        self._llm = llm_client
        self._keyword = keyword

    def execute(
        self,
        insight: InsightRecord,
        scorecard: ScoreCard,
        dataset: NormalizedDataset,
        keyword: str = "",
    ) -> ContentIdeationResult:
        """执行内容选题生成。

        根据评论数量自动选择模式：
        - < 50 条：单 LLM 综合生成
        - >= 50 条：多角度并行生成

        参数：
            insight: 洞察记录
            scorecard: 评分卡
            dataset: 标准化数据
            keyword: 关键词

        返回：
            ContentIdeationResult
        """
        kw = keyword or self._keyword
        comment_count = len(list(dataset.comments)) if dataset.comments else 0

        logger.info(
            "ContentIdeationAgent: keyword=%s, comments=%d",
            kw, comment_count,
        )

        if not self._llm:
            logger.warning("ContentIdeationAgent: llm_client 为空，返回空结果")
            return ContentIdeationResult()

        if comment_count < 50:
            return self._execute_single_llm(insight, scorecard, dataset, kw)
        else:
            return self._execute_multi_perspective(insight, scorecard, dataset, kw)

    # ------------------------------------------------------------------
    # 模式 A：单 LLM 综合生成
    # ------------------------------------------------------------------

    def _execute_single_llm(
        self,
        insight: InsightRecord,
        scorecard: ScoreCard,
        dataset: NormalizedDataset,
        keyword: str,
    ) -> ContentIdeationResult:
        """单 LLM 综合生成模式。"""
        logger.info("ContentIdeationAgent: 使用单 LLM 模式")

        comments_text = _extract_representative_comments(dataset)
        prompt = _build_single_llm_prompt(keyword, insight, scorecard, comments_text)

        try:
            text = self._llm.generate(prompt)
            raw = extract_json_from_text(text)
            if raw is None:
                raise RuntimeError(f"ContentIdeationAgent: LLM 返回非法 JSON，原始内容: {text[:500]}")
            result = self._parse_result(raw, mode="single_llm", perspectives=[])
        except Exception as e:
            logger.error("ContentIdeationAgent(单LLM) generate 失败: %s", e)
            result = ContentIdeationResult()

        # 警告：LLM 成功返回但结果为空（可能是 LLM 未按要求输出字段）
        if not result.topic_suggestions and not result.custom_title_suggestions:
            logger.warning(
                "ContentIdeationAgent(单LLM): LLM 返回了 JSON 但 topic_suggestions "
                "和 custom_title_suggestions 均为空，报告将回退到模板方案。"
            )

        
        return result

    # ------------------------------------------------------------------
    # 模式 B：多角度并行生成
    # ------------------------------------------------------------------

    def _execute_multi_perspective(
        self,
        insight: InsightRecord,
        scorecard: ScoreCard,
        dataset: NormalizedDataset,
        keyword: str,
    ) -> ContentIdeationResult:
        """多角度并行生成模式。"""
        # 判断哪些角度可用
        perspectives: list[str] = []
        perspectives.append("用户痛点角度")
        perspectives.append("内容创作者角度")
        perspectives.append("搜索与流量角度")

        # 角度 4：需要 market_signals 或高 freshness
        if insight.market_signals or scorecard.freshness >= 0.4:
            perspectives.append("热点与趋势角度")

        # 角度 5：需要 solutions 或 purchase_intent
        if insight.solutions or scorecard.purchase_intent >= 0.3:
            perspectives.append("产品与购买角度")

        logger.info(
            "ContentIdeationAgent: 多角度并行模式, 使用 %d 个角度: %s",
            len(perspectives), perspectives,
        )

        comments_text = _extract_representative_comments(dataset)

        # 每个角度并发调用 LLM
        all_topic_sugs: list[dict] = []
        all_title_sugs: list[dict] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(perspectives)) as executor:
            futures: dict[concurrent.futures.Future, str] = {}
            for perspective in perspectives:
                prompt = _build_perspective_prompt(
                    perspective, keyword, insight, scorecard, comments_text,
                )
                future = executor.submit(
                    self._call_llm_for_perspective, prompt, perspective,
                )
                futures[future] = perspective

            for future in concurrent.futures.as_completed(futures):
                perspective = futures[future]
                try:
                    suggestions = future.result()
                    all_topic_sugs.extend(suggestions)
                    all_title_sugs.extend(suggestions)
                    logger.info(
                        "ContentIdeationAgent: 角度 '%s' 完成, %d 条建议",
                        perspective, len(suggestions),
                    )
                except Exception as e:
                    logger.error(
                        "ContentIdeationAgent: 角度 '%s' 失败: %s", perspective, e,
                    )

        # 合并去重
        merged_topics = _merge_suggestions_by_similarity(all_topic_sugs, max_items=5)
        merged_titles = _merge_suggestions_by_similarity(all_title_sugs, max_items=5)

        return ContentIdeationResult(
            topic_suggestions=[TopicSuggestion(**s) for s in merged_topics],
            custom_title_suggestions=[TitleSuggestion(**s) for s in merged_titles],
            generation_mode="multi_perspective",
            perspectives_used=perspectives,
        )

    def _call_llm_for_perspective(
        self,
        prompt: str,
        perspective: str,
    ) -> list[dict]:
        """在独立线程中为某个角度调用 LLM。

        每个线程创建独立的 LLM client 实例。
        """
        # 创建独立的 LLM client（使用 spawn() 保证线程安全）
        llm = self._llm.spawn()

        text = llm.generate(prompt)
        raw = extract_json_from_text(text)
        if raw is None:
            raise RuntimeError(f"ContentIdeationAgent: 角度 '{perspective}' LLM 返回非法 JSON，原始内容: {text[:500]}")
        suggestions = raw.get("suggestions", [])
        if not isinstance(suggestions, list):
            raise ValueError(f"角度 '{perspective}' 返回非 list: {type(suggestions)}")

        # 添加角度标记
        for s in suggestions:
            if isinstance(s, dict):
                s["direction"] = f"[{perspective}] {s.get('direction', '')}"

        return suggestions

    @staticmethod
    def _parse_result(
        raw: dict[str, Any],
        mode: str,
        perspectives: list[str],
    ) -> ContentIdeationResult:
        """解析 LLM 输出为 ContentIdeationResult。"""
        topic_sugs_raw = raw.get("topic_suggestions", [])
        title_sugs_raw = raw.get("custom_title_suggestions", [])

        topic_suggestions = [
            TopicSuggestion(
                direction=s.get("direction", ""),
                title=s.get("title", ""),
                evidence=s.get("evidence", ""),
                content_angle=s.get("content_angle", ""),
            )
            for s in topic_sugs_raw
            if isinstance(s, dict)
        ]

        title_suggestions = [
            TitleSuggestion(
                direction=s.get("direction", ""),
                title=s.get("title", ""),
                evidence=s.get("evidence", ""),
                content_angle=s.get("content_angle", ""),
            )
            for s in title_sugs_raw
            if isinstance(s, dict)
        ]

        return ContentIdeationResult(
            topic_suggestions=topic_suggestions,
            custom_title_suggestions=title_suggestions,
            generation_mode=mode,
            perspectives_used=perspectives,
        )
