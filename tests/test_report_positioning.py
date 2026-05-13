"""报告定位测试：验证报告不再使用市场验证表述。"""

from __future__ import annotations

import json
import os
import sys
import unittest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


class TestReportPositioning(unittest.TestCase):
    """验证报告定位已更新。"""

    def test_report_title_uses_comment_insight(self):
        """报告标题应包含'用户反馈与文案选题'。"""
        report_path = os.path.join(_PROJECT_ROOT, "data", "outputs", "report.html")
        if not os.path.exists(report_path):
            self.skipTest("report.html 不存在，请先运行 pipeline")
        with open(report_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("用户反馈与文案选题", content)

    def test_report_contains_data_limitation(self):
        """报告应包含数据局限说明。"""
        report_path = os.path.join(_PROJECT_ROOT, "data", "outputs", "report.html")
        if not os.path.exists(report_path):
            self.skipTest("report.html 不存在")
        with open(report_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("数据局限说明", content)

    def test_report_does_not_claim_market_validation(self):
        """报告不应包含'市场验证'表述。"""
        report_path = os.path.join(_PROJECT_ROOT, "data", "outputs", "report.html")
        if not os.path.exists(report_path):
            self.skipTest("report.html 不存在")
        with open(report_path, encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("市场验证", content)

    def test_fastapi_title_updated(self):
        """FastAPI title 应使用新定位。"""
        from src.api.main import app
        self.assertEqual(app.title, "XHS Comment Insight Agent API")

    def test_scoring_reason_not_market(self):
        """scoring_reason 不应包含'市场信号'。"""
        scorecard_path = os.path.join(_PROJECT_ROOT, "data", "outputs", "scorecard.json")
        if not os.path.exists(scorecard_path):
            self.skipTest("scorecard.json 不存在")
        with open(scorecard_path, encoding="utf-8") as f:
            data = json.load(f)
        reason = data.get("scoring_reason", "")
        self.assertNotIn("市场信号", reason)


class TestRequiredSections(unittest.TestCase):
    """验证 REQUIRED_SECTIONS 已更新。"""

    def test_required_sections_has_12_items(self):
        """REQUIRED_SECTIONS 应有 12 个章节。"""
        from scripts.acceptance_check import REQUIRED_SECTIONS
        self.assertEqual(len(REQUIRED_SECTIONS), 12)

    def test_required_sections_includes_data_limitation(self):
        """REQUIRED_SECTIONS 应包含'数据局限说明'。"""
        from scripts.acceptance_check import REQUIRED_SECTIONS
        self.assertIn("数据局限说明", REQUIRED_SECTIONS)

    def test_required_sections_includes_content_signal(self):
        """REQUIRED_SECTIONS 应包含'内容选题价值评分'。"""
        from scripts.acceptance_check import REQUIRED_SECTIONS
        self.assertIn("内容选题价值评分", REQUIRED_SECTIONS)

    def test_section_names_updated(self):
        """新旧章节名已更新。"""
        from scripts.acceptance_check import REQUIRED_SECTIONS
        self.assertIn("关键词相关内容选题建议", REQUIRED_SECTIONS)
        self.assertIn("热点选题与文案定制建议", REQUIRED_SECTIONS)
        self.assertNotIn("可写文案方向", REQUIRED_SECTIONS)
        self.assertNotIn("推荐标题", REQUIRED_SECTIONS)


class TestTopicSuggestions(unittest.TestCase):
    """验证 _build_topic_suggestions 使用真实洞察词。"""

    def setUp(self):
        from src.schemas import (
            CommentRecord,
            InsightRecord,
            NormalizedDataset,
            PostRecord,
        )
        from src.reports.report_agent import (
            _build_custom_title_suggestions,
            _build_topic_suggestions,
            _extract_hot_terms,
            _extract_question_like,
        )

        self._build_topic_suggestions = _build_topic_suggestions
        self._build_custom_title_suggestions = _build_custom_title_suggestions
        self._extract_hot_terms = _extract_hot_terms
        self._extract_question_like = _extract_question_like
        self.CommentRecord = CommentRecord
        self.InsightRecord = InsightRecord
        self.NormalizedDataset = NormalizedDataset
        self.PostRecord = PostRecord

    def _make_dataset_with_comments(self, comments_content, posts_content=None):
        posts = []
        if posts_content:
            for i, (title, content) in enumerate(posts_content):
                posts.append(self.PostRecord(
                    platform="xhs",
                    post_id=f"post_{i}",
                    title=title,
                    content=content,
                    author="test_user",
                    publish_time="2025-01-01T00:00:00",
                    likes=10,
                    comments=5,
                ))

        comments = []
        for i, content in enumerate(comments_content):
            comments.append(self.CommentRecord(
                platform="xhs",
                comment_id=f"cmt_{i}",
                post_id="post_0",
                content=content,
                author="test_user",
                publish_time="2025-01-01T00:00:00",
                likes=1,
            ))

        return self.NormalizedDataset(posts=posts, comments=comments)

    def test_topic_suggestions_use_real_insight_terms(self):
        """验证生成的建议中出现 insights 中的真实词。"""
        insight = self.InsightRecord(
            pain_points=["hello-agents", "GitHub路线", "项目原创性顾虑"],
            user_needs=["AI agent工作流", "多agent协作"],
            complaints=["配置太复杂", "文档不清晰"],
            solutions=["LangGraph", "CrewAI"],
            market_signals=["AI agent需求增长", "自动化流程"],
            sentiment="neutral",
            evidence_post_ids=["post_0"],
            evidence_comment_ids=["cmt_0"],
        )
        dataset = self._make_dataset_with_comments(
            ["AI agent怎么配置？有没有好的教程"],
            [("AI agent使用体验", "最近在尝试用AI agent搭建工作流")],
        )

        suggestions = self._build_topic_suggestions("AI agent", dataset, insight)

        # 验证 suggestions 不为空
        self.assertTrue(len(suggestions) > 0)

        # 验证 insights 中的真实词出现在建议中
        combined = " ".join(suggestions)
        self.assertIn("hello-agents", combined)
        self.assertIn("GitHub路线", combined)
        self.assertIn("项目原创性顾虑", combined)
        self.assertIn("AI agent工作流", combined)
        self.assertIn("多agent协作", combined)

    def test_title_suggestions_are_not_generic_only(self):
        """验证不只输出通用模板。"""
        insight = self.InsightRecord(
            pain_points=["内存占用高", "响应速度慢"],
            user_needs=["轻量化方案", "性能优化"],
            complaints=["卡顿严重"],
            solutions=["优化配置", "升级硬件"],
            market_signals=["性能对比需求"],
            sentiment="neutral",
            evidence_post_ids=["post_0"],
            evidence_comment_ids=["cmt_0"],
        )
        dataset = self._make_dataset_with_comments(
            ["哪里可以找到轻量化的方案？有没有推荐"],
            [("性能优化经验", "分享一下性能优化的经验")],
        )

        title_suggestions = self._build_custom_title_suggestions(
            "AI agent", dataset, insight
        )

        # 验证输出了具体建议
        self.assertTrue(len(title_suggestions) >= 1)

        # 验证每个建议包含 direction、title、evidence、content_angle
        for ts in title_suggestions:
            self.assertIn("direction", ts)
            self.assertIn("title", ts)
            self.assertIn("evidence", ts)
            self.assertIn("content_angle", ts)

        # 验证建议不是空的
        for ts in title_suggestions:
            self.assertTrue(len(ts["direction"]) > 0)
            self.assertTrue(len(ts["title"]) > 0)
            self.assertTrue(len(ts["evidence"]) > 0)
            self.assertTrue(len(ts["content_angle"]) > 0)

        # 验证建议包含从 insight 中提取的真实词
        combined_evidence = " ".join(ts["evidence"] for ts in title_suggestions)
        combined_direction = " ".join(ts["direction"] for ts in title_suggestions)
        all_text = combined_evidence + combined_direction
        # 应至少包含某个 insight 关键词
        has_real_term = any(
            term in all_text
            for term in ["内存占用高", "响应速度慢", "轻量化方案", "性能优化", "卡顿严重"]
        )
        self.assertTrue(has_real_term)

    def test_topic_suggestions_include_reason(self):
        """验证每个建议不是空泛模板，有具体引用。"""
        insight = self.InsightRecord(
            pain_points=["学习曲线陡峭", "调试困难"],
            user_needs=["快速上手教程"],
            complaints=["文档太少"],
            solutions=["官方文档"],
            market_signals=["AI编程助手讨论"],
            sentiment="neutral",
            evidence_post_ids=["post_0"],
            evidence_comment_ids=["cmt_0"],
        )
        dataset = self._make_dataset_with_comments(
            ["学习曲线太陡了，有没有快速上手的方法？"],
            [("AI编程助手体验", "AI编程助手真的能提高效率吗")],
        )

        suggestions = self._build_topic_suggestions("AI编程助手", dataset, insight)

        # 验证每个建议都是完整有意义的段落
        self.assertTrue(len(suggestions) > 0)
        for sug in suggestions:
            # 每个建议至少包含一个引用内容或依据
            self.assertTrue(len(sug) > 10, f"建议太短: {sug}")
            # 不应包含"你不得不知道的几件事"这类通用模板
            self.assertNotIn("不得不知道", sug)
            self.assertNotIn("花了冤枉钱", sug)

    def test_topic_suggestions_integration_with_html(self):
        """验证建议能直接用于 HTML 构建。"""
        insight = self.InsightRecord(
            pain_points=["抽油烟机吸力不足", "噪音大"],
            user_needs=["大吸力抽油烟机推荐", "静音抽油烟机"],
            complaints=["清洗困难", "价格虚高"],
            solutions=["老板电器", "方太"],
            market_signals=["侧吸式抽油烟机"],
            sentiment="neutral",
            evidence_post_ids=["post_0"],
            evidence_comment_ids=["cmt_0"],
        )
        dataset = self._make_dataset_with_comments(
            ["侧吸式抽油烟机吸力怎么样？跟顶吸哪个好"],
            [("抽油烟机选购指南", "求推荐大吸力静音抽油烟机")],
        )

        suggestions = self._build_topic_suggestions("抽油烟机", dataset, insight)

        # 构建 HTML 片段
        sug_html = ""
        for i, sug in enumerate(suggestions, 1):
            sug_html += f"<li>{json.dumps(sug, ensure_ascii=False)}</li>\n"

        self.assertIn("侧吸式抽油烟机", sug_html)
        self.assertIn("大吸力", sug_html)

    def test_empty_insight_fallback(self):
        """验证洞察为空时生成 fallback 建议。"""
        insight = self.InsightRecord(
            pain_points=[],
            user_needs=[],
            complaints=[],
            solutions=[],
            market_signals=[],
            sentiment="neutral",
            evidence_post_ids=[],
            evidence_comment_ids=[],
        )
        dataset = self._make_dataset_with_comments([])

        suggestions = self._build_topic_suggestions("测试话题", dataset, insight)

        self.assertTrue(len(suggestions) >= 1)
        self.assertIn("评论样本较少", suggestions[0])

    def test_title_suggestions_empty_fallback(self):
        """验证洞察为空时生成 fallback 标题建议。"""
        insight = self.InsightRecord(
            pain_points=[],
            user_needs=[],
            complaints=[],
            solutions=[],
            market_signals=[],
            sentiment="neutral",
            evidence_post_ids=[],
            evidence_comment_ids=[],
        )
        dataset = self._make_dataset_with_comments([])

        title_suggestions = self._build_custom_title_suggestions(
            "测试话题", dataset, insight
        )

        self.assertTrue(len(title_suggestions) >= 1)
        self.assertIn("评论样本较少", title_suggestions[0]["evidence"])

    def test_hot_topic_suggestions_use_question_and_feedback_terms(self):
        """验证建议包含评论中的疑问词和反馈词。"""
        insight = self.InsightRecord(
            pain_points=["学习路线太杂", "不知道该先学什么"],
            user_needs=["系统化的学习路径", "适合新手的入门资源"],
            complaints=["课程太多不知道选哪个"],
            solutions=["hello-agents框架", "LangGraph"],
            market_signals=["AI agent实战需求"],
            sentiment="neutral",
            evidence_post_ids=["post_0"],
            evidence_comment_ids=["cmt_0", "cmt_1"],
        )
        dataset = self._make_dataset_with_comments([
            "怎么才能系统地学习AI agent？有没有推荐的路线",
            "hello-agents框架怎么用？看不懂文档",
            "太多课程了不知道选哪个好",
        ])

        suggestions = self._build_custom_title_suggestions("AI agent", dataset, insight)

        # 验证输出了建议
        self.assertTrue(len(suggestions) > 0)

        combined = " ".join(s.get("direction", "") for s in suggestions)
        # 应出现与疑问/反馈相关的分类方向
        self.assertTrue(
            any(kw in combined for kw in ["疑问解答", "避坑", "误区", "入门", "学习路线"]),
            f"suggestions should contain question/feedback related direction, got: {combined}"
        )

        # 验证 evidence 引用了真实评论或洞察词
        all_evidence = " ".join(s.get("evidence", "") for s in suggestions)
        self.assertTrue(
            any(term in all_evidence for term in ["怎么", "学习路线", "系统化的学习路径", "hello-agents"]),
            f"evidence should reference real comment or insight terms, got: {all_evidence}"
        )

    def test_hot_topic_suggestions_include_evidence_and_content_angle(self):
        """验证每条建议都包含 evidence 和 content_angle。"""
        insight = self.InsightRecord(
            pain_points=["配置太复杂", "调试困难"],
            user_needs=["快速上手指南", "debug技巧"],
            complaints=["文档太少"],
            solutions=["官方文档"],
            market_signals=["AI编程助手讨论"],
            sentiment="neutral",
            evidence_post_ids=["post_0"],
            evidence_comment_ids=["cmt_0"],
        )
        dataset = self._make_dataset_with_comments([
            "配置太复杂了，有没有简单的方法",
            "这篇文章太长了看不懂",
        ])

        suggestions = self._build_custom_title_suggestions("AI编程助手", dataset, insight)

        self.assertTrue(len(suggestions) > 0)
        for s in suggestions:
            self.assertIn("direction", s)
            self.assertIn("title", s)
            self.assertIn("evidence", s)
            self.assertIn("content_angle", s)
            # evidence 不能为空
            self.assertTrue(len(s["evidence"]) > 0, f"evidence should not be empty for suggestion: {s['direction']}")
            # content_angle 不能为空
            self.assertTrue(len(s["content_angle"]) > 0, f"content_angle should not be empty for suggestion: {s['direction']}")
            # evidence 应包含有意义的分析依据，而非单纯重复词
            self.assertGreater(len(s["evidence"]), 5, f"evidence too short: {s['evidence']}")
            # content_angle 应包含内容制作方向，而非空泛描述
            self.assertGreater(len(s["content_angle"]), 5, f"content_angle too short: {s['content_angle']}")

    def test_title_suggestions_not_generic_templates(self):
        """验证建议不再使用机械化标题模板。"""
        insight = self.InsightRecord(
            pain_points=["内存占用高", "响应速度慢"],
            user_needs=["轻量化方案", "性能优化技巧"],
            complaints=["卡顿严重"],
            solutions=["优化配置", "升级硬件"],
            market_signals=["性能对比需求"],
            sentiment="neutral",
            evidence_post_ids=["post_0"],
            evidence_comment_ids=["cmt_0"],
        )
        dataset = self._make_dataset_with_comments([
            "哪里可以找到轻量化的方案？有没有推荐",
            "卡顿太严重了，有没有优化方法",
        ])

        suggestions = self._build_custom_title_suggestions("AI agent", dataset, insight)

        self.assertTrue(len(suggestions) > 0)

        # 不应包含旧的机械化标题格式："{keyword}的...话题"
        for s in suggestions:
            title = s.get("title", "")
            direction = s.get("direction", "")
            # 不应出现旧的 "{keyword}的{term}话题" 格式
            self.assertNotIn("的", direction.split("话题")[0] if "话题" in direction else "")
            # 不应出现 "评论区都在讨论这些" 这种机械化收尾
            self.assertNotIn("评论区都在讨论这些", title)
            # 不应出现 "{keyword} {term}？" 这种简单拼接
            if "？" in title:
                q_part = title.split("？")[0]
                self.assertFalse(
                    q_part.startswith("AI agent ") and len(q_part.split("AI agent ")[1].strip()) < 10,
                    f"title appears to be mechanical template: {title}"
                )

    def test_copywriting_sections_still_keep_required_section_names(self):
        """验证 HTML 报告仍保留关键词相关内容选题建议和热点选题章节。"""
        from src.schemas import ScoreCard
        from src.reports.report_agent import ReportAgent

        scorecard = ScoreCard(
            demand_intensity=0.6,
            sentiment_friction=0.3,
            solution_saturation=0.4,
            purchase_intent=0.5,
            freshness=0.7,
            overall_score=0.55,
            scoring_reason="【用户关注强度】中等 | 【负面摩擦】较低 | 【方案饱和】中等 | 【购买意向】中等 | 【时效性】较高",
        )
        insight = self.InsightRecord(
            pain_points=["学习曲线陡峭"],
            user_needs=["快速上手教程"],
            complaints=["文档太少"],
            solutions=["官方文档"],
            market_signals=["AI编程助手讨论"],
            sentiment="neutral",
            evidence_post_ids=["post_0"],
            evidence_comment_ids=["cmt_0"],
        )
        dataset = self._make_dataset_with_comments([
            "学习曲线太陡了，有没有快速上手的方法",
        ])

        html = ReportAgent._build_html(insight, scorecard, dataset, topic="AI编程助手", product_direction="AI编程")

        self.assertIn("关键词相关内容选题建议", html)
        self.assertIn("热点选题与文案定制建议", html)


if __name__ == "__main__":
    unittest.main()
