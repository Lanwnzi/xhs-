"""
使用 XHS 导入 JSON 数据运行完整 UGC Market Validator 流水线。

本脚本：
  1. 通过 XhsImportAdapter 从 data/raw/xhs_export.json 加载 XHS 数据
  2. 运行完整流水线（collect -> normalize -> analyze -> score -> render_report）
     SourceAgent 自动将原始数据持久化为 data/raw/raw_posts.json / raw_comments.json
  3. 打印各步骤摘要
  4. 调用 scripts/acceptance_check.py 验证 5 个核心产物

用法：
    python scripts/run_xhs_import_pipeline.py

前置条件：
    - data/raw/xhs_export.json 必须存在
    - scripts/acceptance_check.py 必须存在
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys

# ---------------------------------------------------------------------------
# 确保项目根目录在 sys.path 中
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# 导入（在 sys.path 修正之后）
# ---------------------------------------------------------------------------
from src.adapters import XhsImportAdapter
from src.pipeline.pipeline import Pipeline
from src.schemas import AnalysisRequest
from src.utils import get_app_paths

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _print_header(title: str) -> None:
    """打印带分隔线的标题。"""
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def _count_import_data(adapter: XhsImportAdapter) -> tuple[int, int]:
    """统计 adapter 中的原始数据量（用于打印摘要）。"""
    posts = adapter.fetch_posts()
    comments = adapter.fetch_comments()
    return len(posts), len(comments)


def _read_summary_stats() -> dict:
    """读取已生成的 outputs 文件中的统计数据。"""
    stats: dict = {}

    # 读取洞察
    insights_path = os.path.join(_PROJECT_ROOT, "data", "outputs", "insights.json")
    if os.path.exists(insights_path):
        with open(insights_path, encoding="utf-8") as f:
            data = json.load(f)
        stats["pain_points"] = len(data.get("pain_points", []))
        stats["user_needs"] = len(data.get("user_needs", []))
        stats["complaints"] = len(data.get("complaints", []))
        stats["solutions"] = len(data.get("solutions", []))
        stats["market_signals"] = len(data.get("market_signals", []))
        stats["evidence_posts"] = len(data.get("evidence_post_ids", []))
        stats["evidence_comments"] = len(data.get("evidence_comment_ids", []))

    # 读取评分
    scorecard_path = os.path.join(_PROJECT_ROOT, "data", "outputs", "scorecard.json")
    if os.path.exists(scorecard_path):
        with open(scorecard_path, encoding="utf-8") as f:
            data = json.load(f)
        stats["overall_score"] = data.get("overall_score", 0)
        stats["demand_intensity"] = data.get("demand_intensity", 0)
        stats["sentiment_friction"] = data.get("sentiment_friction", 0)
        stats["solution_saturation"] = data.get("solution_saturation", 0)
        stats["purchase_intent"] = data.get("purchase_intent", 0)
        stats["freshness"] = data.get("freshness", 0)

    # 读取标准化数据
    normalized_posts_path = os.path.join(
        _PROJECT_ROOT, "data", "normalized", "normalized_posts.json"
    )
    if os.path.exists(normalized_posts_path):
        with open(normalized_posts_path, encoding="utf-8") as f:
            data = json.load(f)
        stats["normalized_posts"] = len(data)

    normalized_comments_path = os.path.join(
        _PROJECT_ROOT, "data", "normalized", "normalized_comments.json"
    )
    if os.path.exists(normalized_comments_path):
        with open(normalized_comments_path, encoding="utf-8") as f:
            data = json.load(f)
        stats["normalized_comments"] = len(data)

    return stats


def main() -> None:
    """主入口：初始化 -> 运行流水线 -> 验收检查。"""
    # -----------------------------------------------------------------------
    # 步骤 0：初始化
    # -----------------------------------------------------------------------
    _print_header("Step 0/5: 初始化 XHS 导入适配器")

    import_path = os.path.join(get_app_paths().raw_dir, "xhs_export.json")
    if not os.path.exists(import_path):
        print(f"\n错误: 导入文件不存在: {import_path}")
        print("请确保 data/raw/xhs_export.json 存在。")
        sys.exit(1)

    adapter = XhsImportAdapter(import_path)
    post_count, comment_count = _count_import_data(adapter)
    print(f"  导入文件: {import_path}")
    print(f"  导入帖子数: {post_count}")
    print(f"  导入评论数: {comment_count}")

    # -----------------------------------------------------------------------
    # 步骤 1-5：运行完整流水线
    # -----------------------------------------------------------------------
    _print_header("Step 1-5/5: 运行完整流水线")

    pipeline = Pipeline(adapter=adapter)
    request = AnalysisRequest(
        topic="控油洗发水",
        product_direction="针对油性头皮的氨基酸洗发水",
        industry_question="用户对控油洗发水的主要痛点和需求是什么",
    )

    result = pipeline.run(request)

    if not result.success:
        print(f"\n错误: 流水线执行失败")
        print(result.error_message)
        sys.exit(1)

    print(f"  原始数据已由 SourceAgent 持久化到: {result.raw_posts_path}")

    # -----------------------------------------------------------------------
    # 读取产物统计信息
    # -----------------------------------------------------------------------
    stats = _read_summary_stats()

    # -----------------------------------------------------------------------
    # 打印流水线结果摘要
    # -----------------------------------------------------------------------
    _print_header("流水线执行结果摘要")

    print(f"  [采集]")
    print(f"    原始帖子:  {result.raw_posts_path}")

    print(f"  [标准化]")
    print(f"    标准化帖子数:   {stats.get('normalized_posts', 'N/A')}")
    print(f"    标准化评论数:   {stats.get('normalized_comments', 'N/A')}")
    print(f"    标准化帖子:     {result.normalized_posts_path}")
    print(f"    标准化评论:     {result.normalized_comments_path}")

    print(f"  [分析]")
    print(f"    痛点:     {stats.get('pain_points', 'N/A')}")
    print(f"    用户需求: {stats.get('user_needs', 'N/A')}")
    print(f"    投诉:     {stats.get('complaints', 'N/A')}")
    print(f"    解决方案: {stats.get('solutions', 'N/A')}")
    print(f"    市场信号: {stats.get('market_signals', 'N/A')}")
    print(f"    证据帖子: {stats.get('evidence_posts', 'N/A')}")
    print(f"    证据评论: {stats.get('evidence_comments', 'N/A')}")
    print(f"    洞察文件: {result.insights_path}")

    def _fmt(v: object) -> str:
        return f"{v:.2f}" if isinstance(v, (int, float)) else "N/A"

    print(f"  [评分]")
    print(f"    需求强度:       {_fmt(stats.get('demand_intensity'))}")
    print(f"    负面摩擦:       {_fmt(stats.get('sentiment_friction'))}")
    print(f"    方案饱和度:     {_fmt(stats.get('solution_saturation'))}")
    print(f"    购买意向:       {_fmt(stats.get('purchase_intent'))}")
    print(f"    时效性:         {_fmt(stats.get('freshness'))}")
    print(f"    综合评分:       {_fmt(stats.get('overall_score'))}")
    print(f"    评分文件: {result.scorecard_path}")

    print(f"  [报告]")
    print(f"    HTML 报告: {result.report_path}")

    print()
    logger.info("流水线执行完毕，共生成 5 个产物")

    # -----------------------------------------------------------------------
    # 验收检查
    # -----------------------------------------------------------------------
    _print_header("运行验收检查")

    acceptance_script = os.path.join(_PROJECT_ROOT, "scripts", "acceptance_check.py")
    if not os.path.exists(acceptance_script):
        print(f"警告: 找不到验收脚本: {acceptance_script}，跳过验收检查。")
    else:
        proc = subprocess.run(
            [sys.executable, acceptance_script],
            cwd=_PROJECT_ROOT,
            capture_output=False,
        )
        if proc.returncode != 0:
            print(f"\n验收检查失败 (返回码 {proc.returncode})")
            sys.exit(proc.returncode)
        print(f"\n验收检查全部通过。")

    # -----------------------------------------------------------------------
    # 完成
    # -----------------------------------------------------------------------
    print()
    print("=" * 60)
    print("  XHS 导入流水线完成！")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()
