"""
UGC Market Validator 的验收检查脚本。

验证 5 个核心产物是否存在、能否通过 Pydantic 模型校验，
以及是否包含必需的字段和证据链。

用法：
    python scripts/acceptance_check.py
    python scripts/acceptance_check.py --data-root data/experiments/oil_control_shampoo
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

# 确保项目根目录在 sys.path 中，以便 src 导入能够正常工作。
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# 导入（在 sys.path 修正之后）
# ---------------------------------------------------------------------------

from pydantic import ValidationError

from src.schemas import (
    CommentRecord,
    InsightRecord,
    PostRecord,
    ScoreCard,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"

DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
NORMALIZED_DIR = os.path.join(DATA_DIR, "normalized")
OUTPUTS_DIR = os.path.join(DATA_DIR, "outputs")

CORE_ARTIFACTS = [
    ("原始帖子", os.path.join(RAW_DIR, "raw_posts.json")),
    ("标准化帖子", os.path.join(NORMALIZED_DIR, "normalized_posts.json")),
    ("洞察结果", os.path.join(OUTPUTS_DIR, "insights.json")),
    ("评分结果", os.path.join(OUTPUTS_DIR, "scorecard.json")),
    ("HTML报告", os.path.join(OUTPUTS_DIR, "report.html")),
]

EVIDENCE_ARTIFACTS = [
    ("原始评论", os.path.join(RAW_DIR, "raw_comments.json")),
    ("标准化评论", os.path.join(NORMALIZED_DIR, "normalized_comments.json")),
]

# report.html 中必需的 12 个章节
REQUIRED_SECTIONS = [
    "采集概览",
    "评论区讨论摘要",
    "用户核心关注点",
    "用户高频疑问",
    "高互动内容信号",
    "正负向反馈总结",
    "购买",
    "关键词相关内容选题建议",
    "热点选题与文案定制建议",
    "代表评论证据",
    "内容选题价值评分",
    "数据局限说明",
]

# 灵活章节关键字匹配：每个章节可对应多个可能的子串
SECTION_KEYWORDS: dict[str, list[str]] = {
    "采集概览": ["采集概览"],
    "评论区讨论摘要": ["评论区讨论摘要", "讨论摘要"],
    "用户核心关注点": ["用户核心关注点", "核心关注点"],
    "用户高频疑问": ["用户高频疑问", "高频疑问"],
    "高互动内容信号": ["高互动内容信号", "互动内容信号"],
    "正负向反馈总结": ["正负向反馈总结", "反馈总结"],
    "购买": ["购买", "行动信号"],
    "关键词相关内容选题建议": ["关键词相关内容选题建议", "内容选题建议"],
    "热点选题与文案定制建议": ["热点选题与文案定制建议", "文案定制建议", "热点选题"],
    "代表评论证据": ["代表评论证据", "评论证据"],
    "内容选题价值评分": ["内容选题价值评分", "选题价值评分"],
    "数据局限说明": ["数据局限说明", "局限说明"],
}


# ---------------------------------------------------------------------------
# 路径构建
# ---------------------------------------------------------------------------


def _build_artifact_paths(
    data_root: Optional[str] = None,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], str, str, str]:
    """构建产物文件路径列表。

    参数:
        data_root: 自定义数据根目录（相对于项目根目录），为 None 时使用默认 data/。

    返回:
        (core_artifacts, evidence_artifacts, raw_dir, normalized_dir, outputs_dir)
    """
    if data_root is None:
        return CORE_ARTIFACTS, EVIDENCE_ARTIFACTS, RAW_DIR, NORMALIZED_DIR, OUTPUTS_DIR

    root = os.path.join(_PROJECT_ROOT, data_root)
    raw_dir = os.path.join(root, "raw")
    normalized_dir = os.path.join(root, "normalized")
    outputs_dir = os.path.join(root, "outputs")

    core = [
        ("原始帖子", os.path.join(raw_dir, "raw_posts.json")),
        ("标准化帖子", os.path.join(normalized_dir, "normalized_posts.json")),
        ("洞察结果", os.path.join(outputs_dir, "insights.json")),
        ("评分结果", os.path.join(outputs_dir, "scorecard.json")),
        ("HTML报告", os.path.join(outputs_dir, "report.html")),
    ]
    evidence = [
        ("原始评论", os.path.join(raw_dir, "raw_comments.json")),
        ("标准化评论", os.path.join(normalized_dir, "normalized_comments.json")),
    ]
    return core, evidence, raw_dir, normalized_dir, outputs_dir


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def check(
    name: str, passed: bool, details: str = ""
) -> tuple[int, int]:
    """打印检查结果并返回（通过数, 失败数）。"""
    tag = PASS if passed else FAIL
    msg = f"[{tag}] {name}"
    if details and not passed:
        msg += f"  -- {details}"
    print(msg)
    return (1, 0) if passed else (0, 1)


def file_exists(path: str) -> bool:
    """检查文件是否存在于磁盘上。"""
    return os.path.isfile(path)


def load_json(path: str) -> list[Any] | dict[str, Any]:
    """加载并解析 JSON 文件。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 检查函数
