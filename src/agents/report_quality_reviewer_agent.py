"""报告质量评审 Agent。

评判对象：outputs/report.html
评判依据：keyword, insights, scorecard, posts, comments, comment_annotations

第一版只做规则检查，不接 LLM，不输出数字评分。
P3.1: 增加可选的 LLM 定性评审。LLM 不输出 passed/failed/评分，只输出 issues/revision_instructions/summary。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from src.llm.client import BaseLLMClient, extract_json_from_text
from src.llm.score_filter import filter_forbidden_scores
from src.schemas import CommentRecord, InsightRecord, PostRecord, ScoreCard
from src.schemas.report_review import ReportQualityReview

logger = logging.getLogger(__name__)

# 12 个必需章节
_REQUIRED_SECTIONS = [
    "采集概览",
    "评论区讨论摘要",
    "用户核心关注点",
    "用户高频疑问",
    "高互动内容信号",
    "正负向反馈总结",
    "行动意图与内容机会",
    "关键词相关内容选题建议",
    "热点选题与文案定制建议",
    "代表评论证据",
    "内容选题价值评分",
    "数据局限说明",
]

# 禁止用语
_FORBIDDEN_CLAIMS = [
    "市场规模",
    "销量预测",
    "商业可行性",
    "市场验证成功",
    "市场机会巨大",
    "完整用户画像",
]

# 模板化标题短语
_TEMPLATE_PHRASES = [
    "不得不知道的几件事",
    "谈谈真实感受",
    "选购避坑指南",
    "你需要知道",
    "小白必看",
    "说明用户对此关注度较高",
]


_LLM_REVIEW_PROMPT = """
你是报告质量评审助手。
你要评审的是"小红书评论区用户反馈与文案选题报告"的内容质量。
你不能重新分析评论，不能生成新证据，不能生成评分，不能判断市场规模或商业可行性。
你只能指出报告中的问题，并给出可以传给 ReportAgent 的修订建议。

评审输入：
keyword: {keyword}

报告文本：
{report_text}

insights（痛点/需求/投诉/方案/信号）：
{insights_summary}

代表评论：
{representative_comments}

请输出 JSON，不输出 Markdown：
{{
  "issues": [
    "问题1",
    "问题2"
  ],
  "revision_instructions": [
    "修改建议1",
    "修改建议2"
  ],
  "summary": "评审摘要"
}}

重点评审：
1. 报告是否围绕当前关键词
2. 是否引用了真实评论或洞察词
3. 热点选题是否模板化
4. 每条选题是否有依据和内容切入
5. 报告是否存在夸大结论
6. 文案建议是否对内容运营有实际价值
7. market_signals 是否解释为内容机会信号/行动意图，而不是市场规模判断

