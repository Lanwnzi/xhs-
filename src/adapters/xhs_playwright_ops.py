"""
XhsPlaywrightAdapter 的共享操作层。

包含 Playwright 浏览器管理、搜索页打开、卡片点击、评论滚动等操作。
本模块被 adapter 和 probe 脚本共同使用。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

from playwright.sync_api import Browser, Page, sync_playwright

logger = logging.getLogger(__name__)

# 默认配置
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_STATE_PATH = os.path.join(_PROJECT_ROOT, "data", "private", "xhs_state.json")


def ensure_browser_context(
    headless: bool = False,
    state_path: str = "",
):
    """启动 Playwright browser，加载登录态。

    如果 state_path 存在则加载 storage_state，否则打开浏览器供手动登录。
    返回 (page, context, browser, pw_instance)，调用方负责在 finally 中关闭。
    """
    if not state_path:
        state_path = _STATE_PATH

    os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)

    pw = sync_playwright()
    pw_instance = pw.__enter__()
    browser = pw_instance.chromium.launch(headless=headless)

    if os.path.exists(state_path):
        logger.info("加载登录态: %s", state_path)
        context = browser.new_context(
            storage_state=state_path,
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        return page, context, browser, pw_instance

    logger.info("未发现登录态，打开浏览器供手动登录")
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
    logger.info("请在 60 秒内完成登录...")
    page.wait_for_timeout(60000)
    context.storage_state(path=state_path)
    logger.info("登录态已保存: %s", state_path)
    return page, context, browser, pw_instance


def close_browser_context(page: Page, context, browser, pw_instance) -> None:
    """关闭 browser/context/page，保存登录态。"""
    try:
        os.makedirs(os.path.dirname(_STATE_PATH) or ".", exist_ok=True)
        context.storage_state(path=_STATE_PATH)
    except Exception:
        pass
    try:
        browser.close()
    except Exception:
        pass
    try:
        pw_instance.__exit__(None, None, None)
    except Exception:
        pass


def open_search_page(page: Page, keyword: str) -> None:
    """打开小红书搜索页。"""
    url = f"https://www.xiaohongshu.com/search_result?keyword={keyword}&source=web_explore_feed"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)


def extract_search_cards(page: Page) -> list[Any]:
    """提取搜索页有效卡片。返回 playwright element handles。"""
    sections = page.query_selector_all("section.note-item")
    valid = []
    for card in sections:
        try:
            link = card.query_selector("a[href^='/explore/']")
            if link:
                href = link.get_attribute("href") or ""
                if "?" not in href and href.startswith("/explore/"):
                    valid.append(card)
        except Exception:
            continue
    return valid


def click_card_and_wait(page: Page, card, index: int = 0) -> str:
    """点击卡片并获取 post_id。"""
    link_el = card.query_selector("a[href^='/explore/']")
    raw_href = link_el.get_attribute("href") or "" if link_el else ""
    post_id = raw_href.replace("/explore/", "") if raw_href.startswith("/explore/") else ""
    card.click()
    page.wait_for_timeout(5000)
    return post_id


def detect_access_status(page: Page) -> tuple[str, str, bool]:
    """检测浮层访问状态。返回 (access_status, block_reason, is_valid)。"""
    body = page.inner_text("body") or ""
    if "暂时无法浏览" in body or "请打开小红书App查看" in body:
        return "blocked_app_required", "笔记被限制，需要 App 内查看", False
    if "登录" in body[:500] or "验证码" in body[:500]:
        return "login_or_verification_required", "需要登录或验证码", False
    return "ok", "", True


def scroll_visible_comments(page: Page, rounds: int = 3, timeout_ms: int = 2000) -> None:
    """滚动评论区容器。"""
    for i in range(rounds):
        logger.info("  评论区滚动 %d/%d", i + 1, rounds)
        page.wait_for_timeout(timeout_ms)
        try:
            page.evaluate("""
                () => {
                    const containers = document.querySelectorAll(
                        '.comment-list, .comments-wrapper, .note-scroller, ' +
                        '[class*="comment"], [class*="dialog"], [class*="modal"]'
                    );
                    for (const c of containers) {
                        if (c.scrollHeight > c.clientHeight) {
                            c.scrollTop = c.scrollHeight;
                        }
                    }
                }
            """)
        except Exception as e:
            logger.warning("评论区滚动 JS 执行失败: %s", e)
        page.wait_for_timeout(timeout_ms)


def extract_visible_comments(page: Page, post_id: str = "", max_comments: int = 20) -> list[dict]:
    """从详情浮层提取可见评论。"""
    from src.adapters.xhs_utils import parse_count_text

    # 方案 A：parent-comment > comment-item
    items = page.query_selector_all("div.parent-comment > div.comment-item")
    if not items:
        items = page.query_selector_all(".comment-item, .comment, [class*='comment-item']")

    comments = []
    seen_contents = set()
    seen_ids = set()

    for i, el in enumerate(items[:max_comments]):
        try:
            cid = el.get_attribute("id") or ""
            if cid.startswith("comment-"):
                cid = cid.replace("comment-", "", 1)

            c_el = el.query_selector(".content .note-text, .content span, .text, .comment-text")
            content = c_el.inner_text().strip() if c_el else ""
            if not content:
                continue
            if content in seen_contents or cid in seen_ids:
                continue
            seen_contents.add(content)
            if cid:
                seen_ids.add(cid)

            a_el = el.query_selector(".author-wrapper .author .name, .name, .username")
            author = a_el.inner_text().strip()[:30] if a_el else ""

            t_el = el.query_selector(".info .date, .date, .time, .create-time")
            pub_time = t_el.inner_text().strip()[:30] if t_el else ""

            l_el = el.query_selector(".interactions .like .count, .like .count, .count")
            likes_raw = l_el.inner_text().strip()[:20] if l_el else "0"
            likes_int = parse_count_text(likes_raw)

            if not cid:
                cid = f"{post_id}_{i}_{hash(content) % 10000000}" if post_id else f"idx_{i}_{hash(content) % 10000000}"

            comments.append({
                "comment_id": cid,
                "content": content[:200],
                "author": author,
                "publish_time": pub_time,
                "likes": likes_int,
                "likes_raw": likes_raw,
                "parent_comment_id": None,
            })
        except Exception:
            continue

    return comments


def extract_detail_candidates(page: Page) -> dict[str, Any]:
    """从详情浮层提取帖子候选字段。"""
    from src.adapters.xhs_utils import parse_count_text

    def _extract(selectors, attr="inner_text", max_r=5):
        result = []
        for sel in selectors:
            try:
                els = page.query_selector_all(sel)
                for el in els[:max_r]:
                    text = el.inner_text().strip() if attr == "inner_text" else el.text_content().strip()
                    if text:
                        result.append(text)
            except Exception:
                continue
        return result

    return {
        "title_candidates": _extract(["#detail-title", ".detail-title", "h1#title", ".note-scroller .title"]),
        "content_candidates": _extract(["#detail-desc", ".detail-desc", ".note-scroller .desc", ".note-scroller .content", "[class*='desc']", "[class*='content']"]),
        "author_candidates": _extract([".username", ".author .name", ".author-name", ".note-scroller .author"]),
        "publish_time_candidates": _extract([".date", ".time", ".publish-time", ".bottom-container .date", ".note-scroller .date"]),
        "likes_candidates": _extract([".like-wrapper .count", ".like-count", ".engage-bar .count", "[class*='like'] .count", "span.count"]),
        "favorites_candidates": _extract([".collect-wrapper .count", ".collect-count", "[class*='collect'] .count"]),
        "comments_count_candidates": _extract([".comment-wrapper .count", ".comment-count", ".total-comment", "[class*='comment'] .count"]),
        "shares_candidates": _extract([".share-wrapper .count", ".share-count", "[class*='share'] .count"]),
    }
