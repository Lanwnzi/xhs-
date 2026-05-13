"""LLM 评论级语义标注 Agent。

对 CommentRecord 列表进行批量语义标注。
LLM 只输出每条评论的语义标签和情绪。
comment_id/post_id 由代码绑定，LLM 不生成。

现在支持传入帖子上下文（PostRecord 列表），
prompt 中会包含帖子标题和内容摘要，帮助 LLM 更准确地理解评论语境。

# 示例：带帖子上下文的 prompt 效果
# keyword: "iPhone 17 Pro"
# post_context.title: "iPhone 17 Pro 值得买吗？真实体验分享"
# post_context.content_excerpt: "刚入手一周，谈谈真实感受...价格方面确实不便宜..."
# comments: [{"index": 0, "content": "有叠加国补吗", "likes": 23}]
# -> LLM 应识别为 "补贴政策疑问 / 购买决策信号" 而非泛化的 "购买意向"
#
# keyword: "Agent 学习"
# post_context.title: "零基础学 Agent 开发，先搞懂这几个概念"
# post_context.content_excerpt: "很多同学问我 Agent 怎么学..."
# comments: [{"index": 0, "content": "内容太长", "likes": 12}]
# -> LLM 应识别为 "学习内容负担 / 内容结构化需求" 而非泛化的 "负面反馈"
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
from collections import defaultdict
from typing import Any, Optional

from src.agents.sentiment_agent import SentimentAgent
from src.agents.insight_agent import InsightAgent
from src.llm.client import BaseLLMClient, MockLLMClient, extract_json_from_text
from src.llm.score_filter import filter_forbidden_scores
from src.schemas import CommentRecord, PostRecord
from src.schemas.llm_records import CommentAnnotationRecord

logger = logging.getLogger(__name__)

_ANNOTATION_PROMPT_TEMPLATE = """
分析以下小红书评论，识别用户反馈、疑问、购买顾虑、决策障碍和内容选题信号。

你将看到一个关键词、一个帖子上下文和该帖子下的评论列表。
请结合帖子标题、帖子摘要和评论内容，判断每条评论表达的用户反馈、疑问、购买顾虑、决策障碍、负面体验、解决方案/渠道提及、内容选题信号和行动意图。

不要脱离帖子上下文泛化判断。

keyword: {keyword}

post_context:
  title: {post_title}
  content_excerpt: {post_content_excerpt}

comments:
{comments_json}

对每条评论输出：
1. sentiment: positive / negative / neutral / mixed
2. pain_point_labels: 用户表达的痛点或困扰（如果没有则输出空列表）
3. need_labels: 用户希望达到或得到的效果（如果没有则输出空列表）
4. complaint_labels: 用户对产品或服务的负面评价（如果没有则输出空列表）
5. solution_labels: 用户提到的具体产品、方案、建议（如果没有则输出空列表）
6. market_signal_labels: 用户表达的内容选题信号，如求推荐、询价、渠道等（如果没有则输出空列表）
7. intent_labels: 用户的意图，如求推荐、多少钱、哪里买、想买、入手等（如果没有则输出空列表）
8. reason: 判断理由（简短）

输出格式必须是严格 JSON，不输出 Markdown，不输出解释：
{{
  "annotations": [
    {{
      "index": 0,
      "sentiment": "negative",
      "pain_point_labels": ["标签1", "标签2"],
      "need_labels": [],
      "complaint_labels": [],
      "solution_labels": [],
      "market_signal_labels": [],
      "intent_labels": [],
      "reason": "理由（结合帖子上下文和评论内容）"
    }}
  ]
}}