# ---------------------------------------------------------------------------


def check_core_artifacts_exist(
    data_root: Optional[str] = None,
) -> tuple[int, int]:
    """C1: 检查所有 5 个核心产物是否存在。"""
    total_pass = 0
    total_fail = 0
    core_artifacts, _, _, _, _ = _build_artifact_paths(data_root)
    print("\n--- C1: 核心产物文件存在性 ---")
    for name, path in core_artifacts:
        p, f = check(name, file_exists(path))
        total_pass += p
        total_fail += f
    return total_pass, total_fail


def check_evidence_artifacts_exist(
    data_root: Optional[str] = None,
) -> tuple[int, int]:
    """C2: 检查证据链文件是否存在。"""
    total_pass = 0
    total_fail = 0
    _, evidence_artifacts, _, _, _ = _build_artifact_paths(data_root)
    print("\n--- C2: 证据链文件存在性 ---")
    for name, path in evidence_artifacts:
        p, f = check(name, file_exists(path))
        total_pass += p
        total_fail += f
    return total_pass, total_fail


def check_normalized_posts_schema(
    data_root: Optional[str] = None,
) -> tuple[int, int]:
    """C3a: 用 PostRecord 校验 normalized_posts.json。"""
    total_pass = 0
    total_fail = 0
    _, _, _, normalized_dir, _ = _build_artifact_paths(data_root)
    print("\n--- C3a: 标准化帖子 Pydantic 校验 ---")
    path = os.path.join(normalized_dir, "normalized_posts.json")
    if not file_exists(path):
        return check("normalized_posts.json 不存在", False)
    try:
        data = load_json(path)
        if not isinstance(data, list):
            return check("normalized_posts.json 必须是数组", False)
        if not data:
            return check("normalized_posts.json 不能为空", False)
        for i, item in enumerate(data):
            try:
                PostRecord(**item)
            except ValidationError as e:
                return check(f"normalized_posts.json[{i}] 校验失败", False, str(e))
        return check(f"normalized_posts.json ({len(data)} 条记录)", True)
    except Exception as e:
        return check("normalized_posts.json 读取失败", False, str(e))


def check_normalized_comments_schema(
    data_root: Optional[str] = None,
) -> tuple[int, int]:
    """C3b: 用 CommentRecord 校验 normalized_comments.json。"""
    total_pass = 0
    total_fail = 0
    _, _, _, normalized_dir, _ = _build_artifact_paths(data_root)
    print("\n--- C3b: 标准化评论 Pydantic 校验 ---")
    path = os.path.join(normalized_dir, "normalized_comments.json")
    if not file_exists(path):
        return check("normalized_comments.json 不存在", False)
    try:
        data = load_json(path)
        if not isinstance(data, list):
            return check("normalized_comments.json 必须是数组", False)
        if not data:
            return check("normalized_comments.json 不能为空", False)
        for i, item in enumerate(data):
            try:
                CommentRecord(**item)
            except ValidationError as e:
                return check(f"normalized_comments.json[{i}] 校验失败", False, str(e))
        return check(f"normalized_comments.json ({len(data)} 条记录)", True)
    except Exception as e:
        return check("normalized_comments.json 读取失败", False, str(e))


def check_insights_schema(
    data_root: Optional[str] = None,
) -> tuple[int, int]:
    """C3c: 用 InsightRecord 校验 insights.json。"""
    total_pass = 0
    total_fail = 0
    _, _, _, _, outputs_dir = _build_artifact_paths(data_root)
    print("\n--- C3c: 洞察结果 Pydantic 校验 ---")
    path = os.path.join(outputs_dir, "insights.json")
    if not file_exists(path):
        return check("insights.json 不存在", False)
    try:
        data = load_json(path)
        if not isinstance(data, dict):
            return check("insights.json 必须是对象", False)
        InsightRecord(**data)
        # 检查证据链
        insight = InsightRecord(**data)
        has_evidence = bool(insight.evidence_post_ids) or bool(insight.evidence_comment_ids)
        if not has_evidence:
            return check("insights.json 证据链检查", False, "evidence_post_ids 和 evidence_comment_ids 均为空")
        return check("insights.json (含证据链)", True)
    except ValidationError as e:
        return check("insights.json 校验失败", False, str(e))
    except Exception as e:
        return check("insights.json 读取失败", False, str(e))