禁止输出：passed、failed、评分字段、新证据ID、新comment_id、新post_id、完整HTML、市场规模判断
"""


class ReportQualityReviewerAgent:
    """报告质量评审 Agent。

    第一版只做规则检查。不接 LLM，不输出数字评分。
    P3.1: 增加可选的 LLM 定性评审能力。
    """

    def __init__(
        self,
        llm_client: Optional[BaseLLMClient] = None,
        enable_llm_review: bool = False,
    ):
        """初始化评审 Agent。

        参数：
            llm_client: 可选的 LLM 客户端，用于定性评审
            enable_llm_review: 是否启用 LLM 评审
        """
        self._llm_client = llm_client
        self._enable_llm_review = enable_llm_review

    def _build_llm_input(
        self,
        report_html: str,
        keyword: str = "",
        insights: Optional[InsightRecord] = None,
        comments: Optional[list[CommentRecord]] = None,
        comment_annotations: Optional[list[Any]] = None,
    ) -> str:
        """从报告、洞察和评论中构造精简的 LLM 评审输入。

        参数：
            report_html: 完整的 report.html 内容
            keyword: 搜索关键词
            insights: InsightRecord
            comments: 标准化评论列表
            comment_annotations: 可选评论标注

        返回：
            格式化的 prompt 字符串
        """
        # 将 HTML 转纯文本
        text = re.sub(r'<[^>]+>', '', report_html)
        text = re.sub(r'\s+', ' ', text).strip()
        report_text = text[:5000]

        # insights 摘要
        insights_summary = ""
        if insights:
            parts = []
            for field, label in [
                ("pain_points", "痛点"),
                ("user_needs", "需求"),
                ("complaints", "投诉"),
                ("solutions", "方案"),
                ("market_signals", "信号"),
            ]:
                vals = getattr(insights, field, [])
                if vals:
                    parts.append(f"{label}: {'、'.join(vals[:6])}")
            insights_summary = "；".join(parts)

        # 代表评论（最多 20 条）
        rep_comments = []
        if comments:
            for c in comments[:20]:
                rep_comments.append(c.content or "")

        return _LLM_REVIEW_PROMPT.format(
            keyword=keyword or "",
            report_text=report_text,
            insights_summary=insights_summary or "（无）",
            representative_comments=(
                json.dumps(rep_comments, ensure_ascii=False)
                if rep_comments
                else "（无）"
            ),
        )

    def _run_llm_review(
        self,
        prompt: str,
    ) -> tuple[list[str], list[str], str]:
        """调用 LLM 进行定性评审。

        参数：
            prompt: 完整的 prompt 文本

        返回：
            (issues, revision_instructions, summary) 元组
            issues: LLM 发现的问题列表
            revision_instructions: LLM 给出的修订建议列表
            summary: LLM 评审摘要

        异常：
            RuntimeError: LLM 调用失败
        """
        text = self._llm_client.generate(prompt)
        raw = extract_json_from_text(text)
        if raw is None:
            raise RuntimeError(f"ReportQualityReviewerAgent: LLM 返回非法 JSON，原始内容: {text[:500]}")
        raw = filter_forbidden_scores(raw)

        issues = raw.get("issues", [])
        revision_instructions = raw.get("revision_instructions", [])
        summary = raw.get("summary", "")

        if not isinstance(issues, list):
            issues = []
        if not isinstance(revision_instructions, list):
            revision_instructions = []
        if not isinstance(summary, str):
            summary = str(summary)

        return issues, revision_instructions, summary

    def review(
        self,
        report_html: str,
        keyword: str = "",
        insights: Optional[InsightRecord] = None,
        scorecard: Optional[ScoreCard] = None,
        posts: Optional[list[PostRecord]] = None,
        comments: Optional[list[CommentRecord]] = None,
        comment_annotations: Optional[list[Any]] = None,
    ) -> ReportQualityReview:
        """评审报告质量。

        参数：
            report_html: 完整的 report.html 内容
            keyword: 搜索关键词
            insights: InsightRecord
            scorecard: ScoreCard
            posts: 标准化帖子列表
            comments: 标准化评论列表
            comment_annotations: 可选评论标注

        返回：
            ReportQualityReview
        """
        reasons: list[str] = []
        hard_fail_reasons: list[str] = []
        revision_instructions: list[str] = []

        # 规则 1：12 个必需章节存在
        missing = [s for s in _REQUIRED_SECTIONS if s not in report_html]
        if missing:
            msg = f"报告缺少章节: {', '.join(missing)}"
            hard_fail_reasons.append(msg)
            revision_instructions.append(f"补充以下章节: {', '.join(missing)}")

        # 规则 2：必须包含数据局限说明
        if "数据局限说明" not in report_html:
            hard_fail_reasons.append("缺少数据局限说明")
            revision_instructions.append("补充数据局限说明")

        # 规则 3：禁止夸大结论
        for phrase in _FORBIDDEN_CLAIMS:
            if phrase in report_html:
                hard_fail_reasons.append(f"报告包含禁止用语: {phrase}")
                revision_instructions.append(f"删除或改写'{phrase}'相关表述")

        # 规则 4：代表评论证据必须来自真实 comments
        if comments:
            real_ids = {c.comment_id for c in comments}
            found_ids = re.findall(
                r'comment[_-]?id["\']?\s*[:=]\s*["\']?([^"\'<>\s]+)',
                report_html,
                re.IGNORECASE,
            )
            bad_ids = [cid for cid in found_ids if cid not in real_ids]
            if bad_ids:
                hard_fail_reasons.append(
                    f"报告包含不存在的 comment_id: {', '.join(bad_ids[:5])}"
                )
                revision_instructions.append("修正评论证据引用")

            if not re.search(
                r"(评论|evidence).{0,100}\w+", report_html[:5000]
            ):
                reasons.append("报告前部未展示代表评论证据")
                revision_instructions.append("在代表评论证据部分引用真实评论")

        # 规则 5：热点选题不能完全模板化
        has_template = False
        for phrase in _TEMPLATE_PHRASES:
            if phrase in report_html:
                has_template = True
                break

        if has_template:
            # 检查是否引用了真实洞察词
            if insights:
                real_terms: set[str] = set()
                for field in [
                    insights.user_needs,
                    insights.pain_points,
                    insights.complaints,
                    insights.solutions,
                    insights.market_signals,
                ]:
                    for term in field:
                        if len(term) >= 2:
                            real_terms.add(term)
                # 在"热点选题"相关区域搜索真实词
                start_section = report_html.find("热点选题与文案定制建议")
                section = (
                    report_html[start_section : start_section + 3000]
                    if start_section >= 0
                    else ""
                )
                found_real = [
                    t for t in real_terms if t in (section or report_html)
                ]
                if not found_real:
                    reasons.append("热点选题过于模板化，未引用真实洞察词")
                    revision_instructions.append(
                        "热点选题必须引用真实评论或洞察中的词"
                    )
                    revision_instructions.append(
                        "每条选题建议需要包含依据和内容切入"
                    )
                    revision_instructions.append("避免使用通用模板标题")
            else:
                reasons.append("热点选题可能过于模板化（无 insights 可核对）")

        # 规则 6：报告必须围绕当前 keyword
        if keyword and keyword not in report_html:
            reasons.append(f"报告未出现关键词: {keyword}")
            revision_instructions.append(
                f"围绕当前关键词'{keyword}'重写摘要和选题建议"
            )

        # 规则 7：HTML 结构基本完整
        if (
            "<html" not in report_html.lower()
            and "<body" not in report_html.lower()
        ):
            hard_fail_reasons.append("HTML 结构不完整")
            revision_instructions.append("确保报告包含完整的 HTML 结构")

        # ---- LLM 定性评审 ----
        raw_llm_issues: list[str] = []
        llm_summary_text: str = ""
        if self._enable_llm_review and self._llm_client is not None:
            try:
                prompt = self._build_llm_input(
                    report_html=report_html,
                    keyword=keyword,
                    insights=insights,
                    comments=comments,
                    comment_annotations=comment_annotations,
                )
                llm_issues, llm_revision, llm_summary = self._run_llm_review(prompt)
                raw_llm_issues = llm_issues
                reasons.extend(llm_issues)
                revision_instructions.extend(llm_revision)
                llm_summary_text = llm_summary
                logger.info(
                    "LLM 定性评审完成: %d issues, %d revision_instructions",
                    len(llm_issues),
                    len(llm_revision),
                )
            except Exception as e:
                logger.warning(
                    "LLM review failed, fallback to rule-only review: %s", e
                )

        # ---- 判定是否通过 ----
        passed = len(hard_fail_reasons) == 0

        # 如果规则通过但 LLM 发现模板化问题，可触发修订
        if (
            passed
            and self._enable_llm_review
            and raw_llm_issues
        ):
            template_issues = [
                i
                for i in raw_llm_issues
                if any(
                    kw in i
                    for kw in ["模板化", "未引用", "不贴合", "泛泛"]
                )
            ]
            if len(template_issues) >= 2:
                passed = False
                hard_fail_reasons.append("LLM 评审发现模板化问题")

        # ---- 摘要 ----
        if passed:
            if reasons:
                summary_base = (
                    f"报告通过质量门禁，但有 {len(reasons)} 条建议"
                )
            else:
                summary_base = "报告通过质量门禁"
        else:
            summary_base = (
                f"报告未通过质量门禁。{len(hard_fail_reasons)} 条硬失败，"
                f"{len(reasons)} 条建议。{' '.join(hard_fail_reasons[:2])}"
            )

        # 追加 LLM 摘要
        if llm_summary_text:
            summary = f"{summary_base} LLM: {llm_summary_text}"
        else:
            summary = summary_base

        return ReportQualityReview(
            passed=passed,
            reasons=reasons,
            hard_fail_reasons=hard_fail_reasons,
            revision_instructions=revision_instructions,
            summary=summary,
        )
