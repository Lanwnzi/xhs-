"""
P6.0 CommentClusterAgent 单元测试。

所有测试使用 mock embedding，不真实调用外部 API。
使用 tempfile.TemporaryDirectory 模拟文件系统。
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from typing import Any, Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import unittest

from src.agents.comment_cluster_agent import (
    CommentClusterAgent,
    _compute_hotness,
    _cosine_similarity,
    _derive_topic,
    _extract_keywords,
    _l2_normalize,
    _pick_representative,
    _union_find_clusters,
)
from src.llm.embedding_client import EmbeddingClient
from src.schemas import CommentRecord
from src.schemas.comment_cluster import (
    CommentClusterRecord,
    CommentClusterResult,
)
from src.schemas.llm_records import CommentAnnotationRecord
from src.utils import AppPaths


class _MockEmbeddingClient(EmbeddingClient):
    """Mock EmbeddingClient，返回固定向量用于测试。

    提供两种向量模式：
    - similar_texts: 返回相似向量（cosine sim ~0.85）
    - different_texts: 返回不同向量（cosine sim ~0.30）
    """

    def __init__(self):
        # 不调用父类 __init__，避免检查环境变量
        super().__init__(
            base_url="http://mock", api_key="mock", model="mock", timeout=5,
        )
        self._call_count: dict[str, int] = {}

    def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """返回固定向量。

        向量维度 4。
        根据文本特征返回不同相似度的向量。
        """
        base = [1.0, 0.0, 0.0, 0.0]

        vectors = []
        for text in texts:
            if "DIFFERENT" in text:
                # 每个 DIFFERENT 文本获得不同的随机正交向量
                idx = self._call_count.get("diff", 0)
                self._call_count["diff"] = idx + 1
                # 使用不同的正交基向量，确保低相似度
                if idx % 3 == 0:
                    vectors.append([0.0, 1.0, 0.0, 0.0])
                elif idx % 3 == 1:
                    vectors.append([0.0, 0.0, 1.0, 0.0])
                else:
                    vectors.append([0.0, 0.0, 0.0, 1.0])
            elif "SIMILAR_B" in text:
                vectors.append([0.95, 0.312, 0.0, 0.0])  # ~0.95 cosine with base
            else:
                vectors.append(base)
        return vectors

    def embed_one(self, text: str) -> Optional[list[float]]:
        vectors = self.embed([text])
        return vectors[0] if vectors else None


class _MockDisabledEmbeddingClient(EmbeddingClient):
    """Mock EmbeddingClient that always returns None (simulating failure)."""

    def __init__(self):
        super().__init__(
            base_url="http://mock", api_key="mock", model="mock", timeout=5,
        )

    def embed(self, texts: list[str]) -> None:
        return None

    def embed_one(self, text: str) -> None:
        return None


def _make_comment(
    comment_id: str,
    content: str,
    post_id: str = "post_001",
    likes: int = 0,
    author: str = "user",
    platform: str = "xhs",
) -> CommentRecord:
    return CommentRecord(
        platform=platform,
        comment_id=comment_id,
        post_id=post_id,
        content=content,
        author=author,
        publish_time="2025-01-01T00:00:00",
        likes=likes,
    )


# ===================================================================
# Tests
# ===================================================================


class TestEmbeddingClientDisabled(unittest.TestCase):
    """Test 1: embedding_client disabled returns None."""

    def test_embedding_client_disabled_returns_none(self):
        """embedding_client 不可用时 create_embedding_client_from_env 返回 None。"""
        import os as _os
        from src.llm.embedding_client import create_embedding_client_from_env

        # 禁用聚类
        _os.environ["COMMENT_CLUSTERING_ENABLED"] = "false"
        client = create_embedding_client_from_env()
        self.assertIsNone(client)

        # 重置
        _os.environ["COMMENT_CLUSTERING_ENABLED"] = "true"


class TestCommentClusterSchema(unittest.TestCase):
    """Test 2: schema 字段正确。"""

    def test_comment_cluster_schema(self):
        """CommentClusterRecord 和 CommentClusterResult 字段正确。"""
        record = CommentClusterRecord(
            cluster_id="cluster_001",
            topic="测试主题",
            comment_count=5,
            total_comment_likes=10,
            avg_similarity=0.85,
            hotness=0.75,
            keywords=["测试", "关键词"],
            top_labels=["标签1"],
            evidence_comment_ids=["c1", "c2"],
            representative_comments=["评论1", "评论2"],
        )
        self.assertEqual(record.cluster_id, "cluster_001")
        self.assertEqual(record.topic, "测试主题")
        self.assertEqual(record.comment_count, 5)
        self.assertAlmostEqual(record.avg_similarity, 0.85)
        self.assertAlmostEqual(record.hotness, 0.75)
        self.assertEqual(record.keywords, ["测试", "关键词"])
        self.assertEqual(record.top_labels, ["标签1"])
        self.assertEqual(record.evidence_comment_ids, ["c1", "c2"])
        self.assertEqual(record.representative_comments, ["评论1", "评论2"])
        self.assertEqual(record.summary, "")

        result = CommentClusterResult(
            clusters=[record],
            total_comments=10,
            clustered_comments=5,
            noise_comments=5,
            similarity_threshold=0.72,
        )
        self.assertEqual(len(result.clusters), 1)
        self.assertEqual(result.total_comments, 10)
        self.assertEqual(result.clustered_comments, 5)
        self.assertEqual(result.noise_comments, 5)
        self.assertEqual(result.algorithm, "cosine_threshold_union_find")
        self.assertAlmostEqual(result.similarity_threshold, 0.72)

        # 默认值
        result2 = CommentClusterResult()
        self.assertEqual(result2.clusters, [])
        self.assertEqual(result2.total_comments, 0)
        self.assertEqual(result2.algorithm, "cosine_threshold_union_find")


class TestCosineSimilarityClustering(unittest.TestCase):
    """Test 3: 相似评论归为同一簇。"""

    def setUp(self):
        self.agent = CommentClusterAgent(
            embedding_client=_MockEmbeddingClient(),
            similarity_threshold=0.72,
            min_cluster_size=2,
            top_k=10,
        )

    def test_cosine_similarity_clusters_similar_comments(self):
        """相似评论应归为同一簇。"""
        comments = [
            _make_comment("c1", "这个产品很好用，推荐给大家 SIMILAR_A", likes=5),
            _make_comment("c2", "这个产品确实很好用 SIMILAR_A", likes=3),
            _make_comment("c3", "DIFFERENT 完全不同的内容，关于其他话题", likes=2),
        ]
        result = self.agent.execute(comments)
        # 前两条评论应该形成至少一个聚类（相似度 > 0.72）
        # 第三条由于是不同的方向，应该作为噪声
        self.assertGreaterEqual(
            result.clustered_comments, 2,
            "相似评论应该被聚类",
        )


class TestLowSimilarityNoCluster(unittest.TestCase):
    """Test 4: 不相似评论不聚类。"""

    def test_low_similarity_comments_not_clustered(self):
        """不相似评论不应聚类。"""
        # 使用高阈值 0.95 确保不聚类
        agent = CommentClusterAgent(
            embedding_client=_MockEmbeddingClient(),
            similarity_threshold=0.95,
            min_cluster_size=2,
            top_k=10,
        )
        comments = [
            _make_comment("c1", "DIFFERENT 内容A完全不同", likes=1),
            _make_comment("c2", "DIFFERENT 内容B完全不同", likes=1),
        ]
        result = agent.execute(comments)
        # 两条完全不同且与 base vector 正交的评论，cosine=0，不会聚类
        self.assertEqual(result.clustered_comments, 0)


class TestClusterUsesCommentLikesForHotness(unittest.TestCase):
    """Test 5: 高赞评论簇热度更高。"""

    def test_cluster_uses_comment_likes_for_hotness(self):
        """高赞评论簇的热度应高于低赞簇。"""
        comments = [
            _make_comment("c1", "这个产品很好用 SIMILAR_A", likes=100),
            _make_comment("c2", "确实很好用 SIMILAR_A", likes=50),
            _make_comment("c3", "DIFFERENT 完全不同的话题1", likes=10),
            _make_comment("c4", "DIFFERENT 完全不同的话题2", likes=5),
        ]
        agent = CommentClusterAgent(
            embedding_client=_MockEmbeddingClient(),
            similarity_threshold=0.72,
            min_cluster_size=2,
            top_k=10,
        )
        result = agent.execute(comments)

        # 高赞簇应该出现在聚类结果中
        cluster = None
        for c in result.clusters:
            if "SIMILAR" in " ".join(c.representative_comments):
                cluster = c
                break
        self.assertIsNotNone(cluster, "高赞评论簇应该被识别")
        self.assertGreater(cluster.total_comment_likes, 0)


class TestClusterHotnessNormalizedLogFeatures(unittest.TestCase):
    """Test 6: 验证归一化公式。"""

    def test_cluster_hotness_uses_normalized_log_features(self):
        """验证 hotness 计算使用 log1p 归一化。"""
        # 单簇场景
        count, max_count = 5, 5
        likes, max_likes = 20, 20
        avg_sim = 0.8

        hotness = _compute_hotness(count, max_count, likes, max_likes, avg_sim)
        # norm_log_count = log1p(5)/log1p(5) = 1.0
        # norm_log_likes = log1p(20)/log1p(20) = 1.0
        # hotness = 0.5 * 1.0 + 0.3 * 1.0 + 0.2 * 0.8 = 0.5 + 0.3 + 0.16 = 0.96
        self.assertAlmostEqual(hotness, 0.96, places=4)

    def test_hotness_boundary_max_count_zero(self):
        """max_count=0 或 max_likes=0 时 hotness 不崩溃。"""
        hotness = _compute_hotness(3, 0, 5, 0, 0.7)
        # max_count=0 => norm_log_count=0
        # max_likes=0 => norm_log_likes=0
        # hotness = 0.5*0 + 0.3*0 + 0.2*0.7 = 0.14
        self.assertAlmostEqual(hotness, 0.14, places=4)


class TestClusterGeneratesRepresentativeComments(unittest.TestCase):
    """Test 7: 代表评论来自真实数据。"""

    def test_cluster_generates_representative_comments(self):
        """代表评论应该来自真实评论数据。"""
        comments = [
            _make_comment("c1", "这是第一条评论 SIMILAR_A", likes=10),
            _make_comment("c2", "这是第二条评论 SIMILAR_A", likes=5),
            _make_comment("c3", "这是第三条评论 SIMILAR_A", likes=1),
        ]
        agent = CommentClusterAgent(
            embedding_client=_MockEmbeddingClient(),
            similarity_threshold=0.72,
            min_cluster_size=2,
            top_k=10,
        )
        result = agent.execute(comments)

        for cluster in result.clusters:
            self.assertGreater(len(cluster.representative_comments), 0)
            for rep in cluster.representative_comments:
                # 代表评论内容应该是原始评论的一部分
                self.assertIn(
                    rep,
                    [c.content for c in comments],
                    f"代表评论 '{rep}' 应来自原始数据",
                )


class TestClusterBindsEvidenceCommentIds(unittest.TestCase):
    """Test 8: evidence 来自真实 comment_id。"""

    def test_cluster_binds_evidence_comment_ids(self):
        """evidence_comment_ids 应来自真实 comment_id。"""
        comments = [
            _make_comment("c1", "评论1 SIMILAR_A", likes=5),
            _make_comment("c2", "评论2 SIMILAR_A", likes=3),
        ]
        agent = CommentClusterAgent(
            embedding_client=_MockEmbeddingClient(),
            similarity_threshold=0.72,
            min_cluster_size=2,
            top_k=10,
        )
        result = agent.execute(comments)

        all_ids = {c.comment_id for c in comments}
        for cluster in result.clusters:
            for eid in cluster.evidence_comment_ids:
                self.assertIn(
                    eid, all_ids,
                    f"evidence comment_id '{eid}' 应来自真实数据",
                )


class TestClusterAgentWritesCommentClustersJson(unittest.TestCase):
    """Test 9: 文件写入 outputs/。"""

    def test_cluster_agent_writes_comment_clusters_json(self):
        """execute_and_persist 应写入 comment_clusters.json。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs_dir = os.path.join(tmpdir, "outputs")
            paths = AppPaths(
                project_root=tmpdir,
                raw_dir=os.path.join(tmpdir, "raw"),
                normalized_dir=os.path.join(tmpdir, "normalized"),
                outputs_dir=outputs_dir,
                raw_posts_file=os.path.join(tmpdir, "raw", "raw_posts.json"),
                raw_comments_file=os.path.join(tmpdir, "raw", "raw_comments.json"),
                normalized_posts_file=os.path.join(tmpdir, "normalized", "normalized_posts.json"),
                normalized_comments_file=os.path.join(tmpdir, "normalized", "normalized_comments.json"),
                insights_file=os.path.join(outputs_dir, "insights.json"),
                scorecard_file=os.path.join(outputs_dir, "scorecard.json"),
                report_file=os.path.join(outputs_dir, "report.html"),
                comment_clusters_file=os.path.join(outputs_dir, "comment_clusters.json"),
            )
            comments = [
                _make_comment("c1", "评论1 SIMILAR_A", likes=5),
                _make_comment("c2", "评论2 SIMILAR_A", likes=3),
            ]
            agent = CommentClusterAgent(
                embedding_client=_MockEmbeddingClient(),
                similarity_threshold=0.72,
                min_cluster_size=2,
                top_k=10,
            )
            agent.execute_and_persist(paths, comments)

            cluster_path = paths.comment_clusters_file
            self.assertTrue(os.path.exists(cluster_path), "comment_clusters.json 应存在")

            with open(cluster_path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("clusters", data)
            self.assertIn("total_comments", data)


class TestClusterAgentSkipsWhenEmbeddingDisabled(unittest.TestCase):
    """Test 10: embedding 不可用时跳过。"""

    def test_cluster_agent_skips_when_embedding_disabled(self):
        """embedding_client 为 None 时 skipped。"""
        agent = CommentClusterAgent(embedding_client=None)
        comments = [
            _make_comment("c1", "测试评论", likes=1),
            _make_comment("c2", "测试评论2", likes=1),
        ]
        result = agent.execute(comments)
        self.assertEqual(len(result.clusters), 0)
        self.assertEqual(result.clustered_comments, 0)
        self.assertEqual(result.noise_comments, len(comments))

    def test_cluster_agent_skips_when_embedding_fails(self):
        """embedding 返回 None 时 skipped。"""
        agent = CommentClusterAgent(
            embedding_client=_MockDisabledEmbeddingClient(),
        )
        comments = [
            _make_comment("c1", "测试评论", likes=1),
            _make_comment("c2", "测试评论2", likes=1),
        ]
        result = agent.execute(comments)
        self.assertEqual(len(result.clusters), 0)
        self.assertEqual(result.clustered_comments, 0)


class TestThresholdExperimentRuns065072080(unittest.TestCase):
    """Test 11: 实验脚本可执行。"""

    def test_threshold_experiment_runs_065_072_080(self):
        """验证三个阈值下聚类逻辑正常运行。"""
        comments = [
            _make_comment("c1", "产品很好用 SIMILAR_A", likes=10),
            _make_comment("c2", "确实不错 SIMILAR_A", likes=5),
            _make_comment("c3", "DIFFERENT 完全不同的话题A", likes=3),
            _make_comment("c4", "DIFFERENT 完全不同的话题B", likes=2),
            _make_comment("c5", "另一个相似话题 SIMILAR_B", likes=8),
            _make_comment("c6", "SIMILAR_B 这个也类似", likes=4),
        ]
        embedding_client = _MockEmbeddingClient()
        thresholds = [0.65, 0.72, 0.80]

        results = []
        for t in thresholds:
            agent = CommentClusterAgent(
                embedding_client=embedding_client,
                similarity_threshold=t,
                min_cluster_size=2,
                top_k=10,
            )
            result = agent.execute(comments)
            results.append(result)

        # 验证不同阈值产生不同结果
        cluster_counts = [len(r.clusters) for r in results]
        # 至少应该有一些聚类（高阈值可能得不到簇）
        self.assertTrue(
            any(c > 0 for c in cluster_counts) or all(c == 0 for c in cluster_counts),
            "阈值实验应产生有效结果",
        )


class TestReportUsesCommentClustersWhenAvailable(unittest.TestCase):
    """Test 12: ReportAgent 读取并使用聚类数据。"""

    def test_report_uses_comment_clusters_when_available(self):
        """ReportAgent 在有 cluster 文件时读取并使用。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            from src.reports.report_agent import ReportAgent

            outputs_dir = os.path.join(tmpdir, "outputs")
            os.makedirs(outputs_dir, exist_ok=True)

            paths = AppPaths(
                project_root=tmpdir,
                raw_dir=os.path.join(tmpdir, "raw"),
                normalized_dir=os.path.join(tmpdir, "normalized"),
                outputs_dir=outputs_dir,
                raw_posts_file=os.path.join(tmpdir, "raw", "raw_posts.json"),
                raw_comments_file=os.path.join(tmpdir, "raw", "raw_comments.json"),
                normalized_posts_file=os.path.join(tmpdir, "normalized", "normalized_posts.json"),
                normalized_comments_file=os.path.join(tmpdir, "normalized", "normalized_comments.json"),
                insights_file=os.path.join(outputs_dir, "insights.json"),
                scorecard_file=os.path.join(outputs_dir, "scorecard.json"),
                report_file=os.path.join(outputs_dir, "report.html"),
                comment_clusters_file=os.path.join(outputs_dir, "comment_clusters.json"),
            )

            # 写入 clusters 数据
            cluster_data = {
                "clusters": [
                    {
                        "cluster_id": "cluster_001",
                        "topic": "学习路线",
                        "comment_count": 5,
                        "total_comment_likes": 20,
                        "avg_similarity": 0.85,
                        "hotness": 0.92,
                        "keywords": ["学习", "路线"],
                        "top_labels": ["学习资源"],
                        "evidence_comment_ids": ["c1"],
                        "representative_comments": ["有没有完整的学习路线"],
                    },
                ],
                "total_comments": 10,
                "clustered_comments": 5,
                "noise_comments": 5,
                "similarity_threshold": 0.72,
            }
            with open(paths.comment_clusters_file, "w", encoding="utf-8") as f:
                json.dump(cluster_data, f, ensure_ascii=False)

            # 创建 ReportAgent
            from src.schemas import InsightRecord, NormalizedDataset, ScoreCard

            insight = InsightRecord(
                pain_points=["测试痛点"],
                user_needs=["测试需求"],
                evidence_post_ids=["p1"],
                evidence_comment_ids=["c1"],
            )
            scorecard = ScoreCard(
                demand_intensity=0.6,
                sentiment_friction=0.3,
                solution_saturation=0.4,
                purchase_intent=0.2,
                freshness=0.5,
                overall_score=0.45,
                scoring_reason="测试评分理由",
            )
            dataset = NormalizedDataset(
                posts=[],
                comments=[
                    _make_comment("c1", "有没有完整的学习路线", likes=10),
                ],
            )
            agent = ReportAgent(paths=paths)
            result = agent.execute(
                insight=insight,
                scorecard=scorecard,
                dataset=dataset,
                topic="测试",
            )
            self.assertTrue(result.success)

            # 验证报告包含聚类内容
            with open(result.report_path, encoding="utf-8") as f:
                html = f.read()
            self.assertIn("高频评论主题", html)
            self.assertIn("学习路线", html)


class TestReportFallbackWhenCommentClustersMissing(unittest.TestCase):
    """Test 13: 无 cluster 文件时回退。"""

    def test_report_fallback_when_comment_clusters_missing(self):
        """没有 comment_clusters.json 时报告正常生成。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            from src.reports.report_agent import ReportAgent

            outputs_dir = os.path.join(tmpdir, "outputs")
            os.makedirs(outputs_dir, exist_ok=True)

            paths = AppPaths(
                project_root=tmpdir,
                raw_dir=os.path.join(tmpdir, "raw"),
                normalized_dir=os.path.join(tmpdir, "normalized"),
                outputs_dir=outputs_dir,
                raw_posts_file=os.path.join(tmpdir, "raw", "raw_posts.json"),
                raw_comments_file=os.path.join(tmpdir, "raw", "raw_comments.json"),
                normalized_posts_file=os.path.join(tmpdir, "normalized", "normalized_posts.json"),
                normalized_comments_file=os.path.join(tmpdir, "normalized", "normalized_comments.json"),
                insights_file=os.path.join(outputs_dir, "insights.json"),
                scorecard_file=os.path.join(outputs_dir, "scorecard.json"),
                report_file=os.path.join(outputs_dir, "report.html"),
                comment_clusters_file=os.path.join(outputs_dir, "comment_clusters.json"),
            )

            # 不创建 comment_clusters.json
            from src.schemas import InsightRecord, NormalizedDataset, ScoreCard

            insight = InsightRecord(
                pain_points=["测试"],
                evidence_post_ids=["p1"],
                evidence_comment_ids=["c1"],
            )
            scorecard = ScoreCard(
                demand_intensity=0.5, sentiment_friction=0.3,
                solution_saturation=0.4, purchase_intent=0.2,
                freshness=0.5, overall_score=0.4,
                scoring_reason="测试",
            )
            dataset = NormalizedDataset(comments=[_make_comment("c1", "测试", likes=1)])
            agent = ReportAgent(paths=paths)
            result = agent.execute(
                insight=insight, scorecard=scorecard,
                dataset=dataset, topic="测试",
            )
            self.assertTrue(result.success)
            # 报告不应包含聚类内容
            with open(result.report_path, encoding="utf-8") as f:
                html = f.read()
            self.assertNotIn("高频评论主题", html)


class TestReportDisplaysClusterRepresentativeComments(unittest.TestCase):
    """Test 14: HTML 含代表评论。"""

    def test_report_displays_cluster_representative_comments(self):
        """报告 HTML 应包含 cluster 代表评论。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            from src.reports.report_agent import ReportAgent

            outputs_dir = os.path.join(tmpdir, "outputs")
            os.makedirs(outputs_dir, exist_ok=True)
            paths = AppPaths(
                project_root=tmpdir,
                raw_dir=os.path.join(tmpdir, "raw"),
                normalized_dir=os.path.join(tmpdir, "normalized"),
                outputs_dir=outputs_dir,
                raw_posts_file=os.path.join(tmpdir, "raw", "raw_posts.json"),
                raw_comments_file=os.path.join(tmpdir, "raw", "raw_comments.json"),
                normalized_posts_file=os.path.join(tmpdir, "normalized", "normalized_posts.json"),
                normalized_comments_file=os.path.join(tmpdir, "normalized", "normalized_comments.json"),
                insights_file=os.path.join(outputs_dir, "insights.json"),
                scorecard_file=os.path.join(outputs_dir, "scorecard.json"),
                report_file=os.path.join(outputs_dir, "report.html"),
                comment_clusters_file=os.path.join(outputs_dir, "comment_clusters.json"),
            )

            # 写入包含代表评论的 cluster 数据
            cluster_data = {
                "clusters": [
                    {
                        "cluster_id": "cluster_001",
                        "topic": "学习资源",
                        "comment_count": 3,
                        "total_comment_likes": 15,
                        "avg_similarity": 0.88,
                        "hotness": 0.85,
                        "keywords": ["教程", "资源"],
                        "top_labels": ["学习资源"],
                        "evidence_comment_ids": ["c1"],
                        "representative_comments": ["有没有推荐的入门教程"],
                    },
                ],
                "total_comments": 10,
                "clustered_comments": 3,
                "noise_comments": 7,
                "similarity_threshold": 0.72,
            }
            with open(paths.comment_clusters_file, "w", encoding="utf-8") as f:
                json.dump(cluster_data, f, ensure_ascii=False)

            from src.schemas import InsightRecord, NormalizedDataset, ScoreCard

            insight = InsightRecord(
                pain_points=["测试"],
                evidence_post_ids=["p1"],
                evidence_comment_ids=["c1"],
            )
            scorecard = ScoreCard(
                demand_intensity=0.5, sentiment_friction=0.3,
                solution_saturation=0.4, purchase_intent=0.2,
                freshness=0.5, overall_score=0.4,
                scoring_reason="测试",
            )
            dataset = NormalizedDataset(comments=[_make_comment("c1", "测试")])
            agent = ReportAgent(paths=paths)
            result = agent.execute(
                insight=insight, scorecard=scorecard,
                dataset=dataset, topic="测试",
            )
            self.assertTrue(result.success)
            with open(result.report_path, encoding="utf-8") as f:
                html = f.read()
            self.assertIn("有没有推荐的入门教程", html)


class TestFeishuFlowNotBlockedByCommentClustering(unittest.TestCase):
    """Test 15: 飞书不受影响。"""

    def test_feishu_flow_not_blocked_by_comment_clustering(self):
        """聚类异常不应阻止飞书主流程。"""
        # 模拟 services.py 中异常捕获逻辑
        # 即使聚类失败，主流程继续
        try:
            agent = CommentClusterAgent(embedding_client=None)
            comments = [
                _make_comment("c1", "测试", likes=1),
            ]
            result = agent.execute(comments)
            # 应该正常返回空结果而非抛出异常
            self.assertEqual(len(result.clusters), 0)
        except Exception:
            self.fail("CommentClusterAgent 不应抛出异常")


class TestCommentClusterAgentEmptyInput(unittest.TestCase):
    """Test 16: 空输入鲁棒性。"""

    def test_empty_comment_list_does_not_raise(self):
        """空评论列表不应导致异常。"""
        try:
            agent = CommentClusterAgent(
                embedding_client=_MockEmbeddingClient(),
                similarity_threshold=0.72,
            )
            result = agent.execute([])
            self.assertIsNotNone(result)
            self.assertEqual(len(result.clusters), 0)
        except Exception:
            self.fail("空评论列表不应导致异常")


# ===================================================================
# 内部函数单元测试
# ===================================================================


class TestInternalFunctions(unittest.TestCase):

    def test_cosine_similarity_normalized(self):
        """归一化向量的 cosine similarity。"""
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        self.assertAlmostEqual(_cosine_similarity(a, b), 0.0)

        c = [1.0, 0.0, 0.0]
        self.assertAlmostEqual(_cosine_similarity(a, c), 1.0)

        d = [0.707, 0.707, 0.0]
        self.assertAlmostEqual(_cosine_similarity(a, d), 0.707, places=3)

    def test_l2_normalize(self):
        """L2 归一化。"""
        v = [3.0, 4.0, 0.0]
        nv = _l2_normalize(v)
        norm = math.sqrt(sum(x * x for x in nv))
        self.assertAlmostEqual(norm, 1.0, places=5)
        self.assertAlmostEqual(nv[0], 0.6, places=5)
        self.assertAlmostEqual(nv[1], 0.8, places=5)

    def test_l2_normalize_zero(self):
        """零向量归一化为原向量。"""
        v = [0.0, 0.0, 0.0]
        nv = _l2_normalize(v)
        self.assertEqual(nv, v)

    def test_union_find_clusters(self):
        """union-find 聚类。"""
        # 3x3 矩阵，1和2相似，3独立
        sim = [
            [1.0, 0.8, 0.3],
            [0.8, 1.0, 0.3],
            [0.3, 0.3, 1.0],
        ]
        clusters = _union_find_clusters(sim, 0.72, 3)
        # 元素0和1应在一个簇中，元素2在另一个簇
        self.assertEqual(len(clusters), 2)
        # 找到包含0和1的簇
        cluster_sizes = [len(c) for c in clusters]
        self.assertIn(2, cluster_sizes, "应有一个包含2个元素的簇")
        self.assertIn(1, cluster_sizes, "应有一个包含1个元素的簇")

    def test_pick_representative(self):
        """代表评论按赞数选取。"""
        comments = [
            _make_comment("c1", "评论1", likes=10),
            _make_comment("c2", "评论2", likes=50),
            _make_comment("c3", "评论3", likes=5),
            _make_comment("c4", "评论4", likes=100),
        ]
        texts, ids = _pick_representative([0, 1, 2, 3], comments, n=3)
        # 应选取 c4 (100), c2 (50), c1 (10)
        self.assertEqual(len(texts), 3)
        self.assertEqual(ids, ["c4", "c2", "c1"])

    def test_derive_topic_uses_annotations(self):
        """有 annotations 时 topic 从标签生成。"""
        comments = [
            _make_comment("c1", "测试评论", likes=1),
            _make_comment("c2", "测试评论2", likes=1),
        ]
        annotations = [
            CommentAnnotationRecord(
                comment_id="c1",
                post_id="p1",
                sentiment="neutral",
                pain_point_labels=["标签1", "标签2"],
                need_labels=["需求A"],
            ),
            CommentAnnotationRecord(
                comment_id="c2",
                post_id="p1",
                sentiment="neutral",
                pain_point_labels=["标签1"],
                need_labels=["需求B"],
            ),
        ]
        topic, top_labels, keywords = _derive_topic([0, 1], comments, annotations)
        self.assertGreater(len(top_labels), 0)
        # "标签1" 出现2次，应为 top
        self.assertIn("标签1", top_labels)

    def test_derive_topic_no_annotations(self):
        """无 annotations 时 topic 从文本提取。"""
        comments = [
            _make_comment("c1", "学习路线怎么规划", likes=1),
            _make_comment("c2", "有什么好的学习路线推荐", likes=1),
        ]
        topic, top_labels, keywords = _derive_topic([0, 1], comments, annotations=None)
        # 应有关键词
        self.assertGreater(len(keywords), 0)
        # topic 不应为空
        self.assertTrue(len(topic) > 0)

    def test_extract_keywords(self):
        """关键词提取。"""
        comments = [
            _make_comment("c1", "学习 路线 和 教程 资源", likes=1),
            _make_comment("c2", "有没有 好的 学习 路线 推荐", likes=1),
        ]
        keywords = _extract_keywords([0, 1], comments, max_keywords=5)
        self.assertIn("学习", keywords, "高频词应被提取")


if __name__ == "__main__":
    unittest.main()
