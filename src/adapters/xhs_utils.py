"""
小红书适配器的公共工具函数。

包含计数文本解析、URL 提取等纯函数。

所有函数均为纯函数，不涉及 IO、不读取配置、不访问网络。
"""

from __future__ import annotations

import re


def parse_count_text(text: str | None) -> int:
    """解析小红书计数文本，如 "1.2万" "300" "2k" 等。

    支持格式：
    - 纯数字：300、0
    - 中文万：1.2万、3万
    - 英文 k：2k、1.5K
    - 千分位：1,200
    - 异常值返回 0
    """
    if not text:
        return 0
    text = text.strip()
    if not text:
        return 0

    # 中文万
    if "万" in text:
        try:
            val = float(text.replace("万", ""))
            return int(val * 10000)
        except (ValueError, TypeError):
            pass

    # 英文 k
    if text.lower().endswith("k"):
        try:
            val = float(text[:-1])
            return int(val * 1000)
        except (ValueError, TypeError):
            pass

    # 去除千分位逗号
    text_clean = text.replace(",", "")

    # 纯数字
    try:
        return int(text_clean)
    except (ValueError, TypeError):
        pass

    return 0


def extract_post_id_from_url(url: str) -> str:
    """从小红书笔记 URL 中提取 note_id/post_id。

    支持格式：
    - https://www.xiaohongshu.com/explore/<note_id>
    - https://www.xiaohongshu.com/discovery/item/<note_id>
    - https://xhslink.com/<short_code>
    如果无法提取，返回空字符串。
    """
    if not url:
        return ""

    # explore 格式: /explore/<note_id>
    match = re.search(r"/explore/([a-f0-9]{24,})", url)
    if match:
        return match.group(1)

    # discovery/item 格式
    match = re.search(r"/discovery/item/([a-f0-9]{24,})", url)
    if match:
        return match.group(1)

    return ""
