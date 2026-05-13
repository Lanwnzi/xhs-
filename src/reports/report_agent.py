"""
报告生成器 - 生成小红书评论洞察与文案选题报告

输入：InsightRecord, ScoreCard, NormalizedDataset
输出：ReportResult（report_path 指向 data/outputs/report.html）

操作：
  1. 读取洞察、评分和数据集
  2. 构建内联 CSS 的自包含 HTML 报告
  3. 写入 data/outputs/report.html

边界约束：
  - 不重新计算评分
  - 不重新提取洞察
  - 不编造证据
  - 用户原文使用 html.escape() 转义
"""

from __future__ import annotations

import html
import json
import logging
import os
from collections import Counter
from datetime import datetime
from typing import Any, Optional

from src.keywords import (
    COMPLAINT_KEYWORDS,
    PAIN_POINT_KEYWORDS,
    USER_NEED_KEYWORDS,
)
from src.schemas import (
    CommentRecord,
    InsightRecord,
    NormalizedDataset,
    PostRecord,
    ReportResult,
    ScoreCard,
)
from src.schemas.content_ideation import ContentIdeationResult
from src.utils import AppPaths, get_app_paths

logger = logging.getLogger(__name__)


# 评分等级阈值：(最低分数, 等级名称, 颜色)
_GRADE_THRESHOLDS: list[tuple[float, str, str]] = [
    (0.8, "优秀", "#27ae60"),
    (0.6, "良好", "#f39c12"),
    (0.4, "一般", "#e67e22"),
]

# 购买意向关键字（与 rules.py 保持一致）
_PURCHASE_KEYWORDS: set[str] = {
    "多少钱",
    "哪里买",
    "想买",
    "怎么买",
    "下单",
    "链接",
    "求链接",
    "同求",
    "要买",
    "入手",
    "购买",
    "求购",
    "在哪儿",
    "买",
}


def _grade(score: float) -> tuple[str, str]:
    """根据给定分数返回（等级名称, 颜色十六进制码）。"""
    for threshold, label, color in _GRADE_THRESHOLDS:
        if score >= threshold:
            return label, color
    return "较差", "#e74c3c"


def _score_color(score: float) -> str:
    """根据分数值返回十六进制颜色码。"""
    if score >= 0.7:
        return "#27ae60"  # 绿色
    if score >= 0.4:
        return "#f39c12"  # 黄色/橙色
    return "#e74c3c"  # 红色


# ===================================================================
# HTML 报告构建器
# ===================================================================


