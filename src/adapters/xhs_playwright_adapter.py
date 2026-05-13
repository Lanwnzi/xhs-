"""
小红书 Playwright 实时采集适配器。
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Optional

from src.adapters.base import BaseAdapter
from src.adapters.xhs_collect_config import XhsCollectConfig
from src.adapters.xhs_playwright_ops import (
    ensure_browser_context, close_browser_context,
    open_search_page, extract_search_cards, click_card_and_wait,
    detect_access_status, scroll_visible_comments, extract_visible_comments,
    extract_detail_candidates,
)
from src.adapters.xhs_utils import parse_count_text, extract_post_id_from_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 映射函数
# ---------------------------------------------------------------------------


def _map_post(raw: dict[str, Any]) -> dict[str, Any]:
    """将小红书帖子原始字段映射为 PostRecord 兼容字段。"""
    publish_time = ""
    raw_time = raw.get("create_time") or raw.get("time") or ""
    if isinstance(raw_time, (int, float)):
        try:
            publish_time = datetime.fromtimestamp(raw_time).strftime("%Y-%m-%dT%H:%M:%S")
        except (OSError, ValueError):
            publish_time = str(raw_time)
    elif isinstance(raw_time, str):
        if raw_time and "T" not in raw_time and len(raw_time) >= 10:
            try:
                dt = datetime.fromisoformat(raw_time.replace(" ", "T"))
                publish_time = dt.strftime("%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                publish_time = raw_time
        else:
            publish_time = raw_time

    tags = raw.get("tag_list") or raw.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    return {
        "platform": "xhs",
        "post_id": str(raw.get("note_id") or raw.get("id") or ""),
        "title": raw.get("title") or "",
        "content": raw.get("desc") or raw.get("description") or raw.get("content") or "",
        "author": raw.get("nickname") or raw.get("author") or "",
        "publish_time": publish_time,
        "likes": int(raw.get("liked_count", 0) or raw.get("likes", 0)),
        "comments": int(raw.get("comment_count", 0) or raw.get("comments", 0)),
        "favorites": int(raw.get("collected_count", 0) or raw.get("collected", 0) or raw.get("favorites", 0)),
        "shares": int(raw.get("share_count", 0) or raw.get("shares", 0)),
        "url": raw.get("note_url") or raw.get("url") or "",
        "tags": tags,
    }


def _map_comment(raw: dict[str, Any]) -> dict[str, Any]:
    """将小红书评论原始字段映射为 CommentRecord 兼容字段。"""
    publish_time = ""
    raw_time = raw.get("create_time") or raw.get("time") or ""
    if isinstance(raw_time, (int, float)):
        try:
            publish_time = datetime.fromtimestamp(raw_time).strftime("%Y-%m-%dT%H:%M:%S")
        except (OSError, ValueError):
            publish_time = str(raw_time)
    elif isinstance(raw_time, str):
        if raw_time and "T" not in raw_time and len(raw_time) >= 10:
            try:
                dt = datetime.fromisoformat(raw_time.replace(" ", "T"))
                publish_time = dt.strftime("%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                publish_time = raw_time
        else:
            publish_time = raw_time

    return {
        "platform": "xhs",
        "comment_id": str(raw.get("id") or raw.get("comment_id") or ""),
        "post_id": str(raw.get("note_id") or raw.get("post_id") or ""),
        "content": raw.get("content") or "",
        "author": raw.get("nickname") or raw.get("author") or "",
        "publish_time": publish_time,
        "likes": int(raw.get("like_count", 0) or raw.get("likes", 0)),
        "parent_comment_id": raw.get("parent_comment_id") or raw.get("target_comment_id") or None,
    }


def _filter_post(post: dict[str, Any], config: XhsCollectConfig) -> bool:
    """过滤已映射的帖子（PostRecord 字段）。返回 True 保留，False 跳过。"""
    if not post.get("post_id"):
        return False
    if int(post.get("likes", 0) or 0) < config.min_likes:
        return False
    if int(post.get("comments", 0) or 0) < config.min_comments:
        return False
    if int(post.get("favorites", 0) or 0) < config.min_favorites:
        return False
    return True


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _clean_author(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\n", "").replace("作者", "").strip()
    return text


def _extract_tags(content: str, tags_candidates: list[str] = None) -> list[str]:
    tags = []
    if content:
        tags = re.findall(r'#([^\s#,.，。]+)', content)
    if tags_candidates:
        for t in tags_candidates:
            t_clean = t.replace("#", "").strip()
            if t_clean and t_clean not in tags:
                tags.append(t_clean)
    return tags


def _generate_comment_id(post_id: str, index: int, content: str) -> str:
    return f"{post_id}_{index}_{hash(content) % 10000000}" if post_id else f"idx_{index}_{hash(content) % 10000000}"


def _map_click_detail_post(probe_result: dict[str, Any]) -> dict[str, Any]:
    post_id = probe_result.get("post_id", "")
    title_candidates = probe_result.get("title_candidates") or []
    content_candidates = probe_result.get("content_candidates") or []
    author_candidates = probe_result.get("author_candidates") or []
    pub_time_candidates = probe_result.get("publish_time_candidates") or []
    likes_candidates = probe_result.get("likes_candidates") or []
    fav_candidates = probe_result.get("favorites_candidates") or []
    cmt_count_candidates = probe_result.get("comments_count_candidates") or []
    shares_candidates = probe_result.get("shares_candidates") or []
    tags_candidates = probe_result.get("tags_candidates") or []
    url_candidates = probe_result.get("url_candidates") or []
    visible_comments = probe_result.get("visible_comment_candidates") or []

    comments_count = 0
    if cmt_count_candidates:
        comments_count = parse_count_text(cmt_count_candidates[0])
    else:
        comments_count = len(visible_comments)

    url = url_candidates[0] if url_candidates else f"https://www.xiaohongshu.com/explore/{post_id}" if post_id else ""
    content = content_candidates[0] if content_candidates else ""
    tags = _extract_tags(content, tags_candidates)

    return {
        "platform": "xhs",
        "post_id": post_id or "",
        "title": title_candidates[0] if title_candidates else "",
        "content": content,
        "author": _clean_author(author_candidates[0]) if author_candidates else "",
        "publish_time": pub_time_candidates[0] if pub_time_candidates else "",
        "likes": parse_count_text(likes_candidates[0]) if likes_candidates else 0,
        "comments": comments_count,
        "favorites": parse_count_text(fav_candidates[0]) if fav_candidates else 0,
        "shares": parse_count_text(shares_candidates[0]) if shares_candidates else 0,
        "url": url,
        "tags": tags,
    }


def _map_click_detail_comments(probe_result: dict[str, Any]) -> list[dict[str, Any]]:
    post_id = probe_result.get("post_id", "")
    raw_comments = probe_result.get("visible_comment_candidates") or []

    result = []
    seen_ids = set()
    seen_contents = set()

    for i, c in enumerate(raw_comments):
        content = (c.get("content") or "").strip()
        if not content:
            continue
        if content in seen_contents:
            continue
        seen_contents.add(content)

        cid = c.get("comment_id") or _generate_comment_id(post_id, i, content)
        if cid in seen_ids:
            continue
        seen_ids.add(cid)

        author = _clean_author(c.get("author") or "")
        pub_time = (c.get("publish_time") or "").strip()
        likes_raw = str(c.get("likes") or "0")
        likes_int = parse_count_text(likes_raw)
        parent_id = c.get("parent_comment_id")
        if parent_id is not None and str(parent_id).strip() == "":
            parent_id = None

        result.append({
            "platform": "xhs",
            "comment_id": cid,
            "post_id": post_id,
            "content": content[:200],
            "author": author,
            "publish_time": pub_time,
            "likes": likes_int,
            "parent_comment_id": parent_id,
        })

    return result


def _build_probe_result(page, post_id, candidates, visible_comments, before_url, after_url, keyword, index):
    body_text = page.inner_text("body") or ""
    return {
        "probe_time": datetime.now().isoformat(),
        "mode": "click-detail",
        "keyword": keyword,
        "index": index,
        "before_url": before_url,
        "after_url": after_url,
        "post_id": post_id,
        "access_status": "ok",
        "block_reason": "",
        "is_valid_detail_page": True,
        **candidates,
        "visible_comment_candidates": visible_comments,
        "raw_text_sample": body_text[:2000] if body_text else "",
    }


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def _try_dismiss_overlay(page) -> bool:
    """尝试关闭详情浮层。返回 True 表示成功（或无需关闭）。"""
    try:
        # 如果当前 URL 已返回搜索页，无需关闭
        if "/search_result" in page.url:
            return True
    except Exception:
        pass

    # 1. 尝试点击关闭按钮
    for selector in [
        ".close-button", ".close-btn", ".icon-close",
        "[class*='close']", "[aria-label='关闭']",
    ]:
        try:
            btn = page.query_selector(selector)
            if btn:
                btn.click()
                page.wait_for_timeout(1000)
                return True
        except Exception:
            continue

    # 2. 尝试 Escape 键
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)
        if "/search_result" in page.url:
            return True
    except Exception:
        pass

    # 3. 尝试返回
    try:
        page.go_back(wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        return True
    except Exception:
        pass

    return False


class XhsPlaywrightAdapter(BaseAdapter):
    """小红书 Playwright 可见内容采集适配器。"""

    def __init__(self, config: Optional[XhsCollectConfig] = None):
        self.config = config or XhsCollectConfig()
        self._posts: list[dict] = []
        self._comments: list[dict] = []

    def fetch_posts(self, keyword: str = "", max_count: int = 0) -> list[dict]:
        """采集小红书帖子。

        搜索页 → 遍历卡片 → 点击浮层 → 提取内容 → 关闭浮层 → 下一个。
        单条失败不影响其他，最终最多返回 max_posts 条。
        """
        kw = keyword or self.config.keyword
        max_posts = max_count or self.config.max_posts

        if not kw:
            logger.warning("fetch_posts: keyword 为空")
            return []

        logger.info("XHS fetch_posts: keyword=%s, max_posts=%s, max_comments_per_post=%s",
                    kw, max_posts, self.config.max_comments_per_post)

        page, context, browser, pw = ensure_browser_context(headless=self.config.headless)
        try:
            open_search_page(page, kw)

            # 首次提取所有有效卡片（只获取 URL 列表，不保留 DOM handle）
            cards_data: list[dict[str, str]] = []
            raw_cards = extract_search_cards(page)
            for card in raw_cards:
                try:
                    link = card.query_selector("a[href^='/explore/']")
                    if link:
                        href = link.get_attribute("href") or ""
                        if "?" not in href and href.startswith("/explore/"):
                            pid = href.replace("/explore/", "")
                            if pid:
                                cards_data.append({
                                    "post_id": pid,
                                    "href_raw": href,
                                })
                except Exception:
                    continue

            if not cards_data:
                logger.warning("XHS fetch_posts: 搜索页未找到有效卡片")
                return []

            logger.info("XHS search cards: found=%s, target=%s", len(cards_data), min(len(cards_data), max_posts))

            self._posts = []
            self._comments = []
            collected_post_ids: set[str] = set()

            for i, card_info in enumerate(cards_data):
                if len(self._posts) >= max_posts:
                    logger.info("XHS fetch_posts: 已达到 max_posts=%s 上限", max_posts)
                    break

                post_id = card_info["post_id"]

                if post_id in collected_post_ids:
                    continue
                collected_post_ids.add(post_id)

                logger.info("XHS collecting card %s/%s: post_id=%s, href=%s",
                            i + 1, min(len(cards_data), max_posts), post_id, card_info["href_raw"])

                try:
                    # 点击卡片 — 使用新提取的 selector 定位
                    raw_cards2 = extract_search_cards(page)
                    target_card = None
                    for card in raw_cards2:
                        try:
                            link = card.query_selector("a[href^='/explore/']")
                            if link:
                                h = link.get_attribute("href") or ""
                                pid = h.replace("/explore/", "") if h.startswith("/explore/") and "?" not in h else ""
                                if pid == post_id:
                                    target_card = card
                                    break
                        except Exception:
                            continue

                    if not target_card:
                        logger.warning("  card %s: DOM 中未找到对应卡片，重新加载搜索页", post_id)
                        open_search_page(page, kw)
                        continue

                    target_card.click()
                    page.wait_for_timeout(5000)

                    access_status, block_reason, is_valid = detect_access_status(page)
                    if not is_valid:
                        logger.warning("  card %s: blocked (%s)", post_id, block_reason)
                        _try_dismiss_overlay(page)
                        time.sleep(self.config.request_interval_seconds)
                        continue

                    candidates = extract_detail_candidates(page)
                    scroll_visible_comments(page, rounds=self.config.scroll_rounds)
                    visible_comments = extract_visible_comments(
                        page, post_id=post_id, max_comments=self.config.max_comments_per_post
                    )

                    probe_result = _build_probe_result(
                        page, post_id, candidates, visible_comments,
                        page.url, page.url, kw, i,
                    )

                    post_dict = _map_click_detail_post(probe_result)
                    comment_dicts = _map_click_detail_comments(probe_result)

                    if not _filter_post(post_dict, self.config):
                        logger.info("  card %s: 互动量不足，跳过", post_id)
                        _try_dismiss_overlay(page)
                        time.sleep(self.config.request_interval_seconds)
                        continue

                    self._posts.append(post_dict)
                    self._comments.extend(comment_dicts)
                    logger.info("  XHS collected: post_id=%s title=%s comments=%s",
                                post_id, post_dict.get("title", "")[:20], len(comment_dicts))

                    # 无论浮层是否关闭成功，都强制重新加载搜索页。
                    # 这是最可靠的方式：每次循环都从干净的搜索结果页面开始。
                    # 如果只尝试关闭浮层而不 reload，页面 DOM 状态可能不一致，
                    # 导致下一轮循环的 extract_search_cards() 找不到卡片从而 break。
                    try:
                        _try_dismiss_overlay(page)
                    except Exception:
                        pass
                    open_search_page(page, kw)

                    time.sleep(self.config.request_interval_seconds)

                except Exception as e:
                    logger.warning("  card %s: 采集异常: %s", post_id, e, exc_info=True)
                    try:
                        _try_dismiss_overlay(page)
                    except Exception:
                        pass
                    try:
                        open_search_page(page, kw)
                    except Exception:
                        pass
                    continue

            logger.info("XHS fetch_posts done: posts=%s, comments=%s", len(self._posts), len(self._comments))
            return self._posts

        finally:
            close_browser_context(page, context, browser, pw)

    def fetch_comments(self, post_id: str = "", max_count: int = 0) -> list[dict]:
        max_comments = max_count or self.config.max_comments_per_post
        if post_id:
            return [c for c in self._comments if c.get("post_id") == post_id][:max_comments]
        return self._comments[:max_comments]

    @staticmethod
    def _try_restore_search(page, keyword: str):
        try:
            current = page.url
            if "/search_result" not in current:
                open_search_page(page, keyword)
        except Exception as e:
            logger.warning("恢复搜索页面失败: %s", e)
