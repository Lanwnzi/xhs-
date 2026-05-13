"""Tests for scripts/run_langgraph_experiment_batch.py - LangGraph 批量实验入口。

测试内容：
  1. load_config 能正确读取样本 config.json
  2. 从 config 能构造 AnalysisRequest
  3. 能构造 experiment_paths
  4. 运行至少 1 个样本实验（隔离临时目录）
  5. summary.json 能生成
  6. summary.json 包含 scorecard 和 artifacts
  7. 导入 run_langgraph_experiment_batch 不破坏默认 Pipeline / LangGraph 入口
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.graph.graph import build_ugc_market_graph
from src.graph.state import UGCGraphState
from src.schemas import AnalysisRequest
from src.utils import AppPaths

# ---------------------------------------------------------------------------
# Mock 数据
# ---------------------------------------------------------------------------

_MOCK_SAMPLE = {
    "posts": [
        {
            "note_id": "test_p_001",
            "title": "测试帖",
            "desc": "这个产品真的很好用，控油效果不错",
            "create_time": 1710748800,
            "liked_count": 100,
            "comment_count": 10,
            "nickname": "测试用户",
            "tag_list": ["测试"],
        }
    ],
    "comments": [
        {
            "id": "test_c_001",
            "note_id": "test_p_001",
            "content": "真的很好用，推荐",
            "create_time": 1710777600,
            "like_count": 5,
            "nickname": "评论用户",
        }
    ],
}

_MOCK_CONFIG = {
    "sample_name": "test_sample",
    "topic": "测试",
    "product_direction": "测试产品方向",
    "industry_question": "测试行业问题",
    "input_file": "xhs_export.json",
}


def _create_mock_sample_dir(tmp_dir: str) -> str:
    """在临时目录中创建 mock 样本目录，返回 sample_dir 路径。"""
    sample_dir = os.path.join(tmp_dir, "test_sample")
    os.makedirs(sample_dir, exist_ok=True)

    # 写配置
    config_path = os.path.join(sample_dir, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(_MOCK_CONFIG, f, ensure_ascii=False, indent=2)

    # 写数据
    data_path = os.path.join(sample_dir, "xhs_export.json")
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(_MOCK_SAMPLE, f, ensure_ascii=False, indent=2)

    return sample_dir


# ---------------------------------------------------------------------------
# 测试类
# ---------------------------------------------------------------------------


class TestLoadConfig(unittest.TestCase):
    """T4-C1: load_config 行为测试。"""

    def test_load_config_reads_correctly(self):
        """load_config 能正确读取样本的 config.json。"""
        from scripts.run_langgraph_experiment_batch import load_config

        with tempfile.TemporaryDirectory(prefix="ugc_test_") as tmp_dir:
            _create_mock_sample_dir(tmp_dir)
            sample_path = os.path.join(tmp_dir, "test_sample")
            cfg = load_config(sample_path)
            self.assertIsNotNone(cfg)
            self.assertEqual(cfg["sample_name"], "test_sample")
            self.assertEqual(cfg["topic"], "测试")
            self.assertEqual(cfg["product_direction"], "测试产品方向")
            self.assertEqual(cfg["industry_question"], "测试行业问题")

    def test_load_config_missing_returns_none(self):
        """config.json 不存在时 load_config 返回 None。"""
        from scripts.run_langgraph_experiment_batch import load_config

        with tempfile.TemporaryDirectory(prefix="ugc_test_") as tmp_dir:
            cfg = load_config(tmp_dir)
            self.assertIsNone(cfg)


class TestAnalysisRequestConstruction(unittest.TestCase):
    """T4-C2: 从 config 构造 AnalysisRequest。"""

    def test_construct_from_config(self):
        """从 config 能构造 AnalysisRequest。"""
        cfg = _MOCK_CONFIG
        request = AnalysisRequest(
            topic=cfg["topic"],
            product_direction=cfg["product_direction"],
            industry_question=cfg.get("industry_question", ""),
        )
        self.assertEqual(request.topic, "测试")
        self.assertEqual(request.product_direction, "测试产品方向")
        self.assertEqual(request.industry_question, "测试行业问题")


class TestExperimentPaths(unittest.TestCase):
    """T4-C3: experiment_paths 构造测试。"""

    def test_construct_experiment_paths(self):
        """能正确构造 experiment_paths。"""
        with tempfile.TemporaryDirectory(prefix="ugc_test_") as tmp_dir:
            paths = AppPaths.from_data_root(tmp_dir)
            self.assertTrue(paths.raw_dir.startswith(tmp_dir))
            self.assertTrue(paths.normalized_dir.startswith(tmp_dir))
            self.assertTrue(paths.outputs_dir.startswith(tmp_dir))
            self.assertTrue(paths.raw_posts_file.startswith(paths.raw_dir))
            self.assertTrue(paths.normalized_posts_file.startswith(paths.normalized_dir))
            self.assertTrue(paths.scorecard_file.startswith(paths.outputs_dir))


class TestRunSingleExperiment(unittest.TestCase):
    """T4-C4: 运行单个样本实验（隔离临时目录）。"""

    def test_run_single_experiment_with_mock_data(self):
        """在隔离临时目录中使用 mock 数据运行 run_single_experiment。"""
        from scripts.run_langgraph_experiment_batch import run_single_experiment
        import scripts.run_langgraph_experiment_batch as batch_module

        with tempfile.TemporaryDirectory(prefix="ugc_test_") as tmp_dir:
            _create_mock_sample_dir(tmp_dir)

            # 临时替换模块级路径常量，指向隔离目录
            orig_samples = batch_module.SAMPLES_DIR
            orig_experiments = batch_module.EXPERIMENTS_ROOT
            batch_module.SAMPLES_DIR = tmp_dir
            batch_module.EXPERIMENTS_ROOT = os.path.join(tmp_dir, "experiments")

            try:
                cfg = _MOCK_CONFIG.copy()
                result = run_single_experiment(cfg)

                self.assertTrue(result["success"], f"实验应成功: {result.get('error')}")
                self.assertEqual(result["sample_name"], "test_sample")
                self.assertIsNotNone(result["scorecard"])
                self.assertIn("overall_score", result["scorecard"])
                self.assertIn("artifacts", result)
                self.assertIn("raw_posts", result["artifacts"])
                self.assertIn("scorecard", result["artifacts"])
                self.assertIn("report", result["artifacts"])
                self.assertIsNone(result["error"])
            finally:
                batch_module.SAMPLES_DIR = orig_samples
                batch_module.EXPERIMENTS_ROOT = orig_experiments


class TestSummaryGeneration(unittest.TestCase):
    """T4-C5/C6: summary.json 生成验证。"""

    def test_summary_json_contains_scorecard_and_artifacts(self):
        """summary.json 包含 scorecard 和 artifacts。"""
        from scripts.run_langgraph_experiment_batch import run_single_experiment
        import scripts.run_langgraph_experiment_batch as batch_module

        with tempfile.TemporaryDirectory(prefix="ugc_test_") as tmp_dir:
            _create_mock_sample_dir(tmp_dir)

            orig_samples = batch_module.SAMPLES_DIR
            orig_experiments = batch_module.EXPERIMENTS_ROOT
            batch_module.SAMPLES_DIR = tmp_dir
            batch_module.EXPERIMENTS_ROOT = os.path.join(tmp_dir, "experiments")

            try:
                cfg = _MOCK_CONFIG.copy()
                result = run_single_experiment(cfg)

                # 构造并写入 summary.json
                summary = {
                    "generated_at": "2026-04-30T12:00:00",
                    "experiment_count": 1,
                    "success_count": 1 if result["success"] else 0,
                    "failed_count": 0 if result["success"] else 1,
                    "experiments": [result],
                }

                os.makedirs(batch_module.EXPERIMENTS_ROOT, exist_ok=True)
                summary_path = os.path.join(batch_module.EXPERIMENTS_ROOT, "summary.json")
                with open(summary_path, "w", encoding="utf-8") as f:
                    json.dump(summary, f, ensure_ascii=False, indent=2)

                # 验证文件存在
                self.assertTrue(os.path.exists(summary_path))

                # 重新读取验证
                with open(summary_path, encoding="utf-8") as f:
                    loaded = json.load(f)

                self.assertEqual(loaded["experiment_count"], 1)
                self.assertEqual(loaded["success_count"], 1)

                exp = loaded["experiments"][0]
                self.assertIn("scorecard", exp)
                self.assertIn("artifacts", exp)
                self.assertIn("overall_score", exp.get("scorecard", {}))
                self.assertIn("raw_posts", exp.get("artifacts", {}))
                self.assertIn("scorecard", exp.get("artifacts", {}))
                self.assertIn("report", exp.get("artifacts", {}))
            finally:
                batch_module.SAMPLES_DIR = orig_samples
                batch_module.EXPERIMENTS_ROOT = orig_experiments

    def test_summary_with_failure_has_error_field(self):
        """失败实验的 summary 条目包含 error 字段。"""
        from scripts.run_langgraph_experiment_batch import run_single_experiment
        import scripts.run_langgraph_experiment_batch as batch_module

        with tempfile.TemporaryDirectory(prefix="ugc_test_") as tmp_dir:
            orig_samples = batch_module.SAMPLES_DIR
            orig_experiments = batch_module.EXPERIMENTS_ROOT
            batch_module.SAMPLES_DIR = tmp_dir
            batch_module.EXPERIMENTS_ROOT = os.path.join(tmp_dir, "experiments")

            try:
                # 传一个不存在的 input_file，预期失败
                bad_config = _MOCK_CONFIG.copy()
                bad_config["input_file"] = "nonexistent.json"
                result = run_single_experiment(bad_config)

                self.assertFalse(result["success"])
                self.assertIsNotNone(result["error"])
                self.assertIn("error", result)
            finally:
                batch_module.SAMPLES_DIR = orig_samples
                batch_module.EXPERIMENTS_ROOT = orig_experiments


class TestPipelineNotBroken(unittest.TestCase):
    """T4-C7: 默认 Pipeline / LangGraph 入口未被破坏。"""

    def test_graph_still_compiles(self):
        """验证 graph 仍然可以 compile。"""
        graph = build_ugc_market_graph()
        self.assertIsNotNone(graph)

    def test_graph_has_all_expected_nodes(self):
        """验证 graph 包含 6 个预期节点。"""
        graph = build_ugc_market_graph()
        expected = {"collect", "normalize", "sentiment", "insight", "score", "report"}
        actual = set(graph.nodes.keys())
        for name in expected:
            self.assertIn(name, actual, f"缺少节点: {name}")

    def test_can_construct_state(self):
        """验证可以构造 UGCGraphState。"""
        request = AnalysisRequest(
            topic="测试",
            product_direction="测试产品",
            industry_question="测试问题",
        )
        paths = AppPaths.from_data_root(tempfile.mkdtemp(prefix="ugc_test_"))
        state = UGCGraphState(request=request, paths=paths)
        self.assertIsNotNone(state)
        self.assertEqual(state.request.topic, "测试")
        self.assertEqual(state.success, False)


if __name__ == "__main__":
    unittest.main()