def check_evidence_reverse_traceability(
    data_root: Optional[str] = None,
) -> tuple[int, int]:
    """C3d: 证据反向可追溯性检查。

    只在使用 --data-root 时执行增强检查。
    验证 evidence_post_ids 在 normalized_posts.json 中存在，
    并且 evidence_comment_ids 在 normalized_comments.json 中存在。
    """
    total_pass = 0
    total_fail = 0
    _, _, _, normalized_dir, outputs_dir = _build_artifact_paths(data_root)
    print("\n--- C3d: 证据反向可追溯性检查 ---")

    insights_path = os.path.join(outputs_dir, "insights.json")
    if not file_exists(insights_path):
        return check("evidence 可追溯性", False, "insights.json 不存在")

    try:
        insights = load_json(insights_path)
        if not isinstance(insights, dict):
            return check("evidence 可追溯性", False, "insights.json 不是对象")

        ev_post_ids: list[str] = insights.get("evidence_post_ids", [])
        ev_comment_ids: list[str] = insights.get("evidence_comment_ids", [])

        if not ev_post_ids and not ev_comment_ids:
            return check(
                "evidence 可追溯性",
                False,
                "evidence_post_ids 和 evidence_comment_ids 均为空，无法追溯",
            )

        # 加载 normalized_posts.json
        norm_posts_path = os.path.join(normalized_dir, "normalized_posts.json")
        if not file_exists(norm_posts_path):
            return check("evidence 可追溯性", False, "normalized_posts.json 不存在")

        norm_comments_path = os.path.join(normalized_dir, "normalized_comments.json")
        if not file_exists(norm_comments_path):
            return check("evidence 可追溯性", False, "normalized_comments.json 不存在")

        norm_posts = load_json(norm_posts_path)
        norm_comments = load_json(norm_comments_path)

        post_ids_set = set()
        for p in norm_posts:
            pid = p.get("post_id", "")
            if pid:
                post_ids_set.add(pid)

        comment_ids_set = set()
        for c in norm_comments:
            cid = c.get("comment_id", "")
            if cid:
                comment_ids_set.add(cid)

        missing_post_ids = [eid for eid in ev_post_ids if eid not in post_ids_set]
        missing_comment_ids = [eid for eid in ev_comment_ids if eid not in comment_ids_set]

        if missing_post_ids:
            return check(
                "evidence_post_ids 可追溯",
                False,
                f"以下证据 post_id 在 normalized_posts.json 中不存在: {missing_post_ids}",
            )

        if missing_comment_ids:
            return check(
                "evidence_comment_ids 可追溯",
                False,
                f"以下证据 comment_id 在 normalized_comments.json 中不存在: {missing_comment_ids}",
            )

        return check(
            f"evidence 可追溯性 (帖子 {len(ev_post_ids)} 条, 评论 {len(ev_comment_ids)} 条)",
            True,
        )

    except Exception as e:
        return check("evidence 可追溯性", False, str(e))


def check_scorecard_schema(
    data_root: Optional[str] = None,
) -> tuple[int, int]:
    """C4: 用 ScoreCard 校验 scorecard.json。"""
    total_pass = 0
    total_fail = 0
    _, _, _, _, outputs_dir = _build_artifact_paths(data_root)
    print("\n--- C4: 评分结果 Pydantic 校验 ---")
    path = os.path.join(outputs_dir, "scorecard.json")
    if not file_exists(path):
        return check("scorecard.json 不存在", False)
    try:
        data = load_json(path)
        if not isinstance(data, dict):
            return check("scorecard.json 必须是对象", False)
        scorecard = ScoreCard(**data)

        # 检查所有 6 个维度字段是否存在
        required_fields = [
            "demand_intensity",
            "sentiment_friction",
            "solution_saturation",
            "purchase_intent",
            "freshness",
            "overall_score",
        ]
        missing = [f for f in required_fields if f not in data]
        if missing:
            return check("scorecard.json 字段完整性", False, f"缺少字段: {', '.join(missing)}")

        # 检查 scoring_reason 不为空
        if not scorecard.scoring_reason or not scorecard.scoring_reason.strip():
            return check("scorecard.json scoring_reason", False, "scoring_reason 为空字符串")

        return check("scorecard.json (含打分理由)", True)
    except ValidationError as e:
        return check("scorecard.json 校验失败", False, str(e))
    except Exception as e:
        return check("scorecard.json 读取失败", False, str(e))


