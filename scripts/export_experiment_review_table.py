"""
导出实验评估表格。

读取 data/experiments/summary.json 和每个实验的 insights.json / scorecard.json，
生成 docs/experiment_review_results.md。

用法：
    python scripts/export_experiment_review_table.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.utils import get_app_paths


def load_json(path: str) -> dict | list | None:
    """安全加载 JSON 文件。"""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    # 读取 summary.json
    paths = get_app_paths()
    experiments_root = os.path.join(paths.project_root, "data", "experiments")
    summary_path = os.path.join(experiments_root, "summary.json")

    if not os.path.exists(summary_path):
        print(f"错误: 找不到 {summary_path}")
        print("请先运行 python scripts/run_langgraph_experiment_batch.py")
        sys.exit(1)

    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)

    experiments = summary.get("experiments", [])
    if not experiments:
        print("错误: summary.json 中无实验数据")
        sys.exit(1)

    lines = []
    lines.append("# 实验评估结果\n")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    lines.append("## 实验汇总\n")

    # 表头
    headers = [
        "样本", "主题", "帖数", "评数", "痛点", "需求", "投诉", "方案", "信号",
        "证据帖", "证据评", "需求强度", "负面摩擦", "方案饱和", "购买意向",
        "时效性", "综合评分", "报告",
    ]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for exp in experiments:
        sample_name = exp.get("sample_name", "?")
        topic = exp.get("topic", "?")
        post_count = exp.get("post_count", 0)
        comment_count = exp.get("comment_count", 0)

        # 读取每个实验的 insights.json
        output_root = exp.get("output_root", "")
        insights = {}
        if output_root:
            insights_path = os.path.join(output_root, "outputs", "insights.json")
            data = load_json(insights_path)
            if data:
                insights = data

        pain_points_count = len(insights.get("pain_points", []))
        user_needs_count = len(insights.get("user_needs", []))
        complaints_count = len(insights.get("complaints", []))
        solutions_count = len(insights.get("solutions", []))
        market_signals_count = len(insights.get("market_signals", []))
        evidence_posts = len(insights.get("evidence_post_ids", []))
        evidence_comments = len(insights.get("evidence_comment_ids", []))

        # 评分（优先从 summary 内联的 scorecard 读取）
        sc = exp.get("scorecard") or {}
        demand_intensity = sc.get("demand_intensity", "?")
        sentiment_friction = sc.get("sentiment_friction", "?")
        solution_saturation = sc.get("solution_saturation", "?")
        purchase_intent = sc.get("purchase_intent", "?")
        freshness = sc.get("freshness", "?")
        overall_score = sc.get("overall_score", "?")

        def fmt_score(v):
            if isinstance(v, (int, float)):
                return f"{v:.2f}"
            return str(v)

        # report path（取 artifacts 中的）
        artifacts = exp.get("artifacts") or {}
        report_path = artifacts.get("report", "?")

        row = [
            sample_name, topic,
            str(post_count), str(comment_count),
            str(pain_points_count), str(user_needs_count),
            str(complaints_count), str(solutions_count),
            str(market_signals_count),
            str(evidence_posts), str(evidence_comments),
            fmt_score(demand_intensity), fmt_score(sentiment_friction),
            fmt_score(solution_saturation), fmt_score(purchase_intent),
            fmt_score(freshness), fmt_score(overall_score),
            report_path,
        ]
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("## 人工评估\n")

    for exp in experiments:
        sample_name = exp.get("sample_name", "?")
        topic = exp.get("topic", "?")
        lines.append(f"### {sample_name} ({topic})\n")
        lines.append("- [ ] 洞察是否合理：")
        lines.append("- [ ] 评分是否偏高/偏低：")
        lines.append("- 备注：\n")

    lines.append("---\n")
    lines.append("*由 export_experiment_review_table.py 自动生成*\n")

    # 写入
    output_path = os.path.join(paths.project_root, "docs", "experiment_review_results.md")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"已生成: {output_path}")
    print(f"共 {len(experiments)} 个实验")


if __name__ == "__main__":
    main()
