"""
LangGraph 批量实验：扫描 data/imports/xhs_samples/ 下的所有样本，
使用 LangGraph Runtime 对每个样本运行完整流水线。

用法：
    python scripts/run_langgraph_experiment_batch.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.adapters import XhsImportAdapter
from src.graph.graph import build_ugc_market_graph
from src.graph.state import UGCGraphState
from src.llm.client import MockLLMClient, OpenAICompatLLMClient
from src.schemas import AnalysisRequest
from src.utils import AppPaths

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SAMPLES_DIR = os.path.join(_PROJECT_ROOT, "data", "imports", "xhs_samples")
EXPERIMENTS_ROOT = os.path.join(_PROJECT_ROOT, "data", "experiments")


def load_config(sample_dir: str) -> dict[str, Any] | None:
    """读取样本的 config.json。"""
    config_path = os.path.join(sample_dir, "config.json")
    if not os.path.exists(config_path):
        logger.warning("配置文件不存在: %s", config_path)
        return None
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def run_single_experiment(config: dict[str, Any]) -> dict[str, Any]:
    """运行单个实验。"""
    sample_name = config["sample_name"]
    sample_dir = os.path.join(SAMPLES_DIR, sample_name)
    input_file = config.get("input_file", "xhs_export.json")
    source_path = os.path.join(sample_dir, input_file)
    output_root = os.path.join(EXPERIMENTS_ROOT, sample_name)

    logger.info("=" * 60)
    logger.info("开始实验: %s", sample_name)
    logger.info("  主题: %s", config["topic"])
    logger.info("  产品方向: %s", config.get("product_direction", ""))
    logger.info("  输入文件: %s", source_path)

    request = AnalysisRequest(
        topic=config["topic"],
        product_direction=config.get("product_direction", ""),
        industry_question=config.get("industry_question", ""),
    )

    adapter = XhsImportAdapter(source_path=source_path)
    experiment_paths = AppPaths.from_data_root(output_root)

    # 尝试创建 LLM client 用于 ContentIdeationAgent 选题生成
    try:
        llm_client = OpenAICompatLLMClient()
        logger.info("  llm_client=OpenAICompatLLMClient (for content ideation)")
    except RuntimeError:
        logger.warning("  llm_client 不可用，使用 MockLLMClient")
        llm_client = MockLLMClient()

    graph = build_ugc_market_graph(adapter=adapter, llm_client=llm_client)
    state = UGCGraphState(request=request, paths=experiment_paths)

    try:
        result = graph.invoke(state)

        # 读取结果数据
        post_count = 0
        comment_count = 0
        scorecard_data = None
        if os.path.exists(experiment_paths.scorecard_file):
            with open(experiment_paths.scorecard_file, encoding="utf-8") as f:
                scorecard_data = json.load(f)
        if os.path.exists(experiment_paths.raw_posts_file):
            with open(experiment_paths.raw_posts_file, encoding="utf-8") as f:
                post_count = len(json.load(f))
        if os.path.exists(experiment_paths.raw_comments_file):
            with open(experiment_paths.raw_comments_file, encoding="utf-8") as f:
                comment_count = len(json.load(f))

        overall_score = scorecard_data.get("overall_score", 0) if scorecard_data else 0
        logger.info("实验 %s 完成: posts=%d, comments=%d, score=%.4f",
                    sample_name, post_count, comment_count, overall_score)

        return {
            "sample_name": sample_name,
            "topic": config["topic"],
            "product_direction": config.get("product_direction", ""),
            "industry_question": config.get("industry_question", ""),
            "input_file": source_path,
            "output_root": output_root,
            "success": True,
            "post_count": post_count,
            "comment_count": comment_count,
            "overall_score": overall_score,
            "scorecard": scorecard_data,
            "artifacts": {
                "raw_posts": experiment_paths.raw_posts_file,
                "raw_comments": experiment_paths.raw_comments_file,
                "normalized_posts": experiment_paths.normalized_posts_file,
                "normalized_comments": experiment_paths.normalized_comments_file,
                "insights": experiment_paths.insights_file,
                "scorecard": experiment_paths.scorecard_file,
                "report": experiment_paths.report_file,
            },
            "error": None,
        }

    except Exception as e:
        logger.error("实验 %s 失败: %s", sample_name, e, exc_info=True)
        return {
            "sample_name": sample_name,
            "topic": config["topic"],
            "product_direction": config.get("product_direction", ""),
            "industry_question": config.get("industry_question", ""),
            "input_file": source_path,
            "output_root": output_root,
            "success": False,
            "post_count": 0,
            "comment_count": 0,
            "overall_score": 0,
            "scorecard": None,
            "artifacts": {},
            "error": str(e),
        }


def main():
    logger.info("=" * 60)
    logger.info("LangGraph 批量实验开始")
    logger.info("=" * 60)

    if not os.path.isdir(SAMPLES_DIR):
        logger.error("样本目录不存在: %s", SAMPLES_DIR)
        sys.exit(1)

    sample_dirs = sorted([
        d for d in os.listdir(SAMPLES_DIR)
        if os.path.isdir(os.path.join(SAMPLES_DIR, d))
    ])

    configs = []
    for sample_name in sample_dirs:
        sample_dir = os.path.join(SAMPLES_DIR, sample_name)
        cfg = load_config(sample_dir)
        if cfg is not None:
            configs.append(cfg)
        else:
            logger.warning("跳过 %s: 无有效 config.json", sample_name)

    logger.info("找到 %d 个有效样本", len(configs))

    results = []
    for cfg in configs:
        result = run_single_experiment(cfg)
        results.append(result)

    # 生成 summary.json
    success_count = sum(1 for r in results if r["success"])
    failed_count = sum(1 for r in results if not r["success"])

    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "experiment_count": len(results),
        "success_count": success_count,
        "failed_count": failed_count,
        "experiments": results,
    }

    os.makedirs(EXPERIMENTS_ROOT, exist_ok=True)
    summary_path = os.path.join(EXPERIMENTS_ROOT, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info("汇总已写入: %s", summary_path)

    print(f"\n共 {len(results)} 个实验, {success_count} 成功, {failed_count} 失败")
    for r in results:
        status = "OK" if r["success"] else "FAIL"
        print(f"  [{status}] {r['sample_name']}: overall_score={r['overall_score']:.4f}")

    if failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