def check_report_html(
    data_root: Optional[str] = None,
) -> tuple[int, int]:
    """C5: 检查 report.html 是否存在且包含全部 10 个必需章节。"""
    total_pass = 0
    total_fail = 0
    _, _, _, _, outputs_dir = _build_artifact_paths(data_root)
    print("\n--- C5: HTML 报告完整性 ---")
    path = os.path.join(outputs_dir, "report.html")
    if not file_exists(path):
        return check("report.html 不存在", False)
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()

        if not content.strip():
            return check("report.html 内容为空", False)

        # 检查文件大小是否合理（> 1KB）
        size = len(content.encode("utf-8"))
        if size < 1024:
            return check("report.html 文件大小", False, f"仅 {size} 字节，可能内容不全")

        # 检查 12 个必需章节（使用灵活的关键字匹配）
        missing_sections = []
        for section in REQUIRED_SECTIONS:
            keywords = SECTION_KEYWORDS.get(section, [section])
            if not any(kw in content for kw in keywords):
                missing_sections.append(section)

        if missing_sections:
            return check(f"report.html 必需章节检查", False, f"缺少章节: {', '.join(missing_sections)}")

        total_required = len(REQUIRED_SECTIONS)
        p, f = check(f"report.html ({size // 1024}KB, {total_required}/{total_required} 章节)", True)

        # 额外检查：HTML 结构
        html_checks = [
            ("<!DOCTYPE html>", "DOCTYPE"),
            ("<html", "<html> 标签"),
            ("</html>", "</html> 标签"),
            ("<head>", "<head> 标签"),
            ("<body", "<body> 标签"),
        ]
        for keyword, label in html_checks:
            if keyword not in content:
                p2, f2 = check(f"report.html 结构: {label}", False)
                p += p2
                f += f2
            else:
                p2, f2 = check(f"report.html 结构: {label}", True)
                p += p2
                f += f2

        return p, f
    except Exception as e:
        return check("report.html 读取失败", False, str(e))


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------


def check_report_quality_review(
    data_root: Optional[str] = None,
) -> tuple[int, int]:
    """C6: 检查报告质量评审文件是否存在且通过校验。"""
    total_pass = 0
    total_fail = 0
    _, _, _, _, outputs_dir = _build_artifact_paths(data_root)
    print("\n--- C6: 报告质量评审文件 ---")
    path = os.path.join(outputs_dir, "report_quality_review.json")
    if not os.path.exists(path):
        return check("report_quality_review.json 不存在", False)

    try:
        from src.schemas.report_review import ReportQualityReview
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        ReportQualityReview(**data)
        # 验证必要字段
        required = {"passed", "reasons", "hard_fail_reasons", "revision_instructions", "summary"}
        actual = set(data.keys())
        missing = required - actual
        if missing:
            return check("报告质量评审字段完整性", False, f"缺少字段: {missing}")
        return check("报告质量评审文件校验通过", True)
    except Exception as e:
        return check("报告质量评审文件校验失败", False, str(e))


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="UGC Market Validator 验收检查脚本"
    )
    parser.add_argument(
        "--data-root",
        default=None,
        help="自定义数据根目录（相对于项目根目录），如 data/experiments/oil_control_shampoo",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------


def main() -> None:
    """运行所有验收检查并打印摘要。"""
    args = parse_args()
    data_root: Optional[str] = args.data_root

    total_pass = 0
    total_fail = 0

    checks = [
        lambda dr=data_root: check_core_artifacts_exist(dr),
        lambda dr=data_root: check_evidence_artifacts_exist(dr),
        lambda dr=data_root: check_normalized_posts_schema(dr),
        lambda dr=data_root: check_normalized_comments_schema(dr),
        lambda dr=data_root: check_insights_schema(dr),
    ]

    # 当指定 --data-root 时，执行增强的 evidence 反向可追溯性检查
    if data_root is not None:
        checks.append(lambda dr=data_root: check_evidence_reverse_traceability(dr))

    checks.extend([
        lambda dr=data_root: check_scorecard_schema(dr),
        lambda dr=data_root: check_report_html(dr),
        lambda dr=data_root: check_report_quality_review(dr),
    ])

    for check_fn in checks:
        p, f = check_fn()
        total_pass += p
        total_fail += f

    print(f"\n结果: {total_pass}/{total_pass + total_fail} 通过")
    if total_fail == 0:
        print("验收通过!")
    else:
        print(f"验收失败: {total_fail} 项未通过")
        sys.exit(1)


if __name__ == "__main__":
    main()
