"""
小红书页面字段探测脚本。

三种模式：
1. search -- 搜索页探测
   python scripts/probe_xhs_page.py --mode search --keyword 控油洗发水

2. detail -- 笔记详情页探测
   python scripts/probe_xhs_page.py --mode detail --url https://www.xiaohongshu.com/explore/xxxx

3. click-detail -- 搜索页点击卡片进入详情浮层探测
   python scripts/probe_xhs_page.py --mode click-detail --keyword 控油洗发水 --index 0

本阶段只做字段探测，不进入 SourceAgent/NormalizeAgent/LangGraph，
不生成 pipeline 产物（insights / scorecard / report）。

首次使用需要：
    pip install playwright
    python -m playwright install chromium
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.adapters.xhs_utils import parse_count_text, extract_post_id_from_url
from src.adapters.xhs_playwright_ops import (
    ensure_browser_context, close_browser_context,
    open_search_page, extract_search_cards, click_card_and_wait,
    detect_access_status, scroll_visible_comments, extract_visible_comments,
    extract_detail_candidates, _STATE_PATH,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 输出目录
_PROBE_DIR = os.path.join(_PROJECT_ROOT, "data", "private", "xhs_probe")

# 页面加载超时（毫秒）
_PAGE_TIMEOUT = 30000
# 用户登录等待时间（毫秒）
_LOGIN_TIMEOUT = 60000
# 整体操作超时（毫秒）
_OPERATION_TIMEOUT = 120000


def _ensure_dirs() -> None:
    """确保探测输出目录存在。"""
    os.makedirs(_PROBE_DIR, exist_ok=True)


def _save_json(filename: str, data: Any) -> str:
    """将 data 保存为 JSON 到探测目录。"""
    path = os.path.join(_PROBE_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("已保存: %s", path)
    return path


def _save_debug(page: Any, base_name: str) -> None:
    """保存页面 HTML 和纯文本到 data/private/xhs_probe/。

    Args:
        page: Playwright Page 对象。
        base_name: 文件基础名（不含扩展名），如 "search_page"。
    """
    html_path = os.path.join(_PROBE_DIR, f"{base_name}.html")
    text_path = os.path.join(_PROBE_DIR, f"{base_name}_text.txt")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page.content())

    body_text = page.inner_text("body") or ""
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(body_text)

    logger.info("已保存: %s", html_path)
    logger.info("已保存: %s", text_path)


def _extract_candidates(
    page: Any,
    selectors: list[str],
    attr: str = "text_content",
    max_results: int = 10,
) -> list[str]:
    """用多个 selector 尝试提取候选值。

    Args:
        page: Playwright Page 对象。
        selectors: CSS selector 列表，依次尝试。
        attr: 提取的属性，可选 "text_content"、"href"、"inner_text" 或任意 HTML 属性名。
        max_results: 每个 selector 最多提取的元素数。

    Returns:
        去重后的候选文本列表。
    """
    candidates = []
    seen: set[str] = set()
    for selector in selectors:
        try:
            elements = page.query_selector_all(selector)
            for el in elements[:max_results]:
                if attr == "text_content":
                    text = el.text_content()
                elif attr == "href":
                    text = el.get_attribute("href")
                elif attr == "inner_text":
                    text = el.inner_text()
                else:
                    text = el.get_attribute(attr)
                if text and text.strip() and text.strip() not in seen:
                    seen.add(text.strip())
                    candidates.append(text.strip())
        except Exception:
            continue
    return candidates


def _extract_note_cards(page: Any) -> list[dict]:
    """从搜索页提取结构化笔记卡片信息。

    对每个 section.note-item，提取标准笔记 URL、post_id、标题、作者、时间、点赞数及抽样文本。

    Args:
        page: Playwright Page 对象。

    Returns:
        结构化卡片字典列表，提取失败返回空字符串，不中断。
    """
    cards: list[dict] = []
    sections = page.query_selector_all("section.note-item")
    logger.info("  找到 %d 个 section.note-item", len(sections))
    for section in sections:
        try:
            # 隐藏笔记链接（最可靠的笔记 ID 来源）
            note_link = section.query_selector("a[href^='/explore/']")
            href = ""
            post_id = ""
            if note_link:
                raw_href = note_link.get_attribute("href") or ""
                # 过滤掉 ?channel_type=... 等带查询参数的链接
                if "?" not in raw_href and raw_href.startswith("/explore/"):
                    href = f"https://www.xiaohongshu.com{raw_href}"
                    post_id = raw_href.replace("/explore/", "")

            # 标题
            title_el = section.query_selector("a.title")
            title = title_el.inner_text().strip() if title_el else ""

            # 作者
            author_el = section.query_selector("a.author .name")
            author = author_el.inner_text().strip() if author_el else ""

            # 时间
            time_el = section.query_selector("a.author .time")
            pub_time = time_el.inner_text().strip() if time_el else ""

            # 点赞
            like_el = section.query_selector(".like-wrapper .count")
            like_count = like_el.inner_text().strip() if like_el else ""

            # 文本采样
            text_sample = (section.inner_text() or "")[:200].strip()

            cards.append({
                "href": href,
                "post_id": post_id,
                "possible_title": title,
                "possible_author": author,
                "possible_publish_time": pub_time,
                "possible_like_count": like_count,
                "text_sample": text_sample,
            })
        except Exception:
            continue
    return cards


def probe_search_page(keyword: str, headless: bool = False) -> None:
    """使用 Playwright 探测搜索页。

    行为：
    1. 构造搜索 URL 并打开
    2. 加载/管理登录态
    3. 滚动 3 轮加载更多内容
    4. 保存页面 HTML 和纯文本
    5. 从 section.note-item 提取结构化笔记卡片

    Args:
        keyword: 搜索关键词。
        headless: 是否使用无头模式。
    """
    search_url = (
        f"https://www.xiaohongshu.com/search_result"
        f"?keyword={keyword}&source=web_explore_feed"
    )
    logger.info("搜索页探测: keyword=%s", keyword)
    logger.info("搜索 URL: %s", search_url)

    page, context, browser, pw = ensure_browser_context(headless=headless)
    try:
        logger.info("正在打开搜索页...")
        page.goto(search_url, wait_until="domcontentloaded", timeout=_PAGE_TIMEOUT)

        # 等待初始内容渲染
        page.wait_for_timeout(3000)

        # 滚动 3 轮加载更多
        for i in range(3):
            page.evaluate("window.scrollBy(0, 800)")
            page.wait_for_timeout(3000)
            logger.info("  滚动 %d/3", i + 1)

        # 等待额外内容渲染
        page.wait_for_timeout(2000)

        # 保存页面调试文件
        _save_debug(page, "search_page")

        # ---- 结构化笔记卡片提取 ----
        cards = _extract_note_cards(page)

        # 从卡片派生出各候选字段
        note_links = [c["href"] for c in cards if c["href"]]
        titles = [c["possible_title"] for c in cards if c["possible_title"]]
        authors = [c["possible_author"] for c in cards if c["possible_author"]]
        likes = [c["possible_like_count"] for c in cards if c["possible_like_count"]]

        # 视频标记 / 广告标记（保留通用提取）
        video_markers = _extract_candidates(
            page,
            [
                "[class*='video']",
                "[class*='Video']",
                "[class*='play']",
                "i[class*='video']",
            ],
        )
        ad_markers = _extract_candidates(
            page,
            [
                "[class*='ad']",
                "[class*='Ad']",
                "[class*='sponsor']",
                "[class*='promote']",
            ],
        )

        body_text = page.inner_text("body") or ""
        raw_sample = body_text[:2000] if body_text else ""

        result = {
            "probe_time": datetime.now().isoformat(),
            "mode": "search",
            "keyword": keyword,
            "search_url": search_url,
            "note_card_candidates": cards,
            "note_link_candidates": note_links,
            "title_candidates": titles,
            "author_candidates": authors,
            "like_count_candidates": likes,
            "video_marker_candidates": video_markers,
            "ad_marker_candidates": ad_markers,
            "raw_text_sample": raw_sample,
        }

        path = _save_json("search_probe_result.json", result)
        logger.info("搜索页探测完成: %s", path)

    finally:
        close_browser_context(page, context, browser, pw)


def probe_detail_page(url: str, headless: bool = False) -> None:
    """使用 Playwright 探测笔记详情页。

    行为：
    1. 打开笔记详情 URL
    2. 加载/管理登录态
    3. 保存页面 HTML 和纯文本
    4. 尝试用多个 CSS selector 提取各候选字段

    Args:
        url: 笔记详情页 URL。
        headless: 是否使用无头模式。
    """
    post_id = extract_post_id_from_url(url)
    logger.info("详情页探测: url=%s", url)
    logger.info("  提取 post_id: %s", post_id or "(未识别)")

    page, context, browser, pw = ensure_browser_context(headless=headless)
    try:
        logger.info("正在打开详情页...")
        page.goto(url, wait_until="domcontentloaded", timeout=_PAGE_TIMEOUT)

        # 等待页面内容渲染
        page.wait_for_timeout(5000)

        # 滚动以触发懒加载
        for i in range(2):
            page.evaluate("window.scrollBy(0, 600)")
            page.wait_for_timeout(2000)
            logger.info("  滚动 %d/2", i + 1)

        # 等待评论加载
        page.wait_for_timeout(2000)

        # 保存页面调试文件
        _save_debug(page, "detail_page")

        # ---- 候选字段提取 ----
        titles = _extract_candidates(
            page,
            [
                "#detail-title",
                "h1",
                ".title",
                ".article-title",
                "[class*='title']",
            ],
        )
        contents = _extract_candidates(
            page,
            [
                "#detail-desc",
                ".desc",
                "article",
                ".content",
                ".note-content",
                ".article-content",
                "[class*='desc']",
            ],
        )
        authors = _extract_candidates(
            page,
            [
                ".username",
                ".author",
                ".name",
                ".user",
                ".nickname",
                ".author-name",
                "[class*='author']",
            ],
        )
        publish_times = _extract_candidates(
            page,
            [
                ".date",
                ".time",
                ".publish-time",
                ".create-time",
                "[class*='time']",
                "[class*='date']",
            ],
        )
        likes = _extract_candidates(
            page,
            [
                ".like-count",
                ".likes",
                ".count",
                "[class*='like'] span",
                "[class*='Like'] span",
                "[class*='like-count']",
            ],
        )
        comments_count = _extract_candidates(
            page,
            [
                ".comment-count",
                ".comments",
                ".comment-num",
                "[class*='comment'] span",
                "[class*='Comment'] span",
            ],
        )
        favorites = _extract_candidates(
            page,
            [
                ".collect-count",
                ".favorite",
                ".collects",
                "[class*='collect'] span",
                "[class*='favorite'] span",
                "[class*='star'] span",
            ],
        )
        shares = _extract_candidates(
            page,
            [
                ".share-count",
                ".share",
                "[class*='share'] span",
                "[class*='Share'] span",
            ],
        )
        tags = _extract_candidates(
            page,
            [
                ".tag",
                ".topic",
                ".hashtag",
                "[class*='tag']",
                "[class*='topic']",
                "[class*='hashtag']",
            ],
        )
        visible_comments = _extract_candidates(
            page,
            [
                ".comment-item",
                ".comment",
                ".comments-wrapper .item",
                "[class*='comment-item']",
                "[class*='commentItem']",
            ],
        )

        body_text = page.inner_text("body") or ""
        raw_sample = body_text[:2000] if body_text else ""

        result = {
            "probe_time": datetime.now().isoformat(),
            "mode": "detail",
            "url": url,
            "possible_post_id": post_id or "",
            "url_candidates": [url],
            "title_candidates": titles,
            "content_candidates": contents,
            "author_candidates": authors,
            "publish_time_candidates": publish_times,
            "likes_candidates": likes,
            "comments_count_candidates": comments_count,
            "favorites_candidates": favorites,
            "shares_candidates": shares,
            "tags_candidates": tags,
            "visible_comment_candidates": visible_comments,
            "raw_text_sample": raw_sample,
        }

        path = _save_json("detail_probe_result.json", result)
        logger.info("详情页探测完成: %s", path)

    finally:
        close_browser_context(page, context, browser, pw)


def probe_click_detail(
    keyword: str,
    index: int = 0,
    headless: bool = False,
    comment_scroll_rounds: int = 2,
    max_comments: int = 20,
) -> None:
    """使用 Playwright 点击搜索页卡片进入详情浮层探测。

    行为：
    1. 打开搜索页
    2. 找到第 index 个有效卡片（过滤掉带查询参数的链接）
    3. 点击卡片触发详情浮层
    4. 检查浮层访问状态（是否被拦截）
    5. 提取各候选字段及可见评论
    6. 滚动评论区多轮获取更多评论

    本阶段只做字段探测，不进入 SourceAgent/NormalizeAgent/LangGraph，
    不生成 pipeline 产物。

    Args:
        keyword: 搜索关键词。
        index: 点击第几个有效卡片（默认 0）。
        headless: 是否使用无头模式。
        comment_scroll_rounds: 评论区滚动轮次（默认 2）。
        max_comments: 最大采集评论数（默认 20）。
    """
    search_url = (
        f"https://www.xiaohongshu.com/search_result"
        f"?keyword={keyword}&source=web_explore_feed"
    )
    logger.info(
        "click-detail: keyword=%s, index=%d, scroll_rounds=%d, max_comments=%d",
        keyword, index, comment_scroll_rounds, max_comments,
    )

    page, context, browser, pw = ensure_browser_context(headless=headless)
    try:
        # 打开搜索页
        open_search_page(page, keyword)

        # 找到有效卡片
        valid_cards = extract_search_cards(page)

        if not valid_cards:
            logger.error("未找到有效搜索结果卡片")
            _save_json("click_detail_probe_result.json", {"error": "no_valid_cards"})
            return

        if index >= len(valid_cards):
            logger.error("index %d 超出有效卡片数 %d", index, len(valid_cards))
            return

        target_card = valid_cards[index]

        # 获取点击前的 URL
        before_url = page.url

        # 点击卡片并获取 post_id
        post_id = click_card_and_wait(page, target_card, index)

        after_url = page.url

        # 保存调试文件
        _save_debug(page, "click_detail_page")

        # 检查是否被拦截
        access_status, block_reason, is_valid_detail_page = detect_access_status(page)

        # 提取候选字段和评论（只在浮层有效时进行）
        if is_valid_detail_page:
            candidates = extract_detail_candidates(page)
            scroll_visible_comments(page, rounds=comment_scroll_rounds)
            visible_comments = extract_visible_comments(page, post_id=post_id, max_comments=max_comments)

            # 获取原始的可见评论文本候选（用于更丰富的探测）
            raw_comment_texts = _extract_candidates(
                page,
                [
                    ".comment-item",
                    ".comment",
                    ".comments-wrapper .item",
                    "[class*='comment-item']",
                ],
            )

            urls = [f"https://www.xiaohongshu.com/explore/{post_id}"] if post_id else []
        else:
            candidates = {
                "title_candidates": [],
                "content_candidates": [],
                "author_candidates": [],
                "publish_time_candidates": [],
                "likes_candidates": [],
                "favorites_candidates": [],
                "comments_count_candidates": [],
                "shares_candidates": [],
                "tags_candidates": [],
            }
            visible_comments = []
            raw_comment_texts = []
            urls = []

        result = {
            "probe_time": datetime.now().isoformat(),
            "mode": "click-detail",
            "keyword": keyword,
            "index": index,
            "before_url": before_url,
            "after_url": after_url,
            "post_id": post_id,
            "access_status": access_status,
            "block_reason": block_reason,
            "is_valid_detail_page": is_valid_detail_page,
            **candidates,
            "url_candidates": urls,
            "visible_comment_candidates": visible_comments,
            "raw_comment_text_candidates": raw_comment_texts,
        }

        _save_json("click_detail_probe_result.json", result)
        logger.info(
            "click-detail 探测完成: post_id=%s, access_status=%s",
            post_id,
            access_status,
        )

    finally:
        close_browser_context(page, context, browser, pw)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="小红书页面字段探测")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["search", "detail", "click-detail"],
        help="探测模式: search=搜索页, detail=详情页, click-detail=点击卡片浮层",
    )
    parser.add_argument(
        "--keyword",
        default="",
        help="搜索关键词（search / click-detail 模式）",
    )
    parser.add_argument(
        "--url",
        default="",
        help="笔记 URL（detail 模式）",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=0,
        help="点击第几个有效卡片（click-detail 模式，默认 0）",
    )
    parser.add_argument(
        "--comment-scroll-rounds",
        type=int,
        default=2,
        help="评论区滚动轮次（click-detail 模式，默认 2）",
    )
    parser.add_argument(
        "--max-comments",
        type=int,
        default=20,
        help="最大采集评论数（click-detail 模式，默认 20）",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="无头模式（默认 False）",
    )
    return parser.parse_args()


def main() -> None:
    """入口函数。"""
    args = parse_args()
    _ensure_dirs()

    logger.info("=" * 50)
    logger.info("XHS 页面字段探测开始")
    logger.info("  模式: %s", args.mode)
    logger.info("  headless: %s", args.headless)
    logger.info("=" * 50)

    if args.mode == "search":
        if not args.keyword:
            logger.error("search 模式需要 --keyword 参数")
            sys.exit(1)
        probe_search_page(args.keyword, headless=args.headless)
    elif args.mode == "detail":
        if not args.url:
            logger.error("detail 模式需要 --url 参数")
            sys.exit(1)
        probe_detail_page(args.url, headless=args.headless)
    elif args.mode == "click-detail":
        if not args.keyword:
            logger.error("click-detail 模式需要 --keyword 参数")
            sys.exit(1)
        probe_click_detail(
            args.keyword, index=args.index, headless=args.headless,
            comment_scroll_rounds=args.comment_scroll_rounds,
            max_comments=args.max_comments,
        )

    print(f"\n探测结果已保存到: {_PROBE_DIR}")
    print(f"登录态路径: {_STATE_PATH}")


if __name__ == "__main__":
    main()
