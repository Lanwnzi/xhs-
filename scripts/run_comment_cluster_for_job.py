#!/usr/bin/env python
"""手动补跑评论聚类脚本。

用法:
    python scripts/run_comment_cluster_for_job.py --job-id <job_id>
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from src.agents.comment_cluster_agent import CommentClusterAgent
from src.api.jobs import get_job
from src.llm.embedding_client import create_embedding_client_from_env
from src.schemas.records import CommentRecord
from src.utils import AppPaths

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="手动补跑评论聚类")
    parser.add_argument("--job-id", required=True, help="job_id")
    args = parser.parse_args()

    job = get_job(args.job_id)
    if not job:
        logger.error("job 不存在: %s", args.job_id)
        sys.exit(1)

    logger.info("job found: keyword=%s, data_root=%s", job.keyword, job.data_root)

    paths = AppPaths.from_data_root(job.data_root)

    # 读取 normalized comments
    if not os.path.exists(paths.normalized_comments_file):
        logger.error("normalized_comments 文件不存在: %s", paths.normalized_comments_file)
        sys.exit(1)

    with open(paths.normalized_comments_file, encoding="utf-8") as f:
        comments_data = json.load(f)

    # 读取 annotations（如果存在）
    annotations = None
    annotations_path = os.path.join(paths.outputs_dir, "comment_annotations.json")
    if os.path.exists(annotations_path):
        with open(annotations_path, encoding="utf-8") as f:
            annotations = json.load(f)

    embedding_client = create_embedding_client_from_env()
    agent = CommentClusterAgent(embedding_client=embedding_client)

    comments = [
        CommentRecord(**c)
        for c in (
            comments_data
            if isinstance(comments_data, list)
            else comments_data.get("comments", [])
        )
    ]

    result = agent.execute_and_persist(paths, comments)

    logger.info(
        "聚类完成: total=%d, clusters=%d, noise=%d",
        result.total_comments,
        len(result.clusters),
        result.noise_comments,
    )
    logger.info("输出: %s", paths.comment_clusters_file)

    if result.clusters:
        print(f"\n聚类结果: {len(result.clusters)} 个簇")
        for i, c in enumerate(result.clusters, 1):
            print(
                f"  #{i}: {c.topic} "
                f"(热度={c.hotness:.4f}, "
                f"评论={c.comment_count}, "
                f"标签={c.top_labels})"
            )
    else:
        reason = result.skipped_reason or "无聚类结果"
        print(f"\n聚类跳过: {reason}")


if __name__ == "__main__":
    main()
