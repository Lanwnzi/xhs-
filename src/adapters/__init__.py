"""平台适配器包。

本包包含所有平台采集适配器。
新增平台必须先实现 adapter，再接入主流程。

当前实现：
- XhsImportAdapter：小红书本地导入（从 JSON 文件读取人工整理数据）
- XhsPlaywrightAdapter：小红书 Playwright 实时采集（骨架阶段）

扩展方式：
    class RedditAdapter(BaseAdapter):
        def fetch_posts(self, keyword, max_count=20): ...
        def fetch_comments(self, post_id, max_count=50): ...
"""

from src.adapters.base import BaseAdapter
from src.adapters.xhs_import_adapter import XhsImportAdapter
from src.adapters.xhs_playwright_adapter import XhsPlaywrightAdapter

__all__ = ["BaseAdapter", "XhsImportAdapter", "XhsPlaywrightAdapter"]
