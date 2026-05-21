"""
自动截取项目展示截图。

前置条件：
    前端 dev server 在 5173/5176 端口运行。
    已有分析报告在 data/jobs/ 下。

用法：
    python scripts/capture_screenshots.py
"""

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from playwright.sync_api import sync_playwright

ASSETS_DIR = os.path.join(_PROJECT_ROOT, "assets")
os.makedirs(ASSETS_DIR, exist_ok=True)

# 找一个报告文件
REPORT_FILES = []
for root, dirs, files in os.walk(os.path.join(_PROJECT_ROOT, "data", "jobs")):
    for f in files:
        if f == "report.html":
            REPORT_FILES.append(os.path.join(root, f))
            if len(REPORT_FILES) >= 3:
                break
    if len(REPORT_FILES) >= 3:
        break

if not REPORT_FILES:
    print("未找到报告文件")
    sys.exit(1)

# 找最大（最完整）的报告
best_report = max(REPORT_FILES, key=lambda p: os.path.getsize(p))
print(f"使用报告: {os.path.relpath(best_report, _PROJECT_ROOT)}")

pw = sync_playwright()
pw_instance = pw.__enter__()
browser = pw_instance.chromium.launch(headless=True)

try:
    # --- 截图 1: 前端页面 ---
    for port in [5173, 5174, 5175, 5176]:
        url = f"http://localhost:{port}"
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(url, wait_until="domcontentloaded", timeout=5000)
            page.wait_for_timeout(2000)
            page.screenshot(path=os.path.join(ASSETS_DIR, "frontend.png"), full_page=True)
            print(f"前端截图成功 (port {port})")
            page.close()
            break
        except Exception:
            try:
                page.close()
            except Exception:
                pass
            continue
    else:
        print("前端截图失败: dev server 未运行")

    # --- 截图 2: 报告 HTML ---
    report_url = f"file://{best_report}"
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(report_url, wait_until="domcontentloaded", timeout=10000)
    page.wait_for_timeout(3000)

    # 报告概览
    page.screenshot(path=os.path.join(ASSETS_DIR, "report.png"), full_page=True)
    print("报告截图成功")

    page.close()

    # --- 截图 3: 报告局部（评分区域）---
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(report_url, wait_until="domcontentloaded", timeout=10000)
    page.wait_for_timeout(2000)

    # 尝试定位评分卡片区域
    score_selectors = [
        ".score-card", ".score-section", "#score",
        ".scoring-card", ".scorecard",
        "h2, h3",  # fallback: take top of page
    ]
    for sel in score_selectors:
        try:
            el = page.query_selector(sel)
            if el:
                el.screenshot(path=os.path.join(ASSETS_DIR, "scorecard.png"))
                print(f"评分截图成功 (selector={sel})")
                break
        except Exception:
            continue
    else:
        # fallback: 截取页面中间 1/3
        page.screenshot(
            path=os.path.join(ASSETS_DIR, "scorecard.png"),
            clip={"x": 0, "y": 300, "width": 1440, "height": 600},
        )
        print("评分截图成功 (fallback clip)")

    page.close()

except Exception as e:
    print(f"截图失败: {e}")

finally:
    try:
        browser.close()
    except Exception:
        pass
    pw_instance.__exit__(None, None, None)

print(f"\n截图已保存到 {ASSETS_DIR}/")
for f in os.listdir(ASSETS_DIR):
    size = os.path.getsize(os.path.join(ASSETS_DIR, f))
    print(f"  {f}: {size // 1024} KB")