要求：
1. 只输出 JSON，不输出 Markdown，不输出解释性段落
2. 每个 annotation 必须包含 index，index 必须来自输入列表
3. 不允许新增输入中不存在的 index
4. 不允许输出评分字段
5. label 应该是简短中文短语（4到15个字）
6. 请结合帖子上下文判断，不要只依赖评论本身
7. 对于空内容评论，输出 sentiment: "neutral"，所有 labels 为空列表
"""


def _build_post_context_map(
    comments: list[CommentRecord],
    posts: list[PostRecord],
) -> dict[str, dict[str, str]]:
    """为每个 post_id 构建 post_context。

    返回 {post_id: {"title": "...", "content_excerpt": "..."}}
    content_excerpt 最多 500 个中文字符或 800 个英文字符。
    """
    post_map: dict[str, dict[str, str]] = {}
    for p in posts or []:
        content_excerpt = (p.content or "").strip()
        if len(content_excerpt) > 500:
            content_excerpt = content_excerpt[:500] + "..."
        post_map[p.post_id] = {
            "title": (p.title or "").strip(),
            "content_excerpt": content_excerpt,
        }
    return post_map


def _build_batch_prompt(
    batch: list[CommentRecord],
    start_idx: int,
    post_context_map: dict[str, dict[str, str]] | None = None,
    post_id: str | None = None,
    keyword: str = "",
) -> str:
    """构建带帖子上下文的批量 prompt。

    参数：
        batch: 当前批次的评论列表
        start_idx: 当前批次在原始评论列表中的起始索引
        post_context_map: post_id -> {title, content_excerpt} 映射
        post_id: 当前批次所属的帖子 ID
        keyword: 关键词上下文

    返回：
        格式化后的 prompt 字符串
    """
    ctx: dict[str, str] = {"title": "", "content_excerpt": ""}
    if post_context_map and post_id:
        ctx = post_context_map.get(post_id, ctx)

    comments_data = []
    for i, comment in enumerate(batch):
        comments_data.append({
            "index": start_idx + i,
            "content": comment.content or "",
            "likes": comment.likes,
        })
    comments_json = json.dumps(comments_data, ensure_ascii=False, indent=2)

    return _ANNOTATION_PROMPT_TEMPLATE.format(
        keyword=keyword or "",
        post_title=ctx["title"],
        post_content_excerpt=ctx["content_excerpt"],
        comments_json=comments_json,
    )


_VALID_SENTIMENTS = {"positive", "negative", "neutral", "mixed"}


def _parse_annotations(
    raw: dict[str, Any],
    batch: list[CommentRecord],
    start_idx: int,
) -> list[CommentAnnotationRecord]:
    """解析 LLM 输出为 CommentAnnotationRecord 列表。

    验证：
    - 必须有 annotations 字段
    - annotations 必须是 list
    - annotations 长度必须与 batch 一致
    - 每个 annotation 必须有 index
    - index 必须在 [start_idx, start_idx + len(batch)) 范围内
    - 没有重复 index
    - sentiment 必须在合法枚举中
    - 不包含 forbidden score fields
    """
    raw = filter_forbidden_scores(raw)

    annotations_raw = raw.get("annotations")
    if annotations_raw is None:
        raise ValueError("LLM 输出缺少 annotations 字段")
    if not isinstance(annotations_raw, list):
        raise ValueError(f"annotations 必须是 list，实际类型: {type(annotations_raw)}")
    if len(annotations_raw) != len(batch):
        raise ValueError(
            f"annotations 数量 ({len(annotations_raw)}) 与 batch 输入 ({len(batch)}) 不一致"
        )

    # 检查 index
    seen_indices = set()
    for item in annotations_raw:
        idx = item.get("index")
        if idx is None:
            raise ValueError("annotation 缺少 index")
        if not isinstance(idx, int):
            raise ValueError(f"index 必须是 int，实际类型: {type(idx)}")
        if idx < start_idx or idx >= start_idx + len(batch):
            raise ValueError(f"index {idx} 越界，有效范围 [{start_idx}, {start_idx + len(batch)})")
        if idx in seen_indices:
            raise ValueError(f"重复 index: {idx}")
        seen_indices.add(idx)

    # 解析
    result = []
    for item in annotations_raw:
        sentiment = str(item.get("sentiment", "neutral")).lower()
        if sentiment not in _VALID_SENTIMENTS:
            raise ValueError(f"无效 sentiment: {sentiment}，必须为 positive/negative/neutral/mixed")

        idx = item["index"]
        comment_idx = idx - start_idx
        comment = batch[comment_idx]

        result.append(CommentAnnotationRecord(
            comment_id=comment.comment_id,
            post_id=comment.post_id,
            sentiment=sentiment,
            pain_point_labels=[str(l) for l in item.get("pain_point_labels", []) if l],
            need_labels=[str(l) for l in item.get("need_labels", []) if l],
            complaint_labels=[str(l) for l in item.get("complaint_labels", []) if l],
            solution_labels=[str(l) for l in item.get("solution_labels", []) if l],
            market_signal_labels=[str(l) for l in item.get("market_signal_labels", []) if l],
            intent_labels=[str(l) for l in item.get("intent_labels", []) if l],
            reason=str(item.get("reason", "")),
        ))

    return result


class LLMCommentAnalyzerAgent:
    """LLM 评论级语义标注 Agent。

    对 CommentRecord 列表进行批量语义标注。
    LLM 只输出每条评论的语义标签和情绪。
    comment_id/post_id 由代码绑定。
    LLM 失败时 fallback 到规则版 SentimentAgent/InsightAgent。
    """

    def __init__(
        self,
        llm_client: Optional[BaseLLMClient] = None,
        batch_size: int = 10,
        max_comments: int = 50,
    ):
        self._llm = llm_client or MockLLMClient()
        self._batch_size = batch_size
        self._max_comments = max_comments

    def execute(
        self,
        comments: list[CommentRecord],
        posts: list[PostRecord] | None = None,
    ) -> list[CommentAnnotationRecord]:
        """对评论列表进行批量语义标注。

        参数：
            comments: CommentRecord 列表
            posts: 相关 PostRecord 列表（用于提供帖子上下文）

        返回：
            CommentAnnotationRecord 列表

        抛出：
            Exception: LLM 调用失败或输出不合法时抛出，由上层 fallback
        """
        if not comments:
            logger.info("LLMCommentAnalyzerAgent: comments 为空，返回空列表")
            return []

        # 构建 post context map
        post_context_map = _build_post_context_map(comments, posts or [])

        # 按 post_id 分组，同一 post 的评论尽量在同一 batch 中
        post_groups: dict[str, list[CommentRecord]] = defaultdict(list)
        for c in comments:
            post_groups[c.post_id].append(c)

        all_annotations: list[CommentAnnotationRecord] = []
        for post_id, group in post_groups.items():
            total = min(len(group), self._max_comments)
            for batch_start in range(0, total, self._batch_size):
                batch = group[batch_start:batch_start + self._batch_size]
                batch_end = min(batch_start + self._batch_size, total)
                logger.info(
                    "LLMCommentAnalyzerAgent: post_id=%s 处理 batch [%d, %d)",
                    post_id, batch_start, batch_end,
                )

                prompt = _build_batch_prompt(
                    batch, batch_start,
                    post_context_map=post_context_map,
                    post_id=post_id,
                    keyword="",
                )
                text = self._llm.generate(prompt)
                raw = extract_json_from_text(text)
                if raw is None:
                    raise RuntimeError(f"LLMCommentAnalyzerAgent: LLM 返回非法 JSON，原始内容: {text[:500]}")
                annotations = _parse_annotations(raw, batch, batch_start)
                all_annotations.extend(annotations)

        logger.info("LLMCommentAnalyzerAgent: 完成 %d 条标注", len(all_annotations))
        return all_annotations

    def execute_concurrent(
        self,
        comments: list[CommentRecord],
        posts: list[PostRecord] | None = None,
        max_concurrency: int = 10,
    ) -> list[CommentAnnotationRecord]:
        """并发模式：使用 ThreadPoolExecutor 对评论进行批量语义标注。

        每轮启动 max_concurrency 个 worker，每个处理 batch_size 条评论，
        一轮最多处理 max_concurrency * batch_size 条。

        最后一轮自动调整 worker 数。

        参数：
            comments: CommentRecord 列表
            posts: 相关 PostRecord 列表
            max_concurrency: 最大并发 worker 数（默认 10）

        返回：
            CommentAnnotationRecord 列表（按原始 index 排序）
        """
        if not comments:
            logger.info("LLMCommentAnalyzerAgent(concurrent): comments 为空，返回空列表")
            return []

        # 构建 post context map
        post_context_map = _build_post_context_map(comments, posts or [])

        # 按 post_id 分组，然后展平为全局列表（保持组内顺序）
        post_groups: dict[str, list[CommentRecord]] = defaultdict(list)
        for c in comments:
            post_groups[c.post_id].append(c)

        # 展平：每个 post 组内取前 max_comments 条
        flat_comments: list[CommentRecord] = []
        for post_id, group in post_groups.items():
            flat_comments.extend(group[:self._max_comments])

        total = len(flat_comments)
        if total == 0:
            return []

        logger.info(
            "LLMCommentAnalyzerAgent(concurrent): 展平后 %d 条评论, batch_size=%d, max_concurrency=%d",
            total, self._batch_size, max_concurrency,
        )

        # 切分为 batch
        batches: list[list[CommentRecord]] = []
        for start in range(0, total, self._batch_size):
            batches.append(flat_comments[start:start + self._batch_size])

        # 按轮次处理：每轮 max_concurrency 个 batch
        all_annotations: list[CommentAnnotationRecord] = []
        global_idx = 0  # 全局起始索引

        for round_start in range(0, len(batches), max_concurrency):
            round_batches = batches[round_start:round_start + max_concurrency]
            # 计算每个 batch 在全局列表中的起始索引
            batch_start_indices = [
                global_idx + i * self._batch_size
                for i in range(len(round_batches))
            ]

            logger.info(
                "LLMCommentAnalyzerAgent(concurrent): 第 %d 轮, %d 个 batch, %d 条评论",
                round_start // max_concurrency + 1,
                len(round_batches),
                sum(len(b) for b in round_batches),
            )

            # 并发处理本轮 batch
            round_results = self._process_batch_round(
                round_batches, batch_start_indices, post_context_map, max_concurrency,
            )
            all_annotations.extend(round_results)
            global_idx += len(round_batches) * self._batch_size

        # 按 comment_id 去重（保留首次出现）
        seen_ids: set[str] = set()
        unique_annotations: list[CommentAnnotationRecord] = []
        for a in all_annotations:
            if a.comment_id not in seen_ids:
                seen_ids.add(a.comment_id)
                unique_annotations.append(a)

        logger.info(
            "LLMCommentAnalyzerAgent(concurrent): 完成 %d 条标注（去重后）",
            len(unique_annotations),
        )
        return unique_annotations

    def _process_batch_round(
        self,
        batches: list[list[CommentRecord]],
        start_indices: list[int],
        post_context_map: dict[str, dict[str, str]],
        max_concurrency: int,
    ) -> list[CommentAnnotationRecord]:
        """处理一轮 batch（最多 max_concurrency 个并发任务）。

        每个 batch 在独立线程中处理，单 batch 失败不回滚整轮。
        """
        results: list[CommentAnnotationRecord] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            futures: dict[concurrent.futures.Future, int] = {}
            for i, (batch, start_idx) in enumerate(zip(batches, start_indices)):
                # 确定 batch 所属 post_id（用于 prompt 上下文）
                post_id = batch[0].post_id if batch else ""
                future = executor.submit(
                    self._process_single_batch,
                    batch, start_idx, post_context_map, post_id,
                )
                futures[future] = i

            for future in concurrent.futures.as_completed(futures):
                batch_idx = futures[future]
                try:
                    batch_results = future.result()
                    results.extend(batch_results)
                    logger.info(
                        "LLMCommentAnalyzerAgent(concurrent): batch %d 完成, %d 条标注",
                        batch_idx, len(batch_results),
                    )
                except Exception as e:
                    logger.error(
                        "LLMCommentAnalyzerAgent(concurrent): batch %d 失败 (%s), fallback 到规则版",
                        batch_idx, e,
                    )
                    # fallback：使用规则版 SentimentAgent/InsightAgent
                    fallback = self._fallback_annotate(batches[batch_idx])
                    results.extend(fallback)

        return results

    def _process_single_batch(
        self,
        batch: list[CommentRecord],
        start_idx: int,
        post_context_map: dict[str, dict[str, str]],
        post_id: str,
    ) -> list[CommentAnnotationRecord]:
        """处理单个 batch（在独立线程中执行）。

        每个线程创建独立的 LLM client 实例，保证线程安全。
        """
        # 创建独立的 LLM client 实例（使用 spawn() 保证线程安全）
        llm = self._llm.spawn()

        prompt = _build_batch_prompt(
            batch, start_idx,
            post_context_map=post_context_map,
            post_id=post_id,
            keyword="",
        )
        text = llm.generate(prompt)
        raw = extract_json_from_text(text)
        if raw is None:
            raise RuntimeError(f"LLMCommentAnalyzerAgent(concurrent): LLM 返回非法 JSON，原始内容: {text[:500]}")
        return _parse_annotations(raw, batch, start_idx)

    def _fallback_annotate(
        self,
        batch: list[CommentRecord],
    ) -> list[CommentAnnotationRecord]:
        """对失败 batch 使用规则版 Agent 做 fallback 标注。

        使用 SentimentAgent._classify_comment 做情感分析，
        使用 src.keywords 中的关键词做标签匹配。
        """
        from src.keywords import (
            COMPLAINT_KEYWORDS,
            MARKET_SIGNAL_KEYWORDS,
            PAIN_POINT_KEYWORDS,
            SOLUTION_KEYWORDS,
            USER_NEED_KEYWORDS,
        )

        results: list[CommentAnnotationRecord] = []
        for c in batch:
            content = c.content or ""

            # 情感分类
            sentiment_label = SentimentAgent._classify_comment(c).label

            # 标签匹配
            pain_point_labels = [kw for kw in PAIN_POINT_KEYWORDS if kw in content][:3]
            need_labels = [kw for kw in USER_NEED_KEYWORDS if kw in content][:3]
            complaint_labels = [kw for kw in COMPLAINT_KEYWORDS if kw in content][:3]
            solution_labels = [kw for kw in SOLUTION_KEYWORDS if kw in content][:3]
            market_signal_labels = [kw for kw in MARKET_SIGNAL_KEYWORDS if kw in content][:3]

            results.append(CommentAnnotationRecord(
                comment_id=c.comment_id,
                post_id=c.post_id,
                sentiment=sentiment_label,
                pain_point_labels=pain_point_labels,
                need_labels=need_labels,
                complaint_labels=complaint_labels,
                solution_labels=solution_labels,
                market_signal_labels=market_signal_labels,
                intent_labels=[],
                reason="fallback (规则版关键词匹配)",
            ))
        return results
