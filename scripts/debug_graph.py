"""
独立调试脚本：跳过 FastAPI，直接执行 LangGraph 工作流。

用法：
    python scripts/debug_graph.py

断点位置：
    BP1: graph.invoke() 之前 —— 验证组装
    BP2: graph.invoke() 之后 —— 检查产物
    BP3: 各节点内部的 logger 输出 —— 追踪执行顺序

LLM 调用全部使用 MockLLMClient，不需要真实 API key。
通过 XhsPlaywrightAdapter 采集小红书真实数据（非 headless 模式会打开浏览器）。
"""

import logging
import sys
import os

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 配置日志 —— 打印所有节点日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

from src.graph.graph import build_ugc_market_graph
from src.graph.state import UGCGraphState
from src.adapters.xhs_collect_config import XhsCollectConfig
from src.adapters.xhs_playwright_adapter import XhsPlaywrightAdapter
from src.llm.client import MockLLMClient
from src.schemas import AnalysisRequest
from src.utils import AppPaths


def main():
    keyword = "黄金走势"
    analysis_mode = "rule"          # 选 "rule" 或 "llm_annotation"
    mock_llm = True                 # True = 不花 API 费用
    max_posts = 1
    max_comments = 10
    headless = False                # False = 打开浏览器让你登录

    # ============================================================
    # 组装阶段（对应 services.py 185-236 行）
    # ============================================================

    # 1. 构造产物路径
    paths = AppPaths()  # 默认输出到 data/

    # 2. 构造 LLM Client
    llm_client = MockLLMClient() if mock_llm else None

    # 3. 构造采集 Adapter
    config = XhsCollectConfig(
        keyword=keyword,
        max_posts=max_posts,
        max_comments_per_post=max_comments,
        headless=headless,
    )
    adapter = XhsPlaywrightAdapter(config=config)

    # 4. 构造 LangGraph
    graph = build_ugc_market_graph(
        adapter=adapter,
        analysis_mode=analysis_mode,
        llm_client=llm_client,
        paths=paths,
    )

    # 5. 构造分析请求和初始 State
    analysis_request = AnalysisRequest(
        topic=keyword,
        product_direction=keyword,
        industry_question=f"分析 {keyword} 的用户需求、痛点、反馈",
    )
    state = UGCGraphState(
        request=analysis_request,
        paths=paths,
    )

    # ============================================================
    # BP1：执行前验证组装
    # ============================================================
    import pdb
    print("\n" + "=" * 60)
    print("BP1: 执行前 —— 请检查以下变量：")
    print("  p config          — 采集参数")
    print("  p adapter         — adapter 实例")
    print("  p llm_client      — LLM 客户端")
    print("  p analysis_mode   — 分析模式")
    print("  p analysis_request — 分析请求")
    print("  p state           — 初始状态（只有 request + paths，其他都是 None）")
    print("  c                 — 继续执行")
    print("=" * 60 + "\n")
    pdb.set_trace()

    # ============================================================
    # 执行 —— 这是整个工作流
    # ============================================================
    print("\n开始执行 LangGraph 工作流...\n")
    result = graph.invoke(state)

    # ============================================================
    # BP2：执行后检查产物
    # ============================================================
    print("\n" + "=" * 60)
    print("BP2: 执行后 —— 请检查以下变量：")
    print("  pp dict(result.keys())                        — 所有 state 字段")
    print("  print(result.get('raw_dataset'))               — 原始数据")
    print("  print(result.get('normalized_dataset'))         — 标准化后")
    print("  print(result.get('sentiment_result'))           — 情感分析")
    print("  pp result.get('insights')                       — 洞察")
    print("  pp result.get('scorecard')                      — 评分")
    print("  print(result.get('content_ideation_result'))    — 选题建议")
    print("  print(result.get('report_path'))                — 报告路径")
    print("  print(result.get('success'))                    — 是否成功")
    print("=" * 60 + "\n")
    pdb.set_trace()

    # ============================================================
    # 产物文件检查
    # ============================================================
    print("\n产物文件检查：")
    outputs = [
        ("raw_posts.json",           paths.raw_posts_file),
        ("raw_comments.json",         paths.raw_comments_file),
        ("normalized_posts.json",     paths.normalized_posts_file),
        ("normalized_comments.json",  paths.normalized_comments_file),
        ("insights.json",             paths.insights_file),
        ("scorecard.json",            paths.scorecard_file),
        ("content_ideation.json",     os.path.join(paths.outputs_dir, "content_ideation.json")),
        ("report.html",               paths.report_file),
    ]
    for name, path in outputs:
        status = "exists" if os.path.exists(path) else "MISSING"
        print(f"  [{status:7s}] {name:25s}  → {path}")

    if result.get("success"):
        print(f"\n   报告: file:///{paths.report_file}")
    else:
        print(f"\n  执行未成功，请检查节点日志。")


if __name__ == "__main__":
    main()