class ReportAgent:
    """负责生成小红书评论洞察与文案选题报告的 Agent。

    参数:
        paths: AppPaths 实例，用于定制持久化路径。为 None 时使用全局默认路径。
    """

    def __init__(self, paths: Optional[AppPaths] = None):
        self._paths = paths

    def execute(
        self,
        insight: InsightRecord,
        scorecard: ScoreCard,
        dataset: NormalizedDataset,
        topic: str = "",
        product_direction: str = "",
        revision_instructions: Optional[list[str]] = None,
        comment_clusters_data: Optional[dict] = None,
        content_ideation_result: Optional[ContentIdeationResult] = None,
    ) -> ReportResult:
        """生成 HTML 报告并持久化。

        参数：
            insight: 结构化洞察（含证据链）
            scorecard: 各维度评分及理由
            dataset: 标准化后的帖子和评论
            topic: 主题词，为空时从数据中推断
            product_direction: 产品方向，为空时从数据中推断
            revision_instructions: 质量评审后修订指令，会影响内容块文案
            comment_clusters_data: P6.0 评论聚类数据（dict）。为 None 时自动从文件读取。
            content_ideation_result: P2 新增，ContentIdeationAgent 预生成的内容选题建议。
                不为 None 时替代内部 _build_topic_suggestions / _build_custom_title_suggestions。

        返回：
            ReportResult（含成功状态和文件路径）
        """
        paths = self._paths or get_app_paths()

        # P6.0 读取评论聚类数据（优先使用显式传入的数据，否则从文件读取）
        clusters_data = comment_clusters_data
        if clusters_data is None:
            clusters_path = getattr(paths, "comment_clusters_file", "") or os.path.join(
                paths.outputs_dir, "comment_clusters.json"
            )
            if os.path.exists(clusters_path):
                try:
                    with open(clusters_path, encoding="utf-8") as _f:
                        clusters_data = json.load(_f)
                except Exception:
                    pass

        html_content = self._build_html(
            insight, scorecard, dataset,
            topic, product_direction,
            revision_instructions=revision_instructions,
            clusters_data=clusters_data,
            content_ideation_result=content_ideation_result,
        )
        self._persist(html_content)

        logger.info("报告已生成: %s", paths.report_file)
        return ReportResult(success=True, report_path=paths.report_file)

    # ------------------------------------------------------------------
    # HTML 构建
    # ------------------------------------------------------------------

    @staticmethod
    def _build_html(
        insight: InsightRecord,
        scorecard: ScoreCard,
        dataset: NormalizedDataset,
        topic: str = "",
        product_direction: str = "",
        revision_instructions: Optional[list[str]] = None,
        clusters_data: Optional[dict] = None,
        content_ideation_result: Optional[ContentIdeationResult] = None,
    ) -> str:
        """组装完整 HTML 报告（12 章节结构）。

        参数：
            revision_instructions: 质量评审后的修订指令，
                用于调整内容块文案而不修改 insight/scorecard 数据。
            content_ideation_result: P2 新增，预生成的内容选题建议。
                不为 None 时替代内部 _build_topic_suggestions / _build_custom_title_suggestions。
        """
        # 优先使用传入的主题词/产品方向，否则从第一条帖子推断
        if not topic or not product_direction:
            derived_topic, derived_dir = _derive_topic(dataset)
            if not topic:
                topic = derived_topic
            if not product_direction:
                product_direction = derived_dir

        # 评分等级计算
        overall_grade, overall_color = _grade(scorecard.overall_score)
        grade_label_tc = {
            "优秀": "用户关注度较高，内容方向可行",
            "良好": "用户讨论存在机会，需关注问题点",
            "一般": "用户讨论热度一般，建议谨慎评估",
            "较差": "用户关注度不足，建议重新评估方向",
        }

        # --- 各部分数据准备 ---

        # 正负向反馈
        negative_feedbacks = _dedup_ordered(
            insight.complaints + insight.pain_points
        )

        # 关键词频率
        top_keywords = _compute_keyword_freq(dataset)

        # 代表性证据
        evidence_posts, evidence_comments = _collect_evidence(
            insight, dataset
        )

        # --- 解析修订指令 ---
        _revision_flags = _parse_revision_instructions(revision_instructions)
        _force_topic = _revision_flags.get("force_topic_mention", False)
        _avoid_template = _revision_flags.get("avoid_template", False)

        # ---- 构建 12 个章节 ----
        sections_html = ""

        # ================================================================
        # 1. 采集概览
        # ================================================================
        sections_html += f"""
        <div class="section">
            <h2>采集概览</h2>
            <table class="info-table">
                <tr><td class="label">主题词</td><td>{html.escape(topic)}</td></tr>
                <tr><td class="label">产品方向</td><td>{html.escape(product_direction)}</td></tr>
                <tr><td class="label">数据来源</td><td>{html.escape(_get_data_source(dataset))}</td></tr>
                <tr><td class="label">帖子数</td><td>{len(dataset.posts)}</td></tr>
                <tr><td class="label">评论数</td><td>{len(dataset.comments)}</td></tr>
            </table>
        </div>"""

        # ================================================================
        # 2. 评论区讨论摘要
        # ================================================================
        sentiment_label = (insight.sentiment or "neutral").lower()
        if sentiment_label == "positive":
            sentiment_desc = "偏正面"
        elif sentiment_label == "negative":
            sentiment_desc = "偏负面"
        else:
            sentiment_desc = "偏中性"

        discussion_summary = (
            f"基于 {len(dataset.comments)} 条评论的情感分析，"
            f"评论区整体情感{ sentiment_desc }。"
        )
        if insight.user_needs:
            top_needs = insight.user_needs[:3]
            discussion_summary += (
                f"用户主要关注：{'、'.join(top_needs)}。"
            )
        if negative_feedbacks:
            top_neg = negative_feedbacks[:3]
            discussion_summary += (
                f"常见反馈问题：{'、'.join(top_neg)}。"
            )
        # 修订指令：确保关键词出现在摘要中
        if _force_topic and topic and topic not in discussion_summary:
            discussion_summary += (
                f"围绕关键词「{topic}」的讨论中，"
                f"用户反馈呈现上述特征。"
            )

        sections_html += f"""
        <div class="section">
            <h2>评论区讨论摘要</h2>
            <p>{html.escape(discussion_summary)}</p>
        </div>"""

        # ================================================================
        # 3. 用户核心关注点
        # ================================================================
        needs_html = ""
        if insight.user_needs:
            for need in insight.user_needs:
                needs_html += f'<li class="tag-item">{html.escape(need)}</li>\n'
        else:
            needs_html = '<li class="empty">暂无明确的用户关注点关键词</li>'

        # P6.0 聚类增强：高频评论主题
        cluster_extra_html = _cluster_html(clusters_data)

        sections_html += f"""
        <div class="section">
            <h2>用户核心关注点</h2>
            <p class="section-desc">以下是从帖子和评论中提取的用户核心关注方向：</p>
            <ul class="tag-list">{needs_html}</ul>
            {cluster_extra_html}
        </div>"""

        # ================================================================
        # 4. 用户高频疑问
        # ================================================================
        # 从 user_needs 和 market_signals 中提取疑问性内容
        all_questions = list(insight.user_needs) + list(insight.market_signals)
        question_like = [
            q for q in all_questions
            if any(kw in q for kw in ["?", "吗", "怎么", "如何", "什么", "哪些", "哪个", "还是", "还是说", "是否"])
        ]
        if not question_like:
            question_like = insight.user_needs[:5]
        if not question_like:
            question_like = insight.market_signals[:5]

        q_html = ""
        if question_like:
            for q in question_like[:6]:
                q_html += f'<li class="tag-item question">{html.escape(q)}</li>\n'
        else:
            q_html = '<li class="empty">暂未发现用户高频疑问</li>'

        sections_html += f"""
        <div class="section">
            <h2>用户高频疑问</h2>
            <p class="section-desc">用户在讨论中反复提及的疑问或关注方向：</p>
            <ul class="tag-list">{q_html}</ul>
        </div>"""

        # ================================================================
        # 5. 高互动内容信号
        # ================================================================
        # 按互动量（点赞+评论）排序展示帖子
        sorted_posts = sorted(
            dataset.posts,
            key=lambda p: p.likes + p.comments,
            reverse=True,
        )[:5]

        hi_html = ""
        if sorted_posts:
            for post in sorted_posts:
                engagement = post.likes + post.comments
                hi_html += f"""
                <div class="evidence-card">
                    <div class="evidence-meta">[{html.escape(post.platform)}] {html.escape(post.post_id)} | {{点赞 {post.likes} | 评论 {post.comments}}} | 总互动 {engagement}</div>
                    <div class="evidence-title">{html.escape(post.title)}</div>
                </div>"""
        else:
            hi_html = '<p class="empty">暂无高互动内容数据</p>'

        sections_html += f"""
        <div class="section">
            <h2>高互动内容信号</h2>
            <p class="section-desc">按互动量（点赞+评论）排序的高互动帖子：</p>
            {hi_html}
        </div>"""

        # ================================================================
        # 6. 正负向反馈总结
        # ================================================================
        # 正向：用户需求作为正面关注方向
        positive_items = insight.user_needs[:5]

        # 负向：投诉 + 痛点
        negative_items = negative_feedbacks[:8]

        feedback_html = ""
        if positive_items:
            feedback_html += '<h3>正向关注方向</h3><ul class="tag-list">'
            for item in positive_items:
                feedback_html += f'<li class="tag-item">{html.escape(item)}</li>\n'
            feedback_html += '</ul>'

        if negative_items:
            feedback_html += '<h3 style="margin-top:16px;">负面反馈与痛点</h3><ul class="tag-list">'
            for item in negative_items:
                feedback_html += f'<li class="tag-item negative">{html.escape(item)}</li>\n'
            feedback_html += '</ul>'

        if not positive_items and not negative_items:
            feedback_html = '<p class="empty">暂无明确的用户反馈数据</p>'

        sections_html += f"""
        <div class="section">
            <h2>正负向反馈总结</h2>
            <p class="section-desc">用户表达的正向关注方向与负面反馈：</p>
            {feedback_html}
        </div>"""

        # ================================================================
        # 7. 购买 / 行动信号
        # ================================================================
        # 展示购买相关信号和替代方案
        purchase_signals = [
            s for s in insight.market_signals
            if any(kw in s for kw in _PURCHASE_KEYWORDS)
        ]

        buy_html = ""
        if purchase_signals:
            buy_html += '<h3>购买行动信号</h3><ul class="tag-list">'
            for sig in purchase_signals[:8]:
                buy_html += f'<li class="tag-item">{html.escape(sig)}</li>\n'
            buy_html += '</ul>'

        if insight.solutions:
            buy_html += '<h3 style="margin-top:16px;">被提及的替代方案/产品</h3><ul class="tag-list">'
            for sol in insight.solutions[:6]:
                buy_html += f'<li class="tag-item">{html.escape(sol)}</li>\n'
            buy_html += '</ul>'

        if not purchase_signals and not insight.solutions:
            buy_html = '<p class="empty">暂未发现明确的购买行动信号</p>'

        sections_html += f"""
        <div class="section">
            <h2>购买 / 行动信号</h2>
            <p class="section-desc">用户表达的购买意向、行动信号及提及的替代方案：</p>
            {buy_html}
        </div>"""

        # ================================================================
        # 8. 关键词相关内容选题建议
        # ================================================================
        if content_ideation_result and content_ideation_result.topic_suggestions:
            # P2: 使用 ContentIdeationAgent 预生成的结果
            sug_html = ""
            for i, ts in enumerate(content_ideation_result.topic_suggestions, 1):
                persp_tag = ""
                if content_ideation_result.generation_mode == "multi_perspective":
                    persp_tag = f' <span class="perspective-tag">[{ts.direction}]</span>'
                sug_html += (
                    f'<li><strong>{html.escape(ts.title)}</strong>{persp_tag}'
                    f'<br><small>依据：{html.escape(ts.evidence)}</small>'
                    f'<br><small>文案角度：{html.escape(ts.content_angle)}</small></li>\n'
                )
            sections_html += f"""
            <div class="section">
                <h2>关键词相关内容选题建议</h2>
                <p class="section-desc">基于用户反馈和痛点洞察生成的内容选题方向（LLM 生成{'-多角度' if content_ideation_result.generation_mode == 'multi_perspective' else ''}）：</p>
                <ul class="suggestion-list">{sug_html}</ul>
            </div>"""
        else:
            # 回退：使用原有模板化方法
            topic_suggestions = _build_topic_suggestions(topic, dataset, insight)
            cluster_sugs = _cluster_topic_suggestions(clusters_data)
            if cluster_sugs:
                for csug in cluster_sugs:
                    topic_suggestions.append(csug.get("direction", ""))
            sug_html = ""
            if topic_suggestions:
                for i, sug in enumerate(topic_suggestions, 1):
                    sug_html += f'<li>{html.escape(sug)}</li>\n'
            else:
                sug_html = '<li class="empty">基于当前数据暂无法生成文案方向建议</li>'
            sections_html += f"""
            <div class="section">
                <h2>关键词相关内容选题建议</h2>
                <p class="section-desc">基于用户反馈和痛点洞察生成的内容选题方向：</p>
                <ul class="suggestion-list">{sug_html}</ul>
            </div>"""

        # ================================================================
        # 9. 热点选题与文案定制建议
        # ================================================================
        if content_ideation_result and content_ideation_result.custom_title_suggestions:
            # P2: 使用 ContentIdeationAgent 预生成的结果
            title_html = ""
            for i, ts in enumerate(content_ideation_result.custom_title_suggestions, 1):
                title_html += f"""
                <div class="title-suggestion">
                    <h4>选题 {i}：{html.escape(ts.direction)}</h4>
                    <p><strong>推荐标题：</strong>{html.escape(ts.title)}</p>
                    <p class="evidence"><strong>依据：</strong>{html.escape(ts.evidence)}</p>
                    <p class="content-angle"><strong>内容切入：</strong>{html.escape(ts.content_angle)}</p>
                </div>"""
            sections_html += f"""
            <div class="section">
                <h2>热点选题与文案定制建议</h2>
                <p class="section-desc">基于真实评论数据生成的定制化标题建议（LLM 生成{'-多角度' if content_ideation_result.generation_mode == 'multi_perspective' else ''}）：</p>
                {title_html}
            </div>"""
        else:
            # 回退：使用原有模板化方法
            title_suggestions = _build_custom_title_suggestions(
                topic, dataset, insight,
                avoid_template=_avoid_template,
            )
            cluster_title_sugs = _cluster_topic_suggestions(clusters_data)
            title_suggestions.extend(cluster_title_sugs)
            title_html = ""
            for i, ts in enumerate(title_suggestions, 1):
                direction = ts.get("direction", "")
                title = ts.get("title", "")
                evidence = ts.get("evidence", "")
                content_angle = ts.get("content_angle", "")
                title_html += f"""
                <div class="title-suggestion">
                    <h4>选题 {i}：{html.escape(direction)}</h4>
                    <p><strong>推荐标题：</strong>{html.escape(title)}</p>
                    <p class="evidence"><strong>依据：</strong>{html.escape(evidence)}</p>
                    <p class="content-angle"><strong>内容切入：</strong>{html.escape(content_angle)}</p>
                </div>"""
            sections_html += f"""
            <div class="section">
                <h2>热点选题与文案定制建议</h2>
                <p class="section-desc">基于真实评论数据生成的定制化标题建议：</p>
                {title_html}
            </div>"""

        # ================================================================
        # 10. 代表评论证据
        # ================================================================
        ev_html = ""

        if evidence_posts:
            ev_html += '<h3>相关帖子</h3>'
            for post in evidence_posts:
                content_trunc = post.content[:150] + ("..." if len(post.content) > 150 else "")
                ev_html += f"""
                <div class="evidence-card">
                    <div class="evidence-meta">[{html.escape(post.platform)}] {html.escape(post.post_id)} | {html.escape(post.author)} | {html.escape(post.publish_time)}</div>
                    <div class="evidence-title">{html.escape(post.title)}</div>
                    <div class="evidence-content">{html.escape(content_trunc)}</div>
                </div>"""

        if evidence_comments:
            ev_html += '<h3>相关评论</h3>'
            for comment in evidence_comments:
                ev_html += f"""
                <div class="evidence-card comment">
                    <div class="evidence-meta">{html.escape(comment.comment_id)} | {html.escape(comment.author)} | 赞 {comment.likes}</div>
                    <div class="evidence-content">{html.escape(comment.content)}</div>
                </div>"""

        if not evidence_posts and not evidence_comments:
            ev_html = '<p class="empty">暂无代表性证据数据</p>'

        sections_html += f"""
        <div class="section">
            <h2>代表评论证据</h2>
            {ev_html}
        </div>"""

        # ================================================================
        # 11. 内容选题价值评分
        # ================================================================
        # 评分总览
        sections_html += f"""
        <div class="section">
            <h2>内容选题价值评分</h2>
            <div class="overall-score" style="background:{overall_color}20; border-left:6px solid {overall_color};">
                <span class="score-value" style="color:{overall_color};">{scorecard.overall_score:.2f}</span>
                <span class="score-grade" style="color:{overall_color};">{overall_grade}</span>
                <p class="score-desc">{grade_label_tc.get(overall_grade, "")}</p>
            </div>"""

        # 评分拆解（内嵌在评分章节中）
        dims = [
            ("用户关注度", "demand_intensity", "衡量用户对该话题的关注程度，基于用户需求数量和内容机会信号数量"),
            ("负反馈程度", "sentiment_friction", "衡量用户负面情绪和投诉程度，基于情感倾向和投诉/痛点数量"),
            ("方案饱和度", "solution_saturation", "衡量已有替代方案的充足程度，基于解决方案提及数量"),
            ("行动信号", "purchase_intent", "衡量用户购买行动信号的强烈程度，基于购买相关信号数量"),
            ("时效性", "freshness", "衡量数据的新鲜程度，基于最新帖子的时间距离"),
        ]

        table_rows = ""
        for label, attr, desc in dims:
            val = getattr(scorecard, attr)
            color = _score_color(val)
            reason_line = _extract_reason(scorecard.scoring_reason, attr)
            table_rows += f"""
            <tr>
                <td>{label}</td>
                <td style="color:{color}; font-weight:bold;">{val:.2f}</td>
                <td class="reason-cell">{html.escape(reason_line or desc)}</td>
            </tr>"""

        overall_color_row = _score_color(scorecard.overall_score)
        table_rows += f"""
            <tr class="overall-row">
                <td><strong>内容选题价值</strong></td>
                <td style="color:{overall_color_row}; font-weight:bold;">{scorecard.overall_score:.2f}</td>
                <td class="reason-cell">{html.escape(scorecard.scoring_reason.replace(chr(10), ' | '))}</td>
            </tr>"""

        sections_html += f"""
            <h3 style="margin-top:20px;">评分拆解</h3>
            <table class="score-table">
                <thead>
                    <tr><th>维度</th><th>分数</th><th>评分依据</th></tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </div>"""

        # ================================================================
        # 12. 数据局限说明
        # ================================================================
        sections_html += f"""
        <div class="section">
            <h2>数据局限说明</h2>
            <p>本报告基于小红书搜索结果与可见评论区内容自动生成，仅用于辅助用户反馈分析和内容选题参考，不代表完整市场规模、整体用户画像、真实销量或商业可行性结论。平台推荐机制、关键词选择、采集数量、帖子互动差异和可见评论范围都会影响分析结果。</p>
        </div>"""

        # ---- 组装完整 HTML ----
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>小红书评论洞察与文案选题报告 - {html.escape(topic)}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif; background:#f5f7fa; color:#2c3e50; line-height:1.6; }}
.container {{ max-width:960px; margin:0 auto; padding:20px 16px; }}
.header {{ background:linear-gradient(135deg,#667eea,#764ba2); color:#fff; padding:40px 20px; border-radius:12px; margin-bottom:24px; text-align:center; }}
.header h1 {{ font-size:1.8em; margin-bottom:8px; }}
.header .subtitle {{ font-size:1em; opacity:0.9; }}
.section {{ background:#fff; border-radius:10px; padding:24px; margin-bottom:20px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
.section h2 {{ font-size:1.3em; margin-bottom:16px; color:#2c3e50; border-bottom:3px solid #667eea; padding-bottom:8px; display:inline-block; }}
.section h3 {{ font-size:1.1em; margin:16px 0 8px; color:#555; }}
.section-desc {{ color:#777; font-size:0.9em; margin-bottom:12px; }}
.info-table {{ width:100%; border-collapse:collapse; }}
.info-table td {{ padding:8px 12px; border-bottom:1px solid #eee; }}
.info-table .label {{ font-weight:600; color:#555; width:120px; }}
.overall-score {{ padding:20px; border-radius:8px; text-align:center; margin:12px 0; }}
.overall-score .score-value {{ font-size:3em; font-weight:800; display:block; }}
.overall-score .score-grade {{ font-size:1.5em; font-weight:600; display:block; margin:4px 0; }}
.overall-score .score-desc {{ color:#666; font-size:1em; margin-top:8px; }}
.score-table {{ width:100%; border-collapse:collapse; margin-top:12px; }}
.score-table th {{ background:#f0f2f5; padding:10px 12px; text-align:left; font-weight:600; color:#555; }}
.score-table td {{ padding:10px 12px; border-bottom:1px solid #eee; }}
.score-table .reason-cell {{ font-size:0.88em; color:#666; }}
.score-table .overall-row {{ background:#f8f9ff; }}
.tag-list {{ list-style:none; display:flex; flex-wrap:wrap; gap:8px; }}
.tag-item {{ background:#eef2ff; color:#4a5568; padding:4px 12px; border-radius:16px; font-size:0.9em; }}
.tag-item.negative {{ background:#ffeef0; color:#c0392b; }}
.tag-item.question {{ background:#fef3e2; color:#b8860b; }}
.tag-list .empty {{ color:#999; font-style:italic; }}
.evidence-card {{ background:#f8f9fb; border-left:4px solid #667eea; padding:12px 16px; margin:10px 0; border-radius:4px; }}
.evidence-card.comment {{ border-left-color:#e67e22; }}
.evidence-meta {{ font-size:0.82em; color:#999; margin-bottom:4px; }}
.evidence-title {{ font-weight:600; color:#2c3e50; margin-bottom:4px; }}
.evidence-content {{ font-size:0.92em; color:#555; line-height:1.5; }}
.suggestion-list {{ list-style:disc; padding-left:20px; }}
.suggestion-list li {{ margin:6px 0; color:#555; }}
.title-list {{ list-style:none; padding:0; }}
.title-item {{ background:#f0f7ff; border-left:4px solid #667eea; padding:10px 14px; margin:8px 0; border-radius:4px; color:#2c3e50; font-weight:500; }}
.title-suggestion {{ background:#f0f7ff; border-left:4px solid #667eea; padding:12px 16px; margin:12px 0; border-radius:4px; }}
.title-suggestion h4 {{ font-size:1em; color:#2c3e50; margin-bottom:6px; }}
.title-suggestion p {{ font-size:0.9em; color:#555; margin:4px 0; }}
.cluster-section {{ background:#f0faf0; border-radius:8px; padding:16px; margin-top:12px; }}
.cluster-card {{ background:#fff; border:1px solid #d5e8d5; border-radius:6px; padding:10px 14px; margin:8px 0; display:flex; flex-wrap:wrap; align-items:center; gap:8px; }}
.cluster-rank {{ background:#27ae60; color:#fff; font-weight:700; font-size:0.85em; padding:2px 8px; border-radius:10px; }}
.cluster-topic {{ font-weight:600; color:#2c3e50; font-size:0.95em; }}
.cluster-heat {{ font-size:0.85em; font-weight:600; }}
.cluster-count {{ font-size:0.82em; color:#888; }}
.cluster-quote {{ color:#666; font-size:0.85em; font-style:italic; padding:4px 8px; border-left:3px solid #27ae60; margin:4px 0; width:100%; }}
.empty {{ color:#999; font-style:italic; }}
.footer {{ text-align:center; color:#999; font-size:0.82em; padding:20px 0; border-top:1px solid #eee; margin-top:20px; }}
@media (max-width:600px) {{ .header h1 {{ font-size:1.4em; }} .section {{ padding:16px; }} }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>小红书评论区用户反馈与文案选题报告</h1>
        <div class="subtitle">{html.escape(topic)} — {html.escape(product_direction)}</div>
    </div>
    {sections_html}
    <div class="footer">
        <p>本报告由 XHS Comment Insight Agent 自动生成 | 数据来源：{html.escape(_get_data_source(dataset))} | 评分基于规则引擎</p>
        <p>生成时间：{html.escape(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))}</p>
    </div>
</div>
</body>
</html>"""

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _persist(self, html_content: str) -> None:
        """将 HTML 报告写入磁盘。"""
        paths = self._paths or get_app_paths()
        os.makedirs(paths.outputs_dir, exist_ok=True)

        with open(paths.report_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        logger.info("Persisted report to %s", paths.report_file)


# ===================================================================
# 模块级辅助函数
# ===================================================================


def _get_data_source(dataset: NormalizedDataset) -> str:
    """从数据集中推断数据来源描述。

    如果数据集中的帖子包含真实 post_id 格式（长十六进制），
    且平台为 xhs，标记为"小红书 (真实采集)"。
    否则沿用标记。
    """
    if dataset.posts:
        # 检查是否有真实采集特征：post_id 为 24 位以上 hex
        for post in dataset.posts:
            if post.platform == "xhs" and len(post.post_id) >= 20 and all(c in "0123456789abcdef" for c in post.post_id.lower()):
                return "小红书 (真实采集)"
    return "小红书 (mock)"


def _derive_topic(dataset: NormalizedDataset) -> tuple[str, str]:
    """从数据集中推断主题词和产品方向。

    使用第一条可用的帖子的标题和标签作为占位值。
    """
    if dataset.posts:
        post = dataset.posts[0]
        topic = post.title if post.title else "未知主题"
        # 尝试从标签或标题中提取产品方向
        product_direction = (
            post.tags[0] if post.tags else post.title.split("！")[0]
            if "！" in post.title
            else post.title[:20]
        )
        return topic, product_direction
    return "未知主题", "未知产品方向"


def _dedup_ordered(items: list[str]) -> list[str]:
    """去除重复项，同时保持原有顺序。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _compute_keyword_freq(
    dataset: NormalizedDataset,
) -> list[tuple[str, int]]:
    """从帖子/评论内容中计算关键词频率。

    返回按频率降序排列的前 10 个关键词。
    仅考虑来自 PAIN_POINT_KEYWORDS、USER_NEED_KEYWORDS
    和 COMPLAINT_KEYWORDS 的关键词。
    """
    all_keywords = set(
        PAIN_POINT_KEYWORDS + USER_NEED_KEYWORDS + COMPLAINT_KEYWORDS
    )
    counter: Counter[str] = Counter()

    # 扫描帖子
    for post in dataset.posts:
        text = (post.title + " " + post.content).lower()
        for kw in all_keywords:
            if kw in text:
                counter[kw] += 1

    # 扫描评论
    for comment in dataset.comments:
        text = (comment.content or "").lower()
        for kw in all_keywords:
            if kw in text:
                counter[kw] += 1

    # 返回前 10 个
    return counter.most_common(10)


def _collect_evidence(
    insight: InsightRecord,
    dataset: NormalizedDataset,
) -> tuple[list[PostRecord], list[CommentRecord]]:
    """收集具有代表性的证据帖子和评论。

    从证据 ID 中返回最多 3 条帖子和最多 5 条评论。
    """
    evidence_post_ids = set(insight.evidence_post_ids)
    evidence_comment_ids = set(insight.evidence_comment_ids)

    posts = [p for p in dataset.posts if p.post_id in evidence_post_ids][:3]
    comments = [c for c in dataset.comments if c.comment_id in evidence_comment_ids][:5]

    return posts, comments


def _extract_reason(scoring_reason: str, attr: str) -> str | None:
    """从 scoring_reason 中提取特定维度的理由行。"""
    # 将属性名映射为方括号标签（必须与 rules.py calc_overall 输出一致）
    label_map: dict[str, str] = {
        "demand_intensity": "用户关注强度",
        "sentiment_friction": "负面摩擦",
        "solution_saturation": "方案饱和",
        "purchase_intent": "购买意向",
        "freshness": "时效性",
        "overall_score": "内容选题价值",
    }
    label = label_map.get(attr)
    if not label:
        return None

    for line in scoring_reason.split("\n"):
        line = line.strip()
        if line.startswith(f"【{label}") or line.startswith(f"[{label}"):
            return line
    return None


def _generate_suggestions(
    scorecard: ScoreCard,
    insight: InsightRecord,
) -> list[str]:
    """基于评分卡和洞察数据生成文案方向建议。"""
    suggestions: list[str] = []

    # 关注度 vs 饱和度分析
    if scorecard.demand_intensity >= 0.5 and scorecard.solution_saturation < 0.5:
        suggestions.append(
            "用户关注度较高，且提及的替代方案较少，适合从核心痛点切入展开深度内容。"
        )
    elif scorecard.demand_intensity >= 0.5 and scorecard.solution_saturation >= 0.7:
        suggestions.append(
            "用户讨论热度较高但已有较多替代方案，建议聚焦差异化卖点做对比评测类内容。"
        )
    elif scorecard.demand_intensity < 0.3:
        suggestions.append(
            "当前数据中用户关注信号较弱，建议先通过科普/种草内容测试用户反应。"
        )

    # 行动信号
    if scorecard.purchase_intent >= 0.5:
        suggestions.append(
            "用户购买行动信号强烈，适合制作选购指南、对比测评等转化型内容。"
        )
    elif scorecard.purchase_intent < 0.2:
        suggestions.append(
            "购买信号偏弱，建议先通过痛点共鸣类内容积累用户认知。"
        )

    # 特定痛点建议
    if insight.pain_points:
        top_pains = insight.pain_points[:3]
        suggestions.append(
            f"用户主要痛点包括：{'、'.join(top_pains)}。可围绕这些痛点制作解决方案型内容。"
        )

    return suggestions


def _generate_recommended_titles(
    topic: str,
    product_direction: str,
    insight: InsightRecord,
) -> list[str]:
    """基于主题和洞察生成推荐标题/选题角度。"""
    titles: list[str] = []

    # 从洞察中提取关键词
    top_needs = insight.user_needs[:2] if insight.user_needs else []
    top_pains = insight.pain_points[:2] if insight.pain_points else []

    # 通用小红书风格标题模板
    if topic:
        titles.append(f"关于{topic}，你不得不知道的几件事")
        titles.append(f"用了很久的{topic}，谈谈真实感受")
        titles.append(f"{topic}选购避坑指南｜亲测有效")

    if product_direction and topic:
        titles.append(f"{topic}：{product_direction}到底值不值得买？")

    if top_pains:
        titles.append(f"被问了800遍的{top_pains[0]}问题，一次说清楚")

    if top_needs:
        titles.append(f"想要{top_needs[0]}？试试这个方法")

    if insight.market_signals:
        titles.append(f"看完这篇{topic}测评，帮你省下冤枉钱")

    # 补充通用标题
    titles.append(f"为什么你的{topic}没效果？可能是方法错了")
    titles.append(f"花了很多冤枉钱才总结的{topic}经验")

    # 返回最多 8 个
    return titles[:8]


def _extract_hot_terms(
    dataset: NormalizedDataset,
    insight: InsightRecord,
) -> list[str]:
    """从帖子、评论和洞察中提取高频关注的短语/关键词（去重、短词过滤）。"""
    counter: Counter[str] = Counter()

    # 从帖子中提取
    for post in dataset.posts:
        text = f"{post.title} {post.content}"
        for sep in ["，", "。", "、", "？", "！", "；", "：", " ", ","]:
            text = text.replace(sep, "\n")
        for term in text.split("\n"):
            term = term.strip()
            if len(term) >= 2:
                counter[term] += 1

    # 从评论中提取
    for comment in dataset.comments:
        text = comment.content or ""
        for sep in ["，", "。", "、", "？", "！", "；", "：", " ", ","]:
            text = text.replace(sep, "\n")
        for term in text.split("\n"):
            term = term.strip()
            if len(term) >= 2:
                counter[term] += 1

    # 从 insight 字段中提取
    for term_list in [
        insight.pain_points,
        insight.user_needs,
        insight.complaints,
        insight.solutions,
        insight.market_signals,
    ]:
        for term in term_list:
            if len(term) >= 2:
                counter[term] += 1

    # 按频率排序，取前 20 个短语
    top_terms = [term for term, _ in counter.most_common(20)]
    return top_terms


def _extract_question_like(comments: list[CommentRecord]) -> list[str]:
    """从评论中提取疑问性内容（含怎么、有没有、哪里、值不值等）。"""
    question_keywords = {
        "怎么", "有没有", "哪里", "值不值", "能不能", "何时",
        "如何", "什么", "哪些", "哪个", "是否", "该不该",
    }
    result: list[str] = []
    for comment in comments:
        content = comment.content or ""
        # 查找包含疑问词且包含问号的句子
        if "?" in content or "？" in content:
            sentences = content.replace("?", "？").split("？")
            for sentence in sentences:
                sentence = sentence.strip()
                if sentence and any(qw in sentence for qw in question_keywords):
                    result.append(sentence)
                    break  # 每条评论最多取一条
        else:
            # 没有问号时检查是否包含疑问词
            if any(qw in content for qw in question_keywords):
                result.append(content[:80])  # 截取前80字符

    # 去重
    seen: set[str] = set()
    unique: list[str] = []
    for item in result:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique[:10]


def _build_topic_suggestions(
    keyword: str,
    dataset: NormalizedDataset,
    insight: InsightRecord,
) -> list[str]:
    """基于真实数据生成 3-5 条内容选题建议。

    每条建议应尽量引用 insights 中的真实词。
    方向包括：高频关注点、高频疑问、典型痛点、解决方案、热点延展。
    """
    suggestions: list[str] = []
    questions = _extract_question_like(list(dataset.comments))

    # 从 user_needs 和 market_signals 提取高频关注方向
    if insight.user_needs:
        top_needs = insight.user_needs[:3]
        suggestions.append(
            f'优先围绕"{'、'.join(top_needs)}"展开内容延展。'
            f"当前评论中多次提到这些方向，说明用户关注度较高，适合继续深挖。"
        )

    if questions:
        top_q = questions[:2]
        suggestions.append(
            f'可围绕"{'、'.join(top_q)}"做答疑型内容。'
            f"多条评论在询问相关问题，说明用户仍处在了解或决策阶段，"
            f"适合制作解释型、科普型内容。"
        )

    if insight.pain_points or insight.complaints:
        pains = (insight.pain_points + insight.complaints)[:3]
        suggestions.append(
            f'可围绕"{'、'.join(pains)}"做避坑或对比内容。'
            f"评论里出现了这些痛点/顾虑，说明用户对此较敏感，"
            f"适合做真实体验、对比评测、避坑总结。"
        )

    if insight.solutions:
        top_sol = insight.solutions[:3]
        suggestions.append(
            f'可围绕"{'、'.join(top_sol)}"做推荐型内容。'
            f"用户提到了这些方案/工具/路径，"
            f"适合延展成推荐清单、使用建议或方案对比内容。"
        )

    # 如果没足够数据，fallback
    if not suggestions:
        suggestions.append(
            f'当前关于"{keyword}"的评论样本较少，'
            f"建议补充更多样本后再生成选题建议。"
        )

    return suggestions


def _has_learning_keywords(insight: InsightRecord, comments: list[CommentRecord]) -> bool:
    """检测是否包含学习类关键词。"""
    LEARNING_KW = {"学习", "教程", "路线", "入门", "资料", "资源", "怎么学", "后端", "GitHub", "项目", "面试", "课程", "路径", "知识", "技能"}
    for c in (list(comments) or []):
        content = (c.content or "").lower()
        if any(kw in content for kw in LEARNING_KW):
            return True
    for field in [insight.user_needs, insight.solutions, insight.market_signals]:
        for item in field:
            if any(kw in item for kw in LEARNING_KW):
                return True
    return False


def _has_question_keywords(insight: InsightRecord, comments: list[CommentRecord]) -> bool:
    """检测是否包含疑问类关键词。"""
    Q_KW = {"怎么", "有没有", "哪里", "什么时候", "值不值", "能不能", "适合吗", "求推荐", "求教程", "如何", "哪个"}
    for c in (list(comments) or []):
        content = (c.content or "").lower()
        if any(kw in content for kw in Q_KW):
            return True
    for field in [insight.user_needs, insight.market_signals]:
        for item in field:
            if any(kw in item for kw in Q_KW):
                return True
    return False


def _has_negative_feedback(insight: InsightRecord, comments: list[CommentRecord]) -> bool:
    """检测是否包含负面反馈关键词。"""
    NEG_KW = {"太长", "太杂", "看不懂", "难", "担心", "缺", "没效果", "不会", "不敢", "怕", "顾虑", "问题", "不好", "差", "没用", "失望", "骗"}
    for c in (list(comments) or []):
        content = (c.content or "").lower()
        if any(kw in content for kw in NEG_KW):
            return True
    for field in [insight.pain_points, insight.complaints]:
        for item in field:
            if any(kw in item for kw in NEG_KW):
                return True
    return False


def _has_solution_terms(insight: InsightRecord, comments: list[CommentRecord]) -> bool:
    """检测是否包含具体方案/工具/路径。"""
    SOL_KW = {"GitHub", "hello-agents", "XingClaw", "路线", "后端", "博士", "项目", "工具", "框架", "平台", "渠道", "链接", "资源"}
    for c in (list(comments) or []):
        content = (c.content or "").lower()
        if any(kw.lower() in content for kw in SOL_KW):
            return True
    for item in insight.solutions:
        if any(kw in item for kw in SOL_KW):
            return True
    return False


def _parse_revision_instructions(
    revision_instructions: Optional[list[str]],
) -> dict[str, bool]:
    """解析修订指令为布尔标志位。

    返回：
        {
            "force_topic_mention": bool,  # 需要强化关键词提及
            "avoid_template": bool,       # 需要避免模板化表达
        }
    """
    flags: dict[str, bool] = {
        "force_topic_mention": False,
        "avoid_template": False,
    }
    if not revision_instructions:
        return flags

    for ri in revision_instructions:
        if "关键词" in ri:
            flags["force_topic_mention"] = True
        if "模板化" in ri or "模板" in ri:
            flags["avoid_template"] = True

    return flags


def _build_custom_title_suggestions(
    keyword: str,
    dataset: NormalizedDataset,
    insight: InsightRecord,
    avoid_template: bool = False,
) -> list[dict]:
    """基于真实数据定制化的选题建议。

    每条包含 direction / title / evidence / content_angle。
    不再输出机械化标题，而是基于数据分类生成有分析价值的建议。
    """
    import re

    suggestions: list[dict] = []
    comments = list(dataset.comments) if dataset.comments else []
    posts = list(dataset.posts) if dataset.posts else []

    # 提取疑问类评论
    def _is_question(text: str) -> bool:
        q_words = ["怎么", "有没有", "哪里", "什么时候", "值不值", "能不能", "适合吗", "求推荐", "求教程", "如何", "哪个", "还是"]
        return any(kw in text for kw in q_words)

    # 提取含具体解决方案/资源的评论
    solution_comments = []
    question_comments = []
    neg_feedback_terms = []

    for c in comments:
        content = (c.content or "").strip()
        if not content:
            continue
        if _is_question(content):
            question_comments.append(content)
        if any(kw in content for kw in ["GitHub", "hello-agents", "XingClaw", "链接", "教程", "资源", "路线"]):
            solution_comments.append(content)
        if any(kw in content for kw in ["太长", "太杂", "看不懂", "难", "担心", "顾虑", "缺"]):
            neg_feedback_terms.append(content)

    # 判断内容类型
    has_learning = _has_learning_keywords(insight, comments)
    has_question = _has_question_keywords(insight, comments)
    has_negative = _has_negative_feedback(insight, comments)
    has_solution = _has_solution_terms(insight, comments)

    # 收集热点词
    hot_terms = set()
    for lst in [insight.user_needs, insight.pain_points, insight.complaints, insight.solutions, insight.market_signals]:
        for item in lst:
            if len(item) >= 2:
                hot_terms.add(item)
    for c in comments:
        content = (c.content or "").strip()
        # 提取较长的有意义的片段
        parts = re.split(r'[，。！？、；：\s]', content)
        for p in parts:
            t = p.strip()
            if 4 <= len(t) <= 30 and t not in hot_terms:
                hot_terms.add(t)

    # --- 按分类生成选题 ---

    # 1. 学习路线/入门类
    if has_learning:
        evidence_parts = []
        if insight.solutions:
            evidence_parts.append(f"评论中提到{'、'.join(insight.solutions[:3])}")
        if neg_feedback_terms:
            evidence_parts.append(f"用户反馈包括{'、'.join([t[:15] for t in neg_feedback_terms[:2]])}")

        if avoid_template:
            # 非模板化：使用具体洞察词
            specific_terms = [t for t in insight.solutions if len(t) >= 4] if insight.solutions else []
            term_hint = f"{'、'.join(specific_terms[:3])}" if specific_terms else keyword
            title = f"{keyword}学习路径分析：评论区提到的{term_hint}等方向值得关注"
        else:
            title = f"{keyword}别一上来就乱学，评论区最关心的是这些方向和路径"

        suggestions.append({
            "direction": f"{keyword}学习路线与入门指南",
            "title": title,
            "evidence": "；".join(evidence_parts) if evidence_parts else f"评论和帖子中出现了学习类关键词，说明用户对学习路径和入门方式有明确需求",
            "content_angle": "可以将内容拆解为预备知识、基础概念、核心框架、项目实战和面试表达几个阶段，做成路线型或清单型内容",
        })

    # 2. 答疑/决策类
    if has_question or question_comments:
        q_sample = question_comments[0][:40] if question_comments else ""
        evidence_parts = [f'多条评论在询问相关问题，如"{q_sample}"'] if q_sample else ["多条评论在询问相关问题"]
        if insight.user_needs:
            evidence_parts.append(f"用户需求中包含{'、'.join(insight.user_needs[:3])}")

        if avoid_template:
            needs_hint = "、".join(insight.user_needs[:3]) if insight.user_needs else ""
            if needs_hint:
                title = f"{keyword}用户最关心的{needs_hint}等问题，评论区高频疑问解析"
            else:
                title = f"{keyword}评论区高频疑问整理与详细解答"
        else:
            title = f"{keyword}怎么选/怎么学/怎么用？评论区问得最多的几个问题一次说清"

        suggestions.append({
            "direction": f"{keyword}高频疑问解答",
            "title": title,
            "evidence": "；".join(evidence_parts),
            "content_angle": "适合以FAQ形式展开，收集评论区高频疑问，逐条给出简洁可操作的解答，适合做成答疑型或决策指南型内容",
        })

    # 3. 避坑/误区类
    if has_negative or insight.pain_points:
        evidence_parts = []
        if insight.pain_points:
            evidence_parts.append(f"用户痛点包括{'、'.join(insight.pain_points[:3])}")
        if insight.complaints:
            evidence_parts.append(f"负面反馈包括{'、'.join(insight.complaints[:3])}")

        if avoid_template:
            pain_hint = "、".join(insight.pain_points[:3]) if insight.pain_points else ""
            if pain_hint:
                title = f"{keyword}用户反馈最多的{pain_hint}问题解析与避坑建议"
            else:
                title = f"{keyword}评论区负面反馈归因分析与改进方向"
        else:
            title = f"{keyword}哪些坑最容易踩？评论区这些反馈值得提前了解"

        suggestions.append({
            "direction": f"{keyword}常见误区与避坑",
            "title": title,
            "evidence": "；".join(evidence_parts) if evidence_parts else "评论和洞察中出现了负面反馈，说明用户对此存在顾虑",
            "content_angle": "可以围绕学习误区、内容选择、工具对比、实践方式等角度展开，适合做避坑总结或对比评测型内容",
        })

    # 4. 资源整理/方案推荐类
    if has_solution or insight.solutions:
        sol_sample = "、".join(insight.solutions[:4]) if insight.solutions else ""
        if avoid_template:
            if sol_sample:
                title = f"{keyword}实用资源梳理：评论中提到的{sol_sample}等方案值得关注"
            else:
                title = f"{keyword}评论区高频推荐的资源与工具整理"
        else:
            title = f"{keyword}有哪些值得看的学习资源？评论区提到的这些可以先收藏"

        suggestions.append({
            "direction": f"{keyword}实用资源整理",
            "title": title,
            "evidence": f"评论中提到了{sol_sample}等具体资源/方案/工具，用户对可直接使用的学习资源有需求" if sol_sample else "评论中提到了具体工具、项目或学习资源",
            "content_angle": "可以整理 GitHub 项目、学习路线、实战案例和推荐工具，做成资源清单型内容，便于收藏和传播",
        })

    # 5. 经验/案例分享类
    if insight.market_signals:
        signal_sample = "、".join(insight.market_signals[:3]) if insight.market_signals else ""
        if avoid_template:
            if signal_sample:
                title = f"{keyword}用户实际体验反馈：{signal_sample}等方向值得深入"
            else:
                title = f"{keyword}评论区真实案例与用户经验分享"
        else:
            title = f"{keyword}学完后能做什么？看看大家怎么说的"

        suggestions.append({
            "direction": f"{keyword}真实经验与案例分享",
            "title": title,
            "evidence": f"评论中出现了{signal_sample}等表达，用户不仅关注内容本身，也关注实际应用成果" if signal_sample else "评论中出现了行动信号，说明用户不仅关注内容本身，也关注实际应用",
            "content_angle": "可以从实际应用场景、项目成果、面试经验、行业案例等角度切入，适合做真实体验分享或案例拆解型内容",
        })

    # 如果数据不足
    if not suggestions:
        suggestions.append({
            "direction": f"{keyword}话题引入与观察",
            "title": f"最近{keyword}怎么样？先看看评论区和讨论",
            "evidence": "当前评论样本较少，建议补充更多数据后重新生成定制选题",
            "content_angle": "建议先收集更多相关评论和帖子，再做具体选题判断",
        })

    return suggestions


# ===================================================================
# P6.0 评论主题聚类增强
# ===================================================================


def _cluster_html(clusters_data: Optional[dict]) -> str:
    """从 clusters_data 构建主题聚类 HTML 段落。

    返回空字符串时表示无聚类数据可用。
    """
    if not clusters_data or not isinstance(clusters_data, dict):
        return ""
    clusters = clusters_data.get("clusters", [])
    if not clusters:
        return ""

    items_html = ""
    for i, cl in enumerate(clusters):
        if not isinstance(cl, dict):
            continue
        rank = i + 1
        topic = html.escape(cl.get("topic", "未知主题"))
        hotness = cl.get("hotness", 0.0)
        count = cl.get("comment_count", 0)
        rep = cl.get("representative_comments", [])
        rep_html = ""
        if rep:
            rep_text = rep[0] or ""
            if rep_text:
                sample = html.escape(rep_text[:80])
                rep_html = f'<blockquote class="cluster-quote">{sample}</blockquote>'

        items_html += f"""
        <div class="cluster-card">
            <span class="cluster-rank">#{rank}</span>
            <span class="cluster-topic">{topic}</span>
            <span class="cluster-heat" style="color:{_score_color(hotness)};">热度 {hotness:.2f}</span>
            <span class="cluster-count">{count} 条评论</span>
            {rep_html}
        </div>"""

    if not items_html:
        return ""

    return f"""
    <div class="cluster-section">
        <h3>高频评论主题</h3>
        <p class="section-desc">基于语义相似度和评论互动量自动聚类，按热度排序：</p>
        {items_html}
    </div>"""


def _cluster_topic_suggestions(clusters_data: Optional[dict]) -> list[dict]:
    """从聚类数据生成文案方向建议。

    返回与 _build_custom_title_suggestions 兼容的 dict 列表。
    """
    if not clusters_data or not isinstance(clusters_data, dict):
        return []
    clusters = clusters_data.get("clusters", [])
    if not clusters:
        return []

    suggestions = []
    for i, cl in enumerate(clusters):
        if not isinstance(cl, dict):
            continue
        topic = cl.get("topic", "")
        hotness = cl.get("hotness", 0.0)
        count = cl.get("comment_count", 0)
        rep = cl.get("representative_comments", [])
        rep_sample = rep[0][:60] if rep else ""
        evidence_text = f"聚类主题: {topic} (热度 {hotness:.2f}, {count} 条评论)"
        if rep_sample:
            evidence_text += f" | 代表评论: \"{rep_sample}\""

        suggestions.append({
            "direction": f"聚类主题-{i + 1}: {topic}",
            "title": f"关于「{topic}」大家都在讨论什么？",
            "evidence": evidence_text,
            "content_angle": f"围绕「{topic}」展开深度内容，该主题在评论区形成了{count}条相关讨论，表明用户对此有较高关注度",
        })
    return suggestions
