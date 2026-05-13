"""统一持久化模块。

提供所有产物文件的写入操作，供 node 调用。
Agent 和业务函数不直接做文件 I/O。
"""

from __future__ import annotations

import json
import logging
import os

from src.schemas import (
    InsightRecord,
    NormalizedDataset,
    RawDataset,
    ScoreCard,
)
from src.schemas.content_ideation import ContentIdeationResult
from src.utils import AppPaths

logger = logging.getLogger(__name__)


def save_raw_dataset(dataset: RawDataset, paths: AppPaths) -> None:
    """持久化 RawDataset 到 data/raw/。"""
    os.makedirs(paths.raw_dir, exist_ok=True)
    with open(paths.raw_posts_file, "w", encoding="utf-8") as f:
        json.dump([p.model_dump() for p in dataset.posts], f, ensure_ascii=False, indent=2)
    with open(paths.raw_comments_file, "w", encoding="utf-8") as f:
        json.dump([c.model_dump() for c in dataset.comments], f, ensure_ascii=False, indent=2)
    logger.info(
        "persistence: 已保存 raw dataset (%d 帖子, %d 评论) 到 %s",
        len(dataset.posts), len(dataset.comments), paths.raw_dir,
    )


def save_normalized_dataset(dataset: NormalizedDataset, paths: AppPaths) -> None:
    """持久化 NormalizedDataset 到 data/normalized/。"""
    os.makedirs(paths.normalized_dir, exist_ok=True)
    with open(paths.normalized_posts_file, "w", encoding="utf-8") as f:
        json.dump([p.model_dump() for p in dataset.posts], f, ensure_ascii=False, indent=2)
    with open(paths.normalized_comments_file, "w", encoding="utf-8") as f:
        json.dump([c.model_dump() for c in dataset.comments], f, ensure_ascii=False, indent=2)
    logger.info(
        "persistence: 已保存 normalized dataset (%d 帖子, %d 评论) 到 %s",
        len(dataset.posts), len(dataset.comments), paths.normalized_dir,
    )


def save_insights(insight: InsightRecord, paths: AppPaths) -> None:
    """持久化 InsightRecord 到 data/outputs/insights.json。"""
    os.makedirs(paths.outputs_dir, exist_ok=True)
    with open(paths.insights_file, "w", encoding="utf-8") as f:
        json.dump(insight.model_dump(), f, ensure_ascii=False, indent=2)
    logger.info("persistence: 已保存 insights 到 %s", paths.insights_file)


def save_scorecard(scorecard: ScoreCard, paths: AppPaths) -> None:
    """持久化 ScoreCard 到 data/outputs/scorecard.json。"""
    os.makedirs(paths.outputs_dir, exist_ok=True)
    with open(paths.scorecard_file, "w", encoding="utf-8") as f:
        json.dump(scorecard.model_dump(), f, ensure_ascii=False, indent=2)
    logger.info("persistence: 已保存 scorecard 到 %s", paths.scorecard_file)


def save_content_ideation(result: ContentIdeationResult, paths: AppPaths) -> None:
    """持久化 ContentIdeationResult 到 data/outputs/content_ideation.json。"""
    os.makedirs(paths.outputs_dir, exist_ok=True)
    output_path = os.path.join(paths.outputs_dir, "content_ideation.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)
    logger.info("persistence: 已保存 content_ideation 到 %s", output_path)
