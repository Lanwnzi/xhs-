"""
阈值实验脚本 - CommentClusterAgent 相似度阈值对比实验。

对同一批评论数据，分别在 0.65 / 0.72 / 0.80 三个阈值下运行聚类，
输出对比统计表格，辅助选择最优阈值。

用法：
    python scripts/experiment_comment_cluster_thresholds.py [--data data/demo/...]

默认从 data/outputs/normalized_comments.json 或 data/normalized/normalized_comments.json 读取数据。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Optional

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.agents.comment_cluster_agent import CommentClusterAgent
from src.llm.embedding_client import EmbeddingClient, create_embedding_client_from_env
from src.schemas import CommentRecord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("experiment_comment_cluster_thresholds")


def load_comments(data_path: str) -> list[CommentRecord]:
    """从指定路径加载 normalized_comments.json。"""
    if not os.path.exists(data_path):
        logger.error("文件不存在: %s", data_path)
        return []

    with open(data_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # 兼容 lists 和 objects 两种格式
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("comments", [])
    else:
        logger.error("无法解析 %s: 格式不支持", data_path)
        return []

    # 显式指定驼峰字段映射（CommentRecord 使用 snack_case）
    comments = []
    for item in items:
        try:
            record = CommentRecord(
                platform=item.get("platform", "xhs"),
                comment_id=item.get("comment_id", "") or item.get("commentId", ""),
                post_id=item.get("post_id", "") or item.get("postId", ""),
                content=item.get("content", ""),
                author=item.get("author", ""),
                publish_time=item.get("publish_time", "") or item.get("publishTime", ""),
                likes=item.get("likes", 0),
                parent_comment_id=item.get("parent_comment_id") or item.get("parentCommentId"),
            )
            comments.append(record)
        except Exception as e:
            logger.warning("跳过无法解析的评论: %s", e)

    logger.info("加载 %d 条评论 (来自 %s)", len(comments), data_path)
    return comments


def run_experiment(
    comments: list[CommentRecord],
    thresholds: list[float],
    embedding_client: Optional[EmbeddingClient] = None,
) -> list[dict[str, Any]]:
    """对每个阈值运行聚类，返回对比统计。"""
    results = []

    for threshold in thresholds:
        agent = CommentClusterAgent(
            embedding_client=embedding_client,
            similarity_threshold=threshold,
            min_cluster_size=2,
            top_k=10,
        )
        result = agent.execute(comments)

        cluster_sizes = [c.comment_count for c in result.clusters]
        top_clusters_info = []
        for c in result.clusters[:3]:
            top_clusters_info.append(
                f"  #{c.cluster_id}: {c.topic} (热度={c.hotness:.3f}, {c.comment_count}条)"
            )

        stats = {
            "threshold": threshold,
            "total_comments": result.total_comments,
            "clustered_comments": result.clustered_comments,
            "noise_comments": result.noise_comments,
            "cluster_count": len(result.clusters),
            "avg_cluster_size": (
                sum(cluster_sizes) / len(cluster_sizes) if cluster_sizes else 0
            ),
            "cluster_sizes": cluster_sizes[:5],
            "top_clusters": top_clusters_info,
        }
        results.append(stats)

        logger.info(
            "阈值 %.2f: clusters=%d, clustered=%d, noise=%d, avg_size=%.1f",
            threshold, stats["cluster_count"], stats["clustered_comments"],
            stats["noise_comments"], stats["avg_cluster_size"],
        )

    return results


def print_comparison_table(results: list[dict[str, Any]]) -> None:
    """打印对比表格。"""
    print()
    print("=" * 80)
    print("CommentCluster 阈值实验对比")
    print("=" * 80)
    print(
        f"{'阈值':<8} {'簇数':<8} {'已聚类':<10} {'噪声':<10} {'平均大小':<12} {'前5簇大小':<30}"
    )
    print("-" * 80)

    for r in results:
        sizes_str = ", ".join(str(s) for s in r["cluster_sizes"])
        print(
            f"{r['threshold']:<8.2f} "
            f"{r['cluster_count']:<8} "
            f"{r['clustered_comments']:<10} "
            f"{r['noise_comments']:<10} "
            f"{r['avg_cluster_size']:<12.1f} "
            f"{sizes_str:<30}"
        )

    print("=" * 80)
    print()

    # 打印 top 簇详情
    for r in results:
        print(f"\n阈值 {r['threshold']:.2f} Top 簇:")
        for line in r["top_clusters"]:
            print(line)
    print()


def main() -> None:
    """主入口。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="CommentClusterAgent 阈值实验脚本",
    )
    parser.add_argument(
        "--data",
        default="",
        help="normalized_comments.json 路径",
    )
    args = parser.parse_args()

    # 自动查找数据文件
    data_path = args.data
    if not data_path:
        candidates = [
            os.path.join(_PROJECT_ROOT, "data", "outputs", "normalized_comments.json"),
            os.path.join(_PROJECT_ROOT, "data", "normalized", "normalized_comments.json"),
            os.path.join(_PROJECT_ROOT, "data", "demo", "normalized_comments.json"),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                data_path = candidate
                break

    if not data_path:
        logger.error(
            "未找到评论数据。请指定 --data 路径，或确保以下任一文件存在:\n"
            "  - data/outputs/normalized_comments.json\n"
            "  - data/normalized/normalized_comments.json\n"
            "  - data/demo/normalized_comments.json"
        )
        sys.exit(1)

    comments = load_comments(data_path)
    if not comments:
        logger.error("未加载到有效评论")
        sys.exit(1)

    # 创建 embedding client
    embedding_client = create_embedding_client_from_env()
    if embedding_client is None:
        # 尝试从环境变量手动创建
        base_url = os.getenv("EMBEDDING_BASE_URL", "")
        api_key = os.getenv("EMBEDDING_API_KEY", "")
        model = os.getenv("EMBEDDING_MODEL", "")
        if base_url and api_key and model:
            embedding_client = EmbeddingClient(
                base_url=base_url,
                api_key=api_key,
                model=model,
                timeout=int(os.getenv("EMBEDDING_TIMEOUT", "30")),
            )
        else:
            logger.warning(
                "缺少 embedding 环境变量，将使用 mock 模式（固定向量）"
            )
            # mock: 使用 mock embedding client 测试逻辑
            from tests.test_comment_cluster_agent import _MockEmbeddingClient
            embedding_client = _MockEmbeddingClient()

    thresholds = [0.65, 0.72, 0.80]
    results = run_experiment(comments, thresholds, embedding_client)

    print_comparison_table(results)

    logger.info("实验完成。建议根据业务需求选择最优阈值。")


if __name__ == "__main__":
    main()
