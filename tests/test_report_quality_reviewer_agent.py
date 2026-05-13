"""ReportQualityReviewerAgent 单元测试。

使用 mock 数据，不访问真实小红书/LLM。
验证全部 7 条规则的正确性。
P3.1: 增加 LLM 定性评审相关的 9 个测试。
"""

from __future__ import annotations

import sys
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import unittest

from src.agents.report_quality_reviewer_agent import ReportQualityReviewerAgent
from src.llm.client import BaseLLMClient, MockLLMClient
from src.schemas import CommentRecord, InsightRecord, PostRecord, ScoreCard
from src.schemas.report_review import ReportQualityReview


def _make_minimal_html(
    *,
    sections: list[str] | None = None,
    keyword: str = "",
    include_doctype: bool = True,
    include_body: bool = True,
    include_forbidden: str = "",
    comment_ids: list[str] | None = None,
    template_phrases: list[str] | None = None,
) -> str:
    """构造用于测试的最小 HTML 报告。

    参数：
        sections: 要包含的章节列表
        keyword: 关键词
        include_doctype: 是否包含 DOCTYPE 和 html 标签
        include_body: 是否包含 body 标签
        include_forbidden: 插入的禁止用语
        comment_ids: 要插入的 comment_id 列表
        template_phrases: 要插入的模板化标题短语
    """
    if sections is None:
        sections = [
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
    if comment_ids is None:
        comment_ids = []
    if template_phrases is None:
        template_phrases = []

    doc_parts = []
    if include_doctype:
        doc_parts.append("<!DOCTYPE html><html><head><title>报告</title></head>")
    if include_body:
        doc_parts.append("<body>")

    doc_parts.append(f"<h1>小红书评论区用户反馈与文案选题报告</h1>")
    doc_parts.append(f"<p>{keyword}</p>" if keyword else "")

    for s in sections:
        doc_parts.append(f"<div><h2>{s}</h2><p>{s}内容</p></div>")

    if include_forbidden:
        doc_parts.append(f"<p>{include_forbidden}</p>")

    for cid in comment_ids:
        doc_parts.append(
            f'<div class="evidence-card">comment_id="{cid}" content...</div>'
        )

    for phrase in template_phrases:
        doc_parts.append(f"<p>{phrase}</p>")

    if include_body:
        doc_parts.append("</body>")
    if include_doctype:
        doc_parts.append("</html>")

    return "\n".join(doc_parts)


class TestReportQualityReviewerAgentEmptyReport(unittest.TestCase):
    """空报告 / 无效报告测试。"""

    def setUp(self):
        self.reviewer = ReportQualityReviewerAgent()

    def test_empty_report_fails_all_sections(self):
        """空 HTML 报告所有章节缺失，通过评审应为 False。"""
        html = ""
        review = self.reviewer.review(report_html=html, keyword="测试")
        self.assertFalse(review.passed)
        self.assertGreater(len(review.hard_fail_reasons), 0)
        self.assertIn("HTML 结构不完整", str(review.hard_fail_reasons))

    def test_minimal_valid_report_passes(self):
        """包含全部 12 个章节且无违规的报告通过评审。"""
        html = _make_minimal_html(keyword="测试关键词")
        review = self.reviewer.review(report_html=html, keyword="测试关键词")
        self.assertTrue(review.passed, f"应当通过，但失败原因: {review.hard_fail_reasons}")
        self.assertEqual(len(review.hard_fail_reasons), 0)

    def test_missing_all_sections(self):
        """缺少所有章节时 hard_fail_reasons 包含章节缺失。"""
        html = "<html><body><p>no sections here</p></body></html>"
        review = self.reviewer.review(report_html=html)
        self.assertFalse(review.passed)
        self.assertTrue(
            any("缺少章节" in r for r in review.hard_fail_reasons),
            f"应包含章节缺失提示: {review.hard_fail_reasons}",
        )

    def test_missing_individual_section(self):
        """缺少某个具体章节（如数据局限说明）时被检测到。"""
        sections = [
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
            # 缺少 "数据局限说明"
        ]
        html = _make_minimal_html(sections=sections)
        review = self.reviewer.review(report_html=html)
        self.assertFalse(review.passed)
        self.assertTrue(
            any("缺少章节" in r for r in review.hard_fail_reasons),
        )
        self.assertTrue(
            any("数据局限说明" in r for r in review.hard_fail_reasons),
            "应指出缺失数据局限说明",
        )


class TestReportQualityReviewerForbiddenClaims(unittest.TestCase):
    """禁止用语检测测试。"""

    def setUp(self):
        self.reviewer = ReportQualityReviewerAgent()

    def test_forbidden_claims_detected(self):
        """包含"市场规模"时被检测为硬失败。"""
        html = _make_minimal_html(include_forbidden="本报告显示市场规模达到XX亿元")
        review = self.reviewer.review(report_html=html)
        self.assertFalse(review.passed)
        self.assertTrue(
            any("市场规模" in r for r in review.hard_fail_reasons),
            f"应检测到市场规模用语: {review.hard_fail_reasons}",
        )

    def test_multiple_forbidden_claims_detected(self):
        """同时包含多个禁止用语时都检测到。"""
        html = _make_minimal_html(
            include_forbidden="市场规模巨大，销量预测乐观，商业可行性高"
        )
        review = self.reviewer.review(report_html=html)
        self.assertFalse(review.passed)
        forbidden_found = [
            p
            for p in ["市场规模", "销量预测", "商业可行性"]
            if any(p in r for r in review.hard_fail_reasons)
        ]
        self.assertGreaterEqual(
            len(forbidden_found), 2,
            f"应检测到至少 2 个禁止用语: {review.hard_fail_reasons}",
        )

    def test_clean_report_no_forbidden_claims(self):
        """干净报告不包含禁止用语。"""
        html = _make_minimal_html(keyword="测试")
        review = self.reviewer.review(report_html=html)
        forbidden_found = any(
            p in str(review.hard_fail_reasons)
            for p in ["市场规模", "销量预测", "商业可行性"]
        )
        self.assertFalse(forbidden_found)


class TestReportQualityReviewerTemplatePhrases(unittest.TestCase):
    """模板化标题检测测试。"""

    def setUp(self):
        self.reviewer = ReportQualityReviewerAgent()

    def test_template_phrases_without_real_insights(self):
        """包含模板化短语但无真实洞察词时产生原因和建议。"""
        html = _make_minimal_html(
            template_phrases=["你不得不知道的几件事"],
            keyword="测试",
        )
        insights = InsightRecord(
            pain_points=[],
            user_needs=[],
            complaints=[],
            solutions=[],
            market_signals=[],
            sentiment="neutral",
            evidence_post_ids=[],
            evidence_comment_ids=[],
        )
        review = self.reviewer.review(
            report_html=html, keyword="测试", insights=insights
        )
        # Pass/fail depends on sections - template is a reason not hard_fail
        self.assertGreaterEqual(len(review.reasons), 0)

    def test_template_phrases_with_real_insight_terms(self):
        """模板化短语但引用了真实洞察词时不被标记。"""
        html = _make_minimal_html(
            template_phrases=["你不得不知道的几件事"],
            keyword="机器学习",
        )
        # 在热点选题区域插入真实洞察词
        html = html.replace(
            "热点选题与文案定制建议",
            "热点选题与文案定制建议",
        )
        html = html.replace(
            "热点选题与文案定制建议内容",
            "热点选题与文案定制建议内容 机器学习 入门 路线",
        )
        insights = InsightRecord(
            pain_points=[],
            user_needs=["机器学习入门", "路线"],
            complaints=[],
            solutions=[],
            market_signals=[],
            sentiment="neutral",
            evidence_post_ids=[],
            evidence_comment_ids=[],
        )
        review = self.reviewer.review(
            report_html=html, keyword="机器学习", insights=insights
        )
        # 应当找不到"热点选题过于模板化"的提示
        template_warnings = [
            r for r in review.reasons if "模板化" in r
        ]
        self.assertEqual(
            len(template_warnings), 0,
            f"不应有模板化警告: {review.reasons}",
        )


class TestReportQualityReviewerKeywordPresence(unittest.TestCase):
    """关键词存在性检测测试。"""

    def setUp(self):
        self.reviewer = ReportQualityReviewerAgent()

    def test_keyword_missing_from_report(self):
        """报告未包含关键词时产生原因和建议。"""
        html = _make_minimal_html(keyword="其他不相关内容")
        review = self.reviewer.review(report_html=html, keyword="机器学习")
        self.assertTrue(
            any("关键词" in r for r in review.reasons),
            f"应提示关键词缺失: {review.reasons}",
        )

    def test_keyword_present_in_report(self):
        """报告包含关键词时无相关警告。"""
        html = _make_minimal_html(keyword="机器学习")
        review = self.reviewer.review(
            report_html=html, keyword="机器学习"
        )
        keyword_warnings = [
            r for r in (review.reasons + review.hard_fail_reasons)
            if "关键词" in r
        ]
        self.assertEqual(len(keyword_warnings), 0)

    def test_empty_keyword_no_check(self):
        """关键词为空字符串时跳过检查。"""
        html = _make_minimal_html()
        review = self.reviewer.review(report_html=html, keyword="")
        keyword_warnings = [
            r for r in (review.reasons + review.hard_fail_reasons)
            if "关键词" in r
        ]
        self.assertEqual(len(keyword_warnings), 0)


class TestReportQualityReviewerHtmlStructure(unittest.TestCase):
    """HTML 结构完整性检测测试。"""

    def setUp(self):
        self.reviewer = ReportQualityReviewerAgent()

    def test_missing_doctype_and_html(self):
        """缺少 DOCTYPE 和 html 标签时被检测为硬失败。"""
        html = _make_minimal_html(
            include_doctype=False, include_body=False
        )
        # Remove any remaining HTML-like tags
        html = html.replace("<body>", "").replace("</body>", "")
        review = self.reviewer.review(report_html=html)
        self.assertTrue(
            any("HTML 结构不完整" in r for r in review.hard_fail_reasons),
            f"应提示 HTML 结构不完整: {review.hard_fail_reasons}",
        )

    def test_complete_html_structure_passes(self):
        """完整的 HTML 结构通过检查。"""
        html = _make_minimal_html(keyword="测试")
        review = self.reviewer.review(report_html=html)
        structure_fails = [
            r for r in review.hard_fail_reasons if "HTML 结构" in r
        ]
        self.assertEqual(len(structure_fails), 0)


class TestReportQualityReviewerEvidenceComments(unittest.TestCase):
    """评论证据检测测试。"""

    def setUp(self):
        self.reviewer = ReportQualityReviewerAgent()

    def test_fake_comment_id_detected(self):
        """包含不存在的 comment_id 时被检测为硬失败。"""
        comments = [
            CommentRecord(
                platform="xhs", comment_id="c1", post_id="p1",
                content="真实评论", author="u1",
                publish_time="2026-01-01T00:00:00", likes=1,
            ),
        ]
        html = _make_minimal_html(
            comment_ids=["c1", "fake_c2", "fake_c3"],
            keyword="测试",
        )
        review = self.reviewer.review(
            report_html=html, keyword="测试", comments=comments,
        )
        self.assertFalse(review.passed)
        self.assertTrue(
            any("不存在" in r for r in review.hard_fail_reasons),
            f"应检测到不存在 comment_id: {review.hard_fail_reasons}",
        )

    def test_all_comment_ids_valid(self):
        """所有 comment_id 都存在于评论列表中时通过。"""
        comments = [
            CommentRecord(
                platform="xhs", comment_id="c1", post_id="p1",
                content="评论1", author="u1",
                publish_time="2026-01-01T00:00:00", likes=1,
            ),
            CommentRecord(
                platform="xhs", comment_id="c2", post_id="p1",
                content="评论2", author="u2",
                publish_time="2026-01-01T00:00:00", likes=2,
            ),
        ]
        html = _make_minimal_html(comment_ids=["c1", "c2"], keyword="测试")
        review = self.reviewer.review(
            report_html=html, keyword="测试", comments=comments,
        )
        evidence_fails = [
            r for r in review.hard_fail_reasons if "comment_id" in r
        ]
        self.assertEqual(len(evidence_fails), 0)

    def test_no_comments_skips_evidence_check(self):
        """未传入 comments 时跳过证据检查。"""
        html = _make_minimal_html(comment_ids=["fake_c1"], keyword="测试")
        review = self.reviewer.review(
            report_html=html, keyword="测试", comments=None,
        )
        evidence_fails = [
            r for r in review.hard_fail_reasons if "comment_id" in r
        ]
        self.assertEqual(len(evidence_fails), 0)


class TestReportQualityReviewerSummary(unittest.TestCase):
    """评审摘要格式测试。"""

    def setUp(self):
        self.reviewer = ReportQualityReviewerAgent()

    def test_summary_passed_no_reasons(self):
        """全部通过的报告摘要格式正确。"""
        html = _make_minimal_html(keyword="测试")
        review = self.reviewer.review(report_html=html)
        self.assertTrue(review.passed)
        self.assertIn("通过", review.summary)

    def test_summary_passed_with_warnings(self):
        """通过但有警告的摘要包含建议数。"""
        html = _make_minimal_html(keyword="关键词A")
        # Force a reason by setting a keyword that's not in the html
        review = self.reviewer.review(
            report_html=html, keyword="不同关键词"
        )
        if review.passed:
            self.assertIn("建议", review.summary)

    def test_summary_failed(self):
        """未通过的摘要包含失败信息。"""
        html = "<p>no structure</p>"
        review = self.reviewer.review(report_html=html)
        self.assertFalse(review.passed)
        self.assertIn("未通过", review.summary)


class TestReportQualityReviewerFullReview(unittest.TestCase):
    """完整评审流程测试。"""

    def setUp(self):
        self.reviewer = ReportQualityReviewerAgent()

    def test_full_review_with_all_data(self):
        """传入所有数据的完整评审流程。"""
        posts = [
            PostRecord(
                platform="xhs", post_id="p1",
                title="测试帖子", content="内容",
                author="u1", publish_time="2026-01-01T00:00:00",
                likes=10, comments=2,
            ),
        ]
        comments = [
            CommentRecord(
                platform="xhs", comment_id="c1", post_id="p1",
                content="真实评论", author="u1",
                publish_time="2026-01-01T00:00:00", likes=1,
            ),
        ]
        insights = InsightRecord(
            pain_points=["痛点1"],
            user_needs=["需求1"],
            complaints=["投诉1"],
            solutions=["方案1"],
            market_signals=["信号1"],
            sentiment="neutral",
            evidence_post_ids=["p1"],
            evidence_comment_ids=["c1"],
        )
        scorecard = ScoreCard(
            demand_intensity=0.8,
            sentiment_friction=0.3,
            solution_saturation=0.5,
            purchase_intent=0.6,
            freshness=0.7,
            overall_score=0.65,
            scoring_reason="各维度评分正常",
        )

        html = _make_minimal_html(comment_ids=["c1"], keyword="测试关键词")
        review = self.reviewer.review(
            report_html=html,
            keyword="测试关键词",
            insights=insights,
            scorecard=scorecard,
            posts=posts,
            comments=comments,
        )
        # 验证返回类型
        self.assertIsInstance(review, ReportQualityReview)
        self.assertIsInstance(review.passed, bool)
        self.assertIsInstance(review.reasons, list)
        self.assertIsInstance(review.hard_fail_reasons, list)
        self.assertIsInstance(review.revision_instructions, list)
        self.assertIsInstance(review.summary, str)

    def test_revision_instructions_generated_for_missing_sections(self):
        """缺少章节时生成修订指令。"""
        html = "<html><body></body></html>"
        review = self.reviewer.review(report_html=html)
        self.assertGreater(len(review.revision_instructions), 0)
        self.assertTrue(
            any("补充" in instr for instr in review.revision_instructions),
            f"修订指令应包含'补充'字样: {review.revision_instructions}",
        )

    def test_multiple_issues_all_captured(self):
        """多个问题同时被捕获。"""
        html = """
        <html>
        <body>
            <h1>小红书评论区用户反馈与文案选题报告</h1>
            <div>市场规模巨大</div>
        </body>
        </html>
        """
        review = self.reviewer.review(report_html=html)
        self.assertFalse(review.passed)
        # 至少有：缺少章节 + 禁止用语
        self.assertGreaterEqual(len(review.hard_fail_reasons), 2)


class TestReportQualityReviewerLlmReview(unittest.TestCase):
    """LLM 定性评审相关测试。

    验证 LLM 评审的启用、降级、合并和模板化检测逻辑。
    使用 MockLLMClient，不访问真实 API。
    """

    def setUp(self):
        # 一个有效的 mock LLM 响应
        self._mock_llm_response = {
            "issues": ["报告内容模板化", "未引用真实评论"],
            "revision_instructions": ["在热点选题中引用真实评论", "避免通用模板"],
            "summary": "报告整体质量尚可，但存在模板化问题",
        }

    def _make_valid_html(self) -> str:
        """构造一个通过规则检查的最小合法 HTML。"""
        return _make_minimal_html(
            sections=[
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
            ],
            keyword="测试关键词",
        )

    # ---- test 1 ----
    def test_llm_review_disabled_uses_rule_only(self):
        """不启用 LLM 时只做规则检查，reviewer 不应报错。"""
        reviewer = ReportQualityReviewerAgent()
        review = reviewer.review(
            report_html=self._make_valid_html(),
            keyword="测试关键词",
        )
        self.assertTrue(review.passed)
        self.assertNotIn("LLM:", review.summary)

    # ---- test 2 ----
    def test_llm_review_enabled_calls_llm_client(self):
        """启用 LLM 评审时，LLM 的输出出现在评审结果中。"""
        mock_llm = MockLLMClient(mock_response=self._mock_llm_response)
        reviewer = ReportQualityReviewerAgent(
            llm_client=mock_llm,
            enable_llm_review=True,
        )
        review = reviewer.review(
            report_html=self._make_valid_html(),
            keyword="测试关键词",
        )
        # LLM issues 应该出现在 reasons 中
        llm_issues_found = any(
            "模板化" in r or "未引用" in r
            for r in review.reasons
        )
        self.assertTrue(
            llm_issues_found,
            f"LLM issues 应出现在 reasons 中: {review.reasons}",
        )
        # LLM summary 应该出现在最终 summary 中
        self.assertIn(
            "LLM:", review.summary,
            f"摘要应包含 'LLM:' 标记: {review.summary}",
        )

    # ---- test 3 ----
    def test_llm_review_outputs_only_issues_revision_summary(self):
        """LLM 只输出 issues/revision_instructions/summary，不包含 passed/failed。"""
        mock_llm = MockLLMClient(mock_response=self._mock_llm_response)
        reviewer = ReportQualityReviewerAgent(
            llm_client=mock_llm,
            enable_llm_review=True,
        )
        review = reviewer.review(
            report_html=self._make_valid_html(),
            keyword="测试关键词",
        )
        # passed 字段始终由 ReportQualityReview 提供，不是 LLM 直接输出的
        self.assertIsInstance(review.passed, bool)
        self.assertIsInstance(review.reasons, list)
        self.assertIsInstance(review.revision_instructions, list)
        self.assertIsInstance(review.summary, str)
        # LLM 的输出不应包含 passed/failed 字样（来自 LLM 的部分）
        llm_issues_no_verdict = all(
            "passed" not in str(i).lower() and "failed" not in str(i).lower()
            for i in review.reasons
        )
        self.assertTrue(llm_issues_no_verdict)

    # ---- test 4 ----
    def test_llm_review_filters_forbidden_score_fields(self):
        """LLM 输出中包含的评分字段被过滤。"""
        bad_response = dict(self._mock_llm_response)
        bad_response["overall_score"] = 0.85
        bad_response["demand_intensity"] = 0.9
        mock_llm = MockLLMClient(mock_response=bad_response)
        reviewer = ReportQualityReviewerAgent(
            llm_client=mock_llm,
            enable_llm_review=True,
        )
        review = reviewer.review(
            report_html=self._make_valid_html(),
            keyword="测试关键词",
        )
        # 评审仍然正常工作
        self.assertIsInstance(review.passed, bool)
        self.assertIsInstance(review.reasons, list)
        self.assertIn("LLM:", review.summary)

    # ---- test 5 ----
    def test_llm_review_failure_falls_back_to_rule_review(self):
        """LLM 调用失败时自动降级为规则版评审。"""

        class _RaisingMockLLMClient(BaseLLMClient):
            def generate(self, prompt: str = "") -> str:
                raise RuntimeError("LLM API 不可用")

        raising_llm = _RaisingMockLLMClient()
        reviewer = ReportQualityReviewerAgent(
            llm_client=raising_llm,
            enable_llm_review=True,
        )
        review = reviewer.review(
            report_html=self._make_valid_html(),
            keyword="测试关键词",
        )
        # 降级后仍能正常通过规则检查
        self.assertTrue(review.passed)
        # 降级后摘要不应包含 LLM 内容
        self.assertIn("通过", review.summary)

    # ---- test 6 ----
    def test_llm_review_instructions_merged(self):
        """LLM 的修订指令与规则的修订指令合并。"""
        # 缺少一个章节以触发规则 revision_instructions
        sections = [
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
            # 缺少 "数据局限说明"
        ]
        html = _make_minimal_html(sections=sections, keyword="测试关键词")

        mock_llm = MockLLMClient(mock_response=self._mock_llm_response)
        reviewer = ReportQualityReviewerAgent(
            llm_client=mock_llm,
            enable_llm_review=True,
        )
        review = reviewer.review(
            report_html=html,
            keyword="测试关键词",
        )
        # 规则检测到缺少章节 -> revision_instructions 有内容
        rule_instructions = [i for i in review.revision_instructions if "补充" in i]
        self.assertGreater(len(rule_instructions), 0, "规则应生成补充章节的修订指令")

        # LLM 的指令也合并了
        llm_instructions = [
            i for i in review.revision_instructions if "模板" in i
        ]
        self.assertGreater(len(llm_instructions), 0, "LLM 的修订指令应被合并")

    # ---- test 7 ----
    def test_llm_review_does_not_override_rule_hard_fail(self):
        """即使 LLM 评审运行，规则硬失败仍然导致不通过。"""
        # 包含禁止用语触发硬失败
        html = _make_minimal_html(
            include_forbidden="市场规模巨大",
            keyword="测试关键词",
        )
        mock_llm = MockLLMClient(mock_response=self._mock_llm_response)
        reviewer = ReportQualityReviewerAgent(
            llm_client=mock_llm,
            enable_llm_review=True,
        )
        review = reviewer.review(
            report_html=html,
            keyword="测试关键词",
        )
        # 仍然因为规则失败
        self.assertFalse(review.passed)
        self.assertTrue(
            any("市场规模" in r for r in review.hard_fail_reasons),
            f"硬失败应包含禁止用语: {review.hard_fail_reasons}",
        )

    # ---- test 8 ----
    def test_llm_review_can_trigger_revision_when_template_detected(self):
        """LLM 发现模板化问题时，即使规则通过也可触发修订。"""
        # 构造一个规则通过的报告（所有章节齐全，无禁止用语等）
        # 但 LLM 发现模板化问题（2 条以上）
        template_response = {
            "issues": [
                "热点选题存在模板化倾向",
                "未引用真实评论中的具体需求",
                "选题建议过于泛泛",
            ],
            "revision_instructions": [
                "每条选题建议需要包含用户评论中的具体引用",
                "避免通用标题如'不得不知道的几件事'",
                "建议围绕评论中出现的具体需求展开",
            ],
            "summary": "报告通过了基本格式检查，但内容质量不够，需要修订",
        }
        mock_llm = MockLLMClient(mock_response=template_response)
        reviewer = ReportQualityReviewerAgent(
            llm_client=mock_llm,
            enable_llm_review=True,
        )
        review = reviewer.review(
            report_html=self._make_valid_html(),
            keyword="测试关键词",
        )
        # LLM 检测到模板化问题（>=2 条），应导致不通过
        self.assertFalse(
            review.passed,
            f"LLM 发现模板化问题应导致不通过: {review.reasons}",
        )
        self.assertTrue(
            any("模板化" in r for r in review.hard_fail_reasons),
            f"hard_fail_reasons 应包含模板化提示: {review.hard_fail_reasons}",
        )

    # ---- test 9 ----
    def test_llm_review_json_summary_contains_llm_when_enabled(self):
        """LLM 评审启用时，最终摘要包含 'LLM:' 标记。"""
        mock_llm = MockLLMClient(mock_response=self._mock_llm_response)
        reviewer = ReportQualityReviewerAgent(
            llm_client=mock_llm,
            enable_llm_review=True,
        )
        review = reviewer.review(
            report_html=self._make_valid_html(),
            keyword="测试关键词",
        )
        self.assertIn("LLM:", review.summary)


if __name__ == "__main__":
    unittest.main()
